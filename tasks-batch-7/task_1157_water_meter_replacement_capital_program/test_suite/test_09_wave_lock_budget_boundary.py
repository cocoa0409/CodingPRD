"""Wave lock at the exact budget boundary (PRD 3.3)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, assign_contractor, create_account,
    create_contractor, create_installed_account, create_program, create_wave,
    create_work_order, get_success_data, validate_error, validate_success,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def _edge_program():
    """Budget 18500 == contractor price == default allowance; wave1 OPEN with
    WO1 assigned, so program-wide committed is exactly 18500."""
    prog = create_program(name="AMI-EDGE", budget_total_cents=18500,
                          target_meter_count=100,
                          default_unit_allowance_cents=18500)
    contr = create_contractor(prog["id"], unit_price_cents=18500)
    wave1 = create_wave(prog["id"], wave_number=1, capacity=5)
    acct1, _ = create_installed_account()
    wo1 = create_work_order(wave1["id"], acct1["id"])
    assign_contractor(wo1["id"], contr["id"])
    return prog, contr, wave1


def _add_second_wave(prog, contr):
    """wave2 OPEN with WO2 assigned: program-wide committed grows to 37000."""
    wave2 = create_wave(prog["id"], wave_number=2,
                        window_start="2026-06-01T00:00:00Z",
                        window_end="2026-07-01T00:00:00Z", capacity=5)
    acct2, _ = create_installed_account()
    wo2 = create_work_order(wave2["id"], acct2["id"])
    assign_contractor(wo2["id"], contr["id"])
    return wave2


def test_lock_succeeds_at_exact_budget_equality(api):
    """PRD §3.3: "Locking a wave (`OPEN` → `LOCKED`) runs a program-wide
    commitment check: `budget_committed_cents`, including this wave's live
    work orders, must not exceed `budget_total_cents`, with equality allowed;
    a breach is refused with `ERR_BUDGET_COMMITMENT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/wave_lock_exact_budget_boundary
    """
    prog, contr, wave1 = _edge_program()
    # committed 18500 == budget_total 18500: equality allowed.
    resp = api.lock_wave(wave1["id"], PM)
    data = validate_success(resp)
    assert data["status"] == "LOCKED"


def test_lock_rejected_one_cent_over(api):
    """PRD §3.3: "Locking a wave (`OPEN` → `LOCKED`) runs a program-wide
    commitment check: `budget_committed_cents`, including this wave's live
    work orders, must not exceed `budget_total_cents`, with equality allowed;
    a breach is refused with `ERR_BUDGET_COMMITMENT_EXCEEDED`."
    PRD §3.1: "The `budget_posture` is `OVERRUN` when committed plus spent
    exceeds `budget_total_cents`"

    Design: Difficulty/boundary_precision_check/wave_lock_exact_budget_boundary
    """
    prog, contr, wave1 = _edge_program()
    wave2 = _add_second_wave(prog, contr)
    # Second wave lock: committed 37000 > 18500 -> rejected.
    resp = api.lock_wave(wave2["id"], PM)
    validate_error(resp, ApiErrorId.ERR_BUDGET_COMMITMENT_EXCEEDED.value)
    w2 = get_success_data(api_client.get_wave(wave2["id"], PM))
    assert w2["status"] == "OPEN"
    p = get_success_data(api_client.get_program(prog["id"], PM))
    assert p["budget_committed_cents"] == 37000
    assert p["budget_posture"] == "OVERRUN"
