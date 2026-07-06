"""Pledge endpoints."""

from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list, parse_iso_date,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_INVALID_AMOUNT,
    ERR_CAMPAIGN_NOT_ACTIVE, ERR_NOT_FOUND, ERR_FORBIDDEN,
)

bp = Blueprint("pledges", __name__)

FREQUENCIES = {"ONE_TIME", "WEEKLY", "MONTHLY"}


@bp.route("/pledges", methods=["POST"])
def create_pledge():
    role, user_id = require_role({"FinanceAdmin", "Member", "PlatformAdmin"})
    body = get_json_body()

    # Structural (rung 14) — required + type.
    for k in ("campaign_id", "member_id", "pledged_amount_cents", "frequency", "first_expected_on"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    if not isinstance(body["pledged_amount_cents"], int) or isinstance(body["pledged_amount_cents"], bool):
        raise_err(ERR_INVALID_REQUEST, "pledged_amount_cents must be an integer")
    if body["frequency"] not in FREQUENCIES:
        raise_err(ERR_INVALID_REQUEST, "invalid frequency")
    try:
        first_expected = parse_iso_date(body["first_expected_on"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "first_expected_on must be YYYY-MM-DD")

    # Existence (rung 3).
    campaign = db.pledge_campaigns.get(body["campaign_id"])
    if campaign is None:
        raise_err(ERR_NOT_FOUND, "campaign_id not found")
    member = db.members.get(body["member_id"])
    if member is None:
        raise_err(ERR_NOT_FOUND, "member_id not found")

    # Member self-service ownership (§2.1).
    if role == "Member" and member["id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Member may only create pledges for themselves")

    # Rung 6: campaign must be ACTIVE.
    if campaign.get("status") != "ACTIVE":
        raise_err(ERR_CAMPAIGN_NOT_ACTIVE, "campaign is not ACTIVE")

    # Member must not be DEPARTED.
    if member.get("membership_status") == "DEPARTED":
        raise_err(ERR_INVALID_STATE, "member is DEPARTED")

    # Rung 11: fiscal invariants.
    if body["pledged_amount_cents"] <= 0:
        raise_err(ERR_INVALID_AMOUNT, "pledged_amount_cents must be > 0")
    starts = parse_iso_date(campaign["starts_on"])
    ends = parse_iso_date(campaign["ends_on"])
    if not (starts <= first_expected <= ends):
        raise_err(ERR_INVALID_AMOUNT, "first_expected_on must fall in campaign window")

    rec = {
        "campaign_id": campaign["id"],
        "member_id": member["id"],
        "pledged_amount_cents": body["pledged_amount_cents"],
        "frequency": body["frequency"],
        "first_expected_on": body["first_expected_on"],
        "status": "ACTIVE",
        "received_amount_cents": 0,
        "remaining_amount_cents": body["pledged_amount_cents"],
    }
    stamp_common_create(rec)
    db.pledges[rec["id"]] = rec

    campaign["pledged_total_cents"] = campaign.get("pledged_total_cents", 0) + rec["pledged_amount_cents"]
    bump(campaign)

    return success(rec, 201)


@bp.route("/pledges/<pid>", methods=["GET"])
def get_pledge(pid):
    role, user_id = require_role({"FinanceAdmin", "Coordinator", "Member", "PlatformAdmin"})
    rec = must_exist(db.pledges, pid, "Pledge")
    if role == "Member" and rec["member_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Member may only view their own pledges")
    return success(rec, 200)


@bp.route("/pledges/<pid>/cancel", methods=["POST"])
def cancel_pledge(pid):
    role, user_id = require_role({"FinanceAdmin", "Member", "PlatformAdmin"})
    rec = must_exist(db.pledges, pid, "Pledge")
    if role == "Member" and rec["member_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Member may only cancel their own pledges")
    if rec["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "pledge must be ACTIVE to cancel")
    campaign = db.pledge_campaigns[rec["campaign_id"]]
    if campaign.get("status") != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "cannot cancel a pledge on a campaign that is not ACTIVE")

    rec["status"] = "CANCELLED"
    bump(rec)

    campaign["pledged_total_cents"] = campaign.get("pledged_total_cents", 0) - rec["pledged_amount_cents"]
    bump(campaign)

    return success(rec, 200)


@bp.route("/pledges", methods=["GET"])
def list_pledges():
    role, user_id = require_role({"FinanceAdmin", "Coordinator", "Member", "PlatformAdmin"})
    limit, offset = get_pagination()
    campaign_id = request.args.get("campaign_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    items = list(db.pledges.values())
    if role == "Member":
        items = [p for p in items if p["member_id"] == user_id]
    if campaign_id:
        items = [p for p in items if p.get("campaign_id") == campaign_id]
    if member_id:
        items = [p for p in items if p.get("member_id") == member_id]
    if status:
        items = [p for p in items if p.get("status") == status]
    page, meta = paginate_list(items, limit, offset)
    return success(page, 200, meta_extra=meta)
