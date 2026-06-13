"""False-alarm counting, tiered fines, the dispatch/resolve fork, and the
finalize-cancellation cascade.

Covers: the net-of-waived chargeable ordinal (a waived first fine cheapens a
later one), the RESOLVED_REAL vs RESOLVED_FALSE fork with divergent fine
side-effects, the depth-2 false-alarm count->fine chain, and the depth-3
finalize-cancellation cascade with fee reversal.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
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
    resolve_false_alarm,
    resolve_real,
    fine_for_event,
    dispatch_for_event,
    setup_activated_armed_account,
    arm_payload,
    resolve_payload,
    finalize_cancellation_payload,
)

ADMIN = make_admin_headers()
OPERATOR = make_operator_headers()

PRO = dict(tier="PRO", monthly_fee_cents=6200, police_dispatch_included=True,
           max_sensors=32, cellular_backup_included=True)


# ─── dual_variant_calc: net-of-waived chargeable ordinal ─────────────────────

def _setup_three_false_alarms_first_waived(api):
    """PRO account + ACTIVE permit, armed; three sequential burglary false
    alarms; the first fine is waived before the third resolves.

    Returns the list of three event ids in order plus the account id.
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct = create_account(plan["id"], premises_type="RESIDENTIAL")
    system = create_system(acct["id"], primary_path="CELLULAR")
    sensor = create_sensor(system["id"], zone_number=1, sensor_type="MOTION")
    validate_success(api.activate_account(acct["id"], ADMIN), 200)
    issue_permit(acct["id"], "P-NET-1", filed_days_late=0)
    sub = make_subscriber_headers(acct["id"])
    validate_success(api.arm_system(system["id"], arm_payload("ARMED_AWAY"), sub), 200)

    # Event 1 -> false alarm, then waive its fine.
    ev1 = ingest_route_dispatch(system["id"], sensor["id"], "BURGLARY")
    validate_success(api.resolve_alarm_event(ev1["id"], resolve_payload("FALSE_ALARM"), OPERATOR), 200)
    fine1 = fine_for_event(ev1["id"])
    validate_success(api.waive_fine(fine1["id"], ADMIN), 200)

    # Event 2 -> false alarm.
    set_clock("2026-06-01T00:10:00Z")
    ev2 = ingest_route_dispatch(system["id"], sensor["id"], "BURGLARY")
    validate_success(api.resolve_alarm_event(ev2["id"], resolve_payload("FALSE_ALARM"), OPERATOR), 200)

    # Event 3 -> dispatched, resolution is the trigger.
    set_clock("2026-06-01T00:20:00Z")
    ev3 = ingest_route_dispatch(system["id"], sensor["id"], "BURGLARY")
    return acct["id"], system["id"], sensor["id"], ev3["id"]


def test_net_of_waived_ordinal_assigns_two_to_third_event(api):
    """PRD §3.8: "an account whose first fine is waived will see its third raw
    false alarm counted as ordinal 2 (and so priced in the free band) under this
    net-of-waived rule, rather than ordinal 3."

    Design: Difficulty/dual_variant_calc/fine_ordinal_net_of_waived_vs_gross
    """
    _aid, _sid, _senid, ev3 = _setup_three_false_alarms_first_waived(api)
    resolved = validate_success(
        api.resolve_alarm_event(ev3, resolve_payload("FALSE_ALARM"), OPERATOR), 200)
    assert resolved["chargeable_ordinal"] == 2, (
        f"third raw false alarm with a waived first fine is ordinal 2, "
        f"got {resolved['chargeable_ordinal']}"
    )


def test_net_of_waived_ordinal_prices_third_event_free_band(api):
    """PRD §3.8: "The base is zero for the first two chargeable false alarms of
    the cycle (ordinal 1 or 2, the free allowance)... Because waived fines are
    excluded from this counting, a later false alarm can land in a cheaper tier
    than its raw chronological position would suggest."

    Design: Difficulty/dual_variant_calc/fine_ordinal_net_of_waived_vs_gross
    """
    _aid, _sid, _senid, ev3 = _setup_three_false_alarms_first_waived(api)
    validate_success(api.resolve_alarm_event(ev3, resolve_payload("FALSE_ALARM"), OPERATOR), 200)
    fine3 = fine_for_event(ev3)
    assert fine3 is not None, "a fine must be created for the third false alarm"
    # ordinal 2 -> free band base 0; permit ACTIVE -> no surcharge.
    assert fine3["amount_cents"] == 0, (
        f"ordinal 2 with active permit is priced 0 (free band), got {fine3['amount_cents']}"
    )
    assert fine3["amount_cents"] != 5000, "must not be priced at the gross ordinal-3 WARN tier"


# ─── non_linear_state_machine: RESOLVED_REAL vs RESOLVED_FALSE fork ──────────

def _setup_two_dispatched_events(api):
    """PRO account + ACTIVE permit, armed; two independent dispatched burglary
    events. Returns (system_id, sensor_id, ev_real_id, ev_false_id, account_id).
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct = create_account(plan["id"], premises_type="RESIDENTIAL")
    system = create_system(acct["id"], primary_path="CELLULAR")
    sensor = create_sensor(system["id"], zone_number=1, sensor_type="MOTION")
    validate_success(api.activate_account(acct["id"], ADMIN), 200)
    issue_permit(acct["id"], "P-FORK-1", filed_days_late=0)
    sub = make_subscriber_headers(acct["id"])
    validate_success(api.arm_system(system["id"], arm_payload("ARMED_AWAY"), sub), 200)

    ev_real = ingest_route_dispatch(system["id"], sensor["id"], "BURGLARY")
    set_clock("2026-06-01T00:05:00Z")
    ev_false = ingest_route_dispatch(system["id"], sensor["id"], "BURGLARY")
    return system["id"], sensor["id"], ev_real["id"], ev_false["id"], acct["id"]


def test_fork_real_branch_resolves_real_no_fine(api):
    """PRD §3.6: "Resolving as `REAL` moves the event to `RESOLVED_REAL`...
    A false-alarm resolution carries two further effects in sequence, detailed in
    §3.8: the account's `false_alarm_count_cycle` rises, and that count change
    drives assignment of this event's `chargeable_ordinal` and the creation of a
    fine."

    Design: Difficulty/non_linear_state_machine/alarm_event_fork_real_vs_false_divergent_effects
    """
    sid, senid, ev_real, ev_false, _aid = _setup_two_dispatched_events(api)
    resolved = validate_success(
        api.resolve_alarm_event(ev_real, resolve_payload("REAL"), OPERATOR), 200)
    assert resolved["status"] == "RESOLVED_REAL"
    # No fine on the REAL branch.
    _data, meta = validate_paginated(
        api.list_fines(ADMIN, params={"alarm_event_id": ev_real}))
    assert meta["total_count"] == 0, "REAL resolution creates no fine"


def test_fork_false_branch_resolves_false_creates_fine(api):
    """PRD §3.8: "When a dispatched event is resolved as a false alarm, two
    effects fire in order. First, the account's `false_alarm_count_cycle`...
    increments. Second, driven by that new count, the event's `chargeable_ordinal`
    is assigned and a **fine** is created in status `ASSESSED`."

    Design: Difficulty/non_linear_state_machine/alarm_event_fork_real_vs_false_divergent_effects
    """
    sid, senid, ev_real, ev_false, _aid = _setup_two_dispatched_events(api)
    resolved = validate_success(
        api.resolve_alarm_event(ev_false, resolve_payload("FALSE_ALARM"), OPERATOR), 200)
    assert resolved["status"] == "RESOLVED_FALSE"
    fine = fine_for_event(ev_false)
    assert fine is not None, "FALSE_ALARM resolution creates a fine"
    # First chargeable false alarm (ordinal 1) with an ACTIVE permit -> base 0.
    assert fine["amount_cents"] == 0, (
        f"ordinal 1 with active permit is priced 0, got {fine['amount_cents']}"
    )


# ─── transitive_cascade: depth-2 false-alarm count -> fine ───────────────────

def test_no_permit_third_false_alarm_count_and_ordinal(api):
    """PRD §3.8: "First, the account's `false_alarm_count_cycle` — its running
    tally of non-waived false alarms since the permit cycle anchor — increments.
    Second, driven by that new count, the event's `chargeable_ordinal` is
    assigned and a **fine** is created in status `ASSESSED`."

    Design: Difficulty/transitive_cascade/false_alarm_resolution_count_then_fine_chain
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct = create_account(plan["id"], premises_type="RESIDENTIAL")
    system = create_system(acct["id"], primary_path="CELLULAR")
    sensor = create_sensor(system["id"], zone_number=1, sensor_type="MOTION")
    validate_success(api.activate_account(acct["id"], ADMIN), 200)
    sub = make_subscriber_headers(acct["id"])
    validate_success(api.arm_system(system["id"], arm_payload("ARMED_AWAY"), sub), 200)

    # Two prior false alarms (ordinals 1, 2), no permit ever issued.
    ev1 = ingest_route_dispatch(system["id"], sensor["id"], "BURGLARY")
    validate_success(api.resolve_alarm_event(ev1["id"], resolve_payload("FALSE_ALARM"), OPERATOR), 200)
    set_clock("2026-06-01T00:10:00Z")
    ev2 = ingest_route_dispatch(system["id"], sensor["id"], "BURGLARY")
    validate_success(api.resolve_alarm_event(ev2["id"], resolve_payload("FALSE_ALARM"), OPERATOR), 200)
    set_clock("2026-06-01T00:20:00Z")
    ev3 = ingest_route_dispatch(system["id"], sensor["id"], "BURGLARY")

    resolved = validate_success(
        api.resolve_alarm_event(ev3["id"], resolve_payload("FALSE_ALARM"), OPERATOR), 200)
    assert resolved["chargeable_ordinal"] == 3, "third non-waived false alarm is ordinal 3"
    acct_after = validate_success(api.get_account(acct["id"], ADMIN), 200)
    assert acct_after["false_alarm_count_cycle"] == 3, "count tallies all three non-waived false alarms"


def test_no_permit_third_false_alarm_fine_warn_plus_surcharge(api):
    """PRD §3.8: "it is 5000 cents for ordinals 3, 4, and 5 (the three-wide
    warning band above the free allowance)... a no-permit surcharge of 7500 cents
    is added when the account holds no permit in status `ACTIVE` at the resolution
    instant; otherwise no surcharge applies. The fine's `amount_cents` is the base
    plus the surcharge."

    Design: Difficulty/transitive_cascade/false_alarm_resolution_count_then_fine_chain
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct = create_account(plan["id"], premises_type="RESIDENTIAL")
    system = create_system(acct["id"], primary_path="CELLULAR")
    sensor = create_sensor(system["id"], zone_number=1, sensor_type="MOTION")
    validate_success(api.activate_account(acct["id"], ADMIN), 200)
    sub = make_subscriber_headers(acct["id"])
    validate_success(api.arm_system(system["id"], arm_payload("ARMED_AWAY"), sub), 200)

    ev1 = ingest_route_dispatch(system["id"], sensor["id"], "BURGLARY")
    validate_success(api.resolve_alarm_event(ev1["id"], resolve_payload("FALSE_ALARM"), OPERATOR), 200)
    set_clock("2026-06-01T00:10:00Z")
    ev2 = ingest_route_dispatch(system["id"], sensor["id"], "BURGLARY")
    validate_success(api.resolve_alarm_event(ev2["id"], resolve_payload("FALSE_ALARM"), OPERATOR), 200)
    set_clock("2026-06-01T00:20:00Z")
    ev3 = ingest_route_dispatch(system["id"], sensor["id"], "BURGLARY")
    validate_success(api.resolve_alarm_event(ev3["id"], resolve_payload("FALSE_ALARM"), OPERATOR), 200)

    fine3 = fine_for_event(ev3["id"])
    assert fine3 is not None
    # ordinal 3 -> WARN 5000; no active permit -> +7500 surcharge = 12500.
    assert fine3["amount_cents"] == 12500, (
        f"WARN 5000 + no-permit surcharge 7500 == 12500, got {fine3['amount_cents']}"
    )


# ─── transitive_cascade: depth-3 finalize-cancellation chain ─────────────────

def _setup_open_dispatch_then_request_cancel(api):
    """PRO account, armed, one FIRE event ROUTED+DISPATCHED (ORDERED dispatch,
    fee 4000, left open), then request-cancellation. Returns
    (account_id, system_id, event_id, dispatch_id, version).
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct = create_account(plan["id"], premises_type="RESIDENTIAL")
    system = create_system(acct["id"], primary_path="CELLULAR")
    sensor = create_sensor(system["id"], zone_number=1, sensor_type="SMOKE")
    validate_success(api.activate_account(acct["id"], ADMIN), 200)
    sub = make_subscriber_headers(acct["id"])
    validate_success(api.arm_system(system["id"], arm_payload("ARMED_AWAY"), sub), 200)

    ev = ingest_event(system["id"], sensor["id"], "FIRE")
    validate_success(api.route_alarm_event(ev["id"], OPERATOR), 200)
    validate_success(api.dispatch_alarm_event(ev["id"], OPERATOR), 200)
    disp = dispatch_for_event(ev["id"])

    requested = validate_success(api.request_cancellation(acct["id"], ADMIN), 200)
    return acct["id"], system["id"], ev["id"], disp["id"], requested["version"]


def test_finalize_cancellation_cascades_through_system_event_dispatch(api):
    """PRD §3.7: "First, every security system under the account is forced to
    `arming_state` `DISARMED` and has its test mode cleared. Second — caused by
    that force-disarm — each such system's still-open alarm events, meaning every
    event in `RECEIVED`, `ROUTED`, or `DISPATCHED`, is moved to `SUPPRESSED`.
    Third — caused by that suppression — each `ORDERED` dispatch on those events
    is moved to `CANCELLED`, reversing its `fee_cents` out of
    `monitoring_balance_cents`."

    Design: Difficulty/transitive_cascade/finalize_cancellation_account_system_event_dispatch_chain
    """
    aid, sid, evid, dispid, version = _setup_open_dispatch_then_request_cancel(api)
    finalized = validate_success(
        api.finalize_cancellation(aid, finalize_cancellation_payload(version), ADMIN), 200)
    assert finalized["contract_status"] == "CANCELLED"

    system_after = validate_success(api.get_system(sid, ADMIN), 200)
    assert system_after["arming_state"] == "DISARMED", "hop1: system force-disarmed"

    event_after = validate_success(api.get_alarm_event(evid, ADMIN), 200)
    assert event_after["status"] == "SUPPRESSED", "hop2: open DISPATCHED event suppressed"

    dispatch_after = validate_success(api.get_dispatch(dispid, ADMIN), 200)
    assert dispatch_after["status"] == "CANCELLED", "hop3: ORDERED dispatch cancelled"


def test_finalize_cancellation_reverses_dispatch_fee_to_zero_balance(api):
    """PRD §3.7: "each `ORDERED` dispatch on those events is moved to `CANCELLED`,
    reversing its `fee_cents` out of `monitoring_balance_cents`."

    Design: Difficulty/transitive_cascade/finalize_cancellation_account_system_event_dispatch_chain
    """
    aid, sid, evid, dispid, version = _setup_open_dispatch_then_request_cancel(api)
    finalized = validate_success(
        api.finalize_cancellation(aid, finalize_cancellation_payload(version), ADMIN), 200)
    # day-0 read: proration 0; the 4000 FIRE dispatch fee is reversed -> 0.
    assert finalized["monitoring_balance_cents"] == 0, (
        f"FIRE 4000 fee reversed and day-0 proration 0 -> balance 0, "
        f"got {finalized['monitoring_balance_cents']}"
    )
