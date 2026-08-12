"""Festivals (lifecycle + sweep), the test-driving clock, and vendors."""
from flask import Blueprint

import serialize
from calc import sweep_festival
from store import db
from util import (ALL_ROLES, ApiError, body_json, err, fmt_dt, get_or_404,
                  list_response, new_id, parse_dt, req_int, req_str,
                  require_role, stamp_new, success, touch)

bp = Blueprint("meta", __name__)

FESTIVAL_STATUSES = ("PLANNING", "APPLICATIONS_OPEN", "CURATED", "LIVE",
                     "SETTLEMENT", "CLOSED")
FESTIVAL_NEXT = {
    "PLANNING": "APPLICATIONS_OPEN",
    "APPLICATIONS_OPEN": "CURATED",
    "CURATED": "LIVE",
    "LIVE": "SETTLEMENT",
    "SETTLEMENT": "CLOSED",
}


# ---------------------------------------------------------------------------
# Festivals
# ---------------------------------------------------------------------------

@bp.route("/festivals", methods=["POST"])
def create_festival():
    require_role("FestivalDirector")
    b = body_json()
    name = req_str(b, "name")
    event_start = parse_dt(b.get("event_start"), "event_start")
    event_end = parse_dt(b.get("event_end"), "event_end")
    cap = req_int(b, "category_cap_per_category", min_v=0)
    festival = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "name": name,
        "event_start": event_start,
        "event_end": event_end,
        "category_cap_per_category": cap,
        "status": "PLANNING",
    })
    db.festivals[festival["id"]] = festival
    return success(serialize.serialize_festival(festival), 201)


@bp.route("/festivals", methods=["GET"])
def list_festivals():
    require_role(*ALL_ROLES)
    return list_response(list(db.festivals.values()),
                         serialize.serialize_festival, {"status": "status"})


@bp.route("/festivals/<festivalId>", methods=["GET"])
def get_festival(festivalId):
    require_role(*ALL_ROLES)
    festival = get_or_404(db.festivals, festivalId, "ERR_FESTIVAL_NOT_FOUND", "Festival")
    return success(serialize.serialize_festival(festival))


@bp.route("/festivals/<festivalId>/advance-status", methods=["POST"])
def advance_festival(festivalId):
    require_role("FestivalDirector")
    festival = get_or_404(db.festivals, festivalId, "ERR_FESTIVAL_NOT_FOUND", "Festival")
    b = body_json()
    to_status = b.get("to_status")
    if not isinstance(to_status, str) or to_status not in FESTIVAL_STATUSES:
        err("ERR_INVALID_REQUEST", 400,
            f"Field 'to_status' is required and must be one of {list(FESTIVAL_STATUSES)}")
    if FESTIVAL_NEXT.get(festival["status"]) != to_status:
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"Festival in {festival['status']} may only advance to "
            f"{FESTIVAL_NEXT.get(festival['status'])}")

    if to_status == "APPLICATIONS_OPEN":
        if not any(z["festival_id"] == festival["id"] for z in db.zones.values()):
            err("ERR_FESTIVAL_NOT_CONFIGURED", 409,
                "Festival has no zones; at least one zone is required")
    elif to_status == "CURATED":
        if any(a["festival_id"] == festival["id"] and a["status"] in (
                "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED")
                for a in db.applications.values()):
            err("ERR_APPLICATIONS_PENDING_REVIEW", 409,
                "Applications remain in SUBMITTED/UNDER_REVIEW/CHANGES_REQUESTED")
    elif to_status == "LIVE":
        if any(a["festival_id"] == festival["id"] and a["status"] == "RESERVED"
               for a in db.assignments.values()):
            err("ERR_ASSIGNMENTS_UNCONFIRMED", 409,
                "Assignments remain in RESERVED")
        if not db.clock >= festival["event_start"]:
            err("ERR_FESTIVAL_NOT_STARTED", 409,
                "Logical clock has not reached event_start")
    elif to_status == "SETTLEMENT":
        if not db.clock > festival["event_end"]:
            err("ERR_FESTIVAL_NOT_ENDED", 409,
                "Logical clock is not past event_end")
    elif to_status == "CLOSED":
        if any(s["festival_id"] == festival["id"] and s["status"] != "PAID"
               for s in db.settlements.values()):
            err("ERR_SETTLEMENTS_OPEN", 409,
                "Every settlement of the festival must be PAID")

    festival["status"] = to_status
    touch(festival)

    if to_status == "SETTLEMENT":
        # Side effect: every ACTIVE assignment of this festival -> COMPLETED.
        for a in db.assignments.values():
            if a["festival_id"] == festival["id"] and a["status"] == "ACTIVE":
                a["status"] = "COMPLETED"
                touch(a)

    return success(serialize.serialize_festival(festival))


@bp.route("/festivals/<festivalId>/sweep-operations", methods=["POST"])
def sweep_operations(festivalId):
    require_role("OperationsLead", "FestivalDirector")
    festival = get_or_404(db.festivals, festivalId, "ERR_FESTIVAL_NOT_FOUND", "Festival")
    result = sweep_festival(festival)
    return success(result)


# ---------------------------------------------------------------------------
# Test-driving logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role("FestivalDirector")
    b = body_json()
    db.clock = parse_dt(b.get("to_iso8601"), "to_iso8601")
    return success({"current_utc": fmt_dt(db.clock)})


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@bp.route("/vendors", methods=["POST"])
def create_vendor():
    require_role("FestivalDirector", "VendorManager")
    b = body_json()
    legal_name = req_str(b, "legal_name")
    contact_email = req_str(b, "contact_email")
    vendor = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "legal_name": legal_name,
        "contact_email": contact_email,
        "status": "APPROVED",
        "compliance_strikes": 0,
    })
    db.vendors[vendor["id"]] = vendor
    return success(serialize.serialize_vendor(vendor), 201)


@bp.route("/vendors", methods=["GET"])
def list_vendors():
    require_role("FestivalDirector", "VendorManager", "OperationsLead",
                 "HealthInspector", "SustainabilityOfficer", "FinanceLead")
    return list_response(list(db.vendors.values()),
                         serialize.serialize_vendor, {"status": "status"})


@bp.route("/vendors/<vendorId>", methods=["GET"])
def get_vendor(vendorId):
    require_role(*ALL_ROLES)
    vendor = get_or_404(db.vendors, vendorId, "ERR_VENDOR_NOT_FOUND", "Vendor")
    return success(serialize.serialize_vendor(vendor))
