"""Compensating invariants: budget cents and wave headcount return exactly
after create/cancel (PRD 3.1, 3.3)."""
import pytest

from test_helpers import (
    TEST_USERS, api_client, create_installed_account, create_program,
    create_wave, create_work_order, get_success_data, validate_success,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def test_budget_commit_then_cancel_restores_available(api):
    """PRD §3.1: "`budget_committed_cents` is the sum of
    `committed_amount_cents` over the program's work orders whose
    `lifecycle_status` is neither `CLOSED` nor `CANCELLED` (a work order
    belongs to the program through its wave)."
    PRD §3.3: "At creation the system captures the account's currently
    `INSTALLED` meter as the work order's `old_meter_id`, books a budget
    commitment equal to the program's `default_unit_allowance_cents` into
    `committed_amount_cents`, moves the account `ELIGIBLE` → `IN_PROGRAM`,
    recomputes the program budget"

    Design: Difficulty/compensating_invariant/budget_commit_create_cancel_conservation
    """
    prog = create_program()  # budget 5,000,000; allowance 20,000
    wave = create_wave(prog["id"])
    acct, oldm = create_installed_account()
    wo = create_work_order(wave["id"], acct["id"])
    assert wo["committed_amount_cents"] == 20000
    mid = get_success_data(api_client.get_program(prog["id"], PM))
    assert mid["budget_committed_cents"] == 20000
    assert mid["budget_available_cents"] == 4980000
    validate_success(api.cancel_work_order(wo["id"], SCHED))
    after = get_success_data(api_client.get_program(prog["id"], PM))
    assert after["budget_committed_cents"] == 0
    assert after["budget_available_cents"] == 5000000


def test_cancel_zeroes_commitment_and_identity_holds(api):
    """PRD §3.3: "Cancellation is terminal (`→ CANCELLED`) and shares one set
    of side effects regardless of the from-state: `committed_amount_cents` is
    zeroed, any appointment of the work order still `BOOKED` or `CONFIRMED` is
    moved to `SUPERSEDED`, the account returns to `ELIGIBLE` if no other open
    work order remains, the program budget is recomputed to release the
    commitment, and the work order's `version` increments."
    PRD §3.1: "`budget_available_cents` is `budget_total_cents` minus
    `budget_committed_cents` minus `budget_spent_cents`."

    Design: Difficulty/compensating_invariant/budget_commit_create_cancel_conservation
    """
    prog = create_program()
    wave = create_wave(prog["id"])
    acct, oldm = create_installed_account()
    wo = create_work_order(wave["id"], acct["id"])
    cancelled = validate_success(api.cancel_work_order(wo["id"], SCHED))
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["committed_amount_cents"] == 0
    after = get_success_data(api_client.get_program(prog["id"], PM))
    # Identity: total == committed + spent + available
    assert after["budget_total_cents"] == (
        after["budget_committed_cents"] + after["budget_spent_cents"]
        + after["budget_available_cents"])


def test_wave_headcount_two_create(api):
    """PRD §3.3: "The wave's `committed_count` (its work orders not in
    `CANCELLED`) and `completed_count` (its work orders in `CLOSED`) are
    maintained automatically."

    Design: Difficulty/compensating_invariant/wave_headcount_create_cancel_conservation
    """
    prog = create_program()
    wave = create_wave(prog["id"])
    acctA, _ = create_installed_account()
    woA = create_work_order(wave["id"], acctA["id"])
    acctB, _ = create_installed_account()
    woB = create_work_order(wave["id"], acctB["id"])
    w = get_success_data(api_client.get_wave(wave["id"], PM))
    assert w["committed_count"] == 2
    assert w["completed_count"] == 0


def test_wave_headcount_restored_after_cancel(api):
    """PRD §3.3: "The wave's `committed_count` (its work orders not in
    `CANCELLED`) and `completed_count` (its work orders in `CLOSED`) are
    maintained automatically."
    PRD §3.2: "cancelling the account's open work order returns it
    `IN_PROGRAM` → `ELIGIBLE` provided no other open work order remains."

    Design: Difficulty/compensating_invariant/wave_headcount_create_cancel_conservation
    """
    prog = create_program()
    wave = create_wave(prog["id"])
    acctA, _ = create_installed_account()
    woA = create_work_order(wave["id"], acctA["id"])
    acctB, _ = create_installed_account()
    woB = create_work_order(wave["id"], acctB["id"])
    validate_success(api.cancel_work_order(woA["id"], SCHED))
    w = get_success_data(api_client.get_wave(wave["id"], PM))
    assert w["committed_count"] == 1
    assert w["completed_count"] == 0
    a = get_success_data(api_client.get_account(acctA["id"], SCHED))
    assert a["status"] == "ELIGIBLE"
    b = get_success_data(api_client.get_account(acctB["id"], SCHED))
    assert b["status"] == "IN_PROGRAM"
