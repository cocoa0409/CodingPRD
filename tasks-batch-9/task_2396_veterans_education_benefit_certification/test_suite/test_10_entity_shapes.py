"""Written rows, their server-set openings, and how they read back.

Creation responses, declared defaults, derived fields present from the first write,
read-back fidelity, collection windows and filters, the per-entity not-found
vocabulary, request-shape rejection, and the append-only audit trail.
"""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_certified_certification,
    create_certification,
    create_officials,
    create_student,
    create_verified_student,
    price_certification,
    read_certification,
    record_va_payment,
)
from test_helpers.test_users import (
    BURSAR_HEADERS,
    VA_HEADERS,
    make_supervisory_sco_headers,
)

PLANTED_ID = "11111111-1111-1111-1111-111111111111"
PLANTED_CREATED_AT = "2000-01-01T00:00:00Z"


# ─── Creation responses ────────────────────────────────────────────────
def test_a_new_certifying_official_opens_active_at_version_one(api):
    """The authority tier is client input but the status is not.

    PRD: "The new official's `status` is not a client input: it is set by the
    server to `ACTIVE`, and its only other possible value is `INACTIVE`."

    Design: Corner/entities/create_certifying_official_and_program_return_their_declared_shapes
    """
    official = get_success_data(
        api.create_certifying_official(f.sco_official_payload(), VA_HEADERS),
        expected_status=201,
    )
    a.assert_common_fields(official, expected_version=1)
    a.assert_fields(
        official,
        {
            "full_name": c.SCO_NAME,
            "email": c.SCO_EMAIL,
            "official_level": c.LEVEL_SCO,
            "status": c.OFFICIAL_STATUS_ACTIVE,
        },
    )


def test_a_new_program_opens_as_a_draft_with_no_pinned_catalog(api):
    """A program cannot pre-suppose an approval no agency has granted it.

    PRD: "A new program opens with `approval_status` at `DRAFT` and
    `approved_catalog_version_id` null."

    Design: Corner/entities/create_certifying_official_and_program_return_their_declared_shapes
    """
    supervisor = get_success_data(
        api.create_certifying_official(f.supervisory_official_payload(), VA_HEADERS),
        expected_status=201,
    )
    program = get_success_data(
        api.create_program(
            f.program_payload(), make_supervisory_sco_headers(supervisor["id"])
        ),
        expected_status=201,
    )
    a.assert_common_fields(program, expected_version=1)
    a.assert_fields(
        program,
        {
            "program_code": c.PROGRAM_CODE,
            "name": c.PROGRAM_NAME,
            "degree_level": c.DEGREE_LEVEL_UNDERGRAD,
            "full_time_credit_hours": c.FULL_TIME_CREDIT_HOURS,
            "campus_bah_monthly_cents": c.CAMPUS_BAH_MONTHLY_CENTS,
            "approval_status": c.PROGRAM_STATUS_DRAFT,
            "approved_catalog_version_id": None,
        },
    )


def test_registering_a_student_applies_every_server_set_opening(api):
    """Only the six declared inputs are client-supplied; the rest are openings.

    PRD: "Everything else on a fresh student record is server-initialised:
    `entitlement_days_remaining` opens equal to `entitlement_days_granted`,
    `coe_status` opens at `NOT_SUBMITTED`, `account_hold_status` opens at `NONE`,
    `benefit_payment_protected` opens false, `open_debt_principal_cents` opens at
    0, and `coe_verified_on`, `verified_document_reference` and `protected_until`
    all open null."

    Design: Corner/entities/veteran_student_creation_applies_every_declared_default
    """
    officials = create_officials(api)

    student = get_success_data(
        api.create_veteran_student(
            f.veteran_student_payload(), officials.sco_headers
        ),
        expected_status=201,
    )
    a.assert_common_fields(student, expected_version=1)
    a.assert_fields(
        student,
        {
            "student_number": c.STUDENT_NUMBER,
            "full_name": c.STUDENT_NAME,
            "chapter": c.STUDENT_CHAPTER_CH33,
            "benefit_level_pct": c.STUDENT_BENEFIT_LEVEL_PCT,
            "entitlement_days_granted": c.ENTITLEMENT_DAYS_GRANTED,
            "entitlement_days_remaining": c.ENTITLEMENT_DAYS_GRANTED,
            "coe_status": c.COE_STATUS_NOT_SUBMITTED,
            "coe_issued_on": None,
            "coe_verified_on": None,
            "verified_document_reference": None,
            "protected_until": None,
            "account_hold_status": c.ACCOUNT_HOLD_NONE,
            "benefit_payment_protected": False,
            "open_debt_principal_cents": 0,
        },
    )


def test_drafting_a_certification_already_carries_its_derived_enrollment_block(
    api, baseline
):
    """The pursuit percentage and the housing rate are present in the draft itself.

    PRD: "Next, `rate_of_pursuit_pct` expresses the load as an integer percentage
    of the program's own definition of full time — take `credit_hours_total`,
    multiply by 100, divide by the program's `full_time_credit_hours`, and round
    the result half up to a whole percent."

    Design: Corner/entities/certification_creation_computes_the_pursuit_and_housing_rate_fields
    """
    student_id = create_student(api, baseline.sco_headers)

    certification = get_success_data(
        api.create_enrollment_certification(
            f.certification_payload(student_id, baseline.term_id, baseline.program_id),
            baseline.sco_headers,
        ),
        expected_status=201,
    )
    a.assert_common_fields(certification, expected_version=1)
    a.assert_derived_enrollment_block(
        certification,
        certified_days=c.CANONICAL_CERTIFIED_DAYS,
        rate_of_pursuit_pct=100,
        rop_tier_pct=100,
        training_time=c.TRAINING_TIME_FULL,
        modality=c.MODALITY_RESIDENTIAL,
        mha_eligible=True,
        mha_monthly_rate_cents=c.CAMPUS_BAH_MONTHLY_CENTS,
    )
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_DRAFT,
            "amount_basis": None,
            "mha_term_total_cents": 0,
            "va_tuition_cents": 0,
            "entitlement_days_charged": 0,
        },
    )


# ─── Reading the stored row back ───────────────────────────────────────
def test_a_verified_student_reads_back_its_verification_stamps(api, baseline):
    """The verification date and the window it opened survive the round trip.

    PRD: "It then opens the statutory protection window by setting
    `protected_until` to 90 days after `coe_verified_on`, and finally recomputes
    the student's `benefit_payment_protected` snapshot."

    Design: Corner/entities/get_by_id_returns_the_stored_row_for_each_written_entity
    """
    student_id = create_verified_student(api, baseline.sco_headers)

    student = get_success_data(
        api.get_veteran_student(student_id, baseline.sup_headers)
    )
    a.assert_fields(
        student,
        {
            "id": student_id,
            "student_number": c.STUDENT_NUMBER,
            "chapter": c.STUDENT_CHAPTER_CH33,
            "coe_status": c.COE_STATUS_VERIFIED,
            "coe_issued_on": c.COE_ISSUED_ON,
            "coe_verified_on": c.CLOCK_START_DATE,
            "verified_document_reference": c.COE_REFERENCE,
            "protected_until": "2026-10-30",
        },
    )


def test_a_tuition_report_reads_back_the_covered_amount_it_derived(api, baseline):
    """Nothing on the report is write-only, including its own arithmetic.

    PRD: "From those four figures the report derives its own `net_covered_cents`:
    add `gross_tuition_cents` and `mandatory_fees_cents`, subtract
    `tuition_specific_aid_cents`, and floor the result at 0 so that aid exceeding
    the assessment yields zero rather than a negative covered amount."

    Design: Corner/entities/get_by_id_returns_the_stored_row_for_each_written_entity
    """
    student_id = create_verified_student(api, baseline.sco_headers)
    certification_id, version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )
    report_id, _next_version = price_certification(api, certification_id, version)

    report = get_success_data(api.get_tuition_fee_report(report_id, BURSAR_HEADERS))
    a.assert_integer_cents(
        report,
        "gross_tuition_cents",
        "mandatory_fees_cents",
        "tuition_specific_aid_cents",
        "non_tuition_aid_cents",
        "net_covered_cents",
    )
    a.assert_fields(
        report,
        {
            "id": report_id,
            "certification_id": certification_id,
            "gross_tuition_cents": c.GROSS_TUITION_CENTS,
            "mandatory_fees_cents": c.MANDATORY_FEES_CENTS,
            "tuition_specific_aid_cents": c.TUITION_SPECIFIC_AID_CENTS,
            "non_tuition_aid_cents": c.NON_TUITION_AID_CENTS,
            "net_covered_cents": c.CANONICAL_NET_COVERED_CENTS,
            "status": c.TUITION_REPORT_STATUS_REPORTED,
        },
    )
    term = get_success_data(
        api.get_academic_term(baseline.term_id, baseline.sup_headers)
    )
    a.assert_fields(
        term,
        {
            "term_code": c.TERM_CODE,
            "start_date": c.TERM_START,
            "end_date": c.TERM_END,
            "status": c.TERM_STATUS_OPEN,
        },
    )


# ─── Collection windows and filters ────────────────────────────────────
def _three_drafts_in_one_term(api, baseline):
    """Three students, one certification each, all sitting at DRAFT."""
    ids = []
    for number, name, delimiting in (
        (c.STUDENT_NUMBER, c.STUDENT_NAME, c.DELIMITING_DATE),
        (c.SECOND_STUDENT_NUMBER, c.SECOND_STUDENT_NAME, c.SECOND_DELIMITING_DATE),
        (c.THIRD_STUDENT_NUMBER, c.THIRD_STUDENT_NAME, c.THIRD_DELIMITING_DATE),
    ):
        student_id = create_student(
            api,
            baseline.sco_headers,
            student_number=number,
            full_name=name,
            delimiting_date=delimiting,
        )
        certification_id, _version = create_certification(
            api,
            baseline.sco_headers,
            student_id,
            baseline.term_id,
            baseline.program_id,
        )
        ids.append((student_id, certification_id))
    return ids


def test_the_page_window_slides_while_the_total_count_stays_whole(api, baseline):
    """Two rows then one row, with the total counted before the window is applied.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the number of
    items matching the filters before pagination is applied and `has_more`
    indicates whether any matching item remains beyond the current window."

    Design: Corner/entities/list_enrollment_certifications_filters_by_status_and_paginates
    """
    ids = _three_drafts_in_one_term(api, baseline)

    first_page, first_meta = validate_paginated(
        api.list_enrollment_certifications(
            baseline.sup_headers,
            {"term_id": baseline.term_id, "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_enrollment_certifications(
            baseline.sup_headers,
            {"term_id": baseline.term_id, "limit": 2, "offset": 2},
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    seen = [row["id"] for row in first_page + second_page]
    assert sorted(seen) == sorted(certification_id for _student, certification_id in ids)


def test_the_status_and_student_filters_are_applied_before_the_page(api, baseline):
    """No draft matches CERTIFIED, and one student matches exactly one row.

    PRD: "Enrollment certifications may be filtered by `student_id`, `term_id`,
    `program_id`, `pinned_catalog_version_id`, `submitted_by_official_id`,
    `certified_by_official_id` and `status`."

    Design: Corner/entities/list_enrollment_certifications_filters_by_status_and_paginates
    """
    ids = _three_drafts_in_one_term(api, baseline)
    second_student_id, second_certification_id = ids[1]

    certified, certified_meta = validate_paginated(
        api.list_enrollment_certifications(
            baseline.sup_headers,
            {"term_id": baseline.term_id, "status": c.CERT_STATUS_CERTIFIED},
        )
    )
    assert certified == []
    assert certified_meta["total_count"] == 0
    assert certified_meta["has_more"] is False

    by_student, _meta = validate_paginated(
        api.list_enrollment_certifications(
            baseline.sup_headers, {"student_id": second_student_id}
        )
    )
    assert len(by_student) == 1
    a.assert_fields(
        by_student[0],
        {"id": second_certification_id, "student_id": second_student_id},
    )


# ─── The per-entity not-found vocabulary ───────────────────────────────
@pytest.mark.parametrize(
    "reader_name,expected_error",
    [
        ("get_certifying_official", e.ERR_OFFICIAL_NOT_FOUND),
        ("get_veteran_student", e.ERR_STUDENT_NOT_FOUND),
        ("get_academic_term", e.ERR_TERM_NOT_FOUND),
        ("get_program", e.ERR_PROGRAM_NOT_FOUND),
        ("get_catalog_version", e.ERR_CATALOG_VERSION_NOT_FOUND),
        ("get_yellow_ribbon_agreement", e.ERR_AGREEMENT_NOT_FOUND),
        ("get_enrollment_certification", e.ERR_CERTIFICATION_NOT_FOUND),
        ("get_tuition_fee_report", e.ERR_TUITION_REPORT_NOT_FOUND),
        ("get_yellow_ribbon_award", e.ERR_AWARD_NOT_FOUND),
        ("get_enrollment_change_report", e.ERR_CHANGE_REPORT_NOT_FOUND),
        ("get_benefit_debt", e.ERR_DEBT_NOT_FOUND),
        ("get_student_account_charge", e.ERR_CHARGE_NOT_FOUND),
    ],
)
def test_each_resource_answers_an_unknown_id_with_its_own_not_found(
    api, reader_name, expected_error
):
    """A client can tell which link in a chain is broken from the code alone.

    PRD: "Every id embedded in the URL path resolves, validated left to right,
    else HTTP 404 carrying the code for the first unresolved id:
    `ERR_OFFICIAL_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_TERM_NOT_FOUND`,
    `ERR_PROGRAM_NOT_FOUND`, `ERR_CATALOG_VERSION_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_TUITION_REPORT_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_CHANGE_REPORT_NOT_FOUND`, `ERR_DEBT_NOT_FOUND` or
    `ERR_CHARGE_NOT_FOUND`."

    Design: Corner/entities/every_path_id_lookup_returns_its_entity_scoped_not_found
    """
    officials = create_officials(api)

    response = getattr(api, reader_name)(NON_EXISTENT_UUID, officials.sup_headers)
    validate_error(response, expected_error, 404)


# ─── Request shape ─────────────────────────────────────────────────────
def test_each_write_missing_one_required_field_is_rejected_and_stores_nothing(
    api, baseline
):
    """Required-ness is enforced field by field, not only on an empty body.

    PRD: "The body parses, every required input field is present, every field
    carries its declared type, and every enum-typed field carries a declared
    member, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/omitting_a_required_input_field_is_rejected_with_invalid_request
    """
    student_id = create_student(api, baseline.sco_headers)
    certification_id, version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )

    attempts = [
        api.create_certifying_official(
            f.sco_official_payload(
                full_name="No Level", email="no.level@u.edu", official_level=None
            ),
            VA_HEADERS,
        ),
        api.create_academic_term(
            f.spring_term_payload(term_type=None), baseline.sup_headers
        ),
        api.create_enrollment_certification(
            f.certification_payload(
                student_id,
                baseline.term_id,
                baseline.program_id,
                credit_hours_online=None,
            ),
            baseline.sco_headers,
        ),
        api.create_tuition_fee_report(
            f.tuition_fee_report_payload(
                certification_id, version, gross_tuition_cents=None
            ),
            BURSAR_HEADERS,
        ),
    ]
    for response in attempts:
        validate_error(response, e.ERR_INVALID_REQUEST, 400)

    terms = get_success_data(api.list_academic_terms(baseline.sup_headers))
    assert [term["term_code"] for term in terms] == [c.TERM_CODE]
    certifications = get_success_data(
        api.list_enrollment_certifications(baseline.sup_headers)
    )
    assert [row["id"] for row in certifications] == [certification_id]
    reports = get_success_data(
        api.list_tuition_fee_reports(
            BURSAR_HEADERS, {"certification_id": certification_id}
        )
    )
    assert reports == []
    assert read_certification(api, baseline.sco_headers, certification_id)[
        "version"
    ] == version


def test_undeclared_enum_members_and_out_of_range_numbers_are_rejected(api, baseline):
    """An unknown chapter, an off-list benefit level and a zero credit load all fail.

    PRD: "The registration carries the institutional `student_number`, the
    student's `full_name`, the benefit `chapter` under which they are entitled —
    one of `CH30`, `CH31`, `CH33`, `CH35` or `CH1606` — and the
    `benefit_level_pct` printed on their Certificate of Eligibility, which VA
    issues only at 40, 50, 60, 70, 80, 90 or 100."

    Design: Corner/entities/undeclared_enum_members_and_out_of_range_numbers_return_invalid_request
    """
    student_id = create_student(api, baseline.sco_headers)

    attempts = [
        api.create_veteran_student(
            f.veteran_student_payload(
                student_number="V-9001", full_name="Bad Chapter", chapter="CH99"
            ),
            baseline.sco_headers,
        ),
        api.create_veteran_student(
            f.veteran_student_payload(
                student_number="V-9002", full_name="Bad Level", benefit_level_pct=55
            ),
            baseline.sco_headers,
        ),
        api.create_enrollment_certification(
            f.certification_payload(
                student_id,
                baseline.term_id,
                baseline.program_id,
                credit_hours_total=0,
            ),
            baseline.sco_headers,
        ),
    ]
    for response in attempts:
        validate_error(response, e.ERR_INVALID_REQUEST, 400)

    students = get_success_data(api.list_veteran_students(baseline.sup_headers))
    assert [row["student_number"] for row in students] == [c.STUDENT_NUMBER]
    certifications = get_success_data(
        api.list_enrollment_certifications(baseline.sup_headers)
    )
    assert certifications == []


def test_a_page_limit_above_the_declared_maximum_is_rejected(api, baseline):
    """101 is one past the largest accepted page size.

    PRD: "A `limit` below 1 or above 100, or a negative `offset`, is a malformed
    request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/undeclared_enum_members_and_out_of_range_numbers_return_invalid_request
    """
    response = api.list_veteran_students(
        baseline.sup_headers, {"limit": 101, "offset": 0}
    )
    validate_error(response, e.ERR_INVALID_REQUEST, 400)


def test_client_supplied_system_and_computed_fields_are_overwritten(api, baseline):
    """A body that plants an id, a version and a state does not get to keep them.

    PRD: "Every resource in this service carries a server-minted `id`: a UUID
    string with no type prefix."

    Design: Corner/entities/client_supplied_system_and_computed_fields_are_input_ignored
    """
    student = get_success_data(
        api.create_veteran_student(
            f.veteran_student_payload(
                id=PLANTED_ID,
                created_at=PLANTED_CREATED_AT,
                version=99,
                coe_status=c.COE_STATUS_VERIFIED,
                entitlement_days_remaining=5,
                open_debt_principal_cents=777,
            ),
            baseline.sco_headers,
        ),
        expected_status=201,
    )
    a.assert_common_fields(student, expected_version=1)
    assert student["id"] != PLANTED_ID
    assert student["created_at"] != PLANTED_CREATED_AT
    a.assert_fields(
        student,
        {
            "coe_status": c.COE_STATUS_NOT_SUBMITTED,
            "entitlement_days_remaining": c.ENTITLEMENT_DAYS_GRANTED,
            "open_debt_principal_cents": 0,
        },
    )

    certification = get_success_data(
        api.create_enrollment_certification(
            f.certification_payload(
                student["id"],
                baseline.term_id,
                baseline.program_id,
                status=c.CERT_STATUS_CERTIFIED,
                certified_days=1,
                entitlement_days_charged=999,
            ),
            baseline.sco_headers,
        ),
        expected_status=201,
    )
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_DRAFT,
            "certified_days": c.CANONICAL_CERTIFIED_DAYS,
            "entitlement_days_charged": 0,
        },
    )


# ─── The append-only audit trail ───────────────────────────────────────
def test_an_audit_entry_exposes_no_version_and_no_updated_at(api, baseline):
    """The trail is the one resource that is not a mutable row.

    PRD: "The `CertificationAuditEntry` is the exception. It is append-only and
    immutable once written, so it carries only `id` and `created_at`: both
    `updated_at` and `version` are absent from an audit entry."

    Design: Corner/entities/certification_audit_entries_are_append_only_and_carry_no_version
    """
    scenario = build_certified_certification(api, baseline)

    entries = get_success_data(
        api.list_audit_entries(scenario.certification_id, baseline.sup_headers)
    )
    assert len(entries) == 2
    for entry in entries:
        a.assert_audit_entry_shape(entry)


def test_a_later_event_appends_without_rewriting_the_earlier_entries(api, baseline):
    """Sequence indices 1 and 2 keep their event types once a third arrives.

    PRD: "The `sequence_index` is a per-certification counter that starts at 1 and
    is assigned in ascending `created_at` order of the entries on that
    certification."

    Design: Corner/entities/certification_audit_entries_are_append_only_and_carry_no_version
    """
    scenario = build_certified_certification(api, baseline)
    before = get_success_data(
        api.list_audit_entries(scenario.certification_id, baseline.sup_headers)
    )
    first_entry_id = before[0]["id"]

    record_va_payment(api, scenario.certification_id, 2790000, 776444, "2026-08-15")

    after = get_success_data(
        api.list_audit_entries(scenario.certification_id, baseline.sup_headers)
    )
    assert [entry["sequence_index"] for entry in after] == [1, 2, 3]
    a.assert_event_sequence(
        after,
        [
            c.EVENT_CERTIFICATION_SUBMITTED,
            c.EVENT_CERTIFICATION_CERTIFIED,
            c.EVENT_VA_PAYMENT_RECORDED,
        ],
    )
    preserved = [entry for entry in after if entry["id"] == first_entry_id]
    assert len(preserved) == 1
    a.assert_fields(
        preserved[0],
        {
            "sequence_index": 1,
            "event_type": c.EVENT_CERTIFICATION_SUBMITTED,
            "actor_user_id": baseline.sco_id,
        },
    )


# ─── Body foreign keys ─────────────────────────────────────────────────
def test_body_foreign_keys_answer_in_their_declared_resolution_order(api, baseline):
    """Three unknown references produce the student's code, then the term's, then the program's.

    PRD: "Only once every path identifier resolves does the server resolve the
    foreign keys carried in the request body, and those are resolved in the fixed
    order `student_id`, `term_id`, `program_id`, `certification_id`,
    `agreement_id`, regardless of the order in which the client happened to
    serialise them."

    Design: Corner/entities/body_foreign_keys_are_resolved_in_the_declared_left_to_right_order
    """
    student_id = create_student(api, baseline.sco_headers)

    all_unknown = api.create_enrollment_certification(
        f.certification_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID),
        baseline.sco_headers,
    )
    validate_error(all_unknown, e.ERR_STUDENT_NOT_FOUND, 404)

    student_known = api.create_enrollment_certification(
        f.certification_payload(student_id, NON_EXISTENT_UUID, NON_EXISTENT_UUID),
        baseline.sco_headers,
    )
    validate_error(student_known, e.ERR_TERM_NOT_FOUND, 404)

    term_known = api.create_enrollment_certification(
        f.certification_payload(student_id, baseline.term_id, NON_EXISTENT_UUID),
        baseline.sco_headers,
    )
    validate_error(term_known, e.ERR_PROGRAM_NOT_FOUND, 404)

    certifications = get_success_data(
        api.list_enrollment_certifications(baseline.sup_headers)
    )
    assert certifications == []


def test_a_new_term_and_program_pair_is_still_creatable_after_the_refusals(
    api, baseline
):
    """Once all three references resolve the draft is written exactly once.

    PRD: "The new certification opens with `status` at `DRAFT` and `amount_basis`
    null; over its life its `status` moves among `DRAFT`, `SUBMITTED`, `RETURNED`,
    `CERTIFIED`, `AMENDMENT_PENDING`, `TERMINATED` and `VOID`, of which the last
    two are terminal."

    Design: Corner/entities/body_foreign_keys_are_resolved_in_the_declared_left_to_right_order
    """
    student_id = create_student(api, baseline.sco_headers)
    api.create_enrollment_certification(
        f.certification_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID),
        baseline.sco_headers,
    )

    certification = get_success_data(
        api.create_enrollment_certification(
            f.certification_payload(student_id, baseline.term_id, baseline.program_id),
            baseline.sco_headers,
        ),
        expected_status=201,
    )
    a.assert_fields(
        certification, {"status": c.CERT_STATUS_DRAFT, "amount_basis": None}
    )
    certifications = get_success_data(
        api.list_enrollment_certifications(baseline.sup_headers)
    )
    assert [row["id"] for row in certifications] == [certification["id"]]
