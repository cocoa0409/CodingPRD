"""Conserved-quantity invariants, optimistic-concurrency control, scheduled-action freeing,
and immediate-consistency of cancellation fields.

Covers difficulty Rule 9 and the corner cross_cutting_complexity_layers + consistency_model.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_subscriber_headers, make_agent_headers, TEST_USERS,
    create_plan_payload, create_hold_payload,
    setup_active_contract_with_device, setup_suspended_contract_with_device,
    setup_assigned_alarm,
    set_clock, request_cancellation_active, drive_contract_to_suspended,
    create_shift, raise_alarm, assign_alarm, dispatch,
)

ADMIN = TEST_USERS["admin_headers"]
PLUS_PLAN = dict(tier="PLUS", monthly_fee_cents=4000, fall_detection_addon_cents=1500,
                 included_test_interval_days=30, response_sla_seconds=60,
                 early_termination_fee_cents=20000, min_commitment_months=12)


# ===========================================================================
# Rule 9 — compensating-action invariants
# ===========================================================================
def test_open_alarm_count_conserved_across_resolve(api):
    """PRD 3.8: "The alarm records `signal_received_at` at the current instant, increments the
    device's `open_alarm_count`".
    PRD 3.10: "steps that drive the alarm to a terminal status also set `resolved_at` to the
    current instant and decrement the device's `open_alarm_count` by one."

    Design: Difficulty/compensating_invariant/open_alarm_count_conserved_across_resolve
    """
    sub, contract, device, alarm = setup_assigned_alarm(agent_user_id="agent-inv")
    # Pre-cycle baseline open_alarm_count is 0 (PRD entity default). Raise+resolve must net 0.
    dispatch(alarm["id"], "agent-inv", "CALL_SUBSCRIBER", "ANSWERED")
    res = api.create_dispatch_action(
        alarm["id"], {"action_type": "RESOLVE_OK", "outcome": "CONFIRMED_OK"},
        make_agent_headers("agent-inv"))
    validate_success(res, 201)
    updated = get_success_data(api.get_alarm(alarm["id"], ADMIN))
    assert updated["status"] == "RESOLVED_OK"
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["open_alarm_count"] == 0, (
        f"open_alarm_count must return to 0 after raise+resolve, got {device['open_alarm_count']}"
    )


def test_open_alarm_count_increments_on_raise(api):
    """PRD 3.8: "The alarm records `signal_received_at` at the current instant, increments the
    device's `open_alarm_count`".

    The forward (increment) leg of the conserved counter: raising one alarm moves
    open_alarm_count from its pre-cycle 0 to 1.

    Design: Difficulty/compensating_invariant/open_alarm_count_conserved_across_resolve
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    assert device["open_alarm_count"] == 0
    raise_alarm(device["id"], sub["id"], signal_type="MANUAL_BUTTON")
    device = get_success_data(api.get_device(device["id"], ADMIN))
    assert device["open_alarm_count"] == 1, (
        f"raising an alarm must increment open_alarm_count to 1, got {device['open_alarm_count']}"
    )


def test_outstanding_balance_is_etf_minus_refund(api):
    """PRD 3.7: "computes the refund and early-termination figures, sets
    `outstanding_balance_cents` to `etf_charged_cents` minus `refund_cents`".
    PRD 3.7: "`etf_charged_cents` is set to the pinned `pinned_etf_cents` when the current
    clock instant is before `activated_at` plus `pinned_min_commitment_months` months".

    Design: Difficulty/compensating_invariant/contract_balance_net_etf_minus_refund_invariant
    """
    # PLUS ETF 20000, min_commitment 12mo; addon device; suspended; cancel at 2026-06-15.
    # IMMEDIATE refund 2928; inside commitment -> ETF 20000; balance = 20000 - 2928 = 17072.
    plan, sub, contract, device = setup_suspended_contract_with_device(
        plan_overrides=PLUS_PLAN, device_overrides={"fall_detection_enabled": True},
        clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-15T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    res = api.request_cancellation(
        contract["id"], {"expected_contract_version": contract["version"]},
        make_subscriber_headers(sub["id"]))
    data = validate_success(res, 200)
    assert data["etf_charged_cents"] == 20000, f"ETF must be 20000, got {data['etf_charged_cents']}"
    assert data["refund_cents"] == 2928, f"refund must be 2928, got {data['refund_cents']}"
    assert data["outstanding_balance_cents"] == 17072, (
        f"balance must equal ETF - refund = 17072, got {data['outstanding_balance_cents']}"
    )


def test_outstanding_balance_etf_only_when_refund_zero(api):
    """PRD 3.7: "sets `outstanding_balance_cents` to `etf_charged_cents` minus `refund_cents`".
    PRD 3.7 (STANDARD): "`refund_cents` is 0".
    PRD 3.7: "`etf_charged_cents` is set to the pinned `pinned_etf_cents` when the current clock
    instant is before `activated_at` plus `pinned_min_commitment_months` months".

    The net-balance invariant under the STANDARD (ACTIVE) variant: with ETF 20000 inside the
    commitment window and refund 0, outstanding_balance_cents == 20000 - 0 == 20000.

    Design: Difficulty/compensating_invariant/contract_balance_net_etf_minus_refund_invariant
    """
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=PLUS_PLAN, device_overrides={"fall_detection_enabled": True},
        clock="2026-06-01T00:00:00Z")
    # Cancel while ACTIVE, still inside the 12-month commitment (clock 2026-06-15).
    set_clock("2026-06-15T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    res = api.request_cancellation(
        contract["id"], {"expected_contract_version": contract["version"]},
        make_subscriber_headers(sub["id"]))
    data = validate_success(res, 200)
    assert data["refund_cents"] == 0
    assert data["etf_charged_cents"] == 20000
    assert data["outstanding_balance_cents"] == 20000, (
        f"balance must equal ETF - refund = 20000, got {data['outstanding_balance_cents']}"
    )


# ===========================================================================
# Corner — optimistic concurrency
# ===========================================================================
def test_cancellation_succeeds_with_fresh_version(api):
    """PRD 2.6: "The cancellation-request operation requires `expected_contract_version` as a
    mandatory field in its body, carrying the `version` of the contract the client last
    observed. If `expected_contract_version` does not equal the contract's current `version`,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    A correct (freshly-read) version succeeds, moving service_status to CANCELLATION_REQUESTED.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_write
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    res = api.request_cancellation(
        contract["id"], {"expected_contract_version": contract["version"]},
        make_subscriber_headers(sub["id"]))
    data = validate_success(res, 200)
    assert data["service_status"] == "CANCELLATION_REQUESTED"


def test_stale_version_after_billing_bump_rejected(api):
    """PRD 2.6: "If `expected_contract_version` does not equal the contract's current `version`,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 2.6: "This matters because a contract's `version` legitimately advances between the
    client's read and its cancellation request — a billing action such as marking past-due or
    recording a payment, or a suspend/reinstate cascade, each bump `version`".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_after_cascade_returns_stale_version
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    stale_version = contract["version"]
    # Advance clock, mark past-due (bumps version) while service still ACTIVE.
    set_clock("2026-07-02T00:00:00Z")
    get_success_data(api.mark_past_due(contract["id"], ADMIN))
    res = api.request_cancellation(
        contract["id"], {"expected_contract_version": stale_version},
        make_subscriber_headers(sub["id"]))
    validate_error(res, "ERR_STALE_VERSION")


# ===========================================================================
# Corner — scheduled actions
# ===========================================================================
def test_cancel_hold_frees_interval_for_new_hold(api):
    """PRD 3.12: "A `Subscriber` may cancel a `SCHEDULED` hold, moving it to `CANCELLED`, which
    frees its interval (and the surrounding buffer) for new holds and increments the hold's
    `version`."

    Design: Corner/cross_cutting_complexity_layers/scheduled_hold_cancel_frees_interval
    """
    plan, sub, contract, device = setup_active_contract_with_device(clock="2026-06-01T00:00:00Z")
    hdrs = make_subscriber_headers(sub["id"])
    hold = get_success_data(api.create_hold(
        create_hold_payload(device["id"], "2026-06-05T00:00:00Z", "2026-06-10T00:00:00Z"), hdrs))
    get_success_data(api.cancel_hold(hold["id"], hdrs))
    # A previously-conflicting hold now succeeds because the interval+buffer is freed.
    res = api.create_hold(
        create_hold_payload(device["id"], "2026-06-06T00:00:00Z", "2026-06-12T00:00:00Z"), hdrs)
    data = validate_success(res, 201)
    assert data["status"] == "SCHEDULED"


# ===========================================================================
# Corner — immediate consistency
# ===========================================================================
def test_cancellation_fields_visible_in_same_response(api):
    """PRD 3.7: "In both cases the request moves `service_status` to `CANCELLATION_REQUESTED`,
    computes the refund and early-termination figures, sets `outstanding_balance_cents` to
    `etf_charged_cents` minus `refund_cents`, and increments `version`."
    PRD 3.7 (STANDARD): "`refund_cents` is 0". ETF 0 outside commitment -> etf 0, balance 0.

    Design: Corner/consistency_model/cancellation_fields_visible_in_same_response
    """
    # BASIC ETF 0, min_commitment 0; cancel while ACTIVE -> refund 0, etf 0, balance 0.
    plan, sub, contract, device = setup_active_contract_with_device(
        plan_overrides=create_plan_payload(), clock="2026-06-01T00:00:00Z")
    contract = get_success_data(api.get_contract(contract["id"], ADMIN))
    res = api.request_cancellation(
        contract["id"], {"expected_contract_version": contract["version"]},
        make_subscriber_headers(sub["id"]))
    data = validate_success(res, 200)
    assert data["refund_cents"] == 0
    assert data["etf_charged_cents"] == 0
    assert data["outstanding_balance_cents"] == 0
