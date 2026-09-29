"""Requests that violate two rules at once and must fail on the earlier one.

Validations are evaluated in ascending priority order, so a state gate outranks a
fiscal gate, a program-approval safety check outranks a deadline, and a
referential scope check outranks a uniqueness constraint.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_certified_certification,
    build_submitted_certification,
    create_agreement,
    create_award,
    create_catalog_version,
    read_agreement,
    read_agreement_version,
    read_certification,
    read_student,
    set_clock_to,
)

PAST_DEADLINE_DATE = "2026-10-05"
NEXT_CATALOG_YEAR = "2027-2028"
NEXT_CATALOG_START = "2027-07-01"
NEXT_CATALOG_END = "2028-07-01"


# ─── A state gate outranks the pool check ─────────────────────────────
def _drained_pool_and_an_uncertified_certification(api, baseline):
    """One award empties an 80000-cent pool; a second student is only SUBMITTED."""
    certified = build_certified_certification(api, baseline)
    agreement_id, agreement_version = create_agreement(
        api,
        baseline.sup_headers,
        annual_pool_cents=80000,
        max_participants=5,
    )
    create_award(
        api,
        baseline.sup_headers,
        certified.certification_id,
        agreement_id,
        agreement_version,
    )

    submitted = build_submitted_certification(
        api,
        baseline,
        student_overrides={
            "student_number": c.SECOND_STUDENT_NUMBER,
            "full_name": c.SECOND_STUDENT_NAME,
            "delimiting_date": c.SECOND_DELIMITING_DATE,
        },
    )
    return agreement_id, submitted


def test_the_certification_state_gate_fires_before_the_pool_check(api, baseline):
    """An uncertified certification is refused for its status, not for the empty pool.

    PRD: "Then the state gates, in the order the transition lists them: the
    certification's `status` must be `CERTIFIED`, else
    `ERR_CERTIFICATION_NOT_CERTIFIED`, and only then is the agreement's `status`
    checked for `ACTIVE`, else `ERR_AGREEMENT_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_pool_exhaustion_on_award_creation
    """
    agreement_id, submitted = _drained_pool_and_an_uncertified_certification(
        api, baseline
    )
    current_version = read_agreement_version(api, baseline.sup_headers, agreement_id)

    response = api.create_yellow_ribbon_award(
        f.yellow_ribbon_award_payload(
            submitted.certification_id, agreement_id, current_version
        ),
        baseline.sup_headers,
    )
    validate_error(response, e.ERR_CERTIFICATION_NOT_CERTIFIED, 409)


def test_the_refused_award_leaves_the_exhausted_agreement_untouched(api, baseline):
    """No debit and no participant is booked for a request that never passed the gate.

    PRD: "Award creation debits the agreement: `pool_remaining_cents` falls by
    `school_share_cents`, `participant_count` rises by one, and the agreement's
    `version` increments by one."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_pool_exhaustion_on_award_creation
    """
    agreement_id, submitted = _drained_pool_and_an_uncertified_certification(
        api, baseline
    )
    current_version = read_agreement_version(api, baseline.sup_headers, agreement_id)
    api.create_yellow_ribbon_award(
        f.yellow_ribbon_award_payload(
            submitted.certification_id, agreement_id, current_version
        ),
        baseline.sup_headers,
    )

    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement, {"pool_remaining_cents": 0, "participant_count": 1}
    )
    awards = get_success_data(
        api.list_yellow_ribbon_awards(
            baseline.sup_headers, {"certification_id": submitted.certification_id}
        )
    )
    assert awards == [], f"No award may exist for the refused certification: {awards}"


# ─── Program approval outranks the certification deadline ─────────────
def _program_back_in_review_and_the_deadline_passed(api, baseline):
    """Send a second catalog version to the agency, then move past the deadline."""
    submitted = build_submitted_certification(api, baseline)
    second_catalog_id = create_catalog_version(
        api,
        baseline.sup_headers,
        baseline.program_id,
        catalog_year=NEXT_CATALOG_YEAR,
        effective_start=NEXT_CATALOG_START,
        effective_end=NEXT_CATALOG_END,
    )
    get_success_data(
        api.submit_catalog_version_to_saa(
            second_catalog_id, {}, baseline.sup_headers
        )
    )
    set_clock_to(api, PAST_DEADLINE_DATE)
    return submitted


def test_program_approval_is_checked_before_the_certification_deadline(api, baseline):
    """A program back in agency review blocks certify ahead of the lapsed deadline.

    PRD: "Seven conditions are evaluated, and they are evaluated in this order so
    that the reason a certification cannot proceed is always the earliest reason."

    Design: Difficulty/priority_pair_validation_conflict/program_approval_safety_beats_certification_deadline
    """
    submitted = _program_back_in_review_and_the_deadline_passed(api, baseline)

    response = api.certify_certification(
        submitted.certification_id, {}, baseline.sup_headers
    )
    validate_error(response, e.ERR_PROGRAM_NOT_APPROVED, 422)


def test_the_refused_certify_stamps_nothing_on_the_certification(api, baseline):
    """No certifying official and no entitlement debit survives the refusal.

    PRD: "The program's `approval_status` must be either `APPROVED` or
    `CONDITIONAL` — a program at `DRAFT`, `PENDING_SAA` or `SUSPENDED` cannot
    support certification — else `ERR_PROGRAM_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/program_approval_safety_beats_certification_deadline
    """
    submitted = _program_back_in_review_and_the_deadline_passed(api, baseline)
    api.certify_certification(submitted.certification_id, {}, baseline.sup_headers)

    program = get_success_data(
        api.get_program(baseline.program_id, baseline.sup_headers)
    )
    assert program["approval_status"] == c.PROGRAM_STATUS_PENDING_SAA
    certification = read_certification(
        api, baseline.sup_headers, submitted.certification_id
    )
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_SUBMITTED,
            "certified_by_official_id": None,
            "amount_basis": None,
        },
    )
    student = read_student(api, baseline.sco_headers, submitted.student_id)
    assert student["entitlement_days_remaining"] == c.ENTITLEMENT_DAYS_GRANTED


# ─── Agreement scope outranks the duplicate-award constraint ──────────
def _award_on_one_agreement_and_a_second_year_agreement(api, baseline):
    """Award against the in-scope agreement, then offer an out-of-scope one."""
    certified = build_certified_certification(api, baseline)
    in_scope_id, in_scope_version = create_agreement(api, baseline.sup_headers)
    create_award(
        api,
        baseline.sup_headers,
        certified.certification_id,
        in_scope_id,
        in_scope_version,
    )
    out_of_scope_id, out_of_scope_version = create_agreement(
        api, baseline.sup_headers, academic_year=NEXT_CATALOG_YEAR
    )
    return certified, out_of_scope_id, out_of_scope_version


def test_agreement_scope_is_checked_before_the_one_award_per_certification_rule(
    api, baseline
):
    """A wrong-year agreement fails on scope, not on the existing award.

    PRD: "Then scope: the agreement's `academic_year` must equal the
    `academic_year` of the certification's term and the agreement's
    `degree_level` must equal the `degree_level` of the certification's program,
    else `ERR_AGREEMENT_SCOPE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/agreement_scope_referential_beats_duplicate_award_constraint
    """
    certified, out_of_scope_id, out_of_scope_version = (
        _award_on_one_agreement_and_a_second_year_agreement(api, baseline)
    )

    response = api.create_yellow_ribbon_award(
        f.yellow_ribbon_award_payload(
            certified.certification_id, out_of_scope_id, out_of_scope_version
        ),
        baseline.sup_headers,
    )
    validate_error(response, e.ERR_AGREEMENT_SCOPE_MISMATCH, 422)


def test_the_out_of_scope_agreement_keeps_its_opening_balances(api, baseline):
    """The second agreement still shows a full pool and no participants.

    PRD: "A new agreement opens with `status` `ACTIVE`, `pool_remaining_cents`
    equal to `annual_pool_cents`, and `participant_count` at 0."

    Design: Difficulty/priority_pair_validation_conflict/agreement_scope_referential_beats_duplicate_award_constraint
    """
    certified, out_of_scope_id, out_of_scope_version = (
        _award_on_one_agreement_and_a_second_year_agreement(api, baseline)
    )
    api.create_yellow_ribbon_award(
        f.yellow_ribbon_award_payload(
            certified.certification_id, out_of_scope_id, out_of_scope_version
        ),
        baseline.sup_headers,
    )

    agreement = read_agreement(api, baseline.sup_headers, out_of_scope_id)
    a.assert_fields(
        agreement,
        {
            "status": c.AGREEMENT_STATUS_ACTIVE,
            "pool_remaining_cents": c.YR_ANNUAL_POOL_CENTS,
            "participant_count": 0,
        },
    )
    awards = get_success_data(
        api.list_yellow_ribbon_awards(
            baseline.sup_headers, {"certification_id": certified.certification_id}
        )
    )
    assert len(awards) == 1, f"Exactly one award may exist, got {awards}"
