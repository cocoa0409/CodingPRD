"""ChildCheckIn endpoints."""

import secrets
from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list, clock_now_iso,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_REFERENCE_MISMATCH, ERR_DEPENDENCY_STATE, ERR_SECURITY_HOLD_TRIGGERED,
)

bp = Blueprint("child_checkins", __name__)


def _mint_pin():
    return f"{secrets.randbelow(10000):04d}"


@bp.route("/child-checkins", methods=["POST"])
def create_checkin():
    require_role({"Coordinator", "PlatformAdmin"})
    body = get_json_body()
    for k in ("child_member_id", "event_id", "guardian_member_id"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")

    child = db.members.get(body["child_member_id"])
    if child is None:
        raise_err(ERR_NOT_FOUND, "child_member_id not found")
    event = db.events.get(body["event_id"])
    if event is None:
        raise_err(ERR_NOT_FOUND, "event_id not found")
    guardian = db.members.get(body["guardian_member_id"])
    if guardian is None:
        raise_err(ERR_NOT_FOUND, "guardian_member_id not found")

    # Rung 4: cross-body referential — guardian belongs to child's household AND is in child's guardian list.
    if child.get("member_type") != "CHILD":
        raise_err(ERR_REFERENCE_MISMATCH, "child_member_id must reference a CHILD")
    child_household_id = child.get("household_id")
    if guardian.get("household_id") != child_household_id:
        raise_err(ERR_REFERENCE_MISMATCH, "guardian must belong to child's household")
    if body["guardian_member_id"] not in child.get("guardian_member_ids", []):
        raise_err(ERR_REFERENCE_MISMATCH, "guardian must be in child.guardian_member_ids")

    # Rung 6: cross-entity state dependencies.
    if event.get("status") != "SCHEDULED":
        raise_err(ERR_DEPENDENCY_STATE, "event is not SCHEDULED")
    household = db.households.get(child_household_id)
    if household is None or household.get("status") != "ACTIVE":
        raise_err(ERR_DEPENDENCY_STATE, "child's household must be ACTIVE")

    rec = {
        "child_member_id": child["id"],
        "event_id": event["id"],
        "guardian_member_id": guardian["id"],
        "pickup_pin": _mint_pin(),
        "status": "CHECKED_IN",
        "checked_in_at": clock_now_iso(),
        "checked_out_at": None,
        "hold_reason": None,
    }
    stamp_common_create(rec)
    db.child_checkins[rec["id"]] = rec
    return success(rec, 201)


@bp.route("/child-checkins/<cid>", methods=["GET"])
def get_checkin(cid):
    require_role({"Coordinator", "PlatformAdmin"})
    rec = must_exist(db.child_checkins, cid, "ChildCheckIn")
    return success(rec, 200)


@bp.route("/child-checkins/<cid>/checkout", methods=["POST"])
def checkout(cid):
    require_role({"Coordinator", "PlatformAdmin"})
    rec = must_exist(db.child_checkins, cid, "ChildCheckIn")
    body = get_json_body()
    for k in ("pickup_pin", "pickup_by_member_id"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    if rec["status"] != "CHECKED_IN":
        raise_err(ERR_INVALID_STATE, "check-in must be CHECKED_IN to check out")

    child = db.members.get(rec["child_member_id"])
    guardians = child.get("guardian_member_ids", []) if child else []

    pin_ok = body["pickup_pin"] == rec["pickup_pin"]
    guardian_ok = body["pickup_by_member_id"] in guardians

    if pin_ok and guardian_ok:
        rec["status"] = "CHECKED_OUT"
        rec["checked_out_at"] = clock_now_iso()
        bump(rec)
        return success(rec, 200)

    # Failure — transition to SECURITY_HOLD, then raise the domain error.
    if not pin_ok:
        rec["hold_reason"] = "PIN_MISMATCH"
    else:
        rec["hold_reason"] = "UNAUTHORIZED_PICKUP"
    rec["status"] = "SECURITY_HOLD"
    bump(rec)
    raise_err(ERR_SECURITY_HOLD_TRIGGERED, f"security hold: {rec['hold_reason']}")


@bp.route("/child-checkins/<cid>/security-hold", methods=["POST"])
def security_hold(cid):
    require_role({"Coordinator", "PlatformAdmin"})
    rec = must_exist(db.child_checkins, cid, "ChildCheckIn")
    if rec["status"] != "CHECKED_IN":
        raise_err(ERR_INVALID_STATE, "check-in must be CHECKED_IN to place on hold")
    rec["status"] = "SECURITY_HOLD"
    rec["hold_reason"] = "STAFF_HOLD"
    bump(rec)
    return success(rec, 200)


@bp.route("/child-checkins/<cid>/clear-hold", methods=["POST"])
def clear_hold(cid):
    require_role({"Coordinator", "PlatformAdmin"})
    rec = must_exist(db.child_checkins, cid, "ChildCheckIn")
    if rec["status"] != "SECURITY_HOLD":
        raise_err(ERR_INVALID_STATE, "check-in must be SECURITY_HOLD to clear")
    rec["status"] = "CHECKED_IN"
    rec["hold_reason"] = None
    bump(rec)
    return success(rec, 200)


@bp.route("/child-checkins", methods=["GET"])
def list_checkins():
    require_role({"Coordinator", "PlatformAdmin"})
    limit, offset = get_pagination()
    items = list(db.child_checkins.values())
    for k in ("child_member_id", "guardian_member_id", "event_id", "status"):
        v = request.args.get(k)
        if v:
            items = [c for c in items if c.get(k) == v]
    page, meta = paginate_list(items, limit, offset)
    return success(page, 200, meta_extra=meta)
