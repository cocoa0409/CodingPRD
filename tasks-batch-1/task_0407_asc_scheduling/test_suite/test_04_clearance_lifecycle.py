"""Pre-op clearance lifecycle: the parallel clearance_status dimension, the H&P
window boundary, and the clear() preconditions.

Difficulty queue: non_linear_state_machine / case_parallel_dimensions_evolve_independently.
Corner queue: state_machines (clear blocked by ON_HOLD, H&P window boundaries) and
              errors (HP review missing, DEFER blocks clear, reset-not-on-hold).
"""
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId, fixtures
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

SCHED = TEST_USERS["scheduler_headers"]
NURSE = TEST_USERS["preop_nurse_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine / case_parallel_dimensions_evolve_independently
# ===========================================================================
def test_clearance_fail_then_reset_leaves_case_status_scheduled():
    """PRD §3.8: "A check with `outcome` of `FAIL` drives the case clearance
    `PENDING_CLEARANCE → ON_HOLD`; recording a check requires the clearance to currently
    be `PENDING_CLEARANCE` (otherwise `ERR_CLEARANCE_NOT_PENDING`)."
    PRD §3.8: "a `PreOpNurse` reworks it by resetting clearance `ON_HOLD → PENDING_CLEARANCE`,
    which requires the clearance to be `ON_HOLD` (otherwise `ERR_CLEARANCE_NOT_ON_HOLD`);
    this is the cyclic rework edge, and a failed check can be re-worked and re-submitted
    as many times as needed."

    clearance_status walks PENDING_CLEARANCE -> ON_HOLD -> PENDING_CLEARANCE while
    case_status stays SCHEDULED the whole time (the two axes are independent).

    Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_evolve_independently
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    on_hold = validate_success(api_client.record_clearance_check(
        case["id"], {"check_type": "LABS", "outcome": "FAIL"}, NURSE), 201)
    # The clearance-check create response is the ClearanceCheck row; read the case for status.
    after_fail = get_success_data(api_client.get_surgical_case(case["id"], SCHED))
    assert after_fail["clearance_status"] == "ON_HOLD", after_fail["clearance_status"]
    assert after_fail["case_status"] == "SCHEDULED", after_fail["case_status"]
    reset = validate_success(api_client.clearance_reset(case["id"], NURSE), 200)
    assert reset["clearance_status"] == "PENDING_CLEARANCE", reset["clearance_status"]
    assert reset["case_status"] == "SCHEDULED", reset["case_status"]


def test_clearance_advances_to_cleared_while_case_status_scheduled():
    """PRD §3.8: "A newly booked case starts at `clearance_status` `PENDING_CLEARANCE`, and
    clearance must reach `CLEARED` before the case can ever enter the OR."
    PRD §3.8: "Clearing a case advances `PENDING_CLEARANCE → CLEARED` and is the most heavily
    guarded clearance step."

    clearance_status moves PENDING_CLEARANCE -> CLEARED while case_status remains SCHEDULED:
    the scheduling axis does not move when the clearance axis advances.

    Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_evolve_independently
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    fixtures.record_check(case["id"], "HP_REVIEW", "PASS")
    cleared = validate_success(api_client.clear_case(
        case["id"], {"hp_signed_at": "2026-07-10T00:00:00.000Z"}, NURSE), 200)
    assert cleared["clearance_status"] == "CLEARED", cleared["clearance_status"]
    assert cleared["case_status"] == "SCHEDULED", cleared["case_status"]


# ===========================================================================
# Corner / state_machines / clear_blocked_by_open_failed_check
# (a FAIL puts clearance ON_HOLD; clear while ON_HOLD -> ERR_CLEARANCE_NOT_PENDING)
# ===========================================================================
def test_clear_while_on_hold_rejected():
    """PRD §3.8: "It requires, first, that the clearance is currently `PENDING_CLEARANCE`
    (otherwise `ERR_CLEARANCE_NOT_PENDING`)."
    PRD §3.8: "A check with `outcome` of `FAIL` drives the case clearance
    `PENDING_CLEARANCE → ON_HOLD`..."

    After a FAIL check (clearance now ON_HOLD), calling clear -> ERR_CLEARANCE_NOT_PENDING.

    Design: Corner/state_machines/clear_blocked_by_open_failed_check
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    fixtures.record_check(case["id"], "LABS", "FAIL")
    resp = api_client.clear_case(case["id"], {"hp_signed_at": "2026-07-10T00:00:00.000Z"}, NURSE)
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_NOT_PENDING.value)
    after = get_success_data(api_client.get_surgical_case(case["id"], SCHED))
    assert after["clearance_status"] == "ON_HOLD", after["clearance_status"]


# ===========================================================================
# Corner / state_machines / clear_blocked_by_expired_hp_window_boundary
# ===========================================================================
def test_clear_with_stale_hp_window_rejected():
    """PRD §3.8: "the H&P is fresh when the number of days from `hp_signed_at` to midnight
    UTC of the case's `service_date` is at most the facility's `hp_validity_days` — the
    boundary is inclusive, so exactly `hp_validity_days` is still fresh while
    `hp_validity_days` plus one day is stale, and a stale or missing H&P is rejected with
    `ERR_HP_WINDOW_EXPIRED`."

    service_date 2026-07-15, hp_validity 30; hp_signed_at 2026-06-14 is 31 days before ->
    stale -> ERR_HP_WINDOW_EXPIRED; clearance stays PENDING_CLEARANCE.

    Design: Corner/state_machines/clear_blocked_by_expired_hp_window_boundary
    """
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600,
        world_kwargs={"hp_validity_days": 30})
    fixtures.record_check(case["id"], "HP_REVIEW", "PASS")
    resp = api_client.clear_case(case["id"], {"hp_signed_at": "2026-06-14T00:00:00.000Z"}, NURSE)
    validate_error(resp, ApiErrorId.ERR_HP_WINDOW_EXPIRED.value)
    after = get_success_data(api_client.get_surgical_case(case["id"], SCHED))
    assert after["clearance_status"] == "PENDING_CLEARANCE", after["clearance_status"]


# ===========================================================================
# Corner / state_machines / hp_window_exact_boundary_30_days_is_fresh
# ===========================================================================
def test_clear_with_hp_at_exact_30_day_boundary_succeeds():
    """PRD §3.8: "the boundary is inclusive, so exactly `hp_validity_days` is still fresh
    while `hp_validity_days` plus one day is stale, and a stale or missing H&P is rejected
    with `ERR_HP_WINDOW_EXPIRED`."

    hp_signed_at exactly 30 days before service_date 2026-07-15 (i.e. 2026-06-15) is fresh
    -> clear succeeds -> clearance_status CLEARED.

    Design: Corner/state_machines/hp_window_exact_boundary_30_days_is_fresh
    """
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600,
        world_kwargs={"hp_validity_days": 30})
    fixtures.record_check(case["id"], "HP_REVIEW", "PASS")
    cleared = validate_success(api_client.clear_case(
        case["id"], {"hp_signed_at": "2026-06-15T00:00:00.000Z"}, NURSE), 200)
    assert cleared["clearance_status"] == "CLEARED", cleared["clearance_status"]


# ===========================================================================
# Corner / errors / error_hp_review_missing_on_clear
# ===========================================================================
def test_clear_without_hp_review_pass_rejected():
    """PRD §3.8: "Third, at least one clearance check of `check_type` `HP_REVIEW` with
    `outcome` `PASS` must exist (otherwise `ERR_HP_REVIEW_MISSING`)."

    Clear with a fresh H&P but no passing HP_REVIEW check -> ERR_HP_REVIEW_MISSING;
    clearance stays PENDING_CLEARANCE.

    Design: Corner/errors/error_hp_review_missing_on_clear
    """
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600,
        world_kwargs={"hp_validity_days": 30})
    resp = api_client.clear_case(case["id"], {"hp_signed_at": "2026-07-10T00:00:00.000Z"}, NURSE)
    validate_error(resp, ApiErrorId.ERR_HP_REVIEW_MISSING.value)
    after = get_success_data(api_client.get_surgical_case(case["id"], SCHED))
    assert after["clearance_status"] == "PENDING_CLEARANCE", after["clearance_status"]


# ===========================================================================
# Corner / errors / error_open_failed_check_defer_blocks_clear
# ===========================================================================
def test_clear_blocked_by_unsuperseded_defer():
    """PRD §3.8: "Fourth, there must be no unresolved `DEFER`: if any clearance check on the
    case carries `outcome` `DEFER` recorded after the most recent clearance reset (or after
    the case's creation, if there has been no reset) that has not been superseded by a later
    `PASS` of the same `check_type`, clearing is rejected with `ERR_OPEN_FAILED_CHECK`."

    HP_REVIEW PASS recorded, then a LABS DEFER (clearance stays PENDING_CLEARANCE). Clearing
    with a fresh H&P is still blocked by the un-superseded LABS DEFER -> ERR_OPEN_FAILED_CHECK.

    Design: Corner/errors/error_open_failed_check_defer_blocks_clear
    """
    world, block, case = fixtures.setup_booked_case(
        start_min=480, block_start=480, block_end=600,
        world_kwargs={"hp_validity_days": 30})
    fixtures.record_check(case["id"], "HP_REVIEW", "PASS")
    fixtures.record_check(case["id"], "LABS", "DEFER")
    resp = api_client.clear_case(case["id"], {"hp_signed_at": "2026-07-10T00:00:00.000Z"}, NURSE)
    validate_error(resp, ApiErrorId.ERR_OPEN_FAILED_CHECK.value)
    after = get_success_data(api_client.get_surgical_case(case["id"], SCHED))
    assert after["clearance_status"] == "PENDING_CLEARANCE", after["clearance_status"]


# ===========================================================================
# Corner / errors / error_clearance_not_on_hold_on_reset
# ===========================================================================
def test_reset_while_pending_rejected():
    """PRD §3.8: "a `PreOpNurse` reworks it by resetting clearance `ON_HOLD →
    PENDING_CLEARANCE`, which requires the clearance to be `ON_HOLD` (otherwise
    `ERR_CLEARANCE_NOT_ON_HOLD`)..."

    Resetting clearance while it is PENDING_CLEARANCE (not ON_HOLD) -> ERR_CLEARANCE_NOT_ON_HOLD.

    Design: Corner/errors/error_clearance_not_on_hold_on_reset
    """
    world, block, case = fixtures.setup_booked_case(start_min=480, block_start=480, block_end=600)
    resp = api_client.clearance_reset(case["id"], NURSE)
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_NOT_ON_HOLD.value)
