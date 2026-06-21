"""State-machine corners: initial state, precondition enforcement, invalid and
terminal transitions, idempotency, and cross-entity disarm side effect.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    make_admin_headers,
    make_operator_headers,
    make_subscriber_headers,
    set_clock,
    create_plan,
    create_account,
    create_system,
    create_sensor,
    issue_permit,
    ingest_event,
    ingest_route_dispatch,
    fine_for_event,
    setup_activated_account,
    setup_activated_armed_account,
    arm_payload,
    resolve_payload,
    finalize_cancellation_payload,
)

ADMIN = make_admin_headers()
OPERATOR = make_operator_headers()

BASIC = dict(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
             max_sensors=8, cellular_backup_included=False)
PRO = dict(tier="PRO", monthly_fee_cents=6200, police_dispatch_included=True,
           max_sensors=32, cellular_backup_included=True)


def test_account_initial_state_pending(api):
    """PRD §3.1: "A freshly created account begins with `contract_status` of
    `PENDING`."

    Design: Corner/state_machines/account_initial_state_pending
    """
    plan = create_plan(**BASIC)
    acct = create_account(plan["id"])
    assert acct["contract_status"] == "PENDING"


def test_activate_account_without_system_invalid_state(api):
    """PRD §3.1: "Activation... is permitted only when the account is currently
    `PENDING`, when the account has at least one security system whose
    `sensor_count` is at least one, and when the referenced monitoring plan still
    exists."

    Design: Corner/state_machines/activate_account_without_system_invalid_state
    """
    plan = create_plan(**BASIC)
    acct = create_account(plan["id"])
    res = api.activate_account(acct["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_finalize_cancellation_from_pending_invalid_state(api):
    """PRD §3.1: "Finalization is reserved to an `Administrator` and is allowed
    only while `contract_status` is `CANCELLATION_REQUESTED`."

    Design: Corner/state_machines/finalize_cancellation_from_pending_invalid_state
    """
    plan = create_plan(**BASIC)
    acct = create_account(plan["id"])
    fetched = validate_success(api.get_account(acct["id"], ADMIN), 200)
    res = api.finalize_cancellation(
        acct["id"], finalize_cancellation_payload(fetched["version"]), ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


def test_pay_already_paid_fine_invalid_state(api):
    """PRD §3.8: "A `Subscriber` or `Administrator` may pay an `ASSESSED` fine,
    moving its `settlement_status` to the terminal `PAID`."

    Design: Corner/state_machines/pay_already_paid_fine_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_armed_account(plan_overrides=PRO,
                                        system_overrides={"primary_path": "CELLULAR"},
                                        sensor_overrides={"sensor_type": "MOTION"})
    # No permit -> a no-permit false alarm produces an ASSESSED fine.
    dispatched = ingest_route_dispatch(ctx["system"]["id"], ctx["sensor"]["id"], "BURGLARY")
    validate_success(api.resolve_alarm_event(dispatched["id"], resolve_payload("FALSE_ALARM"), OPERATOR), 200)
    fine = fine_for_event(dispatched["id"])
    validate_success(api.pay_fine(fine["id"], ADMIN), 200)
    res = api.pay_fine(fine["id"], ADMIN)  # second pay -> terminal
    validate_error(res, "ERR_INVALID_STATE")


def test_request_cancellation_from_cancelled_invalid_state(api):
    """PRD §3.1: "A `Subscriber` or an `Administrator` may request cancellation,
    which is allowed only while the contract is `ACTIVE`."

    Design: Corner/state_machines/terminal_cancelled_account_request_cancellation_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_account(plan_overrides=BASIC)
    aid = ctx["account"]["id"]
    requested = validate_success(api.request_cancellation(aid, ADMIN), 200)
    validate_success(
        api.finalize_cancellation(aid, finalize_cancellation_payload(requested["version"]), ADMIN), 200)
    res = api.request_cancellation(aid, ADMIN)  # from terminal CANCELLED
    validate_error(res, "ERR_INVALID_STATE")


def test_disarm_resolves_received_burglary_event_false(api):
    """PRD §3.4: "any alarm event on this system that is still `RECEIVED` and
    whose `signal_type` is `BURGLARY` (and therefore not yet routed) is resolved
    to `RESOLVED_FALSE`. Fire, medical, and panic events on the system are left
    untouched by a disarm."

    Design: Corner/state_machines/disarm_resolves_received_burglary_event_false
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="CELLULAR")
    sen1 = create_sensor(system["id"], zone_number=1, sensor_type="MOTION")
    sen2 = create_sensor(system["id"], zone_number=2, sensor_type="SMOKE")
    validate_success(api.activate_account(acct["id"], ADMIN), 200)
    sub = make_subscriber_headers(acct["id"])
    validate_success(api.arm_system(system["id"], arm_payload("ARMED_AWAY"), sub), 200)

    evb = ingest_event(system["id"], sen1["id"], "BURGLARY")
    evf = ingest_event(system["id"], sen2["id"], "FIRE")
    assert evb["status"] == "RECEIVED"
    assert evf["status"] == "RECEIVED"

    validate_success(api.disarm_system(system["id"], sub), 200)
    burglary_after = validate_success(api.get_alarm_event(evb["id"], ADMIN), 200)
    fire_after = validate_success(api.get_alarm_event(evf["id"], ADMIN), 200)
    assert burglary_after["status"] == "RESOLVED_FALSE", "RECEIVED burglary resolved false on disarm"
    assert fire_after["status"] == "RECEIVED", "FIRE event untouched by disarm"


def test_withdraw_cancellation_resets_etf_and_returns_active(api):
    """PRD §3.1: "withdrawal returns the contract to `ACTIVE`, resets
    `early_termination_fee_cents` back to zero, and increments `version` by one."

    Design: Corner/state_machines/withdraw_cancellation_resets_etf_to_zero
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_account(plan_overrides=BASIC)  # term 12mo at day0
    aid = ctx["account"]["id"]
    requested = validate_success(api.request_cancellation(aid, ADMIN), 200)
    assert requested["early_termination_fee_cents"] == 24000, (
        "12 remaining months * 2000 = 24000 frozen at request"
    )
    withdrawn = validate_success(api.withdraw_cancellation(aid, ADMIN), 200)
    assert withdrawn["contract_status"] == "ACTIVE"
    assert withdrawn["early_termination_fee_cents"] == 0, "withdrawal resets ETF to zero"
