"""Who may call what, under which identity, and on whose data.

The six roles are exercised on their own operations and then pointed at each
other's; the two certifying-official roles are additionally bound to a
registered, active, correctly tiered row; and the student is bound to one record.
"""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_paid_certification,
    build_priced_certification,
    create_program,
    create_verified_student,
    read_certification,
    read_student,
    set_clock_to,
    submit_certification,
)
from test_helpers.test_users import (
    BURSAR_HEADERS,
    SAA_HEADERS,
    VA_HEADERS,
    make_headers,
    make_sco_headers,
    make_student_headers,
    make_supervisory_sco_headers,
)

PAID_TUITION_CENTS = 2790000
PAID_MHA_CENTS = 776444
TUITION_CHARGE_CENTS = 5000
PARTIAL_REPAYMENT_CENTS = 100000

WITHDRAWAL_REPORTED_ON = "2026-09-05"
WITHDRAWAL_EFFECTIVE_DATE = "2026-09-15"

SECOND_PROGRAM_CODE = "ACC-GR"
SECOND_PROGRAM_NAME = "Accounting MS"
SECOND_SUPERVISOR_NAME = "Rowan Diaz"
SECOND_SUPERVISOR_EMAIL = "rowan.diaz@u.edu"
RETIRED_OFFICIAL_NAME = "Casey Lund"
RETIRED_OFFICIAL_EMAIL = "casey.lund@u.edu"
UNDECLARED_ROLE = "Registrar"

CANONICAL_NET_COVERED_CENTS = 2950000


# ─── Each role on its own operations ──────────────────────────────────
def _withdraw_and_reconcile(api, baseline, scenario):
    """The front-line official files a withdrawal and the supervisor reconciles it."""
    set_clock_to(api, WITHDRAWAL_REPORTED_ON)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.complete_withdrawal_payload(
                scenario.certification_id, WITHDRAWAL_EFFECTIVE_DATE
            ),
            baseline.sco_headers,
        ),
        expected_status=201,
    )
    get_success_data(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )
    rows, _meta = validate_paginated(api.list_benefit_debts(BURSAR_HEADERS))
    return rows[0]


def test_all_six_roles_complete_their_own_operations_in_one_pass(api, baseline):
    """Credentialing, approval, pricing, certifying, paying, reporting and repaying.

    PRD: "The `Authorized Role(s)` column lists every value of `X-User-Role`
    accepted on that endpoint; any other role is refused with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/every_role_can_perform_its_own_operations_end_to_end
    """
    scenario = build_paid_certification(
        api, baseline, PAID_TUITION_CENTS, PAID_MHA_CENTS
    )
    get_success_data(
        api.create_student_account_charge(
            f.student_account_charge_payload(
                scenario.student_id,
                baseline.term_id,
                c.CHARGE_TYPE_TUITION,
                TUITION_CHARGE_CENTS,
            ),
            BURSAR_HEADERS,
        ),
        expected_status=201,
    )
    get_success_data(
        api.set_account_hold(
            scenario.student_id,
            f.account_hold_payload(c.ACCOUNT_HOLD_REGISTRATION_HOLD),
            BURSAR_HEADERS,
        )
    )
    debt = _withdraw_and_reconcile(api, baseline, scenario)
    get_success_data(
        api.notify_benefit_debt(
            debt["id"], f.notify_debt_payload(), baseline.sco_headers
        )
    )
    get_success_data(
        api.acknowledge_benefit_debt(
            debt["id"], {}, make_student_headers(scenario.student_id)
        )
    )
    repaid = get_success_data(
        api.create_debt_repayment(
            debt["id"], f.repayment_payload(PARTIAL_REPAYMENT_CENTS), BURSAR_HEADERS
        )
    )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_TERMINATED,
            "tuition_paid_cents": PAID_TUITION_CENTS,
        },
    )
    a.assert_fields(
        repaid,
        {
            "notification_status": c.DEBT_NOTIFICATION_ACKNOWLEDGED,
            "collection_status": c.DEBT_COLLECTION_PARTIALLY_REPAID,
            "repaid_cents": PARTIAL_REPAYMENT_CENTS,
        },
    )
    assert (
        read_student(api, baseline.sco_headers, scenario.student_id)[
            "account_hold_status"
        ]
        == c.ACCOUNT_HOLD_REGISTRATION_HOLD
    )


def test_the_student_reads_their_own_debts_through_their_own_filter(api, baseline):
    """The one operation the student may read is scoped to the student's own id.

    PRD: "Benefit debts may be filtered by `student_id`, `certification_id`,
    `change_report_id`, `waived_by_official_id`, `debtor_type`, `collection_status`
    and `notification_status`."

    Design: Corner/rbac/every_role_can_perform_its_own_operations_end_to_end
    """
    scenario = build_paid_certification(
        api, baseline, PAID_TUITION_CENTS, PAID_MHA_CENTS
    )
    debt = _withdraw_and_reconcile(api, baseline, scenario)

    rows, meta = validate_paginated(
        api.list_benefit_debts(
            make_student_headers(scenario.student_id),
            {"student_id": scenario.student_id},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == debt["id"]
    assert rows[0]["student_id"] == scenario.student_id


# ─── Each role off its own operations ─────────────────────────────────
def _cross_role_attempt(api, baseline, scenario, pending_catalog_id, attempt):
    """Point one role at an operation reserved to a different role."""
    if attempt == "sco_certifies":
        return api.certify_certification(
            scenario.certification_id, {}, baseline.sco_headers
        )
    if attempt == "sco_voids":
        return api.void_certification(
            scenario.certification_id, {}, baseline.sco_headers
        )
    if attempt == "supervisor_prices":
        return api.create_tuition_fee_report(
            f.tuition_fee_report_payload(
                scenario.certification_id, scenario.certification_version
            ),
            baseline.sup_headers,
        )
    if attempt == "supervisor_pays":
        return api.record_va_payment(
            scenario.certification_id,
            f.record_va_payment_payload(
                PAID_TUITION_CENTS, PAID_MHA_CENTS, c.CLOCK_START_DATE
            ),
            baseline.sup_headers,
        )
    if attempt == "bursar_decides_the_catalog":
        return api.record_saa_decision(
            pending_catalog_id,
            f.saa_decision_payload(c.SAA_DECISION_APPROVED),
            BURSAR_HEADERS,
        )
    return api.close_academic_term(baseline.term_id, {}, SAA_HEADERS)


def _submitted_certification_and_a_pending_catalog(api, baseline):
    """A submitted, priced certification alongside a catalog awaiting the agency."""
    scenario = build_priced_certification(api, baseline)
    submitted = submit_certification(
        api, baseline.sco_headers, scenario.certification_id
    )
    scenario.certification_version = submitted["version"]
    other_program_id = create_program(
        api,
        baseline.sup_headers,
        program_code=SECOND_PROGRAM_CODE,
        name=SECOND_PROGRAM_NAME,
        degree_level=c.DEGREE_LEVEL_GRADUATE,
    )
    catalog = get_success_data(
        api.create_catalog_version(
            f.catalog_version_payload(other_program_id), baseline.sup_headers
        ),
        expected_status=201,
    )
    get_success_data(
        api.submit_catalog_version_to_saa(catalog["id"], {}, baseline.sup_headers)
    )
    return scenario, catalog["id"]


@pytest.mark.parametrize(
    "attempt",
    [
        "sco_certifies",
        "sco_voids",
        "supervisor_prices",
        "supervisor_pays",
        "bursar_decides_the_catalog",
        "state_agent_closes_the_term",
    ],
)
def test_no_role_may_invoke_an_operation_reserved_to_another(api, baseline, attempt):
    """Six declared-but-unlisted roles are all turned away the same way.

    PRD: "The `Authorized Role(s)` column lists every value of `X-User-Role`
    accepted on that endpoint; any other role is refused with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/no_role_can_invoke_another_roles_exclusive_operation_unauthorized
    """
    scenario, pending_catalog_id = _submitted_certification_and_a_pending_catalog(
        api, baseline
    )

    response = _cross_role_attempt(
        api, baseline, scenario, pending_catalog_id, attempt
    )
    validate_error(response, "ERR_UNAUTHORIZED", expected_status=403)


def test_the_refused_calls_left_every_row_where_it_was(api, baseline):
    """The bursar's report still stands and nothing advanced a state.

    PRD: "The `Authorized Role(s)` column lists every value of `X-User-Role`
    accepted on that endpoint; any other role is refused with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/no_role_can_invoke_another_roles_exclusive_operation_unauthorized
    """
    scenario, pending_catalog_id = _submitted_certification_and_a_pending_catalog(
        api, baseline
    )
    for attempt in (
        "sco_certifies",
        "supervisor_prices",
        "supervisor_pays",
        "bursar_decides_the_catalog",
        "state_agent_closes_the_term",
    ):
        validate_error(
            _cross_role_attempt(api, baseline, scenario, pending_catalog_id, attempt),
            "ERR_UNAUTHORIZED",
            expected_status=403,
        )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_SUBMITTED,
            "tuition_paid_cents": 0,
            "net_covered_cents": CANONICAL_NET_COVERED_CENTS,
        },
    )
    rows, meta = validate_paginated(api.list_tuition_fee_reports(BURSAR_HEADERS))
    assert meta["total_count"] == 1
    assert rows[0]["status"] == c.TUITION_REPORT_STATUS_REPORTED
    assert (
        get_success_data(
            api.get_catalog_version(pending_catalog_id, baseline.sup_headers)
        )["review_status"]
        == c.CATALOG_REVIEW_PENDING_SAA
    )
    assert (
        get_success_data(api.get_academic_term(baseline.term_id, baseline.sup_headers))[
            "status"
        ]
        == c.TERM_STATUS_OPEN
    )


# ─── The identity behind a certifying-official role ───────────────────
def test_an_unregistered_identifier_cannot_act_as_a_certifying_official(api, baseline):
    """The header id has to resolve to a credentialed official.

    PRD: "For every endpoint whose authorised roles include
    `SchoolCertifyingOfficial` or `SupervisorySCO`, `X-User-ID` resolves to a
    `CertifyingOfficial`, else `ERR_OFFICIAL_NOT_REGISTERED` (403)."

    Design: Corner/rbac/official_identities_must_be_registered_active_and_level_matched
    """
    response = api.create_veteran_student(
        f.veteran_student_payload(), make_sco_headers(NON_EXISTENT_UUID)
    )
    validate_error(response, "ERR_OFFICIAL_NOT_REGISTERED", expected_status=403)

    _rows, meta = validate_paginated(api.list_veteran_students(baseline.sco_headers))
    assert meta["total_count"] == 0


def test_a_deactivated_official_cannot_act(api, baseline):
    """Credentialing is not enough; the row has to still be active.

    PRD: "On the same set of endpoints, that official's `status` is `ACTIVE`, else
    `ERR_OFFICIAL_INACTIVE` (403)."

    Design: Corner/rbac/official_identities_must_be_registered_active_and_level_matched
    """
    retired = get_success_data(
        api.create_certifying_official(
            f.sco_official_payload(
                full_name=RETIRED_OFFICIAL_NAME, email=RETIRED_OFFICIAL_EMAIL
            ),
            VA_HEADERS,
        ),
        expected_status=201,
    )
    get_success_data(
        api.deactivate_certifying_official(retired["id"], {}, VA_HEADERS)
    )

    response = api.create_veteran_student(
        f.veteran_student_payload(), make_sco_headers(retired["id"])
    )
    validate_error(response, "ERR_OFFICIAL_INACTIVE", expected_status=403)

    assert (
        get_success_data(api.get_certifying_official(retired["id"], VA_HEADERS))[
            "status"
        ]
        == c.OFFICIAL_STATUS_INACTIVE
    )


@pytest.mark.parametrize("claimed", ["sco_claims_supervisory", "supervisor_claims_sco"])
def test_a_mismatched_authority_tier_cannot_act(api, baseline, claimed):
    """The tier is checked in both directions.

    PRD: "On the same set of endpoints, that official's `official_level` matches the
    claimed tier, else `ERR_OFFICIAL_LEVEL_MISMATCH` (403)."

    Design: Corner/rbac/official_identities_must_be_registered_active_and_level_matched
    """
    student_id = create_verified_student(api, baseline.sco_headers)

    if claimed == "sco_claims_supervisory":
        # Creating a term is a SupervisorySCO operation, so the claimed tier is
        # on the allow-list and the front-line official's row fails the tier check.
        response = api.create_academic_term(
            f.spring_term_payload(), make_supervisory_sco_headers(baseline.sco_id)
        )
    else:
        # The mirror direction has to be probed on an endpoint that admits
        # `SchoolCertifyingOfficial`; pointing that claim at a SupervisorySCO-only
        # operation would be refused one rung earlier, on the role allow-list.
        response = api.create_veteran_student(
            f.veteran_student_payload(student_number=c.SECOND_STUDENT_NUMBER),
            make_sco_headers(baseline.sup_id),
        )
    validate_error(response, "ERR_OFFICIAL_LEVEL_MISMATCH", expected_status=403)

    assert (
        read_student(api, baseline.sco_headers, student_id)["coe_status"]
        == c.COE_STATUS_VERIFIED
    )


# ─── Authentication before anything else ──────────────────────────────
@pytest.mark.parametrize(
    "headers_name",
    ["role_omitted", "identifier_omitted", "undeclared_role"],
)
def test_a_missing_or_undeclared_role_header_is_unauthenticated(
    api, officials, headers_name
):
    """The header gate answers 401 before any allow-list is consulted.

    PRD: "`X-User-ID` and `X-User-Role` are both present and the role is one of the
    six declared names, else `ERR_UNAUTHENTICATED` (401). Applies to every
    endpoint."

    Design: Corner/rbac/a_request_with_a_missing_or_unknown_role_header_is_unauthorized
    """
    headers = {
        "role_omitted": {"X-User-ID": officials.sup_id},
        "identifier_omitted": {"X-User-Role": c.ROLE_SUPERVISORY_SCO},
        "undeclared_role": make_headers(officials.sup_id, UNDECLARED_ROLE),
    }[headers_name]

    response = api.create_academic_term(f.academic_term_payload(), headers)
    validate_error(response, "ERR_UNAUTHENTICATED", expected_status=401)

    _rows, meta = validate_paginated(api.list_academic_terms(officials.sup_headers))
    assert meta["total_count"] == 0


def test_the_identical_body_succeeds_once_the_headers_are_valid(api, officials):
    """Only the headers were wrong, so the same payload is accepted.

    PRD: "The `Authorized Role(s)` column lists every value of `X-User-Role`
    accepted on that endpoint; any other role is refused with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/a_request_with_a_missing_or_unknown_role_header_is_unauthorized
    """
    validate_error(
        api.create_academic_term(
            f.academic_term_payload(), make_headers(officials.sup_id, UNDECLARED_ROLE)
        ),
        "ERR_UNAUTHENTICATED",
        expected_status=401,
    )

    term = get_success_data(
        api.create_academic_term(f.academic_term_payload(), officials.sup_headers),
        expected_status=201,
    )
    assert term["term_code"] == c.TERM_CODE


# ─── One student, one record ──────────────────────────────────────────
def _two_students_with_debts(api, baseline):
    """Two students, each carrying one reconciled overpayment debt."""
    first = build_paid_certification(
        api, baseline, PAID_TUITION_CENTS, PAID_MHA_CENTS
    )
    second = build_paid_certification(
        api,
        baseline,
        PAID_TUITION_CENTS,
        PAID_MHA_CENTS,
        student_overrides={
            "student_number": c.SECOND_STUDENT_NUMBER,
            "full_name": c.SECOND_STUDENT_NAME,
        },
    )
    set_clock_to(api, WITHDRAWAL_REPORTED_ON)
    debts = {}
    for scenario in (first, second):
        change_report = get_success_data(
            api.create_enrollment_change_report(
                f.complete_withdrawal_payload(
                    scenario.certification_id, WITHDRAWAL_EFFECTIVE_DATE
                ),
                baseline.sco_headers,
            ),
            expected_status=201,
        )
        get_success_data(
            api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
        )
        rows, _meta = validate_paginated(
            api.list_benefit_debts(
                BURSAR_HEADERS, {"student_id": scenario.student_id}
            )
        )
        debt = get_success_data(
            api.notify_benefit_debt(
                rows[0]["id"], f.notify_debt_payload(), baseline.sco_headers
            )
        )
        debts[scenario.student_id] = debt
    return first, second, debts


@pytest.mark.parametrize("reach", ["read_record", "read_debt", "acknowledge_debt"])
def test_a_student_cannot_reach_another_students_data(api, baseline, reach):
    """Reading or acknowledging someone else's row is a scope violation.

    PRD: "On the four operations where a student may act or read — reading one
    veteran student by path id, listing benefit debts, reading one benefit debt by
    path id, and acknowledging a debt notification — `X-User-ID` must equal the
    `VeteranStudent` identifier the target resource belongs to."

    Design: Corner/rbac/a_student_cannot_read_or_acknowledge_another_students_debt
    """
    first, second, debts = _two_students_with_debts(api, baseline)
    intruder = make_student_headers(first.student_id)
    other_debt = debts[second.student_id]

    if reach == "read_record":
        response = api.get_veteran_student(second.student_id, intruder)
    elif reach == "read_debt":
        response = api.get_benefit_debt(other_debt["id"], intruder)
    else:
        response = api.acknowledge_benefit_debt(other_debt["id"], {}, intruder)
    validate_error(response, "ERR_STUDENT_SCOPE_VIOLATION", expected_status=403)

    untouched = get_success_data(
        api.get_benefit_debt(other_debt["id"], BURSAR_HEADERS)
    )
    a.assert_fields(
        untouched,
        {
            "notification_status": c.DEBT_NOTIFICATION_SENT,
            "acknowledged_on": None,
        },
    )


def test_the_scope_confinement_applies_only_to_the_student_role(api, baseline):
    """The supervisor sees both debts that the student may not see.

    PRD: "Any deviation is rejected with `ERR_STUDENT_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/a_student_cannot_read_or_acknowledge_another_students_debt
    """
    first, second, debts = _two_students_with_debts(api, baseline)

    rows, meta = validate_paginated(
        api.list_benefit_debts(
            make_student_headers(first.student_id), {"student_id": first.student_id}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["student_id"] == first.student_id
    assert rows[0]["id"] != debts[second.student_id]["id"]

    rows, meta = validate_paginated(api.list_benefit_debts(baseline.sup_headers))
    assert meta["total_count"] == 2
    assert {row["student_id"] for row in rows} == {
        first.student_id,
        second.student_id,
    }


# ─── Two approvals, two people ────────────────────────────────────────
def _second_supervisor_headers(api):
    """Credential a second supervisory official and act as them."""
    official = get_success_data(
        api.create_certifying_official(
            f.supervisory_official_payload(
                full_name=SECOND_SUPERVISOR_NAME, email=SECOND_SUPERVISOR_EMAIL
            ),
            VA_HEADERS,
        ),
        expected_status=201,
    )
    return official["id"], make_supervisory_sco_headers(official["id"])


def _certification_submitted_by_the_supervisor(api, baseline):
    """A priced certification whose submitting official is the supervisor."""
    scenario = build_priced_certification(api, baseline)
    submitted = submit_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    scenario.certification_version = submitted["version"]
    return scenario


def test_the_submitting_official_may_not_certify_their_own_submission(api, baseline):
    """The same identity cannot stand on both sides of the approval.

    PRD: "An attempt to certify a certification that the same official submitted is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_blocks_an_official_from_approving_their_own_work
    """
    scenario = _certification_submitted_by_the_supervisor(api, baseline)

    response = api.certify_certification(
        scenario.certification_id, {}, baseline.sup_headers
    )
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES", expected_status=422)

    assert (
        read_certification(api, baseline.sup_headers, scenario.certification_id)[
            "status"
        ]
        == c.CERT_STATUS_SUBMITTED
    )


def test_a_second_supervisory_official_may_certify_it(api, baseline):
    """The block is per identity, so another supervisor completes the approval.

    PRD: "The submitting official's identifier is retained on the certification as
    `submitted_by_official_id`, and the certifying official's identifier is retained
    as `certified_by_official_id`."

    Design: Corner/rbac/segregation_of_duties_blocks_an_official_from_approving_their_own_work
    """
    scenario = _certification_submitted_by_the_supervisor(api, baseline)
    second_id, second_headers = _second_supervisor_headers(api)

    certified = get_success_data(
        api.certify_certification(scenario.certification_id, {}, second_headers)
    )
    a.assert_fields(
        certified,
        {
            "status": c.CERT_STATUS_CERTIFIED,
            "submitted_by_official_id": baseline.sup_id,
            "certified_by_official_id": second_id,
        },
    )


def test_the_reconciling_official_may_not_waive_the_resulting_debt(api, baseline):
    """The waiver compares the acting identity against the reconciler.

    PRD: "An attempt to waive a debt by the same official who reconciled the change
    report identified by that debt's `change_report_id` is rejected with
    `ERR_WAIVER_SEGREGATION`."

    Design: Corner/rbac/segregation_of_duties_blocks_an_official_from_approving_their_own_work
    """
    scenario = build_paid_certification(
        api, baseline, PAID_TUITION_CENTS, PAID_MHA_CENTS
    )
    debt = _withdraw_and_reconcile(api, baseline, scenario)

    response = api.waive_benefit_debt(
        debt["id"], f.waive_debt_payload(), baseline.sup_headers
    )
    validate_error(response, "ERR_WAIVER_SEGREGATION", expected_status=422)

    unchanged = get_success_data(api.get_benefit_debt(debt["id"], BURSAR_HEADERS))
    a.assert_fields(
        unchanged,
        {
            "collection_status": c.DEBT_COLLECTION_OPEN,
            "outstanding_cents": debt["outstanding_cents"],
        },
    )


def test_a_different_supervisory_official_may_waive_it(api, baseline):
    """A second identity clears the balance and is recorded as the waiver.

    PRD: "A waiver takes a `waiver_reason`, sets `collection_status` to `WAIVED`,
    records the acting `X-User-ID` as `waived_by_official_id`, stores the reason, and
    drives `outstanding_cents` to 0 while leaving `principal_cents` untouched."

    Design: Corner/rbac/segregation_of_duties_blocks_an_official_from_approving_their_own_work
    """
    scenario = build_paid_certification(
        api, baseline, PAID_TUITION_CENTS, PAID_MHA_CENTS
    )
    debt = _withdraw_and_reconcile(api, baseline, scenario)
    second_id, second_headers = _second_supervisor_headers(api)

    waived = get_success_data(
        api.waive_benefit_debt(debt["id"], f.waive_debt_payload(), second_headers)
    )
    a.assert_fields(
        waived,
        {
            "collection_status": c.DEBT_COLLECTION_WAIVED,
            "waived_by_official_id": second_id,
            "outstanding_cents": 0,
            "principal_cents": debt["principal_cents"],
        },
    )
