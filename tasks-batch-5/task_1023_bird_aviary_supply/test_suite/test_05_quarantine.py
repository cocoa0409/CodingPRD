"""Quarantine risk scoring, the retest cycle, the fail cascade, and clear guards."""
from test_helpers import (
    validate_success, validate_error,
    open_quarantine, TEST_USERS,
)

SM = TEST_USERS["store_manager_headers"]
STAFF = TEST_USERS["aviary_staff_headers"]


# ── dual_variant_calc: bird provisional vs final risk ────────────────────────

def test_bird_provisional_risk_at_intake(api):
    """PRD 3.3: "The provisional score, stored in provisional_risk_score, is the species
    base weight — 40 for appendix I, 25 for II, 15 for III, and 5 for NONE — plus an import
    penalty of 20 points when the bird is imported, and nothing extra otherwise."

    Design: Difficulty/dual_variant_calc/bird_provisional_vs_final_risk
    """
    ctx = open_quarantine(cites_appendix="II", imported=True, housing_capacity=2)
    assert ctx["bird"]["provisional_risk_score"] == 45  # II(25) + import(20)


def test_bird_final_risk_and_clear(api):
    """PRD 3.3: "The final risk score, stored in final_risk_score, is the species base
    weight (40/25/15/5 for I/II/III/NONE) plus 15 points for each failed test counted in
    failed_test_count plus 5 points for each retest counted in retest_count; unlike the
    provisional score, the final score ignores the import flag."
    PRD 3.3: "On a successful clear, the record moves to CLEARED and the owning bird bubbles
    up from IN_QUARANTINE to CLEARED, with its final_risk_score set at that moment."

    Design: Difficulty/dual_variant_calc/bird_provisional_vs_final_risk
    """
    ctx = open_quarantine(cites_appendix="II", imported=True, housing_capacity=2)
    qr_id = ctx["qr_id"]
    validate_success(api.start_test(qr_id, STAFF), 200)
    validate_success(api.record_test_result(qr_id, {"result": "FAIL"}, STAFF), 200)
    validate_success(api.set_clock("2026-07-16T00:00:00Z", SM), 200)
    validate_success(api.clear_quarantine(qr_id, STAFF), 200)
    bird = validate_success(api.get_bird(ctx["bird"]["id"], STAFF), 200)
    assert bird["final_risk_score"] == 40  # II(25) + 1 failed(15), import ignored
    assert bird["status"] == "CLEARED"


# ── non_linear_state_machine: quarantine retest cycle ────────────────────────

def test_retest_returns_record_to_open(api):
    """PRD 3.3: "A result of RETEST increments retest_count by one and returns the record
    to OPEN for another round."

    Design: Difficulty/non_linear_state_machine/quarantine_retest_cycle
    """
    ctx = open_quarantine(cites_appendix="NONE")
    qr_id = ctx["qr_id"]
    validate_success(api.start_test(qr_id, STAFF), 200)
    rec = validate_success(api.record_test_result(qr_id, {"result": "RETEST"}, STAFF), 200)
    assert rec["status"] == "OPEN"
    assert rec["retest_count"] == 1


def test_two_retest_loops_accumulate(api):
    """PRD 3.3: "Starting a test moves an OPEN record to UNDER_TEST".
    PRD 3.3: "A result of RETEST increments retest_count by one and returns the record to
    OPEN for another round."

    Design: Difficulty/non_linear_state_machine/quarantine_retest_cycle
    """
    ctx = open_quarantine(cites_appendix="NONE")
    qr_id = ctx["qr_id"]
    validate_success(api.start_test(qr_id, STAFF), 200)
    validate_success(api.record_test_result(qr_id, {"result": "RETEST"}, STAFF), 200)
    validate_success(api.start_test(qr_id, STAFF), 200)
    rec = validate_success(api.record_test_result(qr_id, {"result": "RETEST"}, STAFF), 200)
    assert rec["retest_count"] == 2
    assert rec["status"] == "OPEN"


# ── transitive_cascade: quarantine-fail depth-3 cascade ──────────────────────

def test_fail_rejects_bird(api):
    """PRD 3.3: "Failing a record is permitted from OPEN or UNDER_TEST and moves it to
    FAILED. This bubbles the owning bird to the terminal REJECTED state and triggers a
    cage-release cascade: the bird's final_risk_score is computed and recorded, the housing
    cage's current_occupancy is decremented by one, the bird's housing_cage_id is cleared,
    and the cage's status is recomputed to AVAILABLE once occupancy drops below capacity."

    Design: Difficulty/transitive_cascade/quarantine_fail_cascade_depth3
    """
    ctx = open_quarantine(cites_appendix="NONE", housing_capacity=1)
    rec = validate_success(api.fail_quarantine(ctx["qr_id"], STAFF), 200)
    assert rec["status"] == "FAILED"
    bird = validate_success(api.get_bird(ctx["bird"]["id"], STAFF), 200)
    assert bird["status"] == "REJECTED"
    assert bird["housing_cage_id"] is None


def test_fail_releases_cage(api):
    """PRD 3.3: "the housing cage's current_occupancy is decremented by one, the bird's
    housing_cage_id is cleared, and the cage's status is recomputed to AVAILABLE once
    occupancy drops below capacity."

    Design: Difficulty/transitive_cascade/quarantine_fail_cascade_depth3
    """
    ctx = open_quarantine(cites_appendix="NONE", housing_capacity=1)
    validate_success(api.fail_quarantine(ctx["qr_id"], STAFF), 200)
    cage = validate_success(api.get_cage(ctx["cage"]["id"], STAFF), 200)
    assert cage["current_occupancy"] == 0
    assert cage["status"] == "AVAILABLE"


# ── boundary_precision_check: risk threshold at 60 ───────────────────────────

def test_clear_rejected_at_risk_threshold_60(api):
    """PRD 3.3: "second, the bird's final risk score must be strictly below the failure
    threshold of 60, else ERR_RISK_TOO_HIGH_TO_CLEAR."
    PRD 3.3: "A score of 60 or higher cannot be cleared and must instead be failed."

    Design: Difficulty/boundary_precision_check/quarantine_risk_at_threshold_60_rejects_clear
    """
    ctx = open_quarantine(cites_appendix="II", housing_capacity=1)
    qr_id = ctx["qr_id"]
    validate_success(api.start_test(qr_id, STAFF), 200)
    validate_success(api.record_test_result(qr_id, {"result": "FAIL"}, STAFF), 200)
    validate_success(api.record_test_result(qr_id, {"result": "FAIL"}, STAFF), 200)
    validate_success(api.record_test_result(qr_id, {"result": "RETEST"}, STAFF), 200)
    validate_success(api.set_clock("2026-07-16T00:00:00Z", SM), 200)
    # final = II(25) + 2 failed(30) + 1 retest(5) = 60 -> exactly at threshold -> rejected
    res = api.clear_quarantine(qr_id, STAFF)
    validate_error(res, "ERR_RISK_TOO_HIGH_TO_CLEAR", expected_status=409)
    rec = validate_success(api.get_quarantine_record(qr_id, STAFF), 200)
    assert rec["status"] == "OPEN"


def test_risk_just_below_threshold_clears(api):
    """PRD 3.3: "the bird's final risk score must be strictly below the failure threshold
    of 60, else ERR_RISK_TOO_HIGH_TO_CLEAR."

    Design: Difficulty/boundary_precision_check/quarantine_risk_at_threshold_60_rejects_clear
    """
    ctx = open_quarantine(cites_appendix="II", housing_capacity=1)
    qr_id = ctx["qr_id"]
    validate_success(api.start_test(qr_id, STAFF), 200)
    validate_success(api.record_test_result(qr_id, {"result": "FAIL"}, STAFF), 200)
    validate_success(api.record_test_result(qr_id, {"result": "FAIL"}, STAFF), 200)
    validate_success(api.set_clock("2026-07-16T00:00:00Z", SM), 200)
    # final = II(25) + 2 failed(30) = 55 -> strictly below 60 -> clears
    rec = validate_success(api.clear_quarantine(qr_id, STAFF), 200)
    assert rec["status"] == "CLEARED"
    bird = validate_success(api.get_bird(ctx["bird"]["id"], STAFF), 200)
    assert bird["final_risk_score"] == 55
    assert bird["status"] == "CLEARED"


# ── corner: clear before minimum hold window ─────────────────────────────────

def test_clear_before_min_days_rejected(api):
    """PRD 3.3: "Clearing a record is permitted from OPEN or UNDER_TEST and is guarded by
    two conditions evaluated in this order: first, the current clock must be at or after
    min_clear_at, else ERR_QUARANTINE_TOO_EARLY".

    Design: Corner/state_machines/clear_before_min_days_rejected
    """
    ctx = open_quarantine(cites_appendix="NONE", housing_capacity=1)
    # clock is still at the open instant (2026-07-01), well before min_clear_at (07-15).
    res = api.clear_quarantine(ctx["qr_id"], STAFF)
    validate_error(res, "ERR_QUARANTINE_TOO_EARLY", expected_status=409)
    rec = validate_success(api.get_quarantine_record(ctx["qr_id"], STAFF), 200)
    assert rec["status"] == "OPEN"


# ── corner: record-test-result requires UNDER_TEST ───────────────────────────

def test_record_test_result_requires_under_test(api):
    """PRD 3.3: "Recording a result on a record that is not UNDER_TEST is rejected with
    ERR_QUARANTINE_NOT_OPEN."

    Design: Corner/state_machines/record_test_result_requires_under_test
    """
    ctx = open_quarantine(cites_appendix="NONE", housing_capacity=1)
    res = api.record_test_result(ctx["qr_id"], {"result": "FAIL"}, STAFF)
    validate_error(res, "ERR_QUARANTINE_NOT_OPEN", expected_status=409)
    rec = validate_success(api.get_quarantine_record(ctx["qr_id"], STAFF), 200)
    assert rec["status"] == "OPEN"
    assert rec["failed_test_count"] == 0
