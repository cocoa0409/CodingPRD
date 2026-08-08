"""Membership cyclic lifecycle: pause/resume loop and billing-driven renewal transitions.

Queue A: non_linear_state_machine (membership pause/resume cycle).
Queue B: pause-already-paused invalid, renew SUCCEEDED self-loop, renew FAILED -> PAST_DUE.
"""
from test_helpers import (
    validate_success, validate_error,
    make_member_headers,
    setup_paused_membership, get_membership,
    new_customer, new_membership, set_clock,
    TEST_USERS,
)

BILLING = TEST_USERS["billing_headers"]


# ─── Queue A: non_linear_state_machine / membership pause/resume cycle ───────

def test_resume_returns_paused_membership_to_active(api):
    """PRD §3.1: "A `PAUSED` membership may be resumed, moving `PAUSED` to `ACTIVE`;
    resuming a membership that is not `PAUSED` is likewise rejected with
    `ERR_INVALID_MEMBERSHIP_STATE`."

    Design: Difficulty/non_linear_state_machine/membership_pause_resume_cycle_returns_to_active
    """
    ctx = setup_paused_membership()
    res = api.resume_membership(ctx["membership_id"], make_member_headers(ctx["customer_id"]))
    mem = validate_success(res, 200)
    assert mem["status"] == "ACTIVE", "resume re-enters the already-occupied ACTIVE state"


def test_pause_then_resume_round_trip_ends_active(api):
    """PRD §3.1: "A `Member` may pause an `ACTIVE` membership, moving it from `ACTIVE` to
    `PAUSED`; only an `ACTIVE` membership may be paused, and attempting to pause from any
    other state is rejected with `ERR_INVALID_MEMBERSHIP_STATE`."
    PRD §3.1: "A `PAUSED` membership may be resumed, moving `PAUSED` to `ACTIVE`; resuming a
    membership that is not `PAUSED` is likewise rejected with `ERR_INVALID_MEMBERSHIP_STATE`."

    Design: Difficulty/non_linear_state_machine/membership_pause_resume_cycle_returns_to_active
    """
    ctx = setup_paused_membership()
    assert get_membership(ctx["membership_id"])["status"] == "PAUSED"
    api.resume_membership(ctx["membership_id"], make_member_headers(ctx["customer_id"]))
    assert get_membership(ctx["membership_id"])["status"] == "ACTIVE"


# ─── Queue B: membership state machine ──────────────────────────────────────

def test_pause_already_paused_membership_rejected(api):
    """PRD §3.1: "only an `ACTIVE` membership may be paused, and attempting to pause from
    any other state is rejected with `ERR_INVALID_MEMBERSHIP_STATE`."

    Design: Corner/state_machines/pause_already_paused_membership_invalid_state
    """
    ctx = setup_paused_membership()
    res = api.pause_membership(ctx["membership_id"], make_member_headers(ctx["customer_id"]))
    validate_error(res, "ERR_INVALID_MEMBERSHIP_STATE", expected_status=409)
    assert get_membership(ctx["membership_id"])["status"] == "PAUSED"


def test_renew_charge_succeeded_rolls_period_and_resets_usage(api):
    """PRD §3.8: "A successful renewal of an `ACTIVE` membership whose period has elapsed
    keeps it `ACTIVE` (a self-loop): the closing period's `final_settlement_charge_cents` is
    computed, the `current_period_start` advances to the prior `current_period_end`, the
    `current_period_end` is recomputed 30 days later, and `deliveries_used_this_period` is
    reset to 0."

    Design: Corner/state_machines/membership_renew_charge_success_rolls_period
    """
    cust = new_customer(name="Uwe", email="uwe@x.com")
    mem = new_membership(cust["id"], included_deliveries=5)
    set_clock("2026-06-01T00:00:00Z")
    res = api.renew_charge_membership(mem["id"], {"outcome": "SUCCEEDED"}, BILLING)
    updated = validate_success(res, 200)
    assert updated["status"] == "ACTIVE"
    assert updated["deliveries_used_this_period"] == 0


def test_renew_charge_failed_moves_membership_past_due(api):
    """PRD §3.8: "A failed renewal of an `ACTIVE` membership whose period has elapsed moves
    it `ACTIVE → PAST_DUE`, computing the closing period's `final_settlement_charge_cents`;"

    Design: Corner/state_machines/membership_renew_charge_failed_goes_past_due
    """
    cust = new_customer(name="Val", email="val@x.com")
    mem = new_membership(cust["id"], included_deliveries=5)
    set_clock("2026-06-01T00:00:00Z")
    res = api.renew_charge_membership(mem["id"], {"outcome": "FAILED"}, BILLING)
    updated = validate_success(res, 200)
    assert updated["status"] == "PAST_DUE"
