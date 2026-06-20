"""Shutoff / reconnect cycles, cross-entity cascades, safety/moratorium gates, boundary
precision, validation-priority pairs, and compensating invariants — the depth instances that
exercise the regulated service lifecycle."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    fixtures as fx,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CS = TEST_USERS["customer_service_headers"]
FT = TEST_USERS["field_tech_headers"]


# ---------------------------------------------------------------------------
# Helper: drive an account fully through the shutoff/reconnect loop.
# ---------------------------------------------------------------------------
def _drive_to_reconnect_ready(api, past_due_amount=7500):
    """Returns (account, meter, reconnect_order) with the account DISCONNECTED, balance
    cleared, a HELD reconnect deposit, and a DISPATCHED RECONNECT order — ready to complete."""
    acct, meter, bill = fx.setup_disconnected_account(past_due_amount=past_due_amount)
    fx.pay_off_bill(acct["id"], bill["id"], amount_cents=past_due_amount,
                    posted_date="2026-04-02T00:00:00.000Z")
    fx.create_held_deposit(acct["id"], reason="RECONNECT")
    rec = fx.get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "RECONNECT", "premise_meter_id": meter["id"],
         "scheduled_date": "2026-04-01T00:00:00.000Z"}, headers=FT))
    fx.get_success_data(api.dispatch_service_order(rec["id"], headers=FT))
    return acct, meter, rec


# ===========================================================================
# non_linear_state_machine
# ===========================================================================
def test_account_returns_to_active_after_shutoff_reconnect_cycle(api):
    """PRD 3.10: "Reconnection restores a disconnected account. ... when a FieldTech completes
    it the account advances DISCONNECTED -> ACTIVE. ... On success the account returns to
    ACTIVE, the meter returns to SET".

    Design: Difficulty/non_linear_state_machine/account_shutoff_reconnect_cycle
    """
    acct, meter, rec = _drive_to_reconnect_ready(api)
    resp = api.complete_service_order(rec["id"], {}, headers=FT)
    validate_success(resp, 200)
    acct_after = fx.get_account(acct["id"])
    assert acct_after["service_status"] == "ACTIVE", f"got {acct_after['service_status']}"
    meter_after = fx.get_success_data(api.get_meter(meter["id"], headers=FT))
    assert meter_after["status"] == "SET", f"got {meter_after['status']}"


def test_shutoff_notice_moves_account_to_shutoff_pending(api):
    """PRD 3.9: "A CustomerService operator issues a shutoff notice, advancing the account
    ACTIVE -> SHUTOFF_PENDING."

    Design: Difficulty/non_linear_state_machine/account_shutoff_reconnect_cycle
    """
    rs, acct, meter, bill = fx.setup_past_due_account(past_due_amount=7500)
    resp = api.shutoff_notice(acct["id"], headers=CS)
    data = validate_success(resp, 200)
    assert data["service_status"] == "SHUTOFF_PENDING", f"got {data['service_status']}"


def test_meter_locks_then_returns_to_set_across_cycle(api):
    """PRD 3.9: "On success the account becomes DISCONNECTED, the meter moves to LOCKED".
    PRD 3.10: "On success the account returns to ACTIVE, the meter returns to SET".

    Design: Difficulty/non_linear_state_machine/meter_set_locked_set_cycle
    """
    acct, meter, bill = fx.setup_disconnected_account(past_due_amount=7500)
    locked = fx.get_success_data(api.get_meter(meter["id"], headers=FT))
    assert locked["status"] == "LOCKED", f"expected LOCKED after disconnect, got {locked['status']}"
    fx.pay_off_bill(acct["id"], bill["id"], amount_cents=7500, posted_date="2026-04-02T00:00:00.000Z")
    fx.create_held_deposit(acct["id"], reason="RECONNECT")
    rec = fx.get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "RECONNECT", "premise_meter_id": meter["id"],
         "scheduled_date": "2026-04-01T00:00:00.000Z"}, headers=FT))
    fx.get_success_data(api.dispatch_service_order(rec["id"], headers=FT))
    fx.get_success_data(api.complete_service_order(rec["id"], {}, headers=FT))
    meter_after = fx.get_success_data(api.get_meter(meter["id"], headers=FT))
    assert meter_after["status"] == "SET", f"expected SET after reconnect, got {meter_after['status']}"


def test_meter_locked_on_shutoff_completion(api):
    """PRD 3.9: "On success the account becomes DISCONNECTED, the meter moves to LOCKED".

    Design: Difficulty/non_linear_state_machine/meter_set_locked_set_cycle
    """
    acct, meter, bill = fx.setup_disconnected_account(past_due_amount=7500)
    locked = fx.get_success_data(api.get_meter(meter["id"], headers=FT))
    assert locked["status"] == "LOCKED", f"got {locked['status']}"


# ===========================================================================
# transitive_cascade
# ===========================================================================
def test_shutoff_completion_three_hop_cascade(api):
    """PRD 3.9: "Disconnection itself happens when a FieldTech completes the SHUTOFF service
    order, advancing the account SHUTOFF_PENDING -> DISCONNECTED. ... On success the account
    becomes DISCONNECTED, the meter moves to LOCKED, Account.version is bumped, and a final
    actual read is posted from the order's captured completion index."

    Design: Difficulty/transitive_cascade/shutoff_completion_three_hop_cascade
    """
    acct, meter, shut = fx.setup_shutoff_pending_dispatched(past_due_amount=7500)
    resp = api.complete_service_order(shut["id"], {"completed_index": 1010}, headers=FT)
    order_data = validate_success(resp, 200)
    assert order_data["status"] == "COMPLETED", f"got {order_data['status']}"
    acct_after = fx.get_account(acct["id"])
    assert acct_after["service_status"] == "DISCONNECTED", f"got {acct_after['service_status']}"
    meter_after = fx.get_success_data(api.get_meter(meter["id"], headers=FT))
    assert meter_after["status"] == "LOCKED", f"got {meter_after['status']}"


def test_shutoff_completion_drives_account_disconnected(api):
    """PRD 3.9: "Disconnection itself happens when a FieldTech completes the SHUTOFF service
    order, advancing the account SHUTOFF_PENDING -> DISCONNECTED."

    Design: Difficulty/transitive_cascade/shutoff_completion_three_hop_cascade
    """
    acct, meter, shut = fx.setup_shutoff_pending_dispatched(past_due_amount=7500)
    fx.get_success_data(api.complete_service_order(shut["id"], {"completed_index": 1010}, headers=FT))
    acct_after = fx.get_account(acct["id"])
    assert acct_after["service_status"] == "DISCONNECTED", f"got {acct_after['service_status']}"


def test_ticket_makesafe_grade1_locks_meter(api):
    """PRD 3.13: "When a GRADE_1 ticket is made safe, the technician locks the meter: the
    ticket's gas_locked flag is set true and the associated meter's status is driven to
    LOCKED."

    Design: Difficulty/transitive_cascade/ticket_makesafe_two_hop_cascade
    """
    acct, meter, ticket = fx.setup_dispatched_grade1_ticket()
    resp = api.make_safe_ticket(ticket["id"], headers=FT)
    data = validate_success(resp, 200)
    assert data["severity"] == "GRADE_1", f"got {data['severity']}"
    assert data["status"] == "MADE_SAFE", f"got {data['status']}"
    assert data["gas_locked"] is True, f"got {data['gas_locked']}"
    meter_after = fx.get_success_data(api.get_meter(meter["id"], headers=FT))
    assert meter_after["status"] == "LOCKED", f"got {meter_after['status']}"


def test_ticket_makesafe_sets_made_safe_and_gas_locked(api):
    """PRD 3.13: "When a GRADE_1 ticket is made safe, the technician locks the meter: the
    ticket's gas_locked flag is set true".

    Design: Difficulty/transitive_cascade/ticket_makesafe_two_hop_cascade
    """
    acct, meter, ticket = fx.setup_dispatched_grade1_ticket()
    data = validate_success(api.make_safe_ticket(ticket["id"], headers=FT), 200)
    assert data["status"] == "MADE_SAFE", f"got {data['status']}"
    assert data["gas_locked"] is True, f"got {data['gas_locked']}"


# ===========================================================================
# priority_pair_validation_conflict
# ===========================================================================
def test_state_check_beats_occ_on_bill_issue(api):
    """PRD 2.10: "The target-state check for a transition then yields ERR_INVALID_STATE (409)
    when the resource is not in a state from which the requested transition is defined. The
    remaining business gates — emergency hold, winter moratorium, register rollback,
    referential billing prerequisites, optimistic-concurrency, and reconnect prerequisites —
    are evaluated after the state check, in that relative order."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_bill_issue
    """
    rs, acct, meter, read, issued = fx.setup_issued_bill()
    # The bill is already ISSUED; re-issuing with a stale version exercises both the state
    # check and OCC. The state check is evaluated first -> ERR_INVALID_STATE.
    acct_now = fx.get_account(acct["id"])
    resp = api.issue_bill(acct["id"], issued["id"],
                          {"expected_account_version": acct_now["version"] - 1}, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_check_beats_occ_with_matching_version_too(api):
    """PRD 2.10: "The remaining business gates — ... optimistic-concurrency ... — are
    evaluated after the state check". Re-issuing an already-ISSUED bill is rejected on state
    regardless of the version supplied.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_bill_issue
    """
    rs, acct, meter, read, issued = fx.setup_issued_bill()
    acct_now = fx.get_account(acct["id"])
    resp = api.issue_bill(acct["id"], issued["id"],
                          {"expected_account_version": acct_now["version"]}, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_emergency_hold_beats_moratorium_on_shutoff_complete(api):
    """PRD 3.9: "Disconnection itself happens when a FieldTech completes the SHUTOFF service
    order ... That completion is again gated: it is rejected with ERR_WINTER_MORATORIUM if the
    moratorium is in effect at completion time, and with ERR_EMERGENCY_HOLD if a live hazard
    ticket exists on the account's meters." PRD 2.10: "In practice this means a safety hold or
    moratorium surfaces ahead of a register-rollback or stale-version rejection on the same
    request."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_shutoff_complete
    """
    acct, meter, shut = fx.setup_shutoff_pending_dispatched(past_due_amount=7500)
    # Open an emergency ticket AND enter the moratorium window.
    fx.open_ticket(meter["id"], account_id=acct["id"], kind="ODOR", reported_indoors=True)
    fx.set_clock("2026-01-10T00:00:00.000Z", True)
    resp = api.complete_service_order(shut["id"], {"completed_index": 1000}, headers=FT)
    # Both gates fire; per priority 7 < 8, the safety hold (ERR_EMERGENCY_HOLD) is returned.
    validate_error(resp, ApiErrorId.ERR_EMERGENCY_HOLD.value)
    acct_after = fx.get_account(acct["id"])
    assert acct_after["service_status"] == "SHUTOFF_PENDING", f"got {acct_after['service_status']}"


def test_emergency_hold_returned_with_both_gates_active(api):
    """PRD 3.9: "it is rejected with ... ERR_EMERGENCY_HOLD if a live hazard ticket exists on
    the account's meters."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_shutoff_complete
    """
    acct, meter, shut = fx.setup_shutoff_pending_dispatched(past_due_amount=7500)
    fx.open_ticket(meter["id"], account_id=acct["id"], kind="ODOR", reported_indoors=True)
    fx.set_clock("2026-01-10T00:00:00.000Z", True)
    resp = api.complete_service_order(shut["id"], {"completed_index": 1000}, headers=FT)
    validate_error(resp, ApiErrorId.ERR_EMERGENCY_HOLD.value)


# ===========================================================================
# boundary_precision_check
# ===========================================================================
def test_shutoff_threshold_exact_75_dollars_eligible(api):
    """PRD 3.9: "An account becomes shutoff-eligible when its past_due_cents is at least the
    shutoff threshold of 7,500 cents (seventy-five dollars) and the winter moratorium is not
    in effect". PRD 3.9: "The notice is permitted only when the account is shutoff-eligible —
    meaning past_due_cents is at least 7,500 cents and the moratorium is not in effect".

    Design: Difficulty/boundary_precision_check/shutoff_threshold_exact_75_dollars_eligible
    """
    rs, acct, meter, bill = fx.setup_past_due_account(past_due_amount=7500)
    acct_before = fx.get_account(acct["id"])
    assert acct_before["past_due_cents"] == 7500, f"got {acct_before['past_due_cents']}"
    resp = api.shutoff_notice(acct["id"], headers=CS)
    data = validate_success(resp, 200)
    assert data["service_status"] == "SHUTOFF_PENDING", f"got {data['service_status']}"


def test_shutoff_threshold_below_75_dollars_not_eligible(api):
    """PRD 3.9: "The notice is permitted only when the account is shutoff-eligible — meaning
    past_due_cents is at least 7,500 cents and the moratorium is not in effect — and is
    otherwise rejected with ERR_NOT_SHUTOFF_ELIGIBLE."

    Design: Difficulty/boundary_precision_check/shutoff_threshold_exact_75_dollars_eligible
    """
    # 7499 is one cent below the 7500 floor -> not eligible.
    rs, acct, meter, bill = fx.setup_past_due_account(past_due_amount=7499)
    acct_before = fx.get_account(acct["id"])
    assert acct_before["past_due_cents"] == 7499, f"got {acct_before['past_due_cents']}"
    resp = api.shutoff_notice(acct["id"], headers=CS)
    validate_error(resp, ApiErrorId.ERR_NOT_SHUTOFF_ELIGIBLE.value)


def test_meter_read_zero_delta_allowed(api):
    """PRD 3.4: "The raw register delta is this read's reading_index minus the prior index; if
    that delta is negative the read is rejected with ERR_INDEX_ROLLBACK, because a register
    cannot run backward."

    Design: Difficulty/boundary_precision_check/meter_read_zero_delta_allowed_vs_rollback
    """
    rs, acct, meter = fx.setup_account_with_set_meter()
    fx.post_read(meter["id"], 1100, "2026-02-15T00:00:00.000Z")
    read2 = fx.post_read(meter["id"], 1100, "2026-03-15T00:00:00.000Z")
    assert read2["ccf_consumed"] == 0, f"got {read2['ccf_consumed']}"
    assert read2["therms_consumed"] == 0.0, f"got {read2['therms_consumed']}"
    assert read2["status"] == "POSTED", f"got {read2['status']}"


def test_meter_read_below_prior_rejected_rollback(api):
    """PRD 3.4: "if that delta is negative the read is rejected with ERR_INDEX_ROLLBACK,
    because a register cannot run backward."

    Design: Difficulty/boundary_precision_check/meter_read_zero_delta_allowed_vs_rollback
    """
    rs, acct, meter = fx.setup_account_with_set_meter()
    fx.post_read(meter["id"], 1100, "2026-02-15T00:00:00.000Z")
    resp = api.post_read(meter["id"], {"reading_index": 1099, "read_date": "2026-03-15T00:00:00.000Z",
                                       "read_type": "ACTUAL"}, headers=FT)
    validate_error(resp, ApiErrorId.ERR_INDEX_ROLLBACK.value)


# ===========================================================================
# cross_entity_state_dependency
# ===========================================================================
def test_shutoff_complete_blocked_by_emergency_ticket(api):
    """PRD 3.9: "it is rejected with ... ERR_EMERGENCY_HOLD if a live hazard ticket exists on
    the account's meters." PRD 3.9: "any emergency ticket in OPEN, DISPATCHED, or MADE_SAFE
    status on any of the account's meters".

    Design: Difficulty/cross_entity_state_dependency/shutoff_complete_blocked_by_emergency_ticket
    """
    acct, meter, shut = fx.setup_shutoff_pending_dispatched(past_due_amount=7500)
    fx.open_ticket(meter["id"], account_id=acct["id"], kind="ODOR", reported_indoors=True)
    resp = api.complete_service_order(shut["id"], {"completed_index": 1000}, headers=FT)
    validate_error(resp, ApiErrorId.ERR_EMERGENCY_HOLD.value)
    acct_after = fx.get_account(acct["id"])
    assert acct_after["service_status"] == "SHUTOFF_PENDING", f"got {acct_after['service_status']}"


def test_shutoff_complete_succeeds_without_emergency_ticket(api):
    """PRD 3.9: "Disconnection itself happens when a FieldTech completes the SHUTOFF service
    order, advancing the account SHUTOFF_PENDING -> DISCONNECTED."

    Design: Difficulty/cross_entity_state_dependency/shutoff_complete_blocked_by_emergency_ticket
    """
    acct, meter, shut = fx.setup_shutoff_pending_dispatched(past_due_amount=7500)
    resp = api.complete_service_order(shut["id"], {"completed_index": 1000}, headers=FT)
    validate_success(resp, 200)
    acct_after = fx.get_account(acct["id"])
    assert acct_after["service_status"] == "DISCONNECTED", f"got {acct_after['service_status']}"


def test_reconnect_blocked_without_held_deposit(api):
    """PRD 3.10: "a deposit whose reason is RECONNECT must be in HELD or WAIVED status, else
    the reconnect is rejected with ERR_RECONNECT_DEPOSIT_REQUIRED."

    Design: Difficulty/cross_entity_state_dependency/reconnect_complete_blocked_without_held_deposit
    """
    acct, meter, bill = fx.setup_disconnected_account(past_due_amount=7500)
    fx.pay_off_bill(acct["id"], bill["id"], amount_cents=7500, posted_date="2026-04-02T00:00:00.000Z")
    # NO reconnect deposit created.
    rec = fx.get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "RECONNECT", "premise_meter_id": meter["id"],
         "scheduled_date": "2026-04-01T00:00:00.000Z"}, headers=FT))
    fx.get_success_data(api.dispatch_service_order(rec["id"], headers=FT))
    resp = api.complete_service_order(rec["id"], {}, headers=FT)
    validate_error(resp, ApiErrorId.ERR_RECONNECT_DEPOSIT_REQUIRED.value)
    acct_after = fx.get_account(acct["id"])
    assert acct_after["service_status"] == "DISCONNECTED", f"got {acct_after['service_status']}"


def test_reconnect_succeeds_with_held_deposit(api):
    """PRD 3.10: "a deposit whose reason is RECONNECT must be in HELD or WAIVED status".
    With the deposit HELD and balance cleared, the reconnect completes.

    Design: Difficulty/cross_entity_state_dependency/reconnect_complete_blocked_without_held_deposit
    """
    acct, meter, rec = _drive_to_reconnect_ready(api)
    resp = api.complete_service_order(rec["id"], {}, headers=FT)
    validate_success(resp, 200)
    acct_after = fx.get_account(acct["id"])
    assert acct_after["service_status"] == "ACTIVE", f"got {acct_after['service_status']}"


# ===========================================================================
# compensating_invariant
# ===========================================================================
def test_deposit_collect_then_refund_conserves_held_cents(api):
    """PRD 3.11: "A required deposit is collected by a CustomerService operator, moving it
    REQUIRED -> HELD and recomputing the account's deposit_held_cents (the sum of held deposit
    amounts net of refunded and applied amounts). ... A held deposit is refunded by a
    BillingAdmin, moving it HELD -> REFUNDED and recomputing deposit_held_cents".

    Design: Difficulty/compensating_invariant/deposit_collect_then_refund_conserves_held_cents
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    # Collect the deposit FIRST (on-time count 0 -> base 15000, REQUIRED -> HELD). Injecting
    # the on-time count before creation would auto-WAIVE the deposit at amount 0 (PRD 3.11),
    # making it un-collectible; the refund threshold is only needed at refund time.
    dep = fx.create_held_deposit(acct["id"], reason="NEW_SERVICE")
    after_collect = fx.get_account(acct["id"])
    assert after_collect["deposit_held_cents"] == 15000, f"got {after_collect['deposit_held_cents']}"
    fx.inject_ontime_count(acct["id"], 12)  # makes refund permitted
    resp = api.refund_deposit(acct["id"], dep["id"], headers=ADMIN)
    data = validate_success(resp, 200)
    assert data["status"] == "REFUNDED", f"got {data['status']}"
    after_refund = fx.get_account(acct["id"])
    assert after_refund["deposit_held_cents"] == 0, (
        f"refund must restore deposit_held_cents to 0, got {after_refund['deposit_held_cents']}")


def test_deposit_collect_raises_held_cents(api):
    """PRD 3.11: "A required deposit is collected by a CustomerService operator, moving it
    REQUIRED -> HELD and recomputing the account's deposit_held_cents".

    Design: Difficulty/compensating_invariant/deposit_collect_then_refund_conserves_held_cents
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    fx.create_held_deposit(acct["id"], reason="NEW_SERVICE")
    after_collect = fx.get_account(acct["id"])
    assert after_collect["deposit_held_cents"] == 15000, f"got {after_collect['deposit_held_cents']}"


def test_shutoff_notice_then_cancel_conserves_open_order_count(api):
    """PRD 3.9: "A successful notice ... auto-creates a SHUTOFF service order in SCHEDULED
    against the account's set meter. The notice can be withdrawn by a CustomerService operator
    with a cancel-shutoff action, moving the account SHUTOFF_PENDING -> ACTIVE, bumping
    Account.version, and cancelling any scheduled or dispatched SHUTOFF service order for the
    account."

    Design: Difficulty/compensating_invariant/shutoff_notice_then_cancel_conserves_open_order_count
    """
    rs, acct, meter, bill = fx.setup_past_due_account(past_due_amount=7500)
    fx.get_success_data(api.shutoff_notice(acct["id"], headers=CS))
    resp = api.cancel_shutoff(acct["id"], headers=CS)
    data = validate_success(resp, 200)
    assert data["service_status"] == "ACTIVE", f"got {data['service_status']}"
    orders = fx.get_success_data(api.list_service_orders(headers=FT, params={"account_id": acct["id"]}))
    open_shutoffs = [o for o in orders
                     if o["order_type"] == "SHUTOFF" and o["status"] in ("SCHEDULED", "DISPATCHED")]
    assert len(open_shutoffs) == 0, (
        f"cancel-shutoff must leave zero open SHUTOFF orders, got {len(open_shutoffs)}")


def test_shutoff_notice_creates_one_shutoff_order(api):
    """PRD 3.9: "A successful notice bumps Account.version and auto-creates a SHUTOFF service
    order in SCHEDULED against the account's set meter."

    Design: Difficulty/compensating_invariant/shutoff_notice_then_cancel_conserves_open_order_count
    """
    rs, acct, meter, bill = fx.setup_past_due_account(past_due_amount=7500)
    fx.get_success_data(api.shutoff_notice(acct["id"], headers=CS))
    orders = fx.get_success_data(api.list_service_orders(headers=FT, params={"account_id": acct["id"]}))
    open_shutoffs = [o for o in orders
                     if o["order_type"] == "SHUTOFF" and o["status"] in ("SCHEDULED", "DISPATCHED")]
    assert len(open_shutoffs) == 1, f"expected one open SHUTOFF order, got {len(open_shutoffs)}"
