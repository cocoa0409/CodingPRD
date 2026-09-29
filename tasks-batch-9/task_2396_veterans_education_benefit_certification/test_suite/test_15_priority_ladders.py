"""Requests that break two rules at once, and the rule that decides the answer.

Each scenario is arranged so that a naive implementation would surface the later
rule: the ladder position is the whole point of the assertion.
"""

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
    Baseline,
    build_certified_certification,
    build_submitted_certification,
    create_agreement,
    create_approved_program,
    create_award,
    create_certification,
    create_student,
    create_term,
    create_verified_student,
    read_agreement,
    read_certification,
    read_student,
    submit_certification,
)
from test_helpers.test_users import BURSAR_HEADERS, make_sco_headers

STALE_VERSION = 99

SHORT_DELIMITING_DATE = "2026-10-01"
PERIOD_INSIDE_DELIMITING_END = "2026-09-30"
PERIOD_PAST_DELIMITING_END = "2026-12-15"
PERIOD_BEFORE_TERM_START = "2026-08-20"
LATER_WINDOW_START = "2027-07-01"
LATER_WINDOW_END = "2028-07-01"
LATER_CATALOG_YEAR = "2027-2028"

SHORT_ENTITLEMENT_DAYS = 100
EXPECTED_DAYS_CHARGED = 110
EXPECTED_DAYS_REMAINING = 970

SINGLE_PARTICIPANT = 1
INELIGIBLE_BENEFIT_LEVEL_PCT = 80
EXPECTED_SCHOOL_SHARE_CENTS = 80000
EXPECTED_POOL_AFTER_AWARD_CENTS = 920000

def _baseline_whose_catalog_starts_next_year(api, officials):
    """A term and a program whose only approved catalog governs the following year."""
    program_id, catalog_id = create_approved_program(
        api,
        officials.sup_headers,
        catalog_overrides={
            "catalog_year": LATER_CATALOG_YEAR,
            "effective_start": LATER_WINDOW_START,
            "effective_end": LATER_WINDOW_END,
        },
    )
    return Baseline(
        officials=officials,
        program_id=program_id,
        catalog_id=catalog_id,
        term_id=create_term(api, officials.sup_headers),
    )


# ─── The global ladder ────────────────────────────────────────────────
def test_the_role_check_precedes_body_validation(api, officials):
    """A front-line official posting a malformed term body is told about the role.

    PRD: "Validations are evaluated in ascending priority order and the **first**
    violated rule decides the response; no later rule can mask an earlier one."

    Design: Corner/validations/the_validation_ladder_rejects_on_its_lowest_numbered_applicable_rule
    """
    response = api.create_academic_term(
        f.academic_term_payload(start_date=None, end_date=None),
        officials.sco_headers,
    )
    validate_error(response, "ERR_UNAUTHORIZED", expected_status=403)

    _rows, meta = validate_paginated(api.list_academic_terms(officials.sup_headers))
    assert meta["total_count"] == 0


def test_the_body_shape_check_precedes_the_foreign_key_lookup(api, baseline):
    """A missing credit-hour load is reported before an unresolvable student.

    PRD: "Validations are evaluated in ascending priority order and the **first**
    violated rule decides the response; no later rule can mask an earlier one."

    Design: Corner/validations/the_validation_ladder_rejects_on_its_lowest_numbered_applicable_rule
    """
    response = api.create_enrollment_certification(
        f.certification_payload(
            NON_EXISTENT_UUID,
            baseline.term_id,
            baseline.program_id,
            credit_hours_total=None,
        ),
        baseline.sco_headers,
    )
    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

    _rows, meta = validate_paginated(
        api.list_enrollment_certifications(baseline.sco_headers)
    )
    assert meta["total_count"] == 0


def test_the_identity_check_precedes_the_uniqueness_check(api, baseline):
    """A supervisory identity claiming the front-line tier never reaches the collision.

    PRD: "Validations are evaluated in ascending priority order and the **first**
    violated rule decides the response; no later rule can mask an earlier one."

    Design: Corner/validations/the_validation_ladder_rejects_on_its_lowest_numbered_applicable_rule
    """
    create_student(api, baseline.sco_headers)

    response = api.create_veteran_student(
        f.veteran_student_payload(), make_sco_headers(baseline.sup_id)
    )
    validate_error(response, "ERR_OFFICIAL_LEVEL_MISMATCH", expected_status=403)

    _rows, meta = validate_paginated(api.list_veteran_students(baseline.sco_headers))
    assert meta["total_count"] == 1


def test_the_body_foreign_key_precedes_the_version_comparison(api, baseline):
    """An unknown certification answers 404 rather than the concurrency 412.

    PRD: "Validations are evaluated in ascending priority order and the **first**
    violated rule decides the response; no later rule can mask an earlier one."

    Design: Corner/validations/the_validation_ladder_rejects_on_its_lowest_numbered_applicable_rule
    """
    student_id = create_student(api, baseline.sco_headers)
    certification_id, version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )

    response = api.create_tuition_fee_report(
        f.tuition_fee_report_payload(NON_EXISTENT_UUID, STALE_VERSION), BURSAR_HEADERS
    )
    validate_error(response, "ERR_CERTIFICATION_NOT_FOUND", expected_status=404)

    _rows, meta = validate_paginated(api.list_tuition_fee_reports(BURSAR_HEADERS))
    assert meta["total_count"] == 0
    assert (
        read_certification(api, baseline.sco_headers, certification_id)["version"]
        == version
    )


# ─── Submit-time temporal and referential gates ───────────────────────
def _short_dated_student(api, baseline):
    """A verified student whose entitlement expires on 2026-10-01."""
    return create_verified_student(
        api, baseline.sco_headers, delimiting_date=SHORT_DELIMITING_DATE
    )


def test_the_closed_term_answers_before_the_delimiting_date(api, baseline):
    """A period that also runs past the delimiting date still reports the term.

    PRD: "Validations are evaluated in ascending priority order and the **first**
    violated rule decides the response; no later rule can mask an earlier one."

    Design: Corner/validations/submit_time_temporal_and_referential_gates_fire_in_priority_order
    """
    student_id = _short_dated_student(api, baseline)
    certification_id, _version = create_certification(
        api,
        baseline.sco_headers,
        student_id,
        baseline.term_id,
        baseline.program_id,
        term_end_certified=PERIOD_PAST_DELIMITING_END,
    )
    get_success_data(api.close_academic_term(baseline.term_id, {}, baseline.sup_headers))

    response = api.submit_certification(certification_id, {}, baseline.sco_headers)
    validate_error(response, "ERR_TERM_CLOSED", expected_status=409)

    certification = read_certification(api, baseline.sco_headers, certification_id)
    a.assert_fields(
        certification,
        {"status": c.CERT_STATUS_DRAFT, "pinned_catalog_version_id": None},
    )


def test_the_delimiting_date_answers_before_the_catalog_lookup(api, officials):
    """The expiry is reported even though no approved catalog governs the start.

    PRD: "Validations are evaluated in ascending priority order and the **first**
    violated rule decides the response; no later rule can mask an earlier one."

    Design: Corner/validations/submit_time_temporal_and_referential_gates_fire_in_priority_order
    """
    baseline = _baseline_whose_catalog_starts_next_year(api, officials)
    student_id = _short_dated_student(api, baseline)
    certification_id, _version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )

    response = api.submit_certification(certification_id, {}, baseline.sco_headers)
    validate_error(response, "ERR_DELIMITING_DATE_PASSED", expected_status=422)

    certification = read_certification(api, baseline.sco_headers, certification_id)
    a.assert_fields(
        certification,
        {"status": c.CERT_STATUS_DRAFT, "pinned_catalog_version_id": None},
    )


def test_the_term_bounds_answer_before_the_catalog_lookup(api, officials):
    """A start before the first instructional day is reported before the catalog.

    PRD: "Validations are evaluated in ascending priority order and the **first**
    violated rule decides the response; no later rule can mask an earlier one."

    Design: Corner/validations/submit_time_temporal_and_referential_gates_fire_in_priority_order
    """
    baseline = _baseline_whose_catalog_starts_next_year(api, officials)
    student_id = _short_dated_student(api, baseline)
    certification_id, _version = create_certification(
        api,
        baseline.sco_headers,
        student_id,
        baseline.term_id,
        baseline.program_id,
        term_start_certified=PERIOD_BEFORE_TERM_START,
        term_end_certified=PERIOD_INSIDE_DELIMITING_END,
    )

    response = api.submit_certification(certification_id, {}, baseline.sco_headers)
    validate_error(response, "ERR_CERTIFIED_DATES_OUTSIDE_TERM", expected_status=422)

    certification = read_certification(api, baseline.sco_headers, certification_id)
    a.assert_fields(
        certification,
        {"status": c.CERT_STATUS_DRAFT, "pinned_catalog_version_id": None},
    )


def test_only_a_submission_that_clears_the_earlier_gates_reaches_the_catalog(
    api, officials
):
    """With the term, the expiry and the bounds all satisfied, the catalog decides.

    PRD: "And an approved catalog version must actually govern the start of the
    period, else `ERR_CATALOG_VERSION_NOT_EFFECTIVE`."

    Design: Corner/validations/submit_time_temporal_and_referential_gates_fire_in_priority_order
    """
    baseline = _baseline_whose_catalog_starts_next_year(api, officials)
    student_id = _short_dated_student(api, baseline)
    certification_id, _version = create_certification(
        api,
        baseline.sco_headers,
        student_id,
        baseline.term_id,
        baseline.program_id,
        term_end_certified=PERIOD_INSIDE_DELIMITING_END,
    )

    response = api.submit_certification(certification_id, {}, baseline.sco_headers)
    validate_error(response, "ERR_CATALOG_VERSION_NOT_EFFECTIVE", expected_status=422)

    certification = read_certification(api, baseline.sco_headers, certification_id)
    a.assert_fields(
        certification,
        {"status": c.CERT_STATUS_DRAFT, "pinned_catalog_version_id": None},
    )


# ─── Certify's pricing and entitlement prerequisites ──────────────────
def test_certify_refuses_a_submission_that_was_never_priced(api, baseline):
    """Nothing has told the service what the term costs, so certification stops.

    PRD: "A tuition and fee report with `status` `REPORTED` must exist for the
    certification, else `ERR_TUITION_REPORT_MISSING`."

    Design: Corner/validations/certify_passes_only_once_pricing_and_entitlement_prerequisites_are_satisfied
    """
    student_id = create_verified_student(api, baseline.sco_headers)
    certification_id, _version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )
    submit_certification(api, baseline.sco_headers, certification_id)

    response = api.certify_certification(certification_id, {}, baseline.sup_headers)
    validate_error(response, "ERR_TUITION_REPORT_MISSING", expected_status=422)

    assert (
        read_certification(api, baseline.sco_headers, certification_id)["status"]
        == c.CERT_STATUS_SUBMITTED
    )


def test_certify_refuses_a_charge_larger_than_the_remaining_entitlement(api, baseline):
    """A 110-day charge against 100 remaining days is refused, not truncated.

    PRD: "And the entitlement charge the certification is about to make must not
    exceed the student's `entitlement_days_remaining`, else
    `ERR_INSUFFICIENT_ENTITLEMENT`."

    Design: Corner/validations/certify_passes_only_once_pricing_and_entitlement_prerequisites_are_satisfied
    """
    scenario = build_submitted_certification(
        api,
        baseline,
        student_overrides={"entitlement_days_granted": SHORT_ENTITLEMENT_DAYS},
    )

    response = api.certify_certification(
        scenario.certification_id, {}, baseline.sup_headers
    )
    validate_error(response, "ERR_INSUFFICIENT_ENTITLEMENT", expected_status=422)

    certification = read_certification(
        api, baseline.sco_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {"status": c.CERT_STATUS_SUBMITTED, "entitlement_days_charged": 0},
    )
    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["entitlement_days_remaining"] == SHORT_ENTITLEMENT_DAYS


def test_the_same_certification_passes_once_the_entitlement_is_sufficient(
    api, baseline
):
    """An identically shaped student with a full grant absorbs the whole charge.

    PRD: "That figure is what the seventh precondition above tests against
    `entitlement_days_remaining`, and once the certification succeeds the student's
    `entitlement_days_remaining` is debited by exactly it, leaving remaining
    entitlement equal to granted entitlement minus everything currently charged."

    Design: Corner/validations/certify_passes_only_once_pricing_and_entitlement_prerequisites_are_satisfied
    """
    scenario = build_certified_certification(api, baseline)

    certification = read_certification(
        api, baseline.sco_headers, scenario.certification_id
    )
    assert certification["entitlement_days_charged"] == EXPECTED_DAYS_CHARGED
    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["entitlement_days_remaining"] == EXPECTED_DAYS_REMAINING
    a.assert_entitlement_ledger_balances(student, EXPECTED_DAYS_CHARGED)


# ─── Yellow Ribbon: eligibility before the participant cap ────────────
def _agreement_with_one_seat_taken(api, baseline):
    """A one-seat agreement whose only seat is held by an eligible student's award."""
    scenario = build_certified_certification(api, baseline)
    agreement_id, version = create_agreement(
        api, baseline.sup_headers, max_participants=SINGLE_PARTICIPANT
    )
    award = create_award(
        api, baseline.sup_headers, scenario.certification_id, agreement_id, version
    )
    return agreement_id, award


def _certified_certification_for_another_student(api, baseline, **student_overrides):
    """A second certified certification belonging to a different student."""
    overrides = {
        "student_number": c.SECOND_STUDENT_NUMBER,
        "full_name": c.SECOND_STUDENT_NAME,
    }
    overrides.update(student_overrides)
    return build_certified_certification(api, baseline, student_overrides=overrides)


def test_an_ineligible_benefit_level_answers_before_the_participant_cap(api, baseline):
    """The 80 percent student is turned away on eligibility, not on the full seat.

    PRD: "Validations are evaluated in ascending priority order and the **first**
    violated rule decides the response; no later rule can mask an earlier one."

    Design: Corner/validations/yellow_ribbon_eligibility_is_checked_before_the_participant_cap
    """
    agreement_id, _award = _agreement_with_one_seat_taken(api, baseline)
    other = _certified_certification_for_another_student(
        api, baseline, benefit_level_pct=INELIGIBLE_BENEFIT_LEVEL_PCT
    )
    agreement = read_agreement(api, baseline.sup_headers, agreement_id)

    response = api.create_yellow_ribbon_award(
        f.yellow_ribbon_award_payload(
            other.certification_id, agreement_id, agreement["version"]
        ),
        baseline.sup_headers,
    )
    validate_error(response, "ERR_YR_INELIGIBLE_STUDENT", expected_status=422)


def test_an_eligible_student_meets_the_participant_cap(api, baseline):
    """With the single seat taken the fiscal gate is what refuses the award.

    PRD: "On award creation, the agreement's `participant_count` is strictly less
    than its `max_participants`, else `ERR_YR_PARTICIPANT_LIMIT_REACHED` (409)."

    Design: Corner/validations/yellow_ribbon_eligibility_is_checked_before_the_participant_cap
    """
    agreement_id, _award = _agreement_with_one_seat_taken(api, baseline)
    other = _certified_certification_for_another_student(api, baseline)
    agreement = read_agreement(api, baseline.sup_headers, agreement_id)

    response = api.create_yellow_ribbon_award(
        f.yellow_ribbon_award_payload(
            other.certification_id, agreement_id, agreement["version"]
        ),
        baseline.sup_headers,
    )
    validate_error(response, "ERR_YR_PARTICIPANT_LIMIT_REACHED", expected_status=409)


def test_neither_refused_award_debits_the_pool(api, baseline):
    """Only the one accepted award moved the agreement's ledgers.

    PRD: "Award creation debits the agreement: `pool_remaining_cents` falls by
    `school_share_cents`, `participant_count` rises by one, and the agreement's
    `version` increments by one."

    Design: Corner/validations/yellow_ribbon_eligibility_is_checked_before_the_participant_cap
    """
    agreement_id, award = _agreement_with_one_seat_taken(api, baseline)
    ineligible = _certified_certification_for_another_student(
        api, baseline, benefit_level_pct=INELIGIBLE_BENEFIT_LEVEL_PCT
    )
    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    validate_error(
        api.create_yellow_ribbon_award(
            f.yellow_ribbon_award_payload(
                ineligible.certification_id, agreement_id, agreement["version"]
            ),
            baseline.sup_headers,
        ),
        "ERR_YR_INELIGIBLE_STUDENT",
        expected_status=422,
    )

    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {
            "participant_count": SINGLE_PARTICIPANT,
            "pool_remaining_cents": EXPECTED_POOL_AFTER_AWARD_CENTS,
        },
    )
    rows, meta = validate_paginated(
        api.list_yellow_ribbon_awards(baseline.sup_headers)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == award["id"]
    a.assert_fields(
        rows[0],
        {
            "school_share_cents": EXPECTED_SCHOOL_SHARE_CENTS,
            "va_match_cents": EXPECTED_SCHOOL_SHARE_CENTS,
        },
    )
