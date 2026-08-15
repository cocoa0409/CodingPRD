"""Availability calendar + logical clock endpoints (PRD §2.4, §3.3)."""

from datetime import datetime, timezone

from flask import Blueprint, request

import db
import domain
from errors import raise_err, ERR_INVALID_REQUEST
from helpers import DATE_RE, check_no_undeclared, get_body, ok_object, req_str, require

bp = Blueprint("misc", __name__)

READERS = ("FarmManager", "GateStaff", "FieldStaff")
FM = ("FarmManager",)


@bp.get("/farm/availability-calendar")
def availability_calendar():
    require(READERS)
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    if from_date is None or not DATE_RE.match(from_date):
        raise_err(ERR_INVALID_REQUEST, "from_date is required (YYYY-MM-DD)")
    if to_date is None or not DATE_RE.match(to_date):
        raise_err(ERR_INVALID_REQUEST, "to_date is required (YYYY-MM-DD)")
    field_filter = request.args.get("field_id")
    rows = []
    for w in db.windows.values():
        if w["status"] == "CANCELLED":
            continue
        if not (from_date <= w["date"] <= to_date):
            continue
        if field_filter is not None and w["field_id"] != field_filter:
            continue
        field = db.fields.get(w["field_id"])
        rows.append(
            {
                "date": w["date"],
                "window_id": w["id"],
                "field_id": w["field_id"],
                "field_name": field["name"] if field else None,
                "field_status": field["status"] if field else None,
                "window_status": w["status"],
                "open_time": w["open_time"],
                "close_time": w["close_time"],
                "picking_capacity_slots": w["picking_capacity_slots"],
                "booked_slots": domain.window_booked_slots(w),
                "projected_remaining_oz": domain.field_projected_remaining_oz(field)
                if field
                else None,
                "_sort": (w["date"], w["open_time"], w["created_at"], w["_seq"]),
            }
        )
    rows.sort(key=lambda r: r["_sort"])
    for r in rows:
        r.pop("_sort", None)
    return ok_object({"rows": rows})


def _format_dt(dt):
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@bp.post("/farm/_clock/set_current_utc")
def set_clock():
    require(FM)
    body = get_body()
    check_no_undeclared(body, {"to_iso8601"})
    raw = req_str(body, "to_iso8601")
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    db.set_logical_now(dt.astimezone(timezone.utc))
    return ok_object({"current_utc": _format_dt(db.logical_now())})
