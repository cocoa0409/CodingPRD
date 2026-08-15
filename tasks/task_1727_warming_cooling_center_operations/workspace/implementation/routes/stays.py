"""Guests and the GuestStay lifecycle."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SITE_NOT_OPEN,
    ERR_GUEST_MEDICAL_HOLD, ERR_GUEST_ALREADY_HAS_ACTIVE_STAY,
    ERR_NO_BED_AVAILABLE, ERR_PET_CAPACITY_EXCEEDED,
    ERR_LOCKER_CAPACITY_EXCEEDED, ERR_DISPATCH_NOT_ARRIVED,
    ERR_CROSS_EPISODE_TRANSFER, ERR_VALIDATION,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import (
    guest_active_stay_in_episode, lockers_for_bags, medical_hold, pools,
    ser_guest, ser_stay,
)
from util import (
    body, opt_bool, opt_int, paginate, req_str, touch,
)

bp = Blueprint("stays", __name__)


def get_guest(guest_id):
    g = db.store["guests"].get(guest_id)
    if g is None:
        raise_err(ERR_NOT_FOUND, f"Guest {guest_id} not found")
    return g


def get_stay(stay_id):
    s = db.store["stays"].get(stay_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, f"GuestStay {stay_id} not found")
    return s


# ------------------------------------------------------------------ guests
@bp.route("/guests", methods=["POST"])
@require_roles("IntakeStaff")
def create_guest():
    b = body()
    alias = req_str(b, "alias")
    has_pets = opt_bool(b, "has_pets", default=False)
    pet_count = opt_int(b, "pet_count", default=0, min_value=0)
    bag_count = opt_int(b, "bag_count", default=0, min_value=0)
    medical_flag = opt_bool(b, "medical_flag", default=False)
    if not has_pets and pet_count != 0:
        raise_err(ERR_VALIDATION, "pet_count must be 0 when has_pets is false")
    now = clock.now()
    g = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "alias": alias,
        "has_pets": has_pets,
        "pet_count": pet_count,
        "bag_count": bag_count,
        "medical_flag": medical_flag,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["guests"][g["id"]] = g
    return respond(ser_guest(g), 201)


@bp.route("/guests/<guest_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_guest(guest_id):
    return respond(ser_guest(get_guest(guest_id)), 200)


# ------------------------------------------------------------------- stays
@bp.route("/site-activations/<act_id>/stays", methods=["POST"])
@require_roles("IntakeStaff")
def walk_in_intake(act_id):
    act = db.store["activations"].get(act_id)
    if act is None:
        raise_err(ERR_NOT_FOUND, f"SiteActivation {act_id} not found")
    b = body()
    guest = None
    if b.get("guest_id") is not None:
        guest = get_guest(b["guest_id"])
    if act["status"] != "OPEN":
        raise_err(
            ERR_SITE_NOT_OPEN,
            f"Intake requires the activation to be OPEN (currently "
            f"{act['status']})",
        )
    if guest is None:
        if "guest_id" not in b or b["guest_id"] is None:
            raise_err(ERR_VALIDATION, "Missing required field: guest_id")
        guest = get_guest(b["guest_id"])
    if medical_hold(guest["id"]):
        raise_err(
            ERR_GUEST_MEDICAL_HOLD,
            "Guest has an active medical hold",
        )
    if guest_active_stay_in_episode(guest["id"], act["episode_id"]):
        raise_err(
            ERR_GUEST_ALREADY_HAS_ACTIVE_STAY,
            "Guest already has a RESERVED or CHECKED_IN stay in this episode",
        )
    p = pools(act)
    if p["beds_free"] is None or p["beds_free"] < 1:
        raise_err(ERR_NO_BED_AVAILABLE, "No free bed at this activation")
    if guest["pet_count"] > p["pet_slots_free"]:
        raise_err(ERR_PET_CAPACITY_EXCEEDED, "Not enough free pet slots")
    lockers_needed = lockers_for_bags(guest["bag_count"])
    if lockers_needed > p["lockers_free"]:
        raise_err(ERR_LOCKER_CAPACITY_EXCEEDED, "Not enough free lockers")
    now = clock.now()
    stay = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "site_activation_id": act["id"],
        "guest_id": guest["id"],
        "transport_dispatch_id": None,
        "status": "CHECKED_IN",
        "pet_slots_used": guest["pet_count"],
        "lockers_used": lockers_needed,
        "checked_in_at": now,
        "checked_out_at": None,
        "transfer_sequence": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["stays"][stay["id"]] = stay
    return respond(ser_stay(stay), 201)


@bp.route("/stays", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_stays():
    items = list(db.store["stays"].values())
    act_id = request.args.get("site_activation_id")
    guest_id = request.args.get("guest_id")
    dispatch_id = request.args.get("transport_dispatch_id")
    status = request.args.get("status")
    if act_id is not None:
        items = [s for s in items if s["site_activation_id"] == act_id]
    if guest_id is not None:
        items = [s for s in items if s["guest_id"] == guest_id]
    if dispatch_id is not None:
        items = [s for s in items if s["transport_dispatch_id"] == dispatch_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, pagination = paginate([ser_stay(s) for s in items])
    return respond_list(page, pagination)


@bp.route("/stays/<stay_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_stay(stay_id):
    return respond(ser_stay(get_stay(stay_id)), 200)


@bp.route("/stays/<stay_id>/check-in", methods=["POST"])
@require_roles("IntakeStaff")
def check_in(stay_id):
    stay = get_stay(stay_id)
    disp = db.store["dispatches"].get(stay["transport_dispatch_id"] or "")
    if disp is not None and disp["status"] != "ARRIVED":
        raise_err(
            ERR_DISPATCH_NOT_ARRIVED,
            "Linked transport dispatch has not arrived",
        )
    if stay["status"] != "RESERVED":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot check in a stay in status {stay['status']}",
        )
    if medical_hold(stay["guest_id"]):
        raise_err(ERR_GUEST_MEDICAL_HOLD, "Guest has an active medical hold")
    stay["status"] = "CHECKED_IN"
    stay["checked_in_at"] = clock.now()
    touch(stay)
    return respond(ser_stay(stay), 200)


@bp.route("/stays/<stay_id>/check-out", methods=["POST"])
@require_roles("IntakeStaff")
def check_out(stay_id):
    stay = get_stay(stay_id)
    if stay["status"] != "CHECKED_IN":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot check out a stay in status {stay['status']}",
        )
    stay["status"] = "CHECKED_OUT"
    stay["checked_out_at"] = clock.now()
    touch(stay)
    return respond(ser_stay(stay), 200)


@bp.route("/stays/<stay_id>/transfer", methods=["POST"])
@require_roles("IntakeStaff")
def transfer(stay_id):
    stay = get_stay(stay_id)
    b = body()
    target = None
    if b.get("target_site_activation_id") is not None:
        target = db.store["activations"].get(b["target_site_activation_id"])
        if target is None:
            raise_err(
                ERR_NOT_FOUND,
                f"SiteActivation {b['target_site_activation_id']} not found",
            )
    if stay["status"] != "CHECKED_IN":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot transfer a stay in status {stay['status']}",
        )
    if target is None:
        if "target_site_activation_id" not in b or b["target_site_activation_id"] is None:
            raise_err(
                ERR_VALIDATION,
                "Missing required field: target_site_activation_id",
            )
    if target["status"] != "OPEN":
        raise_err(
            ERR_SITE_NOT_OPEN,
            f"Transfer target must be OPEN (currently {target['status']})",
        )
    if medical_hold(stay["guest_id"]):
        raise_err(ERR_GUEST_MEDICAL_HOLD, "Guest has an active medical hold")
    source_act = db.store["activations"].get(stay["site_activation_id"])
    if source_act is None or target["episode_id"] != source_act["episode_id"]:
        raise_err(
            ERR_CROSS_EPISODE_TRANSFER,
            "Transfer target belongs to a different episode",
        )
    p = pools(target)
    if p["beds_free"] is None or p["beds_free"] < 1:
        raise_err(ERR_NO_BED_AVAILABLE, "No free bed at the target activation")
    if stay["pet_slots_used"] > p["pet_slots_free"]:
        raise_err(ERR_PET_CAPACITY_EXCEEDED, "Not enough free pet slots")
    if stay["lockers_used"] > p["lockers_free"]:
        raise_err(ERR_LOCKER_CAPACITY_EXCEEDED, "Not enough free lockers")
    now = clock.now()
    stay["status"] = "TRANSFERRED_OUT"
    stay["checked_out_at"] = now
    touch(stay)
    successor = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "site_activation_id": target["id"],
        "guest_id": stay["guest_id"],
        "transport_dispatch_id": None,
        "status": "CHECKED_IN",
        "pet_slots_used": stay["pet_slots_used"],
        "lockers_used": stay["lockers_used"],
        "checked_in_at": now,
        "checked_out_at": None,
        "transfer_sequence": stay["transfer_sequence"] + 1,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["stays"][successor["id"]] = successor
    return respond(ser_stay(successor), 200)
