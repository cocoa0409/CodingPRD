"""Membership routes (PRD §3.6). Branching lifecycle + parallel billing dimension."""
from flask import Blueprint, request

import constants as C
from db import db, common_fields, touch
from errors import err, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER
from middleware import authenticate, authorize
from response import success
from serialize import public
from domain import recompute_winery_loyalty_liability
from club_service import cancel_scheduled_shipments
from validate import (
    get_json_body, require_str, require_int, require_positive_int, require_enum,
    get_or_404, resolve_winery_fk, resolve_fk,
)
from pagination import paginate, sorted_by_creation

bp = Blueprint("memberships", __name__)


def _new_membership(winery_id, member_id, tier, cadence_months, bottles_per_shipment):
    ms = common_fields()
    ms.update({
        "member_id": member_id,
        "winery_id": winery_id,
        "tier": tier,
        "cadence_months": cadence_months,
        "bottles_per_shipment": bottles_per_shipment,
        "billing_status": "CURRENT",
        "loyalty_points": 0,
        "lifetime_bottles_shipped": 0,
        "status": "ENROLLED",
    })
    return ms


@bp.route("/memberships", methods=["POST"])
def create_membership():
    _, role = authenticate()
    authorize(role, ["ClubManager"])
    body = get_json_body()
    winery_id = require_str(body, "winery_id")
    member_id = require_str(body, "member_id")
    tier = require_enum(body, "tier", C.TIERS)
    cadence_months = require_positive_int(body, "cadence_months")
    bottles_per_shipment = require_positive_int(body, "bottles_per_shipment")
    with db.lock:
        resolve_winery_fk(winery_id)
        resolve_fk(db.members, member_id, winery_id)
        ms = _new_membership(winery_id, member_id, tier, cadence_months, bottles_per_shipment)
        db.memberships[ms["id"]] = ms
        return success(public(ms), status=201)


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    user_id, role = authenticate()
    authorize(role, ["ClubManager", "Member", "ComplianceOfficer"])
    with db.lock:
        items = list(db.memberships.values())
        member_id = request.args.get("member_id")
        winery_id = request.args.get("winery_id")
        status = request.args.get("status")
        if member_id is not None:
            items = [m for m in items if m["member_id"] == member_id]
        if winery_id is not None:
            items = [m for m in items if m["winery_id"] == winery_id]
        if status is not None:
            items = [m for m in items if m["status"] == status]
        # Member self-service: read only own memberships (PRD §2.1)
        if role == "Member":
            items = [m for m in items if m["member_id"] == user_id]
        items = sorted_by_creation(items)
        page, pg = paginate(items)
        return success([public(m) for m in page], pagination=pg)


@bp.route("/memberships/<membership_id>", methods=["GET"])
def get_membership(membership_id):
    user_id, role = authenticate()
    authorize(role, ["ClubManager", "Member"])
    with db.lock:
        ms = get_or_404(db.memberships, membership_id)
        if role == "Member" and user_id != ms["member_id"]:
            raise err(ERR_NOT_RESOURCE_OWNER, "Member may only read its own membership")
        return success(public(ms))


@bp.route("/memberships/<membership_id>/transitions", methods=["POST"])
def transition_membership(membership_id):
    _, role = authenticate()
    authorize(role, ["ClubManager"])
    with db.lock:
        ms = get_or_404(db.memberships, membership_id)
        body = get_json_body()
        action = require_enum(body, "action", {"ACTIVATE", "PAUSE", "RESUME", "CANCEL"})
        member = db.members.get(ms["member_id"])
        winery = db.wineries.get(ms["winery_id"])

        if action == "ACTIVATE":
            if ms["status"] != "ENROLLED":
                raise err(ERR_INVALID_STATE, "Membership is not ENROLLED")
            if member is None or member["status"] != "ACTIVE":
                raise err(ERR_INVALID_STATE, "Owning member is not ACTIVE")
            ms["status"] = "ACTIVE"
            touch(ms)

        elif action == "PAUSE":
            if ms["status"] != "ACTIVE":
                raise err(ERR_INVALID_STATE, "Membership is not ACTIVE")
            ms["status"] = "PAUSED"
            touch(ms)
            cancel_scheduled_shipments(ms)

        elif action == "RESUME":
            if ms["status"] != "PAUSED":
                raise err(ERR_INVALID_STATE, "Membership is not PAUSED")
            if member is None or member["status"] != "ACTIVE":
                raise err(ERR_INVALID_STATE, "Owning member is not ACTIVE")
            ms["status"] = "ACTIVE"
            touch(ms)

        else:  # CANCEL
            if ms["status"] not in ("ACTIVE", "PAUSED", "ENROLLED"):
                raise err(ERR_INVALID_STATE, "Membership cannot be cancelled from its current state")
            ms["status"] = "CANCELLED"
            touch(ms)
            cancel_scheduled_shipments(ms)
            # forfeit loyalty points; recompute winery liability
            ms["loyalty_points"] = 0
            touch(ms)
            if winery is not None:
                recompute_winery_loyalty_liability(winery)
                touch(winery)

        return success(public(ms))


@bp.route("/memberships/<membership_id>/billing", methods=["POST"])
def set_billing(membership_id):
    _, role = authenticate()
    authorize(role, ["ClubManager"])
    with db.lock:
        ms = get_or_404(db.memberships, membership_id)
        body = get_json_body()
        billing_status = require_enum(body, "billing_status", C.BILLING_STATUSES)
        ms["billing_status"] = billing_status
        touch(ms)
        return success(public(ms))
