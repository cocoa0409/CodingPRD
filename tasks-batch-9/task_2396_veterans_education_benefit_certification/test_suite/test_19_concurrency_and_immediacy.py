"""Version guards on the two shared ledgers, and the immediacy of certify.

Both guarded writes are attempted from a view taken before an accepted write
moved the row, and the refusals are checked for having moved nothing; the
certify response is then read for the derived values it must already carry.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_certified_certification,
    build_draft_certification,
    build_submitted_certification,
    create_agreement,
    create_award,
    price_certification,
    read_agreement,
    read_certification,
    read_student,
)
from test_helpers.test_users import BURSAR_HEADERS

REVISED_GROSS_TUITION_CENTS = 3200000
REVISED_NET_COVERED_CENTS = 3150000

EXPECTED_VA_TUITION_CENTS = 2790000
EXPECTED_YR_GAP_CENTS = 160000
EXPECTED_ENTITLEMENT_DAYS_CHARGED = 110
EXPECTED_DAYS_REMAINING = 970

SECOND_STUDENT = {
    "student_number": c.SECOND_STUDENT_NUMBER,
    "full_name": c.SECOND_STUDENT_NAME,
}


# ─── Repricing from a stale view of the certification ─────────────────
def _priced_once_from_the_creation_version(api, baseline):
    """A certification priced with the version observed when it was created."""
    scenario = build_draft_certification(api, baseline)
    version_at_creation = scenario.certification_version
    report_id, version_after_pricing = price_certification(
        api, scenario.certification_id, version_at_creation
    )
    scenario.tuition_report_id = report_id
    scenario.certification_version = version_after_pricing
    return scenario, version_at_creation


def _reprice(api, certification_id, expected_certification_version):
    """Attempt a revised pricing that raises gross tuition by 200000 cents."""
    return api.create_tuition_fee_report(
        f.tuition_fee_report_payload(
            certification_id,
            expected_certification_version,
            gross_tuition_cents=REVISED_GROSS_TUITION_CENTS,
        ),
        BURSAR_HEADERS,
    )


def test_replaying_the_version_read_at_creation_is_refused(api, baseline):
    """Accepting the first report moved the version the second report still carries.

    PRD: "Creating a tuition and fee report must carry
    `expected_certification_version` holding the client's last observed `version` of
    the referenced `EnrollmentCertification`. If that value does not equal the
    certification's current `version`, the create is rejected with
    `ERR_STALE_CERTIFICATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/a_stale_certification_version_blocks_the_repricing_and_bumps_nothing
    """
    scenario, version_at_creation = _priced_once_from_the_creation_version(
        api, baseline
    )
    assert scenario.certification_version == version_at_creation + 1

    response = _reprice(api, scenario.certification_id, version_at_creation)
    validate_error(
        response, "ERR_STALE_CERTIFICATION_VERSION", expected_status=412
    )


def test_the_refused_repricing_discards_nothing_that_was_accepted(api, baseline):
    """The pricing already in force survives the stale writer untouched.

    PRD: "That version bump is exactly what the concurrency guard protects: a second
    bursar working from a view of the certification taken before the first report
    landed will find their `expected_certification_version` no longer current and
    will be turned away with `ERR_STALE_CERTIFICATION_VERSION` rather than silently
    discarding the pricing revision that was already accepted."

    Design: Corner/cross_cutting_complexity_layers/a_stale_certification_version_blocks_the_repricing_and_bumps_nothing
    """
    scenario, version_at_creation = _priced_once_from_the_creation_version(
        api, baseline
    )
    validate_error(
        _reprice(api, scenario.certification_id, version_at_creation),
        "ERR_STALE_CERTIFICATION_VERSION",
        expected_status=412,
    )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "net_covered_cents": c.CANONICAL_NET_COVERED_CENTS,
            "version": scenario.certification_version,
        },
    )
    rows, meta = validate_paginated(
        api.list_tuition_fee_reports(
            BURSAR_HEADERS, {"certification_id": scenario.certification_id}
        )
    )
    assert meta["total_count"] == 1
    a.assert_fields(
        rows[0],
        {
            "id": scenario.tuition_report_id,
            "status": c.TUITION_REPORT_STATUS_REPORTED,
        },
    )


def test_the_revision_prices_itself_once_the_current_version_is_read(api, baseline):
    """The retry is accepted and derives its own covered amount from its own figures.

    PRD: "From those four figures the report derives its own `net_covered_cents`: add
    `gross_tuition_cents` and `mandatory_fees_cents`, subtract
    `tuition_specific_aid_cents`, and floor the result at 0 so that aid exceeding the
    assessment yields zero rather than a negative covered amount."

    Design: Corner/cross_cutting_complexity_layers/a_stale_certification_version_blocks_the_repricing_and_bumps_nothing
    """
    scenario, version_at_creation = _priced_once_from_the_creation_version(
        api, baseline
    )
    validate_error(
        _reprice(api, scenario.certification_id, version_at_creation),
        "ERR_STALE_CERTIFICATION_VERSION",
        expected_status=412,
    )

    current_version = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )["version"]
    revision = get_success_data(
        _reprice(api, scenario.certification_id, current_version), expected_status=201
    )
    a.assert_fields(
        revision,
        {
            "gross_tuition_cents": REVISED_GROSS_TUITION_CENTS,
            "mandatory_fees_cents": c.MANDATORY_FEES_CENTS,
            "tuition_specific_aid_cents": c.TUITION_SPECIFIC_AID_CENTS,
            "net_covered_cents": REVISED_NET_COVERED_CENTS,
        },
    )


def test_the_accepted_revision_reprices_the_certification_and_bumps_it_once(
    api, baseline
):
    """Only the accepted writes moved the version, so it stands at three.

    PRD: "Acceptance of a report also writes the derived covered amount onto the
    certification itself as the certification's `net_covered_cents`, and because that
    is a mutation of the certification row it increments the certification's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/a_stale_certification_version_blocks_the_repricing_and_bumps_nothing
    """
    scenario, version_at_creation = _priced_once_from_the_creation_version(
        api, baseline
    )
    validate_error(
        _reprice(api, scenario.certification_id, version_at_creation),
        "ERR_STALE_CERTIFICATION_VERSION",
        expected_status=412,
    )
    get_success_data(
        _reprice(api, scenario.certification_id, scenario.certification_version),
        expected_status=201,
    )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "net_covered_cents": REVISED_NET_COVERED_CENTS,
            "version": version_at_creation + 2,
        },
    )


def test_the_accepted_revision_supersedes_the_report_it_replaced(api, baseline):
    """One report in force, one superseded behind it, nothing lost to the refusal.

    PRD: "A report is created with `status` `REPORTED`, and in the same operation any
    earlier report for the same `certification_id` that was still `REPORTED` is moved
    `REPORTED → SUPERSEDED`, which is terminal — so a certification always has
    exactly one report in force and an arbitrarily long trail of superseded ones
    behind it."

    Design: Corner/cross_cutting_complexity_layers/a_stale_certification_version_blocks_the_repricing_and_bumps_nothing
    """
    scenario, version_at_creation = _priced_once_from_the_creation_version(
        api, baseline
    )
    validate_error(
        _reprice(api, scenario.certification_id, version_at_creation),
        "ERR_STALE_CERTIFICATION_VERSION",
        expected_status=412,
    )
    revision = get_success_data(
        _reprice(api, scenario.certification_id, scenario.certification_version),
        expected_status=201,
    )

    rows, meta = validate_paginated(
        api.list_tuition_fee_reports(
            BURSAR_HEADERS, {"certification_id": scenario.certification_id}
        )
    )
    assert meta["total_count"] == 2
    statuses = {row["id"]: row["status"] for row in rows}
    assert statuses[scenario.tuition_report_id] == (
        c.TUITION_REPORT_STATUS_SUPERSEDED
    )
    assert statuses[revision["id"]] == c.TUITION_REPORT_STATUS_REPORTED


# ─── Awarding from a stale view of the agreement ──────────────────────
def _agreement_with_one_award_placed(api, baseline):
    """Two certified certifications, an agreement, and one award already placed."""
    first = build_certified_certification(api, baseline)
    second = build_certified_certification(
        api, baseline, student_overrides=dict(SECOND_STUDENT)
    )
    agreement_id, version_before_awards = create_agreement(api, baseline.sup_headers)
    first_award = create_award(
        api,
        baseline.sup_headers,
        first.certification_id,
        agreement_id,
        version_before_awards,
    )
    return second, agreement_id, version_before_awards, first_award


def test_an_award_carrying_the_pre_debit_version_is_refused(api, baseline):
    """The first award moved the agreement, so the second request is out of date.

    PRD: "Creating a Yellow Ribbon award must carry `expected_agreement_version`
    holding the client's last observed `version` of the referenced
    `YellowRibbonAgreement`. If that value does not equal the agreement's current
    `version`, the create is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/a_stale_agreement_version_blocks_the_award_and_leaves_the_pool_untouched
    """
    second, agreement_id, stale_version, _first_award = _agreement_with_one_award_placed(
        api, baseline
    )

    response = api.create_yellow_ribbon_award(
        f.yellow_ribbon_award_payload(
            second.certification_id, agreement_id, stale_version
        ),
        baseline.sup_headers,
    )
    validate_error(response, "ERR_STALE_AGREEMENT_VERSION", expected_status=412)


def test_the_refused_award_debited_nothing(api, baseline):
    """The pool and the participant count show only the award that was accepted.

    PRD: "Award creation debits the agreement's remaining pool and increments its
    participant count, so a writer whose view of the agreement predates an
    already-accepted award would compute a school share from a pool balance that no
    longer exists."

    Design: Corner/cross_cutting_complexity_layers/a_stale_agreement_version_blocks_the_award_and_leaves_the_pool_untouched
    """
    second, agreement_id, stale_version, first_award = _agreement_with_one_award_placed(
        api, baseline
    )
    pool_before_refusal = read_agreement(api, baseline.sup_headers, agreement_id)[
        "pool_remaining_cents"
    ]
    validate_error(
        api.create_yellow_ribbon_award(
            f.yellow_ribbon_award_payload(
                second.certification_id, agreement_id, stale_version
            ),
            baseline.sup_headers,
        ),
        "ERR_STALE_AGREEMENT_VERSION",
        expected_status=412,
    )

    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {
            "pool_remaining_cents": pool_before_refusal,
            "participant_count": 1,
        },
    )
    rows, meta = validate_paginated(
        api.list_yellow_ribbon_awards(
            baseline.sup_headers, {"agreement_id": agreement_id}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first_award["id"]


def test_only_the_accepted_award_moved_the_pool_and_the_version(api, baseline):
    """One accepted award, one debit of its own school share, one version step.

    PRD: "Award creation debits the agreement: `pool_remaining_cents` falls by
    `school_share_cents`, `participant_count` rises by one, and the agreement's
    `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/a_stale_agreement_version_blocks_the_award_and_leaves_the_pool_untouched
    """
    second, agreement_id, stale_version, first_award = _agreement_with_one_award_placed(
        api, baseline
    )
    validate_error(
        api.create_yellow_ribbon_award(
            f.yellow_ribbon_award_payload(
                second.certification_id, agreement_id, stale_version
            ),
            baseline.sup_headers,
        ),
        "ERR_STALE_AGREEMENT_VERSION",
        expected_status=412,
    )

    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {
            "pool_remaining_cents": (
                c.YR_ANNUAL_POOL_CENTS - first_award["school_share_cents"]
            ),
            "participant_count": 1,
            "version": stale_version + 1,
        },
    )


def test_the_retry_with_the_refreshed_version_debits_the_pool_again(api, baseline):
    """The second award lands and takes its own share out of what remained.

    PRD: "Award creation debits the agreement: `pool_remaining_cents` falls by
    `school_share_cents`, `participant_count` rises by one, and the agreement's
    `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/a_stale_agreement_version_blocks_the_award_and_leaves_the_pool_untouched
    """
    second, agreement_id, stale_version, first_award = _agreement_with_one_award_placed(
        api, baseline
    )
    validate_error(
        api.create_yellow_ribbon_award(
            f.yellow_ribbon_award_payload(
                second.certification_id, agreement_id, stale_version
            ),
            baseline.sup_headers,
        ),
        "ERR_STALE_AGREEMENT_VERSION",
        expected_status=412,
    )
    refreshed_version = read_agreement(api, baseline.sup_headers, agreement_id)[
        "version"
    ]
    second_award = create_award(
        api,
        baseline.sup_headers,
        second.certification_id,
        agreement_id,
        refreshed_version,
    )

    assert second_award["status"] == c.AWARD_STATUS_PROVISIONAL
    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {
            "pool_remaining_cents": (
                c.YR_ANNUAL_POOL_CENTS
                - first_award["school_share_cents"]
                - second_award["school_share_cents"]
            ),
            "participant_count": 2,
            "version": refreshed_version + 1,
        },
    )


def test_the_retry_snapshots_the_pool_as_the_first_award_left_it(api, baseline):
    """The accepted retry records the balance it actually drew on.

    PRD: "`pool_remaining_before_cents` records the agreement's
    `pool_remaining_cents` immediately before this award."

    Design: Corner/cross_cutting_complexity_layers/a_stale_agreement_version_blocks_the_award_and_leaves_the_pool_untouched
    """
    second, agreement_id, stale_version, _first_award = _agreement_with_one_award_placed(
        api, baseline
    )
    validate_error(
        api.create_yellow_ribbon_award(
            f.yellow_ribbon_award_payload(
                second.certification_id, agreement_id, stale_version
            ),
            baseline.sup_headers,
        ),
        "ERR_STALE_AGREEMENT_VERSION",
        expected_status=412,
    )
    agreement = read_agreement(api, baseline.sup_headers, agreement_id)

    second_award = create_award(
        api,
        baseline.sup_headers,
        second.certification_id,
        agreement_id,
        agreement["version"],
    )
    assert (
        second_award["pool_remaining_before_cents"]
        == agreement["pool_remaining_cents"]
    )


# ─── Everything certify derives, in the response that certified it ────
def _certify(api, baseline):
    """Certify a submitted certification and keep the response body as returned."""
    scenario = build_submitted_certification(api, baseline)
    certified = get_success_data(
        api.certify_certification(scenario.certification_id, {}, baseline.sup_headers)
    )
    return scenario, certified


def test_the_certify_response_already_carries_the_new_status_and_basis(api, baseline):
    """No follow-up read is needed to learn the transition happened.

    PRD: "Once those conditions pass, the certification moves `SUBMITTED →
    CERTIFIED`, records the acting official's `X-User-ID` as
    `certified_by_official_id`, and stamps `amount_basis` with `AS_CERTIFIED` — that
    field, whose only values are `AS_CERTIFIED` and `AS_RECONCILED`, tells any later
    reader which variant of the arithmetic produced the amounts currently stored on
    the row."

    Design: Corner/consistency/certify_returns_every_derived_amount_and_cascade_in_the_same_response
    """
    _scenario, certified = _certify(api, baseline)

    a.assert_fields(
        certified,
        {
            "status": c.CERT_STATUS_CERTIFIED,
            "amount_basis": c.AMOUNT_BASIS_AS_CERTIFIED,
            "certified_by_official_id": baseline.sup_id,
        },
    )


def test_the_certify_response_carries_the_entitlement_it_charged(api, baseline):
    """The day count is in the body that performed the charge.

    PRD: "At certification, `entitlement_days_charged` is a single rounding over the
    whole inclusive period at a single tier: multiply `certified_days` by
    `rop_tier_pct`, divide by 100, and round half up."

    Design: Corner/consistency/certify_returns_every_derived_amount_and_cascade_in_the_same_response
    """
    _scenario, certified = _certify(api, baseline)

    assert certified["certified_days"] == c.CANONICAL_CERTIFIED_DAYS
    assert certified["rop_tier_pct"] == 100
    assert (
        certified["entitlement_days_charged"] == EXPECTED_ENTITLEMENT_DAYS_CHARGED
    )
    assert certified["entitlement_days_charged"] == (
        certified["certified_days"] * certified["rop_tier_pct"] // 100
    )


def test_the_certify_response_carries_the_covered_amount_it_priced(api, baseline):
    """The first step of the waterfall is visible on the returned row.

    PRD: "Step one takes the covered amount straight from the tuition and fee report
    in force — add its `gross_tuition_cents` and `mandatory_fees_cents`, subtract its
    `tuition_specific_aid_cents`, floor at 0 — and stores it as the certification's
    `net_covered_cents`."

    Design: Corner/consistency/certify_returns_every_derived_amount_and_cascade_in_the_same_response
    """
    _scenario, certified = _certify(api, baseline)

    assert certified["net_covered_cents"] == c.CANONICAL_NET_COVERED_CENTS


def test_the_certify_response_carries_the_capped_va_share_and_the_cap_charge(
    api, baseline
):
    """The capped base, the benefit level and the cap charge are all on the body.

    PRD: "Step four takes the smaller of `net_covered_cents` and
    `ay_cap_remaining_before_cents` as the capped base. Step five sets
    `va_tuition_cents` to that capped base multiplied by the student's
    `benefit_level_pct`, divided by 100, rounded half up. Step six sets
    `cap_charged_cents` equal to `va_tuition_cents` and to nothing else."

    Design: Corner/consistency/certify_returns_every_derived_amount_and_cascade_in_the_same_response
    """
    _scenario, certified = _certify(api, baseline)

    assert certified["ay_cap_remaining_before_cents"] == c.ANNUAL_CAP_CENTS
    assert certified["va_tuition_cents"] == EXPECTED_VA_TUITION_CENTS
    assert certified["cap_charged_cents"] == certified["va_tuition_cents"]


def test_the_certify_response_carries_the_gap_left_for_yellow_ribbon(api, baseline):
    """The final step of the waterfall is returned with the rest.

    PRD: "Step seven sets `yr_gap_cents` to `net_covered_cents` minus
    `va_tuition_cents` — the unmet tuition gap that Yellow Ribbon may later match."

    Design: Corner/consistency/certify_returns_every_derived_amount_and_cascade_in_the_same_response
    """
    _scenario, certified = _certify(api, baseline)

    assert certified["yr_gap_cents"] == EXPECTED_YR_GAP_CENTS
    assert certified["yr_gap_cents"] == (
        certified["net_covered_cents"] - certified["va_tuition_cents"]
    )


def test_the_certify_response_is_the_stored_row_itself(api, baseline):
    """Reading the certification back adds nothing the response did not have.

    PRD: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/consistency/certify_returns_every_derived_amount_and_cascade_in_the_same_response
    """
    scenario, certified = _certify(api, baseline)

    stored = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    assert {field: stored[field] for field in certified} == certified


def test_the_students_ledger_is_already_debited_when_certify_returns(api, baseline):
    """The cascade onto the student is not deferred to a later pass.

    PRD: "That figure is what the seventh precondition above tests against
    `entitlement_days_remaining`, and once the certification succeeds the student's
    `entitlement_days_remaining` is debited by exactly it, leaving remaining
    entitlement equal to granted entitlement minus everything currently charged."

    Design: Corner/consistency/certify_returns_every_derived_amount_and_cascade_in_the_same_response
    """
    scenario, certified = _certify(api, baseline)

    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["entitlement_days_remaining"] == EXPECTED_DAYS_REMAINING
    assert student["entitlement_days_remaining"] == (
        student["entitlement_days_granted"] - certified["entitlement_days_charged"]
    )


def test_the_students_protection_is_already_on_when_certify_returns(api, baseline):
    """The same immediate read shows the statutory protection switched on.

    PRD: "Because a freshly certified certification necessarily has a null
    `tuition_payment_posted_on`, the third conjunct of the protection predicate is
    satisfied, and provided the certificate is verified and the window is still open
    the recomputed `benefit_payment_protected` becomes true."

    Design: Corner/consistency/certify_returns_every_derived_amount_and_cascade_in_the_same_response
    """
    scenario, certified = _certify(api, baseline)

    assert certified["tuition_payment_posted_on"] is None
    student = read_student(api, baseline.sco_headers, scenario.student_id)
    a.assert_fields(
        student,
        {
            "coe_status": c.COE_STATUS_VERIFIED,
            "benefit_payment_protected": True,
        },
    )
