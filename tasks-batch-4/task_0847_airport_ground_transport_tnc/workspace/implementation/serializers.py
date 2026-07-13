"""Resource -> JSON serializers. Operator computed fields are derived live on
every read against the current logical clock (PRD 3.1 / 3.7)."""
from common import iso
from store import db
import calc


def compute_rolling(op):
    total = 0
    window_start = calc.rolling_window_start(db.clock)
    for v in db.violations.values():
        if v["operator_id"] != op["id"]:
            continue
        if v["status"] not in ("ASSESSED", "UPHELD"):
            continue
        if v["assessed_at"] is not None and v["assessed_at"] >= window_start:
            total += calc.PENALTY_POINTS_BY_TYPE[v["violation_type"]]
    return total


def compute_lifetime(op):
    total = 0
    for v in db.violations.values():
        if v["operator_id"] != op["id"]:
            continue
        if v["status"] not in ("ASSESSED", "UPHELD"):
            continue
        total += calc.PENALTY_POINTS_BY_TYPE[v["violation_type"]]
    return total


def compute_outstanding(op):
    total = 0
    for t in db.trips.values():
        if t["operator_id"] != op["id"]:
            continue
        if t["status"] == "COMPLETED" and t["settlement_statement_id"] is None:
            total += t["final_fee_cents"] or 0
    return total


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def operator(op):
    d = _common(op)
    d.update(
        {
            "legal_name": op["legal_name"],
            "operator_type": op["operator_type"],
            "contact_email": op["contact_email"],
            "wheelchair_pledge_pct": op["wheelchair_pledge_pct"],
            "status": op["status"],
            "suspended_reason": op["suspended_reason"],
            "rolling_penalty_points": compute_rolling(op),
            "lifetime_penalty_points": compute_lifetime(op),
            "outstanding_fees_cents": compute_outstanding(op),
        }
    )
    return d


def vehicle(v):
    d = _common(v)
    d.update(
        {
            "operator_id": v["operator_id"],
            "plate": v["plate"],
            "is_wheelchair_accessible": v["is_wheelchair_accessible"],
            "status": v["status"],
        }
    )
    return d


def permit(p):
    d = _common(p)
    d.update(
        {
            "vehicle_id": p["vehicle_id"],
            "avi_tag_id": p["avi_tag_id"],
            "decal_number": p["decal_number"],
            "valid_from": iso(p["valid_from"]),
            "valid_until": iso(p["valid_until"]),
            "fee_paid_cents": p["fee_paid_cents"],
            "permit_status": p["permit_status"],
            "suspended_reason": p["suspended_reason"],
        }
    )
    return d


def staging_lot(s):
    d = _common(s)
    d.update(
        {
            "name": s["name"],
            "geofence_center_lat": s["geofence_center_lat"],
            "geofence_center_lng": s["geofence_center_lng"],
            "geofence_radius_m": s["geofence_radius_m"],
            "capacity": s["capacity"],
        }
    )
    return d


def queue_entry(q):
    d = _common(q)
    d.update(
        {
            "staging_lot_id": q["staging_lot_id"],
            "vehicle_id": q["vehicle_id"],
            "position": q["position"],
            "status": q["status"],
            "enter_ts": iso(q["enter_ts"]),
            "exit_ts": iso(q["exit_ts"]),
        }
    )
    return d


def curb_zone(c):
    d = _common(c)
    d.update({"name": c["name"], "terminal": c["terminal"], "capacity": c["capacity"]})
    return d


def curb_assignment(a):
    d = _common(a)
    d.update(
        {
            "curb_zone_id": a["curb_zone_id"],
            "trip_id": a["trip_id"],
            "start_ts": iso(a["start_ts"]),
            "end_ts": iso(a["end_ts"]),
            "status": a["status"],
        }
    )
    return d


def trip(t):
    d = _common(t)
    d.update(
        {
            "operator_id": t["operator_id"],
            "vehicle_id": t["vehicle_id"],
            "trip_kind": t["trip_kind"],
            "is_wheelchair_trip": t["is_wheelchair_trip"],
            "status": t["status"],
            "dispatch_ts": iso(t["dispatch_ts"]),
            "pickup_ts": iso(t["pickup_ts"]),
            "complete_ts": iso(t["complete_ts"]),
            "provisional_fee_cents": t["provisional_fee_cents"],
            "final_fee_cents": t["final_fee_cents"],
            "settlement_statement_id": t["settlement_statement_id"],
        }
    )
    return d


def violation(v):
    d = _common(v)
    d.update(
        {
            "operator_id": v["operator_id"],
            "trip_id": v["trip_id"],
            "violation_type": v["violation_type"],
            "source": v["source"],
            "penalty_points": v["penalty_points"],
            "fine_cents": v["fine_cents"],
            "status": v["status"],
            "assessed_at": iso(v["assessed_at"]),
        }
    )
    return d


def settlement(s):
    d = _common(s)
    d.update(
        {
            "operator_id": s["operator_id"],
            "period_year": s["period_year"],
            "period_month": s["period_month"],
            "status": s["status"],
            "gross_fees_cents": s["gross_fees_cents"],
            "admin_fee_cents": s["admin_fee_cents"],
            "wav_incentive_credit_cents": s["wav_incentive_credit_cents"],
            "net_due_cents": s["net_due_cents"],
            "total_trip_count": s["total_trip_count"],
            "wav_trip_count": s["wav_trip_count"],
            "closed_at": iso(s["closed_at"]),
            "settled_at": iso(s["settled_at"]),
        }
    )
    return d
