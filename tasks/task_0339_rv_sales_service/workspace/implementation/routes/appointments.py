"""Appointment routes + bay overlap with cleanup buffer (PRD 3.9, 2.10)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from common import (body, new_entity, touch, require_enum, paginate, get_or_404,
                    find_dealership, parse_iso, invalid)
from middleware import get_auth, require_role
from response import ok, created, ok_list

bp = Blueprint("appointments", __name__)

APPT_KINDS = {"REPAIR", "PDI"}


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start,a_end) intersects [b_start,b_end)."""
    return a_start < b_end and b_start < a_end


@bp.post("/appointments")
def create_appt():
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor"})
    data = body()
    did = data.get("dealership_id")
    find_dealership(did)
    bay = get_or_404("service_bays", data.get("service_bay_id"))

    appt_kind = require_enum(data, "appt_kind", APPT_KINDS)

    service_order_id = data.get("service_order_id")
    deal_id = data.get("deal_id")
    if appt_kind == "REPAIR":
        if service_order_id is None:
            invalid("REPAIR appointment requires service_order_id.")
        get_or_404("service_orders", service_order_id)
        if bay["bay_kind"] != "REPAIR":
            invalid("REPAIR appointment requires a REPAIR bay.")
        deal_id = None
    else:  # PDI
        if deal_id is None:
            invalid("PDI appointment requires deal_id.")
        get_or_404("deals", deal_id)
        if bay["bay_kind"] != "WASH_PDI":
            invalid("PDI appointment requires a WASH_PDI bay.")
        service_order_id = None

    start_dt = parse_iso(data.get("start_utc"), "start_utc")
    end_dt = parse_iso(data.get("end_utc"), "end_utc")
    if end_dt <= start_dt:
        errors.err("ERR_INVALID_INTERVAL", "end_utc must be strictly after start_utc.")

    # Bay overlap incl. trailing cleanup buffer on each appointment (priority 8).
    buffer = timedelta(minutes=bay["cleanup_buffer_minutes"])
    new_end = end_dt + buffer
    for appt in db.store["appointments"].values():
        if appt["service_bay_id"] != bay["id"]:
            continue
        if appt["status"] == "CANCELLED":
            continue
        ex_start = parse_iso(appt["start_utc"], "start_utc")
        ex_end = parse_iso(appt["end_utc"], "end_utc") + buffer
        if _overlaps(start_dt, new_end, ex_start, ex_end):
            errors.err("ERR_BAY_DOUBLE_BOOKED",
                       "Appointment overlaps another on this bay.")

    rec = new_entity({
        "dealership_id": did,
        "service_bay_id": bay["id"],
        "service_order_id": service_order_id,
        "deal_id": deal_id,
        "appt_kind": appt_kind,
        "start_utc": data["start_utc"],
        "end_utc": data["end_utc"],
        "status": "SCHEDULED",
    })
    db.store["appointments"][rec["id"]] = rec
    return created(rec)


@bp.get("/appointments")
def list_appts():
    _, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor"})
    items = list(db.store["appointments"].values())
    a = request.args
    for field in ("dealership_id", "service_bay_id", "service_order_id", "deal_id", "status"):
        val = a.get(field)
        if val is not None:
            items = [ap for ap in items if ap.get(field) == val]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/appointments/<appt_id>")
def get_appt(appt_id):
    _, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor"})
    rec = get_or_404("appointments", appt_id)
    return ok(rec)


@bp.post("/appointments/<appt_id>/check-in")
def check_in(appt_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor"})
    appt = get_or_404("appointments", appt_id)
    if appt["status"] != "SCHEDULED":
        errors.err("ERR_APPT_BAD_STATE", "Appointment is not SCHEDULED.")
    appt["status"] = "CHECKED_IN"
    touch(appt)
    return ok(appt)


@bp.post("/appointments/<appt_id>/close")
def close_appt(appt_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor"})
    appt = get_or_404("appointments", appt_id)
    if appt["status"] != "CHECKED_IN":
        errors.err("ERR_APPT_BAD_STATE", "Appointment is not CHECKED_IN.")
    appt["status"] = "CLOSED"
    touch(appt)
    return ok(appt)


@bp.post("/appointments/<appt_id>/cancel")
def cancel_appt(appt_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor", "DealerManager"})
    appt = get_or_404("appointments", appt_id)
    if appt["status"] in ("CLOSED", "CANCELLED"):
        errors.err("ERR_APPT_TERMINAL", "Appointment is already terminal.")
    appt["status"] = "CANCELLED"
    touch(appt)
    return ok(appt)
