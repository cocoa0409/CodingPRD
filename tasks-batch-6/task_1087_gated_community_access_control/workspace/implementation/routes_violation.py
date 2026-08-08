from flask import Blueprint, request

from core import (
    db, now, base_entity, touch, serialize, ok_object, ok_array, paginate,
    auth, forbid, lookup, get_body, require_str, opt_str, require_enum,
    require_int, ApiError,
)
from logic import compute_repeat_index, compute_assessed_fine, recompute_resident

bp = Blueprint("violation", __name__)

VIOLATION_TYPES = {"SPEEDING", "NOISE", "PARKING", "UNAUTHORIZED_GUEST", "GATE_TAILGATING"}
RESOLUTIONS = {"UPHELD", "DISMISSED", "REDUCED"}
PAYABLE_STATES = ("ISSUED", "UPHELD", "REDUCED")


@bp.route("/access/violations", methods=["POST"])
def create_violation():
    uid, role = auth({"SecurityOfficer", "CommunityAdmin"})
    body = get_body()
    community_id = require_str(body, "community_id")
    resident_id = require_str(body, "resident_id")
    violation_type = require_enum(body, "violation_type", VIOLATION_TYPES)
    base_fine_cents = require_int(body, "base_fine_cents", minimum=0)
    incident_id = opt_str(body, "incident_id", None)
    lookup(db.communities, community_id, "ERR_COMMUNITY_NOT_FOUND")
    resident = lookup(db.residents, resident_id, "ERR_RESIDENT_NOT_FOUND")
    if incident_id is not None:
        lookup(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")

    issued_at = now()
    obj = base_entity()
    repeat_index = compute_repeat_index(resident_id, violation_type, issued_at, obj["id"])
    assessed = compute_assessed_fine(base_fine_cents, repeat_index, resident["standing"])
    obj.update({
        "community_id": community_id,
        "resident_id": resident_id,
        "incident_id": incident_id,
        "violation_type": violation_type,
        "base_fine_cents": base_fine_cents,
        "assessed_fine_cents": assessed,
        "repeat_index": repeat_index,
        "paid_amount_cents": None,
        "issued_by_user_id": uid,
        "status": "ISSUED",
        "issued_at": issued_at,
    })
    db.violations[obj["id"]] = obj
    recompute_resident(resident)
    return ok_object(serialize(obj), 201)


@bp.route("/access/violations/<violation_id>", methods=["GET"])
def get_violation(violation_id):
    uid, role = auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    obj = lookup(db.violations, violation_id, "ERR_VIOLATION_NOT_FOUND")
    if role == "Resident" and obj["resident_id"] != uid:
        forbid("Resident may only read own violation")
    return ok_object(serialize(obj))


@bp.route("/access/violations", methods=["GET"])
def list_violations():
    uid, role = auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    args = request.args
    rows = list(db.violations.values())
    if role == "Resident":
        rows = [r for r in rows if r["resident_id"] == uid]
    if args.get("community_id"):
        rows = [r for r in rows if r["community_id"] == args["community_id"]]
    if args.get("resident_id"):
        rows = [r for r in rows if r["resident_id"] == args["resident_id"]]
    if args.get("incident_id"):
        rows = [r for r in rows if r["incident_id"] == args["incident_id"]]
    if args.get("status"):
        rows = [r for r in rows if r["status"] == args["status"]]
    if args.get("violation_type"):
        rows = [r for r in rows if r["violation_type"] == args["violation_type"]]
    items, limit, offset, total = paginate(rows)
    return ok_array(items, limit, offset, total)


def _own_violation(role, uid, violation):
    if role == "Resident" and violation["resident_id"] != uid:
        forbid("Resident may only act on own violation")


@bp.route("/access/violations/<violation_id>/appeal", methods=["POST"])
def appeal_violation(violation_id):
    uid, role = auth({"Resident"})
    v = lookup(db.violations, violation_id, "ERR_VIOLATION_NOT_FOUND")
    _own_violation(role, uid, v)
    if v["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Violation is not ISSUED")
    v["status"] = "APPEALED"
    touch(v)
    return ok_object(serialize(v))


@bp.route("/access/violations/<violation_id>/withdraw-appeal", methods=["POST"])
def withdraw_appeal(violation_id):
    uid, role = auth({"Resident"})
    v = lookup(db.violations, violation_id, "ERR_VIOLATION_NOT_FOUND")
    _own_violation(role, uid, v)
    if v["status"] != "APPEALED":
        raise ApiError("ERR_INVALID_STATE", 409, "Violation is not APPEALED")
    v["status"] = "ISSUED"
    touch(v)
    return ok_object(serialize(v))


@bp.route("/access/violations/<violation_id>/resolve", methods=["POST"])
def resolve_violation(violation_id):
    uid, role = auth({"CommunityAdmin"})
    v = lookup(db.violations, violation_id, "ERR_VIOLATION_NOT_FOUND")
    body = get_body()
    resolution = require_enum(body, "resolution", RESOLUTIONS)

    # Segregation of duties (before state per PRD 2.10)
    if uid == v["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Resolver issued this violation")

    if v["status"] != "APPEALED":
        raise ApiError("ERR_INVALID_STATE", 409, "Violation is not APPEALED")

    resident = db.residents.get(v["resident_id"])

    if resolution == "UPHELD":
        v["status"] = "UPHELD"
        touch(v)
        if resident:
            recompute_resident(resident)
    elif resolution == "DISMISSED":
        v["status"] = "DISMISSED"
        touch(v)
        if resident:
            recompute_resident(resident)
    elif resolution == "REDUCED":
        reduced = body.get("reduced_fine_cents")
        if (
            reduced is None
            or isinstance(reduced, bool)
            or not isinstance(reduced, int)
            or reduced < 0
            or reduced > v["assessed_fine_cents"]
        ):
            raise ApiError("ERR_INVALID_RESOLUTION", 422, "Invalid reduced_fine_cents")
        v["assessed_fine_cents"] = reduced
        v["status"] = "REDUCED"
        touch(v)
        if resident:
            recompute_resident(resident)

    return ok_object(serialize(v))


@bp.route("/access/violations/<violation_id>/pay", methods=["POST"])
def pay_violation(violation_id):
    uid, role = auth({"Resident", "CommunityAdmin"})
    v = lookup(db.violations, violation_id, "ERR_VIOLATION_NOT_FOUND")
    _own_violation(role, uid, v)
    body = get_body()
    amount_cents = require_int(body, "amount_cents", minimum=0)

    if v["status"] not in PAYABLE_STATES:
        raise ApiError("ERR_INVALID_STATE", 409, "Violation not in a payable state")
    if amount_cents != v["assessed_fine_cents"]:
        raise ApiError("ERR_INVALID_RESOLUTION", 422, "Payment must equal assessed fine")

    v["paid_amount_cents"] = amount_cents
    v["status"] = "PAID"
    touch(v)
    resident = db.residents.get(v["resident_id"])
    if resident:
        recompute_resident(resident)
    return ok_object(serialize(v))
