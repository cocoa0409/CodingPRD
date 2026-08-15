"""OutreachCampaign and OutreachNotice endpoints (PRD §3.7)."""

from flask import Blueprint, request

import db
import services.domain as domain
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list

bp = Blueprint("outreach_campaigns", __name__)

CO = "ComplianceOfficer"
READ_ROLES = ("TenantAdmin", "ComplianceOfficer", "Auditor")


@bp.route("/tenants/<tid>/outreach_campaigns", methods=["POST"])
def create_outreach(tid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    body = request.get_json(silent=True) or {}
    rec = db.make_record({
        "tenant_id": tenant["id"],
        "name": body.get("name"),
        "target_state_filter": body.get("target_state_filter") or [],
        "days_before_expiration": body.get("days_before_expiration"),
        "scheduled_send_day_index": body.get("scheduled_send_day_index"),
        "sent_count": 0,
        "status": "DRAFT",
    })
    db.stores["outreach_campaigns"][rec["id"]] = rec
    return created(db.pub(rec))


@bp.route("/tenants/<tid>/outreach_campaigns/<oid>", methods=["GET"])
def get_outreach(tid, oid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("outreach_campaigns", oid, tenant["id"])
    return ok(db.pub(campaign))


@bp.route("/tenants/<tid>/outreach_campaigns/<oid>/schedule", methods=["POST"])
def schedule_outreach(tid, oid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("outreach_campaigns", oid, tenant["id"])
    if campaign["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT outreach campaign can be scheduled", 409)
    # days_before_expiration must be at least 1, failing as an invalid
    # transition (priority 5) before the schedule-in-past check (priority 14).
    dbe = campaign["days_before_expiration"]
    if not isinstance(dbe, int) or dbe < 1:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "days_before_expiration must be at least 1", 409)
    if campaign["scheduled_send_day_index"] is None or campaign["scheduled_send_day_index"] < tenant["audit_clock_day_index"]:
        raise ApiError("ERR_SCHEDULE_IN_PAST", "scheduled_send_day_index must be the current day index or later", 422)
    campaign["status"] = "SCHEDULED"
    bump(campaign)
    return ok(db.pub(campaign))


@bp.route("/tenants/<tid>/outreach_campaigns/<oid>/cancel", methods=["POST"])
def cancel_outreach(tid, oid):
    require_role(CO)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("outreach_campaigns", oid, tenant["id"])
    # Priority 23: a campaign already in SENDING or DONE may not be cancelled.
    if campaign["status"] in ("SENDING", "DONE"):
        raise ApiError("ERR_CAMPAIGN_ALREADY_SENDING", "A campaign already in SENDING or DONE may not be cancelled", 409)
    if campaign["status"] == "DRAFT":
        campaign["status"] = "CANCELLED"
    elif campaign["status"] == "SCHEDULED":
        # A SCHEDULED campaign may be cancelled only while the current day
        # remains strictly earlier than its scheduled_send_day_index.
        if tenant["audit_clock_day_index"] >= campaign["scheduled_send_day_index"]:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "A SCHEDULED campaign can be cancelled only strictly before its send day",
                409,
            )
        campaign["status"] = "CANCELLED"
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Campaign cannot be cancelled from its current state", 409)
    bump(campaign)
    return ok(db.pub(campaign))


@bp.route("/tenants/<tid>/outreach_campaigns/<oid>/notices", methods=["GET"])
def list_notices(tid, oid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    campaign = domain.get_scoped("outreach_campaigns", oid, tenant["id"])
    items = [n for n in db.stores["outreach_notices"].values() if n["campaign_id"] == campaign["id"]]
    items.sort(key=lambda n: n["_seq"])
    return ok_list([db.pub(n) for n in items])
