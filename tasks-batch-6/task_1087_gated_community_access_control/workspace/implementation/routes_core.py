import random

from flask import Blueprint, request

from core import (
    db, now, base_entity, touch, serialize, ok_object, ok_array, paginate,
    auth, forbid, lookup, get_body, require_str, opt_str, require_enum,
    opt_bool, parse_dt, ApiError, DELINQUENCY_THRESHOLD_CENTS,
)
from logic import (
    recompute_resident, suspend_resident, moveout_cascade,
    compute_outstanding_balance, compute_accrued_late_fee,
)

bp = Blueprint("core", __name__)

RESIDENT_TYPES = {"OWNER", "TENANT"}
RESIDENT_STATES = {"ACTIVE", "SUSPENDED", "MOVED_OUT"}


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
@bp.route("/access/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"CommunityAdmin"})
    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise ApiError("ERR_VALIDATION", 400, "Missing to_iso8601")
    db.clock = parse_dt(body["to_iso8601"])
    return ok_object({})


# ---------------------------------------------------------------------------
# Communities (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.route("/access/communities", methods=["POST"])
def create_community():
    auth({"CommunityAdmin"})
    body = get_body()
    name = require_str(body, "name")
    timezone = opt_str(body, "timezone", "UTC")
    obj = base_entity()
    obj.update({"name": name, "timezone": timezone})
    db.communities[obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@bp.route("/access/communities/<community_id>", methods=["GET"])
def get_community(community_id):
    auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    obj = lookup(db.communities, community_id, "ERR_COMMUNITY_NOT_FOUND")
    return ok_object(serialize(obj))


# ---------------------------------------------------------------------------
# Residents (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.route("/access/residents", methods=["POST"])
def create_resident():
    auth({"CommunityAdmin"})
    body = get_body()
    community_id = require_str(body, "community_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    resident_type = require_enum(body, "resident_type", RESIDENT_TYPES)
    phone = opt_str(body, "phone", None)
    unit_label = opt_str(body, "unit_label", None)
    lot_number = opt_str(body, "lot_number", None)
    directory_listed = opt_bool(body, "directory_listed", True)
    lookup(db.communities, community_id, "ERR_COMMUNITY_NOT_FOUND")

    obj = base_entity()
    obj.update({
        "community_id": community_id,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "resident_type": resident_type,
        "unit_label": unit_label,
        "lot_number": lot_number,
        "directory_listed": directory_listed,
        "callbox_code": "".join(random.choices("0123456789", k=4)),
        "status": "ACTIVE",
        "standing": "GOOD",
        "outstanding_balance_cents": 0,
    })
    db.residents[obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@bp.route("/access/residents/<resident_id>", methods=["GET"])
def get_resident(resident_id):
    uid, role = auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    obj = lookup(db.residents, resident_id, "ERR_RESIDENT_NOT_FOUND")
    if role == "Resident" and obj["id"] != uid:
        forbid("Resident may only read own record")
    return ok_object(serialize(obj))


@bp.route("/access/residents", methods=["GET"])
def list_residents():
    auth({"CommunityAdmin", "SecurityOfficer"})
    args = request.args
    rows = list(db.residents.values())
    if args.get("community_id"):
        rows = [r for r in rows if r["community_id"] == args["community_id"]]
    if args.get("standing"):
        rows = [r for r in rows if r["standing"] == args["standing"]]
    if args.get("status"):
        rows = [r for r in rows if r["status"] == args["status"]]
    if args.get("directory_listed") is not None and args.get("directory_listed") != "":
        want = args["directory_listed"].lower() == "true"
        rows = [r for r in rows if r["directory_listed"] == want]
    items, limit, offset, total = paginate(rows)
    return ok_array(items, limit, offset, total)


@bp.route("/access/residents/<resident_id>/transition", methods=["POST"])
def transition_resident(resident_id):
    auth({"CommunityAdmin"})
    resident = lookup(db.residents, resident_id, "ERR_RESIDENT_NOT_FOUND")
    body = get_body()
    to_status = require_enum(body, "to_status", RESIDENT_STATES)

    cur = resident["status"]
    allowed = {
        "ACTIVE": {"SUSPENDED", "MOVED_OUT"},
        "SUSPENDED": {"ACTIVE", "MOVED_OUT"},
        "MOVED_OUT": set(),
    }
    if to_status not in allowed.get(cur, set()):
        raise ApiError("ERR_INVALID_STATE", 409, "Transition not permitted")

    if to_status == "SUSPENDED":
        suspend_resident(resident)
    elif to_status == "ACTIVE":
        if resident["outstanding_balance_cents"] >= DELINQUENCY_THRESHOLD_CENTS:
            raise ApiError("ERR_RESIDENT_NOT_ELIGIBLE", 409, "Balance at or above threshold")
        resident["status"] = "ACTIVE"
        touch(resident)
    elif to_status == "MOVED_OUT":
        resident["status"] = "MOVED_OUT"
        touch(resident)
        moveout_cascade(resident)
    return ok_object(serialize(resident))


@bp.route("/access/residents/<resident_id>/statement", methods=["GET"])
def resident_statement(resident_id):
    uid, role = auth({"CommunityAdmin", "Resident"})
    resident = lookup(db.residents, resident_id, "ERR_RESIDENT_NOT_FOUND")
    if role == "Resident" and resident["id"] != uid:
        forbid("Resident may only read own statement")
    outstanding = compute_outstanding_balance(resident_id)
    late_fee = compute_accrued_late_fee(resident_id)
    return ok_object({
        "outstanding_balance_cents": outstanding,
        "accrued_late_fee_cents": late_fee,
        "statement_total_cents": outstanding + late_fee,
        "standing": resident["standing"],
    })


# ---------------------------------------------------------------------------
# Community reports (PRD 3.8)
# ---------------------------------------------------------------------------
@bp.route("/access/communities/<community_id>/reports/access-log", methods=["GET"])
def report_access_log(community_id):
    auth({"CommunityAdmin"})
    lookup(db.communities, community_id, "ERR_COMMUNITY_NOT_FOUND")
    args = request.args
    from_iso = parse_dt(args["from_iso"]) if args.get("from_iso") else None
    to_iso = parse_dt(args["to_iso"]) if args.get("to_iso") else None

    events = [e for e in db.gate_events.values() if e["community_id"] == community_id]
    if from_iso is not None:
        events = [e for e in events if e["event_at"] >= from_iso]
    if to_iso is not None:
        events = [e for e in events if e["event_at"] <= to_iso]

    allow = sum(1 for e in events if e["decision"] == "ALLOW")
    deny = sum(1 for e in events if e["decision"] == "DENY")
    unmatched = sum(1 for e in events if e["matched_type"] == "UNMATCHED")
    return ok_object({
        "total_events": len(events),
        "allow_count": allow,
        "deny_count": deny,
        "unmatched_count": unmatched,
    })


@bp.route("/access/communities/<community_id>/reports/violations-summary", methods=["GET"])
def report_violations_summary(community_id):
    auth({"CommunityAdmin"})
    lookup(db.communities, community_id, "ERR_COMMUNITY_NOT_FOUND")
    open_states = ("ISSUED", "APPEALED", "UPHELD", "REDUCED")
    open_violations = [
        v for v in db.violations.values()
        if v["community_id"] == community_id and v["status"] in open_states
    ]
    open_count = len(open_violations)
    total_assessed = sum(v["assessed_fine_cents"] for v in open_violations)
    delinquent = sum(
        1 for r in db.residents.values()
        if r["community_id"] == community_id and r["standing"] == "DELINQUENT"
    )
    return ok_object({
        "open_count": open_count,
        "total_assessed_cents": total_assessed,
        "delinquent_resident_count": delinquent,
    })
