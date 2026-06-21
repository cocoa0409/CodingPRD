"""WaitlistEntry endpoints + transitions."""
from flask import Blueprint, request

from db import db
from errors import (err, ERR_INVALID_STATE, ERR_OFFER_EXPIRED, ERR_DISTANCE_FULL,
                    ERR_STALE_DISTANCE_VERSION, ERR_NOT_RESOURCE_OWNER, ERR_NOT_FOUND)
from middleware import auth, require_role, get_json, now_dt
from response import object_response
from services.store import (serialize_waitlist, touch, confirmed_count,
                            paginate_and_respond)
from services.calculations import registration_amount_due
from services.validate import require_int, lookup
from services.waitlist import promote_head

bp = Blueprint("waitlist", __name__)


def _tiers_for_distance(distance_id):
    return [t for t in db.pricing_tiers.values() if t["distance_id"] == distance_id]


def _owner_check(user_id, role, owner_participant_id):
    if role == "Participant" and user_id != owner_participant_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Acting participant is not the resource owner")


@bp.route("/waitlist-entries/<waitlist_entry_id>", methods=["GET"])
def get_waitlist(waitlist_entry_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant"})
    e = lookup(db.waitlist_entries, waitlist_entry_id, "WaitlistEntry")
    return object_response(serialize_waitlist(e), 200)


@bp.route("/distances/<distance_id>/waitlist-entries", methods=["GET"])
def list_distance_waitlist(distance_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant"})
    lookup(db.distances, distance_id, "Distance")
    items = [e for e in db.waitlist_entries.values() if e["distance_id"] == distance_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginate_and_respond("waitlist", items, request.args)


@bp.route("/waitlist-entries", methods=["GET"])
def list_waitlist():
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant"})
    items = list(db.waitlist_entries.values())
    for f in ("distance_id", "registration_id", "participant_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e.get(f) == v]
    return paginate_and_respond("waitlist", items, request.args)


@bp.route("/waitlist-entries/<waitlist_entry_id>/claim", methods=["POST"])
def claim_waitlist(waitlist_entry_id):
    user_id, role = auth()
    require_role(role, {"Participant"})
    e = lookup(db.waitlist_entries, waitlist_entry_id, "WaitlistEntry")
    _owner_check(user_id, role, e["participant_id"])

    body = get_json()
    expected_version = require_int(body, "expected_distance_version")

    # state: must be OFFERED
    if e["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Waitlist entry must be OFFERED to claim")

    # temporal: now < offer_expires_utc
    if e["_offer_expires_dt"] is None or now_dt() >= e["_offer_expires_dt"]:
        raise err(ERR_OFFER_EXPIRED, "Offer has expired")

    distance = db.distances.get(e["distance_id"])
    if distance is None:
        raise err(ERR_NOT_FOUND, "Distance not found")

    # explicit claim against a full distance errors
    if confirmed_count(distance["id"]) >= distance["capacity_total"]:
        raise err(ERR_DISTANCE_FULL, "Distance is full")

    # OCC
    if expected_version != distance["version"]:
        raise err(ERR_STALE_DISTANCE_VERSION, "expected_distance_version is stale")

    reg = db.registrations.get(e["registration_id"])
    e["status"] = "CLAIMED"
    touch(e)

    if reg is not None:
        now = now_dt()
        amount, fee, _disc = registration_amount_due(
            reg["entry_type"], reg["party_size"], reg["promo_code"],
            _tiers_for_distance(distance["id"]), now)
        reg["amount_paid_cents"] = amount
        reg["processing_fee_cents"] = fee
        reg["status"] = "CONFIRMED"
        touch(reg)
    touch(distance)  # confirmed_count changed
    return object_response(serialize_waitlist(e), 200)


@bp.route("/waitlist-entries/<waitlist_entry_id>/decline", methods=["POST"])
def decline_waitlist(waitlist_entry_id):
    user_id, role = auth()
    require_role(role, {"Participant"})
    e = lookup(db.waitlist_entries, waitlist_entry_id, "WaitlistEntry")
    _owner_check(user_id, role, e["participant_id"])

    if e["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Waitlist entry must be OFFERED to decline")

    e["status"] = "DECLINED"
    touch(e)
    reg = db.registrations.get(e["registration_id"])
    if reg is not None and reg["status"] not in (
            "CANCELLED", "TRANSFERRED", "DEFERRED", "FINISHED"):
        reg["status"] = "CANCELLED"
        touch(reg)
    # promote next QUEUED entry
    promote_head(e["distance_id"])
    return object_response(serialize_waitlist(e), 200)


@bp.route("/waitlist-entries/<waitlist_entry_id>/withdraw", methods=["POST"])
def withdraw_waitlist(waitlist_entry_id):
    user_id, role = auth()
    require_role(role, {"Participant"})
    e = lookup(db.waitlist_entries, waitlist_entry_id, "WaitlistEntry")
    _owner_check(user_id, role, e["participant_id"])

    if e["status"] != "QUEUED":
        raise err(ERR_INVALID_STATE, "Waitlist entry must be QUEUED to withdraw")

    e["status"] = "WITHDRAWN"
    touch(e)
    reg = db.registrations.get(e["registration_id"])
    if reg is not None and reg["status"] not in (
            "CANCELLED", "TRANSFERRED", "DEFERRED", "FINISHED"):
        reg["status"] = "CANCELLED"
        touch(reg)
    return object_response(serialize_waitlist(e), 200)


@bp.route("/waitlist-entries/<waitlist_entry_id>/expire-check", methods=["POST"])
def expire_check(waitlist_entry_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector"})
    e = lookup(db.waitlist_entries, waitlist_entry_id, "WaitlistEntry")

    if e["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Waitlist entry must be OFFERED to expire-check")

    # only expires when now >= offer_expires_utc
    if e["_offer_expires_dt"] is None or now_dt() < e["_offer_expires_dt"]:
        raise err(ERR_INVALID_STATE, "Offer window has not elapsed")

    e["status"] = "EXPIRED"
    touch(e)
    # promote next QUEUED entry on the distance
    promote_head(e["distance_id"])
    return object_response(serialize_waitlist(e), 200)
