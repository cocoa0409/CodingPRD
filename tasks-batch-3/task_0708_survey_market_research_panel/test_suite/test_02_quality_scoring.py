"""Quality score weighting, tier boundaries, and the seat-conservation invariant.

Difficulty queue (A): combinatorial_formula (quality_score 3-input),
boundary_precision_check (quality PASS at 70), compensating_invariant (seat
reserve+release conservation).
"""
from test_helpers import (
    validate_success, get_success_data, make_panelist_headers, TEST_USERS,
    setup_started_participation_with_checks, submit_payload,
)

OPS = TEST_USERS["panel_ops_headers"]


def test_quality_score_three_input_nonlinear_weighting(api):
    """PRD §3.6: "The overall `quality_score` weights attention at 0.5, speed at
    0.3, and straightlining at 0.2, summing the three weighted components and
    rounding half-up to a whole number in the 0-to-100 range."
    PRD §3.6: "if the panelist's `completion_seconds` is below 34 percent of the
    study's estimated duration in seconds (that is, below `estimated_minutes` times
    60 times 0.34), the speed score is 0, because suspiciously fast completion is
    the strongest fraud signal".
    PRD §3.6: "The **straightlining** component starts at 100 and subtracts 4
    points for each unit of `straightline_run`, but never drops below 0".

    Design: Difficulty/combinatorial_formula/quality_score_three_input_nonlinear_weighting
    """
    # 1/2 attention checks passed -> attention 50; completion 100s < 204 -> speed 0;
    # straightline_run 5 -> ss = 100 - 5*4 = 80. score = 0.5*50 + 0.3*0 + 0.2*80 = 41.
    study, cell, panelist, participation = setup_started_participation_with_checks(
        checks=[("TRAP_QUESTION", True), ("INSTRUCTED_RESPONSE", False)],
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10})
    ph = make_panelist_headers(panelist["id"])

    submitted = validate_success(api.submit_participation(
        participation["id"], submit_payload(completion_seconds=100, straightline_run=5), ph))
    assert submitted["quality_score"] == 41, \
        f"expected quality_score 41, got {submitted['quality_score']}"
    assert submitted["quality_status"] == "FAIL", \
        f"41 < 50 must be FAIL, got {submitted['quality_status']}"
    assert submitted["screening_status"] == "SCREENED_OUT", \
        f"FAIL releases the seat (SCREENED_OUT), got {submitted['screening_status']}"


def test_quality_status_pass_at_exact_threshold_70(api):
    """PRD §3.6: "From the score, `quality_status` is derived in tiers: `PASS` when
    the score is at least 70, `FLAGGED` when the score is at least 50 but below 70
    (kept in the dataset but marked for human review), and `FAIL` when the score is
    below 50."
    PRD §3.3: "When quality lands at `PASS` or `FLAGGED`, the participation advances
    `SCREENED_IN → QUALIFIED`".

    Design: Difficulty/boundary_precision_check/quality_pass_boundary_exact_70_vs_69
    """
    # 2/2 attention -> 100; completion 100s < 204 -> speed 0; straightline 0 -> ss 100.
    # score = 0.5*100 + 0.3*0 + 0.2*100 = 70 -> PASS (>= 70).
    study, cell, panelist, participation = setup_started_participation_with_checks(
        checks=[("TRAP_QUESTION", True), ("INSTRUCTED_RESPONSE", True)],
        target_n=5, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10})
    ph = make_panelist_headers(panelist["id"])

    submitted = validate_success(api.submit_participation(
        participation["id"], submit_payload(completion_seconds=100, straightline_run=0), ph))
    assert submitted["quality_score"] == 70, \
        f"expected quality_score 70, got {submitted['quality_score']}"
    assert submitted["quality_status"] == "PASS", \
        f"70 >= 70 must be PASS, got {submitted['quality_status']}"
    assert submitted["screening_status"] == "QUALIFIED", \
        f"PASS commits the seat (QUALIFIED), got {submitted['screening_status']}"


def test_quality_status_flagged_just_below_threshold_69(api):
    """PRD §3.6: "`FLAGGED` when the score is at least 50 but below 70 (kept in the
    dataset but marked for human review)".
    PRD §3.3: "When quality lands at `PASS` or `FLAGGED`, the participation advances
    `SCREENED_IN → QUALIFIED`".

    Design: Difficulty/boundary_precision_check/quality_pass_boundary_exact_70_vs_69
    """
    # 2/2 attention -> 100; speed 0; straightline_run 1 -> ss = 100 - 4 = 96.
    # score = 0.5*100 + 0.3*0 + 0.2*96 = 50 + 0 + 19.2 = 69.2 -> round_half_up 69 -> FLAGGED.
    study, cell, panelist, participation = setup_started_participation_with_checks(
        checks=[("TRAP_QUESTION", True), ("INSTRUCTED_RESPONSE", True)],
        target_n=5, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10})
    ph = make_panelist_headers(panelist["id"])

    submitted = validate_success(api.submit_participation(
        participation["id"], submit_payload(completion_seconds=100, straightline_run=1), ph))
    assert submitted["quality_score"] == 69, \
        f"expected quality_score 69, got {submitted['quality_score']}"
    assert submitted["quality_status"] == "FLAGGED", \
        f"69 in [50,70) must be FLAGGED, got {submitted['quality_status']}"
    assert submitted["screening_status"] == "QUALIFIED", \
        f"FLAGGED also commits the seat (QUALIFIED), got {submitted['screening_status']}"


def test_seat_reserve_then_release_conserves_available_n(api):
    """PRD §2.7: "A participation **reserves** a seat while its screening axis is
    `SCREENING` or `SCREENED_IN`; it **commits** a seat once its screening axis
    reaches `QUALIFIED`."
    PRD §3.3: "When instead quality lands at `FAIL`, the participation moves
    `SCREENED_IN → SCREENED_OUT`: the reserved seat is released (the cell's
    `reserved_n` recomputes)".
    PRD §2.7: "and `available_n` is the target minus reserved minus committed".

    Design: Difficulty/compensating_invariant/seat_reserve_then_release_conserves_available_n
    """
    # 0/2 attention -> 0; completion 100s < 204 -> speed 0; straightline_run 10 ->
    # ss = max(0, 100-40) = 60. score = 0.5*0 + 0.3*0 + 0.2*60 = 12 -> FAIL.
    study, cell, panelist, participation = setup_started_participation_with_checks(
        checks=[("TRAP_QUESTION", False), ("INSTRUCTED_RESPONSE", False)],
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10})
    ph = make_panelist_headers(panelist["id"])

    submitted = validate_success(api.submit_participation(
        participation["id"], submit_payload(completion_seconds=100, straightline_run=10), ph))
    assert submitted["quality_score"] == 12, \
        f"expected quality_score 12, got {submitted['quality_score']}"
    assert submitted["quality_status"] == "FAIL"
    assert submitted["screening_status"] == "SCREENED_OUT"

    # Seat conserved: reserved+committed back to 0, available_n back to target_n.
    cell_after = validate_success(api.get_quota_cell(cell["id"], OPS))
    assert cell_after["reserved_n"] == 0, f"reserved_n should be 0, got {cell_after['reserved_n']}"
    assert cell_after["committed_n"] == 0, f"committed_n should be 0, got {cell_after['committed_n']}"
    assert cell_after["available_n"] == 2, \
        f"available_n should return to target_n 2, got {cell_after['available_n']}"
