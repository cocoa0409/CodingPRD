import uuid

from flask import Blueprint, request

from core import (
    db, now, base_entity, touch, serialize, ok_object, ok_array, paginate,
    auth, forbid, lookup, get_body, require_str, opt_str, require_enum,
    require_dt, ApiError,
)
from logic import compute_estimated_fee, process_gate_event

bp = Blueprint("pass", __name__)

PASS_TYPES = {"GUEST", "VENDOR"}
DECISIONS = {"APPROVED", "DENIED"}
DIRECTIONS = {"ENTRY", "EXIT"}


# ---------------------------------------------------------------------------
# Passes (PRD 3.3)
# ---------------------------------------------------------------------------
@bp.route("/access/passes", methods=["POST"])
def create_pass():
    uid, role = auth({"Resident", "CommunityAdmin"})
    body = get_body()
    sponsor_resident_id = require_str(body, "sponsor_resident_id")
    if role == "Resident" and sponsor_resident_id != uid:
        forbid("Resident may only sponsor own pass")
    pass_type = require_enum(body, "pass_type", PASS_TYPES)
    visitor_name = require_str(body, "visitor_name")
    visitor_plate = require_str(body, "visitor_plate")
    valid_from = require_dt(body, "valid_from")
    valid_until = require_dt(body, "valid_until")
    plate_state = opt_str(body, "plate_state", None)
    vendor_company = opt_str(body, "vendor_company", None)
    lookup(db.residents, sponsor_resident_id, "ERR_RESIDENT_NOT_FOUND")

    obj = base_entity()
    obj.update({
        "sponsor_resident_id": sponsor_resident_id,
        "pass_type": pass_type,
        "visitor_name": visitor_name,
        "visitor_plate": visitor_plate,
        "plate_state": plate_state,
        "vendor_company": vendor_company,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "auth_status": "PENDING",
        "presence_status": "OFFSITE",
        "estimated_fee_cents": None,
        "final_fee_cents": None,
        "entry_at": None,
        "exit_at": None,
    })
    db.passes[obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@bp.route("/access/passes/<pass_id>", methods=["GET"])
def get_pass(pass_id):
    uid, role = auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    obj = lookup(db.passes, pass_id, "ERR_PASS_NOT_FOUND")
    if role == "Resident" and obj["sponsor_resident_id"] != uid:
        forbid("Resident may only read own pass")
    return ok_object(serialize(obj))


@bp.route("/access/passes", methods=["GET"])
def list_passes():
    uid, role = auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    args = request.args
    rows = list(db.passes.values())
    if role == "Resident":
        rows = [r for r in rows if r["sponsor_resident_id"] == uid]
    if args.get("sponsor_resident_id"):
        rows = [r for r in rows if r["sponsor_resident_id"] == args["sponsor_resident_id"]]
    if args.get("auth_status"):
        rows = [r for r in rows if r["auth_status"] == args["auth_status"]]
    if args.get("presence_status"):
        rows = [r for r in rows if r["presence_status"] == args["presence_status"]]
    items, limit, offset, total = paginate(rows)
    return ok_array(items, limit, offset, total)


@bp.route("/access/passes/<pass_id>/authorize", methods=["POST"])
def authorize_pass(pass_id):
    auth({"SecurityOfficer", "CommunityAdmin"})
    p = lookup(db.passes, pass_id, "ERR_PASS_NOT_FOUND")
    body = get_body()
    decision = require_enum(body, "decision", DECISIONS)

    if p["auth_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Pass is not PENDING")

    if decision == "DENIED":
        p["auth_status"] = "DENIED"
        touch(p)
        return ok_object(serialize(p))

    # APPROVED: sponsor eligibility, then window validity.
    sponsor = db.residents.get(p["sponsor_resident_id"])
    if sponsor is None or sponsor["status"] != "ACTIVE" or sponsor["standing"] != "GOOD":
        raise ApiError("ERR_SPONSOR_NOT_ELIGIBLE", 409, "Sponsor not eligible")
    if not (p["valid_from"] < p["valid_until"] and p["valid_until"] > now()):
        raise ApiError("ERR_PASS_WINDOW_INVALID", 422, "Pass window invalid or past")

    p["auth_status"] = "APPROVED"
    p["estimated_fee_cents"] = compute_estimated_fee(p)
    touch(p)
    return ok_object(serialize(p))


@bp.route("/access/passes/<pass_id>/revoke", methods=["POST"])
def revoke_pass(pass_id):
    auth({"SecurityOfficer", "CommunityAdmin"})
    p = lookup(db.passes, pass_id, "ERR_PASS_NOT_FOUND")
    if p["auth_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Pass is not APPROVED")
    p["auth_status"] = "REVOKED"
    touch(p)
    return ok_object(serialize(p))


# ---------------------------------------------------------------------------
# Gate events / LPR (PRD 3.4)
# ---------------------------------------------------------------------------
@bp.route("/access/gate-events", methods=["POST"])
def create_gate_event():
    auth({"SecurityOfficer"})
    body = get_body()
    community_id = require_str(body, "community_id")
    gate_id = require_str(body, "gate_id")
    direction = require_enum(body, "direction", DIRECTIONS)
    plate_read = require_str(body, "plate_read")
    plate_state = opt_str(body, "plate_state", None)
    lookup(db.communities, community_id, "ERR_COMMUNITY_NOT_FOUND")

    event = {
        "id": str(uuid.uuid4()),
        "created_at": now(),
        "_seq": db.next_seq(),
        "community_id": community_id,
        "gate_id": gate_id,
        "direction": direction,
        "plate_read": plate_read,
        "plate_state": plate_state,
        "matched_type": "UNMATCHED",
        "matched_id": None,
        "decision": "DENY",
        "reason": "NO_MATCH",
        "event_at": now(),
    }
    process_gate_event(event, community_id, direction, plate_read)
    db.gate_events[event["id"]] = event
    return ok_object(serialize(event), 201)


@bp.route("/access/gate-events/<gate_event_id>", methods=["GET"])
def get_gate_event(gate_event_id):
    auth({"CommunityAdmin", "SecurityOfficer"})
    obj = lookup(db.gate_events, gate_event_id, "ERR_GATE_EVENT_NOT_FOUND")
    return ok_object(serialize(obj))


@bp.route("/access/gate-events", methods=["GET"])
def list_gate_events():
    auth({"CommunityAdmin", "SecurityOfficer"})
    args = request.args
    rows = list(db.gate_events.values())
    if args.get("community_id"):
        rows = [r for r in rows if r["community_id"] == args["community_id"]]
    if args.get("direction"):
        rows = [r for r in rows if r["direction"] == args["direction"]]
    if args.get("decision"):
        rows = [r for r in rows if r["decision"] == args["decision"]]
    if args.get("matched_type"):
        rows = [r for r in rows if r["matched_type"] == args["matched_type"]]
    items, limit, offset, total = paginate(rows)
    return ok_array(items, limit, offset, total)
