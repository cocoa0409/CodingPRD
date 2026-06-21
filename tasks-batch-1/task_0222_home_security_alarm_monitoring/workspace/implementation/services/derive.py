"""Derived-field computation and entity serialization.

Derived fields are never stored authoritatively for read purposes — they are
recomputed on every read (PRD §2.8, §3.1, §3.2):
  - SecuritySystem.communicator_health, sensor_count
  - Account.monitoring_status, monitoring_balance_cents, false_alarm_count_cycle
"""
import clock
from db import db
from services import calc


# ---------------------------------------------------------------------------
# SecuritySystem derivations
# ---------------------------------------------------------------------------
def system_health(system):
    return calc.communicator_health(
        system["last_checkin_minutes_ago"],
        system["cellular_signal_dbm"],
        system["backup_battery_pct"],
    )


def system_sensor_count(system_id):
    return sum(
        1
        for s in db.sensors.values()
        if s["system_id"] == system_id and s["status"] != "REMOVED"
    )


def systems_for_account(account_id):
    return [s for s in db.systems.values() if s["account_id"] == account_id]


# ---------------------------------------------------------------------------
# Account derivations
# ---------------------------------------------------------------------------
def monitoring_status(account):
    cs = account["contract_status"]
    if cs == "CANCELLED":
        return "TERMINATED"
    if cs == "PENDING":
        return "SUSPENDED"
    # ACTIVE or CANCELLATION_REQUESTED
    for sys in systems_for_account(account["id"]):
        if system_health(sys) == "OFFLINE":
            return "SUSPENDED"
    return "ACTIVE"


def plan_fee_by_tier(tier):
    for p in db.monitoring_plans.values():
        if p["tier"] == tier:
            return p["monthly_fee_cents"]
    return None


def monitoring_proration(account):
    if account.get("cycle_anchor_utc") is None:
        return 0
    segments = db.plan_change_segments.get(account["id"], [])
    anchor_tier = account.get("_anchor_tier")
    return calc.monitoring_proration(
        account["cycle_anchor_utc"],
        clock.now(),
        anchor_tier,
        segments,
        plan_fee_by_tier,
    )


def monitoring_balance(account):
    if account["contract_status"] == "PENDING":
        return 0
    proration = monitoring_proration(account)
    dispatch_total = 0
    for d in db.dispatches.values():
        if d["account_id"] == account["id"] and d["status"] in ("ORDERED", "CONFIRMED"):
            dispatch_total += d["fee_cents"]
    balance = proration + dispatch_total
    if balance < 0:
        balance = 0
    return balance


def false_alarm_count_cycle(account):
    """Count of non-waived FALSE_ALARM events since the permit cycle anchor."""
    anchor = permit_cycle_anchor(account)
    count = 0
    for ev in db.alarm_events.values():
        if ev.get("_account_id") != account["id"]:
            continue
        if ev.get("resolution") != "FALSE_ALARM":
            continue
        fine = _fine_for_event(ev["id"])
        if fine is not None and fine["settlement_status"] == "WAIVED":
            continue
        if anchor is not None and ev["raised_utc"] < anchor:
            continue
        count += 1
    return count


def permit_cycle_anchor(account):
    """The account's ACTIVE permit cycle anchor, else the account cycle anchor."""
    for p in db.permits.values():
        if p["account_id"] == account["id"] and p["status"] == "ACTIVE":
            return p["cycle_anchor_utc"]
    return account.get("cycle_anchor_utc")


def _fine_for_event(alarm_event_id):
    for f in db.fines.values():
        if f["alarm_event_id"] == alarm_event_id:
            return f
    return None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _base_common(entity):
    return {
        "id": entity["id"],
        "created_at": clock.format_ts(entity["created_at"]),
        "updated_at": clock.format_ts(entity["updated_at"]),
        "version": entity["version"],
    }


def serialize_plan(p):
    return {
        "id": p["id"],
        "created_at": clock.format_ts(p["created_at"]),
        "tier": p["tier"],
        "monthly_fee_cents": p["monthly_fee_cents"],
        "police_dispatch_included": p["police_dispatch_included"],
        "max_sensors": p["max_sensors"],
        "cellular_backup_included": p["cellular_backup_included"],
    }


def serialize_account(a):
    out = _base_common(a)
    out.update({
        "premises_type": a["premises_type"],
        "plan_id": a["plan_id"],
        "contract_status": a["contract_status"],
        "monitoring_status": monitoring_status(a),
        "contract_start_utc": clock.format_ts(a.get("contract_start_utc")),
        "contract_term_months": a["contract_term_months"],
        "cycle_anchor_utc": clock.format_ts(a.get("cycle_anchor_utc")),
        "current_tier": a.get("current_tier"),
        "monitoring_balance_cents": monitoring_balance(a),
        "false_alarm_count_cycle": false_alarm_count_cycle(a),
        "early_termination_fee_cents": a.get("early_termination_fee_cents", 0),
    })
    return out


def serialize_system(s):
    out = _base_common(s)
    out.update({
        "account_id": s["account_id"],
        "arming_state": s["arming_state"],
        "test_mode": s["test_mode"],
        "test_mode_expires_utc": clock.format_ts(s.get("test_mode_expires_utc")),
        "primary_path": s["primary_path"],
        "cellular_signal_dbm": s["cellular_signal_dbm"],
        "backup_battery_pct": s["backup_battery_pct"],
        "last_checkin_minutes_ago": s["last_checkin_minutes_ago"],
        "communicator_health": system_health(s),
        "sensor_count": system_sensor_count(s["id"]),
    })
    return out


def serialize_sensor(s):
    out = _base_common(s)
    out.update({
        "system_id": s["system_id"],
        "zone_number": s["zone_number"],
        "sensor_type": s["sensor_type"],
        "status": s["status"],
    })
    return out


def serialize_alarm_event(e):
    out = _base_common(e)
    out.update({
        "system_id": e["system_id"],
        "sensor_id": e["sensor_id"],
        "signal_type": e["signal_type"],
        "status": e["status"],
        "routed_service": e.get("routed_service"),
        "raised_utc": clock.format_ts(e.get("raised_utc")),
        "resolution": e.get("resolution"),
        "chargeable_ordinal": e.get("chargeable_ordinal"),
    })
    return out


def serialize_dispatch(d):
    out = _base_common(d)
    out.update({
        "alarm_event_id": d["alarm_event_id"],
        "account_id": d["account_id"],
        "service": d["service"],
        "status": d["status"],
        "fee_cents": d["fee_cents"],
    })
    return out


def serialize_permit(p):
    out = _base_common(p)
    out.update({
        "account_id": p["account_id"],
        "permit_number": p["permit_number"],
        "status": p["status"],
        "filed_days_late": p["filed_days_late"],
        "cycle_anchor_utc": clock.format_ts(p.get("cycle_anchor_utc")),
        "fee_total_cents": p["fee_total_cents"],
    })
    return out


def serialize_fine(f):
    out = _base_common(f)
    out.update({
        "account_id": f["account_id"],
        "alarm_event_id": f["alarm_event_id"],
        "amount_cents": f["amount_cents"],
        "settlement_status": f["settlement_status"],
    })
    return out
