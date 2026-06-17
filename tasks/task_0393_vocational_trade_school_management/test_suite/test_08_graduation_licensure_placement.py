"""Graduation gating, licensure eligibility, placement reporting.

Covers difficulty queue A:
  - priority_pair_validation_conflict / graduate_invalid_state_beats_balance_outstanding
  - boundary_precision_check / licensure_attendance_exactly_at_threshold_is_eligible
  - boundary_precision_check / placement_rate_empty_graduated_set_is_zero
And corner queue B:
  - state_machines / graduate_clock_hours_unmet_rejected
  - calculations / licensure_exam_attempt_pass_fail_computed
  - calculations / placement_outcome_counts_as_placed_computed
  - calculations / placement_rate_latest_outcome_per_agreement
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

REGISTRAR = TEST_USERS["registrar_headers"]
ADVISOR = TEST_USERS["academic_advisor_headers"]


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / graduate_invalid_state_beats_balance_outstanding
# --------------------------------------------------------------------------
def test_graduate_drafted_with_balance_returns_invalid_state(api):
    """PRD §2.5: "the state-machine precondition that the target resource is in a
    state from which the requested transition is defined, failing with
    ERR_INVALID_STATE; and then (7 and beyond) the operation-specific business
    rules described in §3."
    PRD §3.9: "It enforces, beyond the state check that the agreement is ENROLLED
    (else ERR_INVALID_STATE), a sequence of academic and fiscal gates: ... and the
    agreement's ledger_balance_cents must be 0 or below (else
    ERR_BALANCE_OUTSTANDING)."

    Design: Difficulty/priority_pair_validation_conflict/graduate_invalid_state_beats_balance_outstanding
    """
    # DRAFTED agreement (never enrolled) with outstanding balance 500000.
    program, cohort = fx.setup_program_and_cohort(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 500_000})
    agr = fx.create_drafted_agreement(cohort["id"], contract_tuition_cents=500_000)
    resp = api.graduate_agreement(agr["id"], REGISTRAR)
    # State check (priority 6) precedes the fiscal balance gate (priority 17).
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_graduate_drafted_invalid_state_http_409(api):
    """PRD §3.9: "Graduation is the gated capstone of the agreement lifecycle and
    is a registrar action that moves an agreement ENROLLED → GRADUATED. It
    enforces, beyond the state check that the agreement is ENROLLED (else
    ERR_INVALID_STATE), a sequence of academic and fiscal gates ..."

    Design: Difficulty/priority_pair_validation_conflict/graduate_invalid_state_beats_balance_outstanding
    """
    program, cohort = fx.setup_program_and_cohort(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 500_000})
    agr = fx.create_drafted_agreement(cohort["id"], contract_tuition_cents=500_000)
    resp = api.graduate_agreement(agr["id"], REGISTRAR)
    assert resp.status_code == 409, resp.text
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------
# boundary_precision_check / licensure_attendance_exactly_at_threshold_is_eligible
# --------------------------------------------------------------------------
def test_licensure_eligible_when_attendance_meets_threshold_on_graduate(api):
    """PRD §3.9: "The agreement's licensure_eligible is true when it is
    graduation-ready, its attendance_pct is at least the program's
    licensure_min_attendance_pct (an attendance fraction exactly equal to the
    threshold is eligible, since the comparison is "greater than or equal to"),
    and its sap_standing is GOOD or WARNING."
    PRD §3.4: "The attendance_pct is clock_hours_completed divided by
    scheduled_hours_to_date ..."

    Design: Difficulty/boundary_precision_check/licensure_attendance_exactly_at_threshold_is_eligible
    """
    # 1000h program (600 theory + 400 externship), licensure_min_attendance 0.9.
    # THEORY 600/600 + EXTERNSHIP 444/400 -> clock 1000, scheduled 1044,
    # attendance 1000/1044 ~= 0.9579 (>= 0.9).
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "required_theory_hours": 600,
                           "required_externship_hours": 400, "tuition_cents": 0,
                           "licensure_min_attendance_pct": 0.9},
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
        agreement_overrides={"contract_tuition_cents": 0},
    )
    fx.post_attendance(agreement["id"], kind="THEORY", scheduled_hours=600, attended_hours=600, term_index=1)
    fx.post_attendance(agreement["id"], kind="EXTERNSHIP", scheduled_hours=444, attended_hours=400, term_index=2)
    graduated = validate_success(api.graduate_agreement(agreement["id"], REGISTRAR))
    assert graduated["status"] == "GRADUATED", graduated
    assert graduated["attendance_pct"] == pytest.approx(1000 / 1044, abs=1e-6), graduated
    assert graduated["licensure_eligible"] is True, graduated


def test_graduate_attendance_pct_exact_ratio(api):
    """PRD §3.4: "The attendance_pct is clock_hours_completed divided by
    scheduled_hours_to_date; as a boundary rule, when scheduled_hours_to_date is 0
    the attendance_pct is exactly 1.0 rather than a division by zero. Hours and
    ratios are kept as exact values and compared against thresholds with "greater
    than or equal to" semantics."

    Design: Difficulty/boundary_precision_check/licensure_attendance_exactly_at_threshold_is_eligible
    """
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "required_theory_hours": 600,
                           "required_externship_hours": 400, "tuition_cents": 0,
                           "licensure_min_attendance_pct": 0.9},
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
        agreement_overrides={"contract_tuition_cents": 0},
    )
    fx.post_attendance(agreement["id"], kind="THEORY", scheduled_hours=600, attended_hours=600, term_index=1)
    fx.post_attendance(agreement["id"], kind="EXTERNSHIP", scheduled_hours=444, attended_hours=400, term_index=2)
    agr = validate_success(api.get_agreement(agreement["id"], REGISTRAR))
    assert agr["attendance_pct"] == pytest.approx(1000 / 1044, abs=1e-6), agr


# --------------------------------------------------------------------------
# boundary_precision_check / placement_rate_empty_graduated_set_is_zero
# --------------------------------------------------------------------------
def test_placement_rate_empty_graduated_set_is_zero(api):
    """PRD §3.9: "The placeable count is the number of the program's agreements
    whose status is GRADUATED."
    PRD §3.9: "The placement_rate_pct is the placed count divided by the placeable
    count, or 0.0 when there are no placeable (graduated) agreements rather than a
    division by zero ..."

    Design: Difficulty/boundary_precision_check/placement_rate_empty_graduated_set_is_zero
    """
    # Program OPEN with one ENROLLED (not graduated) agreement -> zero placeable.
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 500_000},
        agreement_overrides={"contract_tuition_cents": 500_000},
    )
    report = validate_success(api.get_placement_report(program["id"], REGISTRAR))
    assert report["graduated_count"] == 0, report
    assert report["placed_count"] == 0, report
    assert report["placement_rate_pct"] == pytest.approx(0.0, abs=1e-9), report


def test_placement_rate_zero_when_no_graduates_recorded(api):
    """PRD §3.9: "or 0.0 when there are no placeable (graduated) agreements rather
    than a division by zero; the rate is stored to four decimal places using
    round-half-up. The report returns the program_id, the graduated_count, the
    placed_count, and the placement_rate_pct."

    Design: Difficulty/boundary_precision_check/placement_rate_empty_graduated_set_is_zero
    """
    program = fx.create_open_program(required_clock_hours=1000, tuition_cents=500_000)
    report = validate_success(api.get_placement_report(program["id"], REGISTRAR))
    assert report["program_id"] == program["id"], report
    assert report["graduated_count"] == 0, report
    assert report["placement_rate_pct"] == pytest.approx(0.0, abs=1e-9), report


# --------------------------------------------------------------------------
# corner: graduate_clock_hours_unmet_rejected
# --------------------------------------------------------------------------
def test_graduate_clock_hours_unmet_rejected(api):
    """PRD §3.9: "the agreement's clock_hours_completed must have reached at least
    the program's required_clock_hours (else ERR_CLOCK_HOURS_UNMET) ..."

    Design: Corner/state_machines/graduate_clock_hours_unmet_rejected
    """
    # ENROLLED, zero tuition (no balance), GOOD standing (no review), no hours.
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 0},
        agreement_overrides={"contract_tuition_cents": 0},
    )
    resp = api.graduate_agreement(agreement["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_CLOCK_HOURS_UNMET.value)


# --------------------------------------------------------------------------
# corner: licensure_exam_attempt_pass_fail_computed
# --------------------------------------------------------------------------
def test_licensure_exam_attempt_result_pass_computed(api):
    """PRD §3.9: "The system computes result as PASS when scaled_score is at least
    passing_score, and FAIL otherwise."

    Design: Corner/calculations/licensure_exam_attempt_pass_fail_computed
    """
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 0},
        agreement_overrides={"contract_tuition_cents": 0},
    )
    attempt = validate_success(
        api.create_exam_attempt(
            {"agreement_id": agreement["id"], "attempt_index": 1,
             "scaled_score": 720, "passing_score": 700}, ADVISOR),
        expected_status=201)
    assert attempt["result"] == "PASS", attempt


# --------------------------------------------------------------------------
# corner: placement_outcome_counts_as_placed_computed
# --------------------------------------------------------------------------
def test_placement_outcome_counts_as_placed_computed(api):
    """PRD §3.9: "The system computes counts_as_placed as true exactly when the
    outcome_type is EMPLOYED_IN_FIELD or EMPLOYED_RELATED; this flag is the
    placement-rate numerator."

    Design: Corner/calculations/placement_outcome_counts_as_placed_computed
    """
    program, cohort, agreement = fx.setup_graduated_agreement()
    outcome = validate_success(
        api.create_placement_outcome(
            {"agreement_id": agreement["id"], "outcome_term_index": 9,
             "outcome_type": "EMPLOYED_IN_FIELD", "employer_name": "ACME"}, ADVISOR),
        expected_status=201)
    assert outcome["counts_as_placed"] is True, outcome


# --------------------------------------------------------------------------
# corner: placement_rate_latest_outcome_per_agreement
# --------------------------------------------------------------------------
def test_placement_rate_uses_latest_outcome_per_agreement(api):
    """PRD §3.9: "The placed count is the number of those graduated agreements
    whose latest placement outcome counts as placed: for each graduated agreement,
    take its placement outcome with the greatest outcome_term_index, breaking ties
    by the later created_at, and count it if that latest outcome's
    counts_as_placed is true."

    Design: Corner/calculations/placement_rate_latest_outcome_per_agreement
    """
    program, cohort, agreement = fx.setup_graduated_agreement()
    # Earlier NOT_PLACED (term 9), then later EMPLOYED_IN_FIELD (term 11) is latest.
    validate_success(
        api.create_placement_outcome(
            {"agreement_id": agreement["id"], "outcome_term_index": 9,
             "outcome_type": "NOT_PLACED"}, ADVISOR),
        expected_status=201)
    validate_success(
        api.create_placement_outcome(
            {"agreement_id": agreement["id"], "outcome_term_index": 11,
             "outcome_type": "EMPLOYED_IN_FIELD", "employer_name": "ACME"}, ADVISOR),
        expected_status=201)
    report = validate_success(api.get_placement_report(program["id"], REGISTRAR))
    assert report["graduated_count"] == 1, report
    assert report["placed_count"] == 1, report
    assert report["placement_rate_pct"] == pytest.approx(1.0, abs=1e-9), report
