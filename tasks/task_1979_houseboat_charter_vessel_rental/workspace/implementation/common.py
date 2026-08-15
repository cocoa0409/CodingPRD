"""Shared parsing, pagination and serialization helpers."""

from datetime import datetime, date, timezone

from flask import request

import db
import errors


# ---------------------------------------------------------------------------
# Body / field parsing (priority-5 ERR_INVALID_REQUEST checks)
# ---------------------------------------------------------------------------

def json_body(required=True):
    """Return the parsed JSON object body. Non-object / unparseable -> 400.
    When required is False and no body was sent, returns {}."""
    raw = request.get_data()
    if not raw:
        if required:
            errors.err(errors.ERR_INVALID_REQUEST, "Request body is required")
        return {}
    try:
        body = request.get_json(force=True)
    except Exception:
        errors.err(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON")
    if not isinstance(body, dict):
        errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def req_field(body, name):
    if name not in body or body[name] is None:
        errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return body[name]


def opt_field(body, name, default=None):
    return body.get(name, default)


def as_str(value, name):
    if not isinstance(value, str) or value == "":
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return value


def as_enum(value, name, members):
    if not isinstance(value, str) or value not in members:
        errors.err(
            errors.ERR_INVALID_REQUEST,
            f"Field {name} must be one of {sorted(members)}",
        )
    return value


def as_list(value, name):
    if not isinstance(value, list):
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an array")
    return value


def parse_date(value, name):
    if not isinstance(value, str):
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} is not a valid ISO date")


def parse_datetime(value, name):
    if not isinstance(value, str):
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an ISO datetime string")
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} is not a valid ISO datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_pagination():
    """limit (default 10, bounds [1,100]) and offset (default 0, >= 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            errors.err(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            errors.err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(records):
    """Sort by created_at ascending and apply limit/offset."""
    limit, offset = parse_pagination()
    ordered = db.sorted_created(records)
    page = ordered[offset:offset + limit]
    return page, len(ordered), limit, offset


# ---------------------------------------------------------------------------
# Serializers — whitelist public fields, never leak _seq
# ---------------------------------------------------------------------------

def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def vessel_out(v):
    out = _common(v)
    out.update({
        "name": v["name"],
        "size_class": v["size_class"],
        "berth_count": v["berth_count"],
        "home_marina": v["home_marina"],
        "fuel_tank_capacity_gallons": v["fuel_tank_capacity_gallons"],
        "status": v["status"],
    })
    return out


def season_rate_out(r):
    out = _common(r)
    out.update({
        "size_class": r["size_class"],
        "season": r["season"],
        "start_date": r["start_date"].isoformat(),
        "end_date": r["end_date"].isoformat(),
        "nightly_rate_cents": r["nightly_rate_cents"],
        "weekly_discount_pct": r["weekly_discount_pct"],
    })
    return out


def geo_zone_out(z):
    out = _common(z)
    out.update({
        "zone_code": z["zone_code"],
        "name": z["name"],
        "max_vessels_per_night": z["max_vessels_per_night"],
        "allowed_size_classes": list(z["allowed_size_classes"]),
    })
    return out


def renter_out(r):
    out = _common(r)
    out.update({
        "full_name": r["full_name"],
        "email": r["email"],
        "date_of_birth": r["date_of_birth"].isoformat(),
        "qualification_status": r["qualification_status"],
        "risk_score_lifetime": r["risk_score_lifetime"],
        "risk_score_rolling_24m": r["risk_score_rolling_24m"],
        "deposit_multiplier": r["deposit_multiplier"],
    })
    return out


def certificate_out(c):
    out = _common(c)
    out.update({
        "renter_id": c["renter_id"],
        "cert_number": c["cert_number"],
        "issuing_authority": c["issuing_authority"],
        "issued_on": c["issued_on"].isoformat(),
        "expires_on": c["expires_on"].isoformat(),
        "status": c["status"],
    })
    return out


def booking_out(b):
    out = _common(b)
    out.update({
        "vessel_id": b["vessel_id"],
        "renter_id": b["renter_id"],
        "start_date": b["start_date"].isoformat(),
        "end_date": b["end_date"].isoformat(),
        "party_size": b["party_size"],
        "status": b["status"],
        "settlement_status": b["settlement_status"],
        "deposit_status": b["deposit_status"],
        "orientation_status": b["orientation_status"],
        "orientation_items": [
            {"item_code": i["item_code"], "signed": i["signed"]}
            for i in b["orientation_items"]
        ],
        "total_nights": b["total_nights"],
        "quoted_total_cents": b["quoted_total_cents"],
        "deposit_required_cents": b["deposit_required_cents"],
        "deposit_held_cents": b["deposit_held_cents"],
        "deposit_applied_cents": b["deposit_applied_cents"],
        "deposit_released_cents": b["deposit_released_cents"],
        "refund_issued_cents": b["refund_issued_cents"],
        "provisional_estimate_cents": b["provisional_estimate_cents"],
        "final_settlement_cents": b["final_settlement_cents"],
        "checkout_fuel_gauge_percent": b["checkout_fuel_gauge_percent"],
        "checkout_pump_out_done": b["checkout_pump_out_done"],
        "return_fuel_gauge_percent": b["return_fuel_gauge_percent"],
        "return_pump_out_done": b["return_pump_out_done"],
        "actual_return_at": db.fmt_dt(b["actual_return_at"]) if b["actual_return_at"] else None,
        "hold_expires_at": db.fmt_dt(b["hold_expires_at"]),
        "cancellation_reason": b["cancellation_reason"],
    })
    return out


def itinerary_out(it):
    out = _common(it)
    out.update({
        "booking_id": it["booking_id"],
        "waypoints": [
            {"zone_id": w["zone_id"], "night_date": w["night_date"].isoformat()}
            for w in it["waypoints"]
        ],
        "status": it["status"],
    })
    return out


def charge_out(c):
    out = _common(c)
    out.update({
        "booking_id": c["booking_id"],
        "line_type": c["line_type"],
        "amount_cents": c["amount_cents"],
        "status": c["status"],
        "note": c["note"],
    })
    return out


def incident_out(i):
    out = _common(i)
    out.update({
        "booking_id": i["booking_id"],
        "incident_type": i["incident_type"],
        "occurred_at": db.fmt_dt(i["occurred_at"]),
        "description": i["description"],
        "status": i["status"],
        "severity": i["severity"],
        "resolution": i["resolution"],
        "downtime_days": i["downtime_days"],
        "assessed_damage_cents": i["assessed_damage_cents"],
    })
    return out


def maintenance_window_out(w):
    out = _common(w)
    out.update({
        "vessel_id": w["vessel_id"],
        "start_date": w["start_date"].isoformat(),
        "end_date": w["end_date"].isoformat(),
        "reason": w["reason"],
        "source": w["source"],
        "status": w["status"],
    })
    return out


def cleaning_turn_out(t):
    out = _common(t)
    out.update({
        "booking_id": t["booking_id"],
        "scheduled_date": t["scheduled_date"].isoformat(),
        "status": t["status"],
        "re_clean_count": t["re_clean_count"],
    })
    return out


def weather_advisory_out(a):
    out = _common(a)
    out.update({
        "severity": a["severity"],
        "zone_ids": list(a["zone_ids"]),
        "window_start": db.fmt_dt(a["window_start"]),
        "window_end": db.fmt_dt(a["window_end"]),
        "status": a["status"],
    })
    return out
