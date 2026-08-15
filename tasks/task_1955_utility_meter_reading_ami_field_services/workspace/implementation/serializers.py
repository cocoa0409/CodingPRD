"""Entity serialization, including on-the-fly computed fields."""
from db import db
from util import parse_dt

COMMON = ("id", "created_at", "updated_at", "version")


def _pub(rec, fields):
    out = {f: rec.get(f) for f in fields}
    for f in COMMON:
        out[f] = rec[f]
    return out


# ----- computed helpers -------------------------------------------------

def account_current_meter_id(account_id):
    for m in db.meters.values():
        if m["installed_service_account_id"] == account_id and m["meter_status"] == "IN_SERVICE":
            return m["id"]
    return None


def account_last_validated(account_id):
    """(value, read_at) of the most recent VALIDATED read by read_at, else (None, None)."""
    cands = [
        r for r in db.reads.values()
        if r["service_account_id"] == account_id and r["read_status"] == "VALIDATED"
    ]
    if not cands:
        return None, None
    best = max(cands, key=lambda r: (parse_dt(r["read_at"]), r["_seq"]))
    return best["read_value"], best["read_at"]


def period_unresolved_stop_count(period_id):
    return sum(
        1 for s in db.stops.values()
        if s["billing_cycle_period_id"] == period_id
        and s["stop_status"] in ("PENDING", "NO_READ_PENDING")
    )


def route_stops(route_id):
    return [s for s in db.stops.values() if s["route_id"] == route_id]


def route_stops_total(route_id):
    return sum(1 for s in route_stops(route_id) if s["stop_status"] != "CANCELLED")


def route_captured_count(route_id):
    return sum(
        1 for s in route_stops(route_id)
        if s["stop_status"] in ("READ_CAPTURED", "VALIDATED", "ESTIMATED", "SUPERSEDED")
    )


def campaign_counts(campaign_id):
    enrs = [e for e in db.enrollments.values() if e["campaign_id"] == campaign_id]
    enrolled = sum(1 for e in enrs if e["enrollment_status"] in ("ENROLLED", "WORK_ORDER_CREATED"))
    replaced = sum(1 for e in enrs if e["enrollment_status"] == "REPLACED")
    withdrawn = sum(1 for e in enrs if e["enrollment_status"] == "WITHDRAWN")
    return enrolled, replaced, withdrawn


def read_is_billable(read):
    if read["read_status"] == "VALIDATED":
        return True
    if read["read_status"] == "ESTIMATED":
        stop = db.stops.get(read.get("route_stop_id") or "")
        if stop:
            period = db.periods.get(stop["billing_cycle_period_id"])
            if period and period["period_status"] not in ("BILLED", "CLOSED"):
                return True
        return False
    return False


# ----- serializers --------------------------------------------------------

def ser_technician(t):
    return _pub(t, ("display_name", "technician_status"))


def ser_account(a):
    out = _pub(a, (
        "account_number", "service_address", "billing_cycle_code",
        "estimation_method", "account_status", "estimated_read_streak",
    ))
    out["current_meter_id"] = account_current_meter_id(a["id"])
    v, at = account_last_validated(a["id"])
    out["last_validated_read_value"] = v
    out["last_validated_read_at"] = at
    return out


def ser_meter(m):
    return _pub(m, (
        "serial_number", "meter_type", "meter_status", "endpoint_comms_status",
        "tamper_status", "installed_service_account_id", "consecutive_missed_days",
        "non_communicating_since",
    ))


def ser_period(p):
    out = _pub(p, (
        "cycle_code", "period_start_date", "period_end_date",
        "read_window_open_date", "read_window_close_date", "bill_run_date",
        "period_status",
    ))
    out["unresolved_stop_count"] = period_unresolved_stop_count(p["id"])
    return out


def ser_route(r):
    out = _pub(r, (
        "billing_cycle_period_id", "scheduled_date", "route_shift",
        "two_person_crew", "technician_id", "route_status",
        "read_rate_percent", "net_read_rate_percent",
    ))
    out["stops_total"] = route_stops_total(r["id"])
    out["captured_stop_count"] = route_captured_count(r["id"])
    return out


def ser_stop(s):
    return _pub(s, (
        "route_id", "service_account_id", "billing_cycle_period_id",
        "sequence_number", "stop_status", "no_read_reason", "hazard_flag_id",
        "current_read_id",
    ))


def ser_read(r):
    out = _pub(r, (
        "route_stop_id", "service_account_id", "meter_id", "read_value",
        "read_at", "read_source", "read_status", "estimation_method",
        "tamper_indication", "supersedes_read_id", "rejection_reason",
    ))
    out["is_billable"] = read_is_billable(r)
    return out


def ser_hazard(h):
    return _pub(h, (
        "service_account_id", "hazard_type", "severity", "flag_status",
        "reported_by_technician_id", "reported_at", "expires_at", "renewed_count",
    ))


def ser_work_order(w):
    return _pub(w, (
        "work_order_type", "service_account_id", "meter_id", "route_stop_id",
        "investigation_id", "campaign_enrollment_id", "scheduled_date",
        "work_shift", "notes", "technician_id", "work_order_status",
        "new_meter_id", "old_final_read_value", "new_initial_read_value",
        "reread_value", "reread_at", "evidence_note", "completed_at",
    ))


def ser_investigation(i):
    return _pub(i, (
        "service_account_id", "meter_id", "indication_type",
        "investigation_status", "opened_by_user_id", "closed_by_user_id",
        "triggering_read_id", "exchange_work_order_id", "theft_window_months",
        "monthly_estimated_kwh", "backbill_cents", "evidence_notes",
    ))


def ser_campaign(c):
    out = _pub(c, ("campaign_name", "quota", "campaign_status"))
    enrolled, replaced, withdrawn = campaign_counts(c["id"])
    out["enrolled_count"] = enrolled
    out["replaced_count"] = replaced
    out["withdrawn_count"] = withdrawn
    return out


def ser_enrollment(e):
    return _pub(e, ("campaign_id", "meter_id", "enrollment_status", "work_order_id"))


def ser_snapshot(s):
    return _pub(s, (
        "snapshot_at", "snapshot_status", "eligible_stop_count",
        "covered_stop_count", "backlog_count", "backlog_aged_7plus_count",
        "estimated_read_count", "validated_read_count", "read_rate_percent",
        "net_read_rate_percent", "sla_breach",
    ))
