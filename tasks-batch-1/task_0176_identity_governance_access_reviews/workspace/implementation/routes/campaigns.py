"""Certification campaign routes (PRD §3.7, §3.8).

Create (DRAFT) -> launch (ACTIVE, enroll grants + items) -> close (CLOSED,
auto-revoke undecided items). Derived posture/completion/revocation counts.
"""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string,
    parse_pagination, paginate, filter_enum_param, parse_iso8601,
)
from services import domain
from services import campaign as campaign_svc

bp = Blueprint("campaigns", __name__)

READ_ROLES = {"CampaignAdmin", "Certifier", "AccessManager"}
STATUS_VALUES = {"DRAFT", "ACTIVE", "CLOSED"}
ITEM_DECISION = {"PENDING", "UNDER_REVIEW", "CERTIFIED", "REVOKED"}


def _serialize_campaign(record):
    """Refresh derived fields then serialize (read-time consistency)."""
    campaign_svc.recompute_campaign_derived(record)
    return serialize(record)


@bp.route("/certification-campaigns", methods=["POST"])
def create_campaign():
    require_role({"CampaignAdmin"})
    body = get_json_body()
    name = require_string(body, "name")
    scope_role_id = require_string(body, "scope_role_id")
    window_start_raw = require_string(body, "review_window_start")
    window_end_raw = require_string(body, "review_window_end")
    window_start = parse_iso8601(window_start_raw, "review_window_start")
    window_end = parse_iso8601(window_end_raw, "review_window_end")

    with db.LOCK:
        if db.roles.get(scope_role_id) is None:
            raise err(errors.ERR_NOT_FOUND, "Scope role not found")
        if window_end < window_start:
            raise err(errors.ERR_VALIDATION,
                      "review_window_end must be on or after review_window_start")

        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "name": name,
            "scope_role_id": scope_role_id,
            "review_window_start": window_start_raw,
            "review_window_end": window_end_raw,
            "status": "DRAFT",
            "posture": "OPEN",
            "item_count": 0,
            "completion_pct": 100.00,
            "projected_revocation_count": 0,
            "realized_revocation_count": 0,
        }
        campaign_svc.recompute_campaign_derived(record)
        db.certification_campaigns[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/certification-campaigns/<id>", methods=["GET"])
def get_campaign(id):
    require_role(READ_ROLES)
    with db.LOCK:
        record = db.certification_campaigns.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Campaign not found")
        return object_response(_serialize_campaign(record), 200)


@bp.route("/certification-campaigns", methods=["GET"])
def list_campaigns():
    require_role(READ_ROLES)
    scope_role_id = request.args.get("scope_role_id")
    status = filter_enum_param(request.args, "status", STATUS_VALUES)
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.certification_campaigns.values())
        if scope_role_id is not None:
            records = [c for c in records if c["scope_role_id"] == scope_role_id]
        if status is not None:
            records = [c for c in records if c["status"] == status]
        for c in records:
            campaign_svc.recompute_campaign_derived(c)
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/certification-campaigns/<id>/launch", methods=["POST"])
def launch_campaign(id):
    require_role({"CampaignAdmin"})
    with db.LOCK:
        campaign = db.certification_campaigns.get(id)
        if campaign is None:
            raise err(errors.ERR_NOT_FOUND, "Campaign not found")
        if campaign["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Campaign is not DRAFT")

        role = db.roles.get(campaign["scope_role_id"])
        if role is None or role["status"] != "ACTIVE":
            raise err(errors.ERR_ROLE_RETIRED, "Scope role is not ACTIVE")

        scope_role_id = campaign["scope_role_id"]
        this_start = parse_iso8601(campaign["review_window_start"], "review_window_start")

        # No other ACTIVE campaign for the same scope role.
        for c in db.certification_campaigns.values():
            if c["id"] == id:
                continue
            if c["scope_role_id"] == scope_role_id and c["status"] == "ACTIVE":
                raise err(errors.ERR_CAMPAIGN_WINDOW_OVERLAP,
                          "Another ACTIVE campaign exists for this role")

        # This window start must be >= prior CLOSED campaign end + 1 day buffer.
        for c in db.certification_campaigns.values():
            if c["id"] == id:
                continue
            if c["scope_role_id"] == scope_role_id and c["status"] == "CLOSED":
                prior_end = parse_iso8601(c["review_window_end"], "review_window_end")
                if this_start < prior_end + timedelta(days=1):
                    raise err(errors.ERR_CAMPAIGN_WINDOW_OVERLAP,
                              "Window violates the 1-day buffer after a CLOSED campaign")

        # Enroll every ACTIVE grant of an entitlement bundled by the scope role.
        bundled = set(role.get("entitlement_ids", []))
        enrolled = [g for g in db.grants.values()
                    if g["lifecycle_status"] == "ACTIVE"
                    and g["entitlement_id"] in bundled]
        enrolled.sort(key=lambda g: g.get("_seq", 0))

        item_count = 0
        for g in enrolled:
            # Review dimension NOT_DUE -> UNDER_REVIEW (parallel; lifecycle untouched).
            g["review_status"] = "UNDER_REVIEW"
            db.touch(g)
            common = db.new_common()
            item = {
                "id": common["id"],
                "created_at": common["created_at"],
                "updated_at": common["updated_at"],
                "version": common["version"],
                "_seq": common["_seq"],
                "campaign_id": id,
                "grant_id": g["id"],
                "decision_status": "PENDING",
                "decided_by_user_id": None,
            }
            db.certification_items[item["id"]] = item
            item_count += 1

        campaign["status"] = "ACTIVE"
        campaign["item_count"] = item_count
        campaign_svc.recompute_campaign_derived(campaign)
        db.touch(campaign)
        return object_response(serialize(campaign), 200)


@bp.route("/certification-campaigns/<id>/close", methods=["POST"])
def close_campaign(id):
    require_role({"CampaignAdmin"})
    with db.LOCK:
        campaign = db.certification_campaigns.get(id)
        if campaign is None:
            raise err(errors.ERR_NOT_FOUND, "Campaign not found")
        if campaign["status"] != "ACTIVE":
            raise err(errors.ERR_INVALID_STATE, "Campaign is not ACTIVE")

        # Continue-revoke: every still-undecided item -> REVOKED, cascading its
        # grant ACTIVE -> REVOKED with full revoke side-effects.
        undecided = [it for it in db.certification_items.values()
                     if it["campaign_id"] == id
                     and it["decision_status"] in ("PENDING", "UNDER_REVIEW")]
        undecided.sort(key=lambda it: it.get("_seq", 0))
        for it in undecided:
            it["decision_status"] = "REVOKED"
            it["decided_by_user_id"] = "system"
            db.touch(it)
            grant = db.grants.get(it["grant_id"])
            if grant is not None:
                grant["review_status"] = "FLAGGED"
                db.touch(grant)
                if grant["lifecycle_status"] == "ACTIVE":
                    identity = db.identities.get(grant["identity_id"])
                    domain.revoke_grant(grant, identity, "system")

        campaign["status"] = "CLOSED"
        campaign_svc.recompute_campaign_derived(campaign)
        db.touch(campaign)
        return object_response(serialize(campaign), 200)


@bp.route("/certification-campaigns/<id>/items", methods=["GET"])
def list_campaign_items(id):
    require_role(READ_ROLES)
    decision = filter_enum_param(request.args, "decision_status", ITEM_DECISION)
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        if db.certification_campaigns.get(id) is None:
            raise err(errors.ERR_NOT_FOUND, "Campaign not found")
        records = [it for it in db.certification_items.values()
                   if it["campaign_id"] == id]
        if decision is not None:
            records = [it for it in records if it["decision_status"] == decision]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)
