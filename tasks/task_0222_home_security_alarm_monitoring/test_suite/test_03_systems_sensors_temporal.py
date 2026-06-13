"""Security systems, arming cycle, sensor inventory, communicator-health
boundaries, temporal-overlap windows, and conservation invariants.

Covers: the cyclic arming state machine, the signal-dBm and max-sensors
boundaries, the half-open test-mode window and the debounce buffer, and the
two conservation invariants (monetary balance and integer sensor count).
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
    create_sensor_payload,
    create_alarm_event_payload,
    setup_activated_account,
    setup_activated_armed_account,
    arm_payload,
    dispatch_for_event,
    ingest_route_dispatch,
)

ADMIN = make_admin_headers()
OPERATOR = make_operator_headers()

PRO = dict(tier="PRO", monthly_fee_cents=6200, police_dispatch_included=True,
           max_sensors=32, cellular_backup_included=True)
BASIC = dict(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
             max_sensors=8, cellular_backup_included=False)


# ─── non_linear_state_machine: cyclic arming DISARMED->AWAY->DISARMED->STAY ──

def test_arming_cycle_disarmed_to_armed_away_back_to_disarmed(api):
    """PRD §3.4: "the system's `arming_state` moves from `DISARMED` to the chosen
    mode... Disarming returns the system to `DISARMED` and is permitted only from
    `ARMED_STAY` or `ARMED_AWAY`."

    Design: Difficulty/non_linear_state_machine/system_arming_cycle_disarmed_armed_disarmed
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_account(plan_overrides=BASIC)
    sub = make_subscriber_headers(ctx["account"]["id"])
    sid = ctx["system"]["id"]

    armed = validate_success(api.arm_system(sid, arm_payload("ARMED_AWAY"), sub), 200)
    assert armed["arming_state"] == "ARMED_AWAY"

    disarmed = validate_success(api.disarm_system(sid, sub), 200)
    assert disarmed["arming_state"] == "DISARMED", "system re-enters DISARMED"


def test_arming_cycle_rearm_to_armed_stay_after_disarm(api):
    """PRD §3.4: "The arming state is otherwise free to cycle among `DISARMED`,
    `ARMED_STAY`, and `ARMED_AWAY` while the account is `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/system_arming_cycle_disarmed_armed_disarmed
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_account(plan_overrides=BASIC)
    sub = make_subscriber_headers(ctx["account"]["id"])
    sid = ctx["system"]["id"]

    validate_success(api.arm_system(sid, arm_payload("ARMED_AWAY"), sub), 200)
    validate_success(api.disarm_system(sid, sub), 200)
    rearmed = validate_success(api.arm_system(sid, arm_payload("ARMED_STAY"), sub), 200)
    assert rearmed["arming_state"] == "ARMED_STAY", "the same system re-arms to a new mode"


# ─── boundary_precision: communicator signal_dbm >= -85 ──────────────────────

def test_signal_dbm_minus85_is_healthy_boundary(api):
    """PRD §3.3: "the signal is acceptable when `cellular_signal_dbm` is at or
    above −85 dBm... When both are acceptable, health is `HEALTHY`."

    Design: Difficulty/boundary_precision_check/communicator_signal_dbm_boundary_minus85_healthy
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="CELLULAR",
                           cellular_signal_dbm=-50, backup_battery_pct=100,
                           last_checkin_minutes_ago=5)
    patched = validate_success(
        api.patch_system(system["id"], {"cellular_signal_dbm": -85}, OPERATOR), 200)
    assert patched["communicator_health"] == "HEALTHY", "-85 is inclusive -> HEALTHY"


def test_signal_dbm_minus86_is_degraded(api):
    """PRD §3.3: "when the system is not `OFFLINE` but at least one of signal or
    battery falls below its threshold, health is `DEGRADED`."

    Design: Difficulty/boundary_precision_check/communicator_signal_dbm_boundary_minus85_healthy
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="CELLULAR",
                           cellular_signal_dbm=-50, backup_battery_pct=100,
                           last_checkin_minutes_ago=5)
    patched = validate_success(
        api.patch_system(system["id"], {"cellular_signal_dbm": -86}, OPERATOR), 200)
    assert patched["communicator_health"] == "DEGRADED", "-86 is below -85 -> DEGRADED"


# ─── boundary_precision: sensor_count == max_sensors ─────────────────────────

def test_enroll_second_sensor_at_max_succeeds(api):
    """PRD §3.5: "enrolling a sensor must not push the system's `sensor_count`
    above the `max_sensors` of the account's plan, and an over-limit enrolment is
    rejected with `ERR_SENSOR_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/sensor_enrollment_at_max_sensors_boundary
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                       max_sensors=2, cellular_backup_included=False)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="BROADBAND")
    create_sensor(system["id"], zone_number=1, sensor_type="DOOR")

    res = api.create_sensor(create_sensor_payload(system["id"], zone_number=2, sensor_type="MOTION"), ADMIN)
    validate_success(res, 201)
    system_after = validate_success(api.get_system(system["id"], ADMIN), 200)
    assert system_after["sensor_count"] == 2, "count reaches the limit, not over"


def test_enroll_third_sensor_over_max_rejected(api):
    """PRD §3.5: "an over-limit enrolment is rejected with
    `ERR_SENSOR_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/sensor_enrollment_at_max_sensors_boundary
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
                       max_sensors=2, cellular_backup_included=False)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="BROADBAND")
    create_sensor(system["id"], zone_number=1, sensor_type="DOOR")
    create_sensor(system["id"], zone_number=2, sensor_type="MOTION")

    res = api.create_sensor(create_sensor_payload(system["id"], zone_number=3, sensor_type="GLASS_BREAK"), ADMIN)
    validate_error(res, "ERR_SENSOR_LIMIT_EXCEEDED")


# ─── resource_temporal_overlap: half-open test-mode window ───────────────────

def test_reenter_test_mode_mid_window_rejected(api):
    """PRD §3.4: "a window is considered open precisely while the current clock is
    strictly before `test_mode_expires_utc`. Entering is therefore allowed when
    `test_mode` is false, or when the current clock has reached
    `test_mode_expires_utc`; a re-entry exactly at `test_mode_expires_utc` is
    permitted, while any earlier re-entry is rejected with
    `ERR_TEST_MODE_ALREADY_OPEN`."

    Design: Difficulty/resource_temporal_overlap/test_mode_window_overlap_half_open_adjacency
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_account(plan_overrides=PRO, system_overrides={"primary_path": "CELLULAR"})
    sid = ctx["system"]["id"]
    validate_success(api.enter_test_mode(sid, OPERATOR), 200)  # window [00:00, 02:00)

    set_clock("2026-06-01T01:00:00Z")  # +60m, still open
    res = api.enter_test_mode(sid, OPERATOR)
    validate_error(res, "ERR_TEST_MODE_ALREADY_OPEN")


def test_reenter_test_mode_at_window_boundary_succeeds(api):
    """PRD §3.4: "a re-entry exactly at `test_mode_expires_utc` is permitted...
    On entry, `test_mode` is set true, `test_mode_expires_utc` is set to the
    current clock plus the 120-minute test-mode window, and `arming_state` is
    forced to `DISARMED`."

    Design: Difficulty/resource_temporal_overlap/test_mode_window_overlap_half_open_adjacency
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_account(plan_overrides=PRO, system_overrides={"primary_path": "CELLULAR"})
    sid = ctx["system"]["id"]
    validate_success(api.enter_test_mode(sid, OPERATOR), 200)  # window [00:00, 02:00)

    set_clock("2026-06-01T02:00:00Z")  # +120m, exactly at expiry boundary
    re_entered = validate_success(api.enter_test_mode(sid, OPERATOR), 200)
    assert re_entered["test_mode"] is True, "re-entry at the expiry boundary is allowed"


# ─── resource_temporal_overlap: signal debounce buffer ──────────────────────

def test_debounce_second_signal_within_60s_rejected(api):
    """PRD §3.6: "A new alarm event from the same sensor whose `raised_utc` falls
    within 60 seconds of a still-open prior event from that sensor — where 'still
    open' means a prior event in `RECEIVED`, `ROUTED`, or `DISPATCHED` — is
    rejected as a duplicate with `ERR_SIGNAL_DEBOUNCED`."

    Design: Difficulty/resource_temporal_overlap/signal_debounce_buffer_window_same_sensor
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_armed_account(plan_overrides=PRO,
                                        system_overrides={"primary_path": "CELLULAR"},
                                        sensor_overrides={"sensor_type": "MOTION"})
    sid, senid = ctx["system"]["id"], ctx["sensor"]["id"]
    validate_success(api.create_alarm_event(create_alarm_event_payload(sid, senid, signal_type="BURGLARY"), OPERATOR), 201)

    set_clock("2026-06-01T00:00:30Z")  # +30s, within window
    res = api.create_alarm_event(create_alarm_event_payload(sid, senid, signal_type="BURGLARY"), OPERATOR)
    validate_error(res, "ERR_SIGNAL_DEBOUNCED")


def test_debounce_third_signal_after_61s_accepted(api):
    """PRD §3.6: "The window is a buffer measured from the prior event: two events
    from the same sensor spaced strictly more than 60 seconds apart never
    collide."

    Design: Difficulty/resource_temporal_overlap/signal_debounce_buffer_window_same_sensor
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_armed_account(plan_overrides=PRO,
                                        system_overrides={"primary_path": "CELLULAR"},
                                        sensor_overrides={"sensor_type": "MOTION"})
    sid, senid = ctx["system"]["id"], ctx["sensor"]["id"]
    validate_success(api.create_alarm_event(create_alarm_event_payload(sid, senid, signal_type="BURGLARY"), OPERATOR), 201)

    set_clock("2026-06-01T00:01:01Z")  # +61s, strictly past the 60s buffer
    res = api.create_alarm_event(create_alarm_event_payload(sid, senid, signal_type="BURGLARY"), OPERATOR)
    validate_success(res, 201)


# ─── compensating_invariant: monetary balance conserved ──────────────────────

def test_dispatch_then_cancel_conserves_balance(api):
    """PRD §3.6: "Cancellation is compensating: the dispatch's `fee_cents` is
    reversed out of the account's `monitoring_balance_cents`, returning the
    balance to its pre-dispatch value."

    Design: Difficulty/compensating_invariant/dispatch_then_cancel_conserves_monitoring_balance
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_armed_account(plan_overrides=PRO,
                                        system_overrides={"primary_path": "CELLULAR"},
                                        sensor_overrides={"sensor_type": "SMOKE"})
    aid, sid, senid = ctx["account"]["id"], ctx["system"]["id"], ctx["sensor"]["id"]

    bal_before = validate_success(api.get_account(aid, ADMIN), 200)["monitoring_balance_cents"]
    assert bal_before == 0, "day-0 proration is 0"

    dispatched = ingest_route_dispatch(sid, senid, "FIRE")
    disp = dispatch_for_event(dispatched["id"])
    assert disp["fee_cents"] == 4000, "FIRE dispatch fee is 4000 while ORDERED"

    validate_success(api.cancel_dispatch(disp["id"], OPERATOR), 200)
    bal_after = validate_success(api.get_account(aid, ADMIN), 200)["monitoring_balance_cents"]
    assert bal_after == 0, "fee reversed -> balance returns to pre-dispatch value (0)"


def test_dispatch_fee_4000_recorded_on_ordered_dispatch(api):
    """PRD §3.6: "a fire dispatch costs 4000 cents... The chosen amount is
    recorded on the dispatch's `fee_cents` and added to `monitoring_balance_cents`
    at creation."

    Design: Difficulty/compensating_invariant/dispatch_then_cancel_conserves_monitoring_balance
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_armed_account(plan_overrides=PRO,
                                        system_overrides={"primary_path": "CELLULAR"},
                                        sensor_overrides={"sensor_type": "SMOKE"})
    sid, senid = ctx["system"]["id"], ctx["sensor"]["id"]
    dispatched = ingest_route_dispatch(sid, senid, "FIRE")
    disp = dispatch_for_event(dispatched["id"])
    assert disp["fee_cents"] == 4000
    bal = validate_success(api.get_account(ctx["account"]["id"], ADMIN), 200)["monitoring_balance_cents"]
    assert bal == 4000, "the 4000 fee is added to the balance at dispatch creation"


# ─── compensating_invariant: sensor_count conserved ──────────────────────────

def test_enroll_then_remove_conserves_sensor_count(api):
    """PRD §3.5: "removal decrements the system's `sensor_count` by one, so that
    an enrol-then-remove pair leaves the tally conserved."

    Design: Difficulty/compensating_invariant/enroll_then_remove_conserves_sensor_count
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**BASIC)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="BROADBAND")
    create_sensor(system["id"], zone_number=1, sensor_type="DOOR")
    count_before = validate_success(api.get_system(system["id"], ADMIN), 200)["sensor_count"]
    assert count_before == 1

    s2 = create_sensor(system["id"], zone_number=2, sensor_type="MOTION")
    validate_success(api.remove_sensor(s2["id"], ADMIN), 200)
    count_after = validate_success(api.get_system(system["id"], ADMIN), 200)["sensor_count"]
    assert count_after == 1, "enroll+remove conserves the sensor count"


def test_enroll_raises_sensor_count_by_one(api):
    """PRD §3.5: "A new sensor starts in status `ENROLLED`, and enrolling it
    increments the owning system's `sensor_count`."

    Design: Difficulty/compensating_invariant/enroll_then_remove_conserves_sensor_count
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**BASIC)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="BROADBAND")
    create_sensor(system["id"], zone_number=1, sensor_type="DOOR")
    create_sensor(system["id"], zone_number=2, sensor_type="MOTION")
    count = validate_success(api.get_system(system["id"], ADMIN), 200)["sensor_count"]
    assert count == 2, "each enroll raises sensor_count by 1"
