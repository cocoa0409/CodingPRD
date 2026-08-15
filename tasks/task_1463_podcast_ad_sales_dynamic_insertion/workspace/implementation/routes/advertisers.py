"""Advertiser endpoints: create, get, list, SUSPEND / REINSTATE transitions."""

from flask import Blueprint, request

import db
from errors import err_not_found, err_invalid
from helpers import body_of, new_id, now_timestamp, require_string, require_enum
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response, serialize
from services import Changes, cascade_advertiser_suspended

bp = Blueprint("advertisers", __name__)

ADVERTISER_CATEGORIES = {
    "AUTOMOTIVE",
    "CPG_FOOD",
    "FINTECH",
    "GAMBLING",
    "ALCOHOL",
    "HEALTH_PHARMA",
    "TECHNOLOGY",
}


def get_advertiser_or_404(advertiser_id):
    advertiser = db.advertisers.get(advertiser_id)
    if advertiser is None:
        raise err_not_found(f"Advertiser '{advertiser_id}' not found")
    return advertiser


@bp.route("/adnet/advertisers", methods=["POST"])
def create_advertiser():
    require_roles({"AdOps"})
    body = body_of(request)

    agency_id = body.get("agency_id")
    if isinstance(agency_id, str) and agency_id not in db.agencies:
        raise err_not_found(f"Agency '{agency_id}' not found")

    name = require_string(body, "name")
    category = require_enum(body, "category", ADVERTISER_CATEGORIES)
    if agency_id is not None and not isinstance(agency_id, str):
        raise err_invalid("Field 'agency_id' must be a string when provided")

    ts = now_timestamp()
    advertiser = {
        "id": new_id(),
        "name": name,
        "category": category,
        "agency_id": agency_id,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.advertisers[advertiser["id"]] = advertiser
    return success_object(serialize(advertiser), 201)


@bp.route("/adnet/advertisers/<advertiser_id>", methods=["GET"])
def get_advertiser(advertiser_id):
    require_roles(ALL_ROLES)
    return success_object(serialize(get_advertiser_or_404(advertiser_id)))


@bp.route("/adnet/advertisers", methods=["GET"])
def list_advertisers():
    require_roles(ALL_ROLES)
    items = list(db.advertisers.values())
    agency_id = request.args.get("agency_id")
    category = request.args.get("category")
    status = request.args.get("status")
    if agency_id is not None:
        items = [a for a in items if a.get("agency_id") == agency_id]
    if category is not None:
        items = [a for a in items if a["category"] == category]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items, request.args)


@bp.route("/adnet/advertisers/<advertiser_id>/transition", methods=["POST"])
def transition_advertiser(advertiser_id):
    require_roles({"AdOps"})
    advertiser = get_advertiser_or_404(advertiser_id)
    body = body_of(request)
    action = body.get("action")
    if action not in ("SUSPEND", "REINSTATE"):
        raise err_invalid("Field 'action' must be one of SUSPEND, REINSTATE")

    if action == "SUSPEND":
        if advertiser["status"] != "ACTIVE":
            raise err_invalid(f"Advertiser is {advertiser['status']}; SUSPEND requires ACTIVE")
        ch = Changes()
        ch.update(advertiser, status="SUSPENDED")
        cascade_advertiser_suspended(advertiser, ch)
        ch.commit()
    else:  # REINSTATE — deliberately resumes nothing downstream.
        if advertiser["status"] != "SUSPENDED":
            raise err_invalid(
                f"Advertiser is {advertiser['status']}; REINSTATE requires SUSPENDED"
            )
        ch = Changes()
        ch.update(advertiser, status="ACTIVE")
        ch.commit()
    return success_object(serialize(advertiser))
