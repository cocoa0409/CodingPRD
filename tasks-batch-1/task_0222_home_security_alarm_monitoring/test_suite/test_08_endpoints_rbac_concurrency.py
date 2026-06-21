"""Endpoint actions, RBAC, optimistic-concurrency, and immediate-consistency
corners.

Covers: change-plan success path, status-filtered alarm-event listing, a
forbidden cross-role call, missing-auth rejection, OCC stale-version on
change-plan, version increment on request-cancellation, and immediate dispatch
fee visibility on the account balance.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    make_admin_headers,
    make_operator_headers,
    make_subscriber_headers,
    build_user_headers,
    set_clock,
    create_plan,
    create_account,
    create_system,
    create_sensor,
    ingest_event,
    ingest_route_dispatch,
    setup_activated_account,
    setup_activated_armed_account,
    setup_two_plans_activated_account,
    change_plan_payload,
    arm_payload,
)

ADMIN = make_admin_headers()
OPERATOR = make_operator_headers()

BASIC = dict(tier="BASIC", monthly_fee_cents=1500, police_dispatch_included=False,
             max_sensors=8, cellular_backup_included=False)
PLUS = dict(tier="PLUS", monthly_fee_cents=3100, police_dispatch_included=True,
            max_sensors=16, cellular_backup_included=True)
PRO = dict(tier="PRO", monthly_fee_cents=6200, police_dispatch_included=True,
           max_sensors=32, cellular_backup_included=True)


# ─── endpoints ───────────────────────────────────────────────────────────────

def test_change_plan_success_updates_tier_and_bumps_version(api):
    """PRD §3.2: "A successful change records a proration segment boundary at the
    current clock, updates `current_tier`, recomputes `monitoring_balance_cents`
    to its authoritative value, and increments the account's `version` by one."

    Design: Corner/endpoints/change_plan_success_updates_current_tier
    """
    ctx = setup_two_plans_activated_account(base_plan=BASIC, alt_plan=PLUS)
    aid = ctx["account"]["id"]
    av = ctx["version"]
    changed = validate_success(
        api.change_plan(aid, change_plan_payload(ctx["alt_plan"]["id"], av), ADMIN), 200)
    assert changed["current_tier"] == "PLUS"
    assert changed["version"] == av + 1, "change-plan bumps version by exactly 1"


def test_list_alarm_events_filter_by_suppressed_status(api):
    """PRD §3.9: "alarm events by `system_id`, `sensor_id`, or `status`."
    PRD §3.6: "If the raising system is in test mode... the event is auto-resolved
    to `SUPPRESSED` — logged only, never routed and never dispatched."

    Design: Corner/endpoints/list_alarm_events_filter_by_status
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_account(plan_overrides=PRO, system_overrides={"primary_path": "CELLULAR"},
                                  sensor_overrides={"sensor_type": "MOTION"})
    sid, senid = ctx["system"]["id"], ctx["sensor"]["id"]
    validate_success(api.enter_test_mode(sid, OPERATOR), 200)
    ev = ingest_event(sid, senid, "BURGLARY")
    assert ev["status"] == "SUPPRESSED"

    data, meta = validate_paginated(
        api.list_alarm_events(OPERATOR, params={"system_id": sid, "status": "SUPPRESSED"}))
    assert meta["total_count"] == 1
    assert data[0]["status"] == "SUPPRESSED"


# ─── rbac ────────────────────────────────────────────────────────────────────

def test_subscriber_cannot_route_alarm_event_forbidden(api):
    """PRD §2.1: "When a well-authenticated caller attempts an operation their
    role is not permitted to perform, the request is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/subscriber_cannot_route_alarm_event
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(**PRO)
    acct = create_account(plan["id"])
    system = create_system(acct["id"], primary_path="CELLULAR")
    sensor = create_sensor(system["id"], zone_number=1, sensor_type="SMOKE")
    validate_success(api.activate_account(acct["id"], ADMIN), 200)
    sub = make_subscriber_headers(acct["id"])
    validate_success(api.arm_system(system["id"], arm_payload("ARMED_AWAY"), sub), 200)
    ev = ingest_event(system["id"], sensor["id"], "FIRE")

    # route is MonitoringOperator-exclusive; the role check fires before ownership.
    res = api.route_alarm_event(ev["id"], sub)
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value,
    is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    plan = create_plan(**BASIC)
    res = api.get_monitoring_plan(plan["id"], headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── cross_cutting_complexity_layers ─────────────────────────────────────────

def test_occ_stale_version_change_plan_rejected(api):
    """PRD §2.7: "Two strictly sequential plan-change calls that both carry the
    same observed version reproduce this exactly: the first advances `version`,
    and the second is rejected as stale."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_change_plan
    """
    set_clock("2026-06-01T00:00:00Z")
    bp = create_plan(**BASIC)
    pp = create_plan(**PLUS)
    rp = create_plan(**PRO)
    acct = create_account(bp["id"])
    system = create_system(acct["id"], primary_path="BROADBAND")
    create_sensor(system["id"], zone_number=1, sensor_type="DOOR")
    activated = validate_success(api.activate_account(acct["id"], ADMIN), 200)
    av = activated["version"]

    # First change-plan with observed version av -> succeeds, advances version.
    validate_success(api.change_plan(acct["id"], change_plan_payload(pp["id"], av), ADMIN), 200)
    # Second change-plan carrying the same stale version -> rejected.
    res = api.change_plan(acct["id"], change_plan_payload(rp["id"], av), ADMIN)
    validate_error(res, "ERR_STALE_VERSION")


def test_version_increments_on_request_cancellation(api):
    """PRD §3.1: "At that moment the early-termination fee is computed and frozen
    onto `early_termination_fee_cents` (see §3.2), and the account's `version`
    increments by one."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_request_cancellation
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_account(plan_overrides=BASIC)
    av = ctx["version"]
    requested = validate_success(api.request_cancellation(ctx["account"]["id"], ADMIN), 200)
    assert requested["version"] == av + 1, "request-cancellation bumps version by exactly 1"


# ─── consistency_model ───────────────────────────────────────────────────────

def test_dispatch_fee_visible_immediately_on_account(api):
    """PRD §3.2: "The authoritative `monitoring_balance_cents` is the sum of the
    day-by-day proration to date plus the fees of every dispatch on the account
    that is in status `ORDERED` or `CONFIRMED`... This balance is recomputed on
    activation, on plan change, on dispatch creation and cancellation, and on
    every account read."

    Design: Corner/consistency_model/dispatch_fee_visible_immediately_on_account
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_activated_armed_account(plan_overrides=PRO,
                                        system_overrides={"primary_path": "CELLULAR"},
                                        sensor_overrides={"sensor_type": "SMOKE"})
    ingest_route_dispatch(ctx["system"]["id"], ctx["sensor"]["id"], "FIRE")
    acct = validate_success(api.get_account(ctx["account"]["id"], ADMIN), 200)
    # day-0 proration 0 + 4000 FIRE dispatch fee = 4000.
    assert acct["monitoring_balance_cents"] == 4000
