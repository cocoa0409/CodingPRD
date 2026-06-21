"""Certification item routes (PRD §3.7).

Certify keeps the grant (review_status -> CERTIFIED). Revoke drives the grant
review_status -> FLAGGED and cascades lifecycle ACTIVE -> REVOKED. Both require
the owning campaign to be ACTIVE (ERR_CAMPAIGN_NOT_ACTIVE).
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role
from response import object_response, array_response
from services.common import (
    serialize, parse_pagination, paginate, filter_enum_param,
)
from services import domain
from services import campaign as campaign_svc

bp = Blueprint("items", __name__)

READ_ROLES = {"CampaignAdmin", "Certifier", "AccessManager"}
ITEM_DECISION = {"PENDING", "UNDER_REVIEW", "CERTIFIED", "REVOKED"}


@bp.route("/certification-items/<id>", methods=["GET"])
def get_item(id):
    require_role(READ_ROLES)
    with db.LOCK:
        record = db.certification_items.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Certification item not found")
        return object_response(serialize(record), 200)


@bp.route("/certification-items", methods=["GET"])
def list_items():
    require_role(READ_ROLES)
    grant_id = request.args.get("grant_id")
    campaign_id = request.args.get("campaign_id")
    decision = filter_enum_param(request.args, "decision_status", ITEM_DECISION)
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.certification_items.values())
        if grant_id is not None:
            records = [it for it in records if it["grant_id"] == grant_id]
        if campaign_id is not None:
            records = [it for it in records if it["campaign_id"] == campaign_id]
        if decision is not None:
            records = [it for it in records if it["decision_status"] == decision]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/certification-items/<id>/certify", methods=["POST"])
def certify_item(id):
    user_id, _ = require_role({"Certifier"})
    with db.LOCK:
        item = db.certification_items.get(id)
        if item is None:
            raise err(errors.ERR_NOT_FOUND, "Certification item not found")
        campaign = db.certification_campaigns.get(item["campaign_id"])
        if campaign is None or campaign["status"] != "ACTIVE":
            raise err(errors.ERR_CAMPAIGN_NOT_ACTIVE, "Owning campaign is not ACTIVE")
        if item["decision_status"] not in ("PENDING", "UNDER_REVIEW"):
            raise err(errors.ERR_INVALID_STATE, "Item already decided")

        item["decision_status"] = "CERTIFIED"
        item["decided_by_user_id"] = user_id
        db.touch(item)

        grant = db.grants.get(item["grant_id"])
        if grant is not None:
            # Keep the grant: review dimension UNDER_REVIEW -> CERTIFIED.
            grant["review_status"] = "CERTIFIED"
            db.touch(grant)

        campaign_svc.recompute_campaign_derived(campaign)
        db.touch(campaign)

        subject_identity = grant["identity_id"] if grant is not None else None
        domain.append_audit(subject_identity, "ITEM_CERTIFIED", user_id,
                            "Certification item %s certified" % id)
        return object_response(serialize(item), 200)


@bp.route("/certification-items/<id>/revoke", methods=["POST"])
def revoke_item(id):
    user_id, _ = require_role({"Certifier"})
    with db.LOCK:
        item = db.certification_items.get(id)
        if item is None:
            raise err(errors.ERR_NOT_FOUND, "Certification item not found")
        campaign = db.certification_campaigns.get(item["campaign_id"])
        if campaign is None or campaign["status"] != "ACTIVE":
            raise err(errors.ERR_CAMPAIGN_NOT_ACTIVE, "Owning campaign is not ACTIVE")
        if item["decision_status"] not in ("PENDING", "UNDER_REVIEW"):
            raise err(errors.ERR_INVALID_STATE, "Item already decided")

        item["decision_status"] = "REVOKED"
        item["decided_by_user_id"] = user_id
        db.touch(item)

        grant = db.grants.get(item["grant_id"])
        if grant is not None:
            grant["review_status"] = "FLAGGED"
            db.touch(grant)
            if grant["lifecycle_status"] == "ACTIVE":
                identity = db.identities.get(grant["identity_id"])
                domain.revoke_grant(grant, identity, user_id)

        campaign_svc.recompute_campaign_derived(campaign)
        db.touch(campaign)
        return object_response(serialize(item), 200)
