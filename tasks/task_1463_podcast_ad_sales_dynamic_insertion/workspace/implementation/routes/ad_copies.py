"""Ad copy endpoints: create (buyer side), get, list, submit, review
(APPROVE / REQUEST_CHANGES by kind-scoped reviewer; WITHDRAW owner-only)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    err_not_found,
    err_invalid,
    err_conflict,
    err_forbidden,
    err_agency_mismatch,
    ERR_COPY_STATE,
    ERR_HOST_READ_REQUIRES_SHOW,
)
from helpers import body_of, new_id, now_timestamp, require_string, require_enum
from middleware import require_roles, ALL_ROLES, check_campaign_scope
from response import success_object, list_response, serialize
from services import Changes, cascade_copy_revoked

bp = Blueprint("ad_copies", __name__)

KINDS = {"HOST_READ_SCRIPT", "PRODUCED_AUDIO"}
WRITE_ROLES = {"Advertiser", "Agency"}
REVIEW_ROLES = {"AdOps", "ShowProducer", "Advertiser", "Agency"}


def get_copy_or_404(copy_id):
    copy = db.ad_copies.get(copy_id)
    if copy is None:
        raise err_not_found(f"AdCopy '{copy_id}' not found")
    return copy


@bp.route("/adnet/ad-copies", methods=["POST"])
def create_ad_copy():
    user_id, role = require_roles(WRITE_ROLES)
    body = body_of(request)

    campaign_id = body.get("campaign_id")
    show_id = body.get("show_id")

    # Existence + ownership/agency scope.
    campaign = None
    if isinstance(campaign_id, str):
        campaign = db.campaigns.get(campaign_id)
        if campaign is None:
            raise err_not_found(f"Campaign '{campaign_id}' not found")
    if campaign is not None:
        check_campaign_scope(campaign, user_id, role)
    if isinstance(show_id, str) and show_id not in db.shows:
        raise err_not_found(f"Show '{show_id}' not found")

    # Cross-reference integrity: host-read scripts must name their show.
    kind = body.get("kind")
    if kind == "HOST_READ_SCRIPT" and not (isinstance(show_id, str) and show_id):
        raise ApiError(
            ERR_HOST_READ_REQUIRES_SHOW,
            "HOST_READ_SCRIPT ad copy requires show_id",
            400,
        )

    # Field shape (catch-all).
    campaign_id = require_string(body, "campaign_id")
    kind = require_enum(body, "kind", KINDS)
    script_text = require_string(body, "script_text")
    if show_id is not None and not isinstance(show_id, str):
        raise err_invalid("Field 'show_id' must be a string when provided")

    ts = now_timestamp()
    copy = {
        "id": new_id(),
        "campaign_id": campaign_id,
        "kind": kind,
        "show_id": show_id,
        "script_text": script_text,
        "revision": 1,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.ad_copies[copy["id"]] = copy
    return success_object(serialize(copy), 201)


@bp.route("/adnet/ad-copies/<copy_id>", methods=["GET"])
def get_ad_copy(copy_id):
    require_roles(ALL_ROLES)
    return success_object(serialize(get_copy_or_404(copy_id)))


@bp.route("/adnet/ad-copies", methods=["GET"])
def list_ad_copies():
    require_roles(ALL_ROLES)
    items = list(db.ad_copies.values())
    for param in ("campaign_id", "show_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c.get(param) == value]
    return list_response(items, request.args)


@bp.route("/adnet/ad-copies/<copy_id>/submit", methods=["POST"])
def submit_ad_copy(copy_id):
    user_id, role = require_roles(WRITE_ROLES)
    copy = get_copy_or_404(copy_id)
    campaign = db.campaigns.get(copy["campaign_id"])
    if campaign is not None:
        check_campaign_scope(campaign, user_id, role)

    if copy["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise err_conflict(
            ERR_COPY_STATE,
            f"AdCopy is {copy['status']}; submit requires DRAFT or CHANGES_REQUESTED",
        )
    ch = Changes()
    if copy["status"] == "CHANGES_REQUESTED":
        ch.update(copy, status="SUBMITTED", revision=copy["revision"] + 1)
    else:
        ch.update(copy, status="SUBMITTED")
    ch.commit()
    return success_object(serialize(copy))


@bp.route("/adnet/ad-copies/<copy_id>/review", methods=["POST"])
def review_ad_copy(copy_id):
    user_id, role = require_roles(REVIEW_ROLES)
    copy = get_copy_or_404(copy_id)
    body = body_of(request)
    action = body.get("action")

    # Ownership/scope, keyed by the requested action.
    if action in ("APPROVE", "REQUEST_CHANGES"):
        if copy["kind"] == "HOST_READ_SCRIPT":
            if role != "ShowProducer" or user_id != copy.get("show_id"):
                raise err_forbidden(
                    "HOST_READ_SCRIPT copies are reviewed by the show's ShowProducer"
                )
        else:  # PRODUCED_AUDIO
            if role != "AdOps":
                raise err_forbidden("PRODUCED_AUDIO copies are reviewed by AdOps")
    elif action == "WITHDRAW":
        campaign = db.campaigns.get(copy["campaign_id"])
        if role == "Advertiser":
            if campaign is None or campaign["advertiser_id"] != user_id:
                raise err_forbidden("Only the owning advertiser may withdraw")
        elif role == "Agency":
            advertiser = (
                db.advertisers.get(campaign["advertiser_id"]) if campaign else None
            )
            if advertiser is None or advertiser.get("agency_id") != user_id:
                raise err_agency_mismatch()
        else:
            raise err_forbidden("Only the owning advertiser or its agency may withdraw")

    # State legality.
    allowed = {
        "APPROVE": {"SUBMITTED"},
        "REQUEST_CHANGES": {"SUBMITTED", "APPROVED"},
        "WITHDRAW": {"DRAFT"},
    }.get(action)
    if allowed is None:
        raise err_invalid(
            "Field 'action' must be one of APPROVE, REQUEST_CHANGES, WITHDRAW"
        )
    if copy["status"] not in allowed:
        raise err_conflict(
            ERR_COPY_STATE,
            f"AdCopy is {copy['status']}; {action} is not permitted from this state",
        )

    ch = Changes()
    if action == "APPROVE":
        ch.update(copy, status="APPROVED")
    elif action == "REQUEST_CHANGES":
        was_approved = copy["status"] == "APPROVED"
        ch.update(copy, status="CHANGES_REQUESTED")
        if was_approved:
            # Revocation: pause every ACTIVE line item referencing this copy.
            cascade_copy_revoked(copy, ch)
    else:  # WITHDRAW
        ch.update(copy, status="WITHDRAWN")
    ch.commit()
    return success_object(serialize(copy))
