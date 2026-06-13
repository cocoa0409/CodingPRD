"""Validation-ordering conflicts: when two checks could both fire on one
request, the higher-priority error is returned per the fixed §2.10 order.

Covers the {state vs business-safety} pair (route a terminal event whose
system is also in test mode) and the {ownership vs safety} pair (a non-owner
Subscriber arms an OFFLINE system).
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
    create_alarm_event_payload,
    arm_payload,
)

ADMIN = make_admin_headers()
OPERATOR = make_operator_headers()

PRO = dict(tier="PRO", monthly_fee_cents=6200, police_dispatch_included=True,
           max_sensors=32, cellular_backup_included=True)


# ─── state (pri6) vs business_safety (pri7): route a suppressed test-mode event ──

def test_route_terminal_event_returns_invalid_state_over_test_mode(api):
    """PRD §2.10: "then the subscriber ownership check (`ERR_NOT_ACCOUNT_OWNER`),
    then whether the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`). Business-specific safety,
    constraint, and temporal checks follow, in the relative order given in §3
    where each is described."

    Design: Difficulty/priority_pair_validation_conflict/route_invalid_state_beats_test_mode_active
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="CELLULAR")
    sensor = create_sensor(system["id"], zone_number=1, sensor_type="MOTION")
    validate_success(api.activate_account(acct["id"], ADMIN), 200)
    # System enters test mode; a burglary signal under test mode auto-SUPPRESSED.
    validate_success(api.enter_test_mode(system["id"], OPERATOR), 200)
    ev = validate_success(
        api.create_alarm_event(create_alarm_event_payload(system["id"], sensor["id"], signal_type="BURGLARY"), OPERATOR),
        201)
    assert ev["status"] == "SUPPRESSED", "test-mode burglary signal is auto-suppressed (terminal)"

    # Routing a terminal (not RECEIVED) event that is ALSO on a test-mode system:
    # the state check (transition undefined) wins over the test-mode-active check.
    res = api.route_alarm_event(ev["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE")


def test_route_terminal_event_does_not_return_test_mode_active(api):
    """PRD §3.6: "An attempt to route an event whose system is in test mode is
    rejected with `ERR_TEST_MODE_ACTIVE`, since test-mode signals never
    escalate."

    Here the event is terminal (SUPPRESSED), so the §2.10 state check pre-empts
    the test-mode-active safety check, which therefore must NOT be returned.

    Design: Difficulty/priority_pair_validation_conflict/route_invalid_state_beats_test_mode_active
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="CELLULAR")
    sensor = create_sensor(system["id"], zone_number=1, sensor_type="MOTION")
    validate_success(api.activate_account(acct["id"], ADMIN), 200)
    validate_success(api.enter_test_mode(system["id"], OPERATOR), 200)
    ev = validate_success(
        api.create_alarm_event(create_alarm_event_payload(system["id"], sensor["id"], signal_type="BURGLARY"), OPERATOR),
        201)

    res = api.route_alarm_event(ev["id"], OPERATOR)
    body = res.json()
    assert body["data"]["error_id"] != "ERR_TEST_MODE_ACTIVE", (
        "the higher-priority state check pre-empts the test-mode-active error"
    )


# ─── business_referential (pri5) vs business_safety (pri8): non-owner arm OFFLINE ──

def test_arm_non_owner_offline_returns_not_account_owner(api):
    """PRD §2.10: "then resolution of body-referenced foreign keys
    (`ERR_REFERENCE_NOT_FOUND`), then the subscriber ownership check
    (`ERR_NOT_ACCOUNT_OWNER`), then whether the target resource is in a state from
    which the requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/arm_owner_check_beats_communicator_offline
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct_a = create_account(plan["id"])
    acct_b = create_account(plan["id"])
    # A owns an OFFLINE system (stale check-in).
    system = create_system(acct_a["id"], primary_path="CELLULAR", last_checkin_minutes_ago=9999)
    create_sensor(system["id"], zone_number=1, sensor_type="MOTION")
    validate_success(api.activate_account(acct_a["id"], ADMIN), 200)

    # B's subscriber attempts to arm A's system: the ownership check fires first.
    sub_b = make_subscriber_headers(acct_b["id"])
    res = api.arm_system(system["id"], arm_payload("ARMED_AWAY"), sub_b)
    validate_error(res, "ERR_NOT_ACCOUNT_OWNER")


def test_arm_non_owner_offline_does_not_return_communicator_offline(api):
    """PRD §3.4: "A system whose communicator cannot reach the monitoring centre —
    that is, one whose `communicator_health` is `OFFLINE` — cannot be armed, and
    the attempt is rejected with `ERR_COMMUNICATOR_OFFLINE`."

    Here the caller is not the owner, so the §2.10 ownership check pre-empts the
    communicator-offline safety check, which therefore must NOT be returned.

    Design: Difficulty/priority_pair_validation_conflict/arm_owner_check_beats_communicator_offline
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct_a = create_account(plan["id"])
    acct_b = create_account(plan["id"])
    system = create_system(acct_a["id"], primary_path="CELLULAR", last_checkin_minutes_ago=9999)
    create_sensor(system["id"], zone_number=1, sensor_type="MOTION")
    validate_success(api.activate_account(acct_a["id"], ADMIN), 200)

    sub_b = make_subscriber_headers(acct_b["id"])
    res = api.arm_system(system["id"], arm_payload("ARMED_AWAY"), sub_b)
    body = res.json()
    assert body["data"]["error_id"] != "ERR_COMMUNICATOR_OFFLINE", (
        "the higher-priority ownership check pre-empts the communicator-offline error"
    )
