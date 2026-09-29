"""The pinned statutory clock and the base window an exclusion is credited against."""
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    ExclusionStatus,
    api_client,
    assert_evaluation,
    assert_timeline_exclusion,
    fixtures,
)
from test_helpers.test_users import TEST_USERS


def _high_school_case():
    """One consented, assigned evaluation whose clock starts on 2026-08-01."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Westgate High",
        building_code="WG03",
        grade_band="HIGH",
        concurrent_meeting_capacity=1,
        enrollment_count=1200,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Dan Ivers",
        employee_number="E-1004",
        credential_type="PHD",
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-E", requested_domains=["COGNITIVE"]
    )
    evaluation = fixtures.assign_evaluator(evaluation["id"], psychologist["id"])
    return school, psychologist, evaluation


def _case_with_a_credited_closure():
    """The same case after a fifteen-day closure has been approved."""
    school, psychologist, evaluation = _high_school_case()
    closure = fixtures.claim_exclusion(
        evaluation["id"],
        psychologist["id"],
        "BREAK_CLOSURE",
        "2026-08-10",
        "2026-08-24",
        claim_note="District summer closure",
    )
    closure = fixtures.decide_exclusion(closure["id"], "APPROVE")
    return school, psychologist, evaluation, closure


def _edge_window_case():
    """One assigned evaluation read at a clock past its base due date."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Brookfield Elementary",
        building_code="BF12",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=360,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]], full_name="Kip Doyle", employee_number="E-1012"
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-N", requested_domains=["ADAPTIVE"]
    )
    evaluation = fixtures.assign_evaluator(evaluation["id"], psychologist["id"])
    fixtures.set_clock("2026-10-10T00:00:00Z")
    return school, psychologist, evaluation


def test_closure_credit_is_capped_below_the_days_it_claimed():
    """A fifteen-day closure inside the base window earns the fourteen-day ceiling.

    "`BREAK_CLOSURE`, covering scheduled district closures, is capped at fourteen days — two full weeks."

    Design: Difficulty/combinatorial_formula/timeline_clock_base_window_evaluation_order_pin
    """
    _, _, evaluation, closure = _case_with_a_credited_closure()

    assert_timeline_exclusion(closure)
    assert closure["status"] == ExclusionStatus.APPROVED.value
    assert closure["days_claimed"] == 15
    assert closure["days_credited"] == 14

    refreshed = fixtures.get_evaluation(evaluation["id"])
    assert_evaluation(refreshed)
    assert refreshed["clock_start_date"] == "2026-08-01"
    assert refreshed["base_due_date"] == "2026-09-30"
    assert refreshed["credited_exclusion_days"] == 14
    assert refreshed["statutory_due_date"] == "2026-10-14"


def test_a_later_claim_is_measured_against_the_base_window_not_the_extended_one():
    """A window inside the extended due date but past the base one earns nothing.

    "Its intersection window is the closed window running from `clock_start_date` to the step-1 `base_due_date` — never the already-extended `statutory_due_date`."

    Design: Difficulty/combinatorial_formula/timeline_clock_base_window_evaluation_order_pin
    """
    _, psychologist, evaluation, _ = _case_with_a_credited_closure()
    fixtures.set_clock("2026-10-15T00:00:00Z")
    later_claim = fixtures.claim_exclusion(
        evaluation["id"],
        psychologist["id"],
        "PARENT_UNAVAILABLE",
        "2026-10-05",
        "2026-10-14",
        claim_note="Parent out of district",
    )
    assert later_claim["days_claimed"] == 10

    # The window sits inside the extended due date of 2026-10-14 yet entirely
    # after the base due date of 2026-09-30.
    response = api_client.decide_timeline_exclusion(
        later_claim["id"],
        {"decision": "APPROVE"},
        TEST_USERS["psych_services_supervisor_headers"],
    )

    validate_error(response, ApiErrorId.ERR_EXCLUSION_ZERO_DAYS.value, 422)


def test_a_zero_day_claim_stays_claimed_and_moves_no_clock():
    """The refused claim keeps its status and contributes nothing to the credit.

    "Exclusions in `CLAIMED` or `REJECTED` status contribute nothing to this sum."

    Design: Difficulty/combinatorial_formula/timeline_clock_base_window_evaluation_order_pin
    """
    _, psychologist, evaluation, _ = _case_with_a_credited_closure()
    fixtures.set_clock("2026-10-15T00:00:00Z")
    later_claim = fixtures.claim_exclusion(
        evaluation["id"],
        psychologist["id"],
        "PARENT_UNAVAILABLE",
        "2026-10-05",
        "2026-10-14",
        claim_note="Parent out of district",
    )

    api_client.decide_timeline_exclusion(
        later_claim["id"],
        {"decision": "APPROVE"},
        TEST_USERS["psych_services_supervisor_headers"],
    )

    claims = {
        row["id"]: row for row in fixtures.evaluation_exclusions(evaluation["id"])
    }
    refused = claims[later_claim["id"]]
    assert refused["status"] == ExclusionStatus.CLAIMED.value
    assert refused["days_credited"] == 0

    refreshed = fixtures.get_evaluation(evaluation["id"])
    assert refreshed["credited_exclusion_days"] == 14
    assert refreshed["statutory_due_date"] == "2026-10-14"


def test_a_window_ending_on_the_base_due_date_earns_exactly_one_day():
    """Six claimed days straddling the due date intersect it on a single day.

    "The overlap starts on the later of the claim's `start_date` and the evaluation's `clock_start_date`, and ends on the earlier of the claim's `end_date` and the evaluation's `base_due_date`."

    Design: Difficulty/boundary_precision_check/exclusion_overlap_days_one_day_window_edge
    """
    _, psychologist, evaluation = _edge_window_case()

    straddling = fixtures.claim_exclusion(
        evaluation["id"],
        psychologist["id"],
        "BREAK_CLOSURE",
        "2026-09-30",
        "2026-10-05",
        claim_note="Autumn closure straddling the due date",
    )
    assert straddling["days_claimed"] == 6

    decided = fixtures.decide_exclusion(straddling["id"], "APPROVE")
    assert decided["status"] == ExclusionStatus.APPROVED.value
    assert decided["days_credited"] == 1

    refreshed = fixtures.get_evaluation(evaluation["id"])
    assert refreshed["credited_exclusion_days"] == 1
    assert refreshed["statutory_due_date"] == "2026-10-01"


def test_a_window_starting_the_day_after_the_base_due_date_earns_nothing():
    """Shifting the same six-day window one day later collapses the overlap.

    "If that overlap end falls before the overlap start, the overlap is zero days; otherwise the overlap is the inclusive count of calendar days between them."

    Design: Difficulty/boundary_precision_check/exclusion_overlap_days_one_day_window_edge
    """
    _, psychologist, evaluation = _edge_window_case()
    straddling = fixtures.claim_exclusion(
        evaluation["id"],
        psychologist["id"],
        "BREAK_CLOSURE",
        "2026-09-30",
        "2026-10-05",
        claim_note="Autumn closure straddling the due date",
    )
    fixtures.decide_exclusion(straddling["id"], "APPROVE")

    after_window = fixtures.claim_exclusion(
        evaluation["id"],
        psychologist["id"],
        "BREAK_CLOSURE",
        "2026-10-01",
        "2026-10-06",
        claim_note="Closure entirely after the due date",
    )
    assert after_window["days_claimed"] == 6

    response = api_client.decide_timeline_exclusion(
        after_window["id"],
        {"decision": "APPROVE"},
        TEST_USERS["psych_services_supervisor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_EXCLUSION_ZERO_DAYS.value, 422)

    claims = {
        row["id"]: row for row in fixtures.evaluation_exclusions(evaluation["id"])
    }
    assert claims[after_window["id"]]["status"] == ExclusionStatus.CLAIMED.value
    assert claims[after_window["id"]]["days_credited"] == 0

    refreshed = fixtures.get_evaluation(evaluation["id"])
    assert refreshed["credited_exclusion_days"] == 1
