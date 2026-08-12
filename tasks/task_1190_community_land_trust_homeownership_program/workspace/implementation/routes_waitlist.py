"""WaitlistEntry endpoints."""
from flask import Blueprint, g, jsonify

import db
import engine
from auth import require, require_household_owner
from errors import (
    ApiError, ERR_CERT_STALE, ERR_EDUCATION_INCOMPLETE, ERR_HOUSEHOLD_INELIGIBLE,
    ERR_INVALID_STATE,
)
from scope import get_household_or_404, get_program_or_404, get_waitlist_entry_or_404
from util import (
    body, bump, new_entity, ok_object, paginated, query_str, req_int,
    ser_waitlist_entry,
)

bp = Blueprint("waitlist", __name__)

STAFF_READ = ["PlatformAdmin", "ProgramAdmin", "ComplianceOfficer",
              "LeaseManager", "IntakeSpecialist"]


@bp.post("/programs/<pid>/households/<hid>/waitlist-entries")
@require(["IntakeSpecialist", "Household"])
def create_waitlist_entry(pid, hid):
    get_program_or_404(pid)
    h = get_household_or_404(pid, hid)
    require_household_owner(h["id"])
    data = body()
    desired_bedrooms = req_int(data, "desired_bedrooms")
    max_price = req_int(data, "max_price_cents")

    now = db.get_now()
    if h["eligibility_status"] != "ELIGIBLE":
        raise ApiError(ERR_HOUSEHOLD_INELIGIBLE, 409,
                       "Household must be ELIGIBLE to join the waitlist")
    if h["education_completed_at"] is None:
        raise ApiError(ERR_EDUCATION_INCOMPLETE, 409,
                       "Household has not completed required education")
    cert = engine.latest_approved_cert(h["id"])
    if not engine.cert_is_fresh(cert, now):
        raise ApiError(ERR_CERT_STALE, 409,
                       "Latest approved certification is older than 24 months")

    e = new_entity()
    e.update({
        "household_id": h["id"],
        "desired_bedrooms": desired_bedrooms,
        "max_price_cents": max_price,
        "priority_score": 0,
        "status": "ACTIVE",
        "matched_unit_id": None,
        "matched_at": None,
        "match_rank_at_match": None,
    })
    engine.refresh_priority_score(e, now)
    db.store.waitlist[e["id"]] = e
    h["waitlist_entry_id"] = e["id"]
    bump(h)
    return jsonify(ok_object(ser_waitlist_entry(e))), 201


@bp.get("/programs/<pid>/waitlist-entries")
@require(STAFF_READ)
def list_program_waitlist(pid):
    get_program_or_404(pid)
    items = []
    for e in db.store.waitlist.values():
        h = db.store.households.get(e["household_id"])
        if h and h["program_id"] == pid:
            items.append(e)
    status = query_str("status")
    if status:
        items = [e for e in items if e["status"] == status]
    household_id = query_str("household_id")
    if household_id:
        items = [e for e in items if e["household_id"] == household_id]
    return jsonify(paginated(items, ser_waitlist_entry)), 200


@bp.get("/programs/<pid>/households/<hid>/waitlist-entries")
@require(STAFF_READ + ["Household"])
def list_household_waitlist(pid, hid):
    h = get_household_or_404(pid, hid)
    require_household_owner(h["id"])
    items = [e for e in db.store.waitlist.values() if e["household_id"] == hid]
    status = query_str("status")
    if status:
        items = [e for e in items if e["status"] == status]
    return jsonify(paginated(items, ser_waitlist_entry)), 200


@bp.get("/programs/<pid>/waitlist-entries/<wid>")
@require(STAFF_READ + ["Household"])
def get_waitlist_entry(pid, wid):
    get_program_or_404(pid)
    e = get_waitlist_entry_or_404(pid, wid)
    require_household_owner(e["household_id"])
    return jsonify(ok_object(ser_waitlist_entry(e))), 200


@bp.post("/programs/<pid>/waitlist-entries/<wid>/withdraw")
@require(["Household", "LeaseManager"])
def withdraw_waitlist_entry(pid, wid):
    get_program_or_404(pid)
    e = get_waitlist_entry_or_404(pid, wid)
    require_household_owner(e["household_id"])
    if e["status"] not in ("ACTIVE", "MATCHED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE or MATCHED entry can be withdrawn")

    if e["status"] == "MATCHED":
        # Return the associated listing to OPEN (re-listed).
        for listing in db.store.listings.values():
            if listing["matched_waitlist_entry_id"] == e["id"] and listing["status"] == "MATCHED":
                listing["status"] = "OPEN"
                listing["matched_waitlist_entry_id"] = None
                listing["buyer_household_id"] = None
                bump(listing)

    e["status"] = "WITHDRAWN"
    bump(e)
    h = db.store.households.get(e["household_id"])
    if h and h["waitlist_entry_id"] == e["id"]:
        h["waitlist_entry_id"] = None
        bump(h)
    return jsonify(ok_object(ser_waitlist_entry(e))), 200
