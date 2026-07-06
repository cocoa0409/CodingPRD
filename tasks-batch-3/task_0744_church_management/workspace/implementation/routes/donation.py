"""Donation endpoints."""

from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list, parse_iso_date,
    clock_now_iso, clock_now_dt, add_days_iso,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_INVALID_AMOUNT,
    ERR_REFERENCE_MISMATCH, ERR_NOT_FOUND, ERR_REFUND_WINDOW_EXPIRED,
    ERR_NO_ACTIVE_PLEDGE, ERR_FORBIDDEN,
)
from services.donation import apply_post, apply_refund, apply_fail

bp = Blueprint("donations", __name__)

PAYMENT_METHODS = {"CASH", "CHECK", "CARD", "ACH"}


def _validate_donation_body(body):
    for k in ("member_id", "amount_cents", "donation_date", "payment_method"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    if not isinstance(body["amount_cents"], int) or isinstance(body["amount_cents"], bool):
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be an integer")
    try:
        parse_iso_date(body["donation_date"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "donation_date must be YYYY-MM-DD")
    if body["payment_method"] not in PAYMENT_METHODS:
        raise_err(ERR_INVALID_REQUEST, "invalid payment_method")
    if "is_tax_deductible" in body and body["is_tax_deductible"] is not None:
        if not isinstance(body["is_tax_deductible"], bool):
            raise_err(ERR_INVALID_REQUEST, "is_tax_deductible must be a boolean")
    if "split_across" in body and body["split_across"] is not None:
        if not isinstance(body["split_across"], bool):
            raise_err(ERR_INVALID_REQUEST, "split_across must be a boolean")


def _do_split(parent_body, member, campaign):
    """Return the list of splits [{pledge_id, amount_cents}] using the pinned rounding order."""
    amt = parent_body["amount_cents"]
    candidates = [
        p for p in db.pledges.values()
        if p.get("member_id") == member["id"]
        and p.get("campaign_id") == campaign["id"]
        and p.get("status") == "ACTIVE"
    ]
    # Sort by remaining_amount_cents DESC, created_at ASC.
    candidates.sort(key=lambda p: (-p.get("remaining_amount_cents", 0), p.get("created_at", "")))
    denom = sum(p.get("remaining_amount_cents", 0) for p in candidates)
    if denom <= 0 or not candidates:
        raise_err(ERR_NO_ACTIVE_PLEDGE, "no ACTIVE pledges available for split")

    shares = []
    running = 0
    for p in candidates[:-1]:
        share = (amt * p.get("remaining_amount_cents", 0)) // denom
        shares.append({"pledge_id": p["id"], "amount_cents": share})
        running += share
    last = candidates[-1]
    shares.append({"pledge_id": last["id"], "amount_cents": amt - running})
    return shares


@bp.route("/donations", methods=["POST"])
def create_donation():
    role, user_id = require_role({"FinanceAdmin", "Member", "PlatformAdmin"})
    body = get_json_body()
    _validate_donation_body(body)

    # Rung 3: existence checks for referenced ids (left-to-right in the body).
    member = db.members.get(body["member_id"])
    if member is None:
        raise_err(ERR_NOT_FOUND, "member_id not found")
    if role == "Member" and member["id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Member may only create donations for themselves")

    campaign = None
    if body.get("campaign_id") is not None:
        campaign = db.pledge_campaigns.get(body["campaign_id"])
        if campaign is None:
            raise_err(ERR_NOT_FOUND, "campaign_id not found")

    pledge = None
    if body.get("pledge_id") is not None:
        pledge = db.pledges.get(body["pledge_id"])
        if pledge is None:
            raise_err(ERR_NOT_FOUND, "pledge_id not found")

    split_across = bool(body.get("split_across")) if "split_across" in body else False

    # Structural: split_across mode requires no explicit pledge_id AND a campaign_id.
    if split_across:
        if body.get("pledge_id") is not None:
            raise_err(ERR_INVALID_REQUEST, "split_across requires no explicit pledge_id")
        if body.get("campaign_id") is None:
            raise_err(ERR_INVALID_REQUEST, "split_across requires a campaign_id")

    # Rung 4: cross-body referential integrity for pledge_id.
    if pledge is not None:
        if pledge.get("member_id") != member["id"]:
            raise_err(ERR_REFERENCE_MISMATCH, "pledge.member_id does not match donation.member_id")
        if campaign is None or pledge.get("campaign_id") != campaign["id"]:
            raise_err(ERR_REFERENCE_MISMATCH, "pledge.campaign_id does not match donation.campaign_id")

    # Rung 11: fiscal — amount_cents > 0.
    if body["amount_cents"] <= 0:
        raise_err(ERR_INVALID_AMOUNT, "amount_cents must be > 0")

    method = body["payment_method"]
    initial_status = "POSTED" if method in ("CASH", "CHECK") else "PENDING"

    parent = {
        "member_id": member["id"],
        "campaign_id": campaign["id"] if campaign else None,
        "pledge_id": pledge["id"] if pledge else None,
        "amount_cents": body["amount_cents"],
        "donation_date": body["donation_date"],
        "payment_method": method,
        "is_tax_deductible": body["is_tax_deductible"] if "is_tax_deductible" in body else True,
        "status": "PENDING",  # will overwrite below
        "posted_at": None,
        "refunded_at": None,
    }
    stamp_common_create(parent)

    if split_across:
        # Compute splits (may raise ERR_NO_ACTIVE_PLEDGE).
        splits = _do_split(body, member, campaign)
        # Parent is an audit/aggregator record: keep campaign_id so campaign summing counts it once,
        # but DO NOT create it as a separate ledger contributor. Children carry the pledge attribution;
        # each child has campaign_id=None so aggregations by campaign only count the parent (avoiding
        # double-count of the same money).
        parent["status"] = initial_status
        parent["split_across"] = True
        parent["splits"] = splits  # keep for response
        db.donations[parent["id"]] = parent

        # Create child donations (one per split), each linked to the pledge.
        child_ids = []
        for s in splits:
            child = {
                "member_id": member["id"],
                "campaign_id": None,  # avoid double-count vs parent for campaign received_total
                "pledge_id": s["pledge_id"],
                "amount_cents": s["amount_cents"],
                "donation_date": body["donation_date"],
                "payment_method": method,
                "is_tax_deductible": body["is_tax_deductible"] if "is_tax_deductible" in body else True,
                "status": "PENDING",
                "posted_at": None,
                "refunded_at": None,
                "parent_donation_id": parent["id"],
                "is_split_child": True,
            }
            stamp_common_create(child)
            db.donations[child["id"]] = child
            child_ids.append(child["id"])

        if initial_status == "POSTED":
            # Post parent: campaign accumulates parent's amount.
            parent["posted_at"] = clock_now_iso()
            campaign["received_total_cents"] = campaign.get("received_total_cents", 0) + parent["amount_cents"]
            bump(campaign)
            bump(parent)
            # Post each child: pledge accumulates the share, may auto-fulfill.
            for cid in child_ids:
                child = db.donations[cid]
                child["status"] = "POSTED"
                child["posted_at"] = clock_now_iso()
                pl = db.pledges[child["pledge_id"]]
                pl["received_amount_cents"] = pl.get("received_amount_cents", 0) + child["amount_cents"]
                pl["remaining_amount_cents"] = max(0, pl["pledged_amount_cents"] - pl["received_amount_cents"])
                if pl["status"] == "ACTIVE" and pl["received_amount_cents"] >= pl["pledged_amount_cents"]:
                    pl["status"] = "FULFILLED"
                    campaign["fulfilled_pledge_count"] = campaign.get("fulfilled_pledge_count", 0) + 1
                    bump(campaign)
                bump(pl)
                bump(child)

        parent["child_donation_ids"] = child_ids
        return success(parent, 201)

    # Non-split path.
    db.donations[parent["id"]] = parent
    if initial_status == "POSTED":
        apply_post(parent)
        bump(parent)  # apply_post did not bump the donation itself
    else:
        parent["status"] = "PENDING"
    return success(parent, 201)


@bp.route("/donations/<did>", methods=["GET"])
def get_donation(did):
    role, user_id = require_role({"FinanceAdmin", "Member", "PlatformAdmin"})
    rec = must_exist(db.donations, did, "Donation")
    if role == "Member" and rec["member_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Member may only view their own donations")
    return success(rec, 200)


@bp.route("/donations/<did>/post", methods=["POST"])
def post_donation(did):
    require_role({"FinanceAdmin", "PlatformAdmin"})
    rec = must_exist(db.donations, did, "Donation")
    if rec["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "donation must be PENDING to post")
    apply_post(rec)
    bump(rec)
    return success(rec, 200)


@bp.route("/donations/<did>/refund", methods=["POST"])
def refund_donation(did):
    require_role({"FinanceAdmin", "PlatformAdmin"})
    rec = must_exist(db.donations, did, "Donation")
    if rec["status"] != "POSTED":
        raise_err(ERR_INVALID_STATE, "donation must be POSTED to refund")
    # Rung 10: refund window.
    donation_date = parse_iso_date(rec["donation_date"])
    cutoff = add_days_iso(rec["donation_date"], 60)
    now_date = clock_now_dt().date()
    if now_date > cutoff:
        raise_err(ERR_REFUND_WINDOW_EXPIRED, "refund window has passed")
    apply_refund(rec)
    bump(rec)
    return success(rec, 200)


@bp.route("/donations/<did>/mark-failed", methods=["POST"])
def mark_failed(did):
    require_role({"FinanceAdmin", "PlatformAdmin"})
    rec = must_exist(db.donations, did, "Donation")
    if rec["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "donation must be PENDING to mark failed")
    apply_fail(rec)
    bump(rec)
    return success(rec, 200)


@bp.route("/donations", methods=["GET"])
def list_donations():
    role, user_id = require_role({"FinanceAdmin", "Member", "PlatformAdmin"})
    limit, offset = get_pagination()
    items = list(db.donations.values())
    if role == "Member":
        items = [d for d in items if d["member_id"] == user_id]
    for k in ("member_id", "campaign_id", "pledge_id", "status"):
        v = request.args.get(k)
        if v:
            items = [d for d in items if d.get(k) == v]
    page, meta = paginate_list(items, limit, offset)
    return success(page, 200, meta_extra=meta)
