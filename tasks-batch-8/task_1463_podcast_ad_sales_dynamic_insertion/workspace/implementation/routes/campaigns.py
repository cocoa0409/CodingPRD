"""Campaign endpoints: create (role-scoped), get, list, OCC-guarded PATCH,
lifecycle transitions, live report, attribution-event listing."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    err_not_found,
    err_invalid,
    err_stale,
    err_conflict,
    err_forbidden,
    err_agency_mismatch,
    ERR_CAMPAIGN_NOT_ACTIVATABLE,
    ERR_CAMPAIGN_NOT_EDITABLE,
    ERR_ADVERTISER_SUSPENDED,
    ERR_NO_APPROVED_COPY,
    ERR_FLIGHT_WINDOW_INVALID,
)
from helpers import (
    body_of,
    new_id,
    now_timestamp,
    require_string,
    require_enum,
    require_int,
    parse_dt,
)
from middleware import require_roles, ALL_ROLES, check_campaign_scope
from response import success_object, list_response, serialize
from services import (
    Changes,
    end_campaign,
    campaign_report,
    recompute_episode_slots,
)

bp = Blueprint("campaigns", __name__)

BILLING_MODELS = {"ACTUAL_DELIVERY", "BOOKED_GROSS"}
WRITE_ROLES = {"AdOps", "Advertiser", "Agency"}
ATTRIBUTION_READ_ROLES = {"AdOps", "Advertiser", "Agency", "Finance"}


def get_campaign_or_404(campaign_id):
    campaign = db.campaigns.get(campaign_id)
    if campaign is None:
        raise err_not_found(f"Campaign '{campaign_id}' not found")
    return campaign


@bp.route("/adnet/campaigns", methods=["POST"])
def create_campaign():
    user_id, role = require_roles(WRITE_ROLES)
    body = body_of(request)

    # Ownership / agency representation (before existence, per the pipeline).
    advertiser_id = body.get("advertiser_id")
    if role == "Advertiser":
        if isinstance(advertiser_id, str) and advertiser_id != user_id:
            raise err_forbidden("Advertiser may create campaigns only for itself")
    elif role == "Agency":
        if isinstance(advertiser_id, str):
            advertiser = db.advertisers.get(advertiser_id)
            if advertiser is not None and advertiser.get("agency_id") != user_id:
                raise err_agency_mismatch()

    # Existence.
    if isinstance(advertiser_id, str) and advertiser_id not in db.advertisers:
        raise err_not_found(f"Advertiser '{advertiser_id}' not found")

    # Temporal: flight_end strictly after flight_start (422).
    start_dt = parse_dt(body.get("flight_start"))
    end_dt = parse_dt(body.get("flight_end"))
    if start_dt is not None and end_dt is not None and not (end_dt > start_dt):
        raise ApiError(
            ERR_FLIGHT_WINDOW_INVALID, "flight_end must be strictly after flight_start", 422
        )

    # Structural: the advertiser must be ACTIVE at creation.
    if isinstance(advertiser_id, str):
        advertiser = db.advertisers.get(advertiser_id)
        if advertiser is not None and advertiser["status"] != "ACTIVE":
            raise err_conflict(
                ERR_ADVERTISER_SUSPENDED, "Advertiser is not ACTIVE"
            )

    # Field shape (catch-all).
    advertiser_id = require_string(body, "advertiser_id")
    name = require_string(body, "name")
    flight_start = body.get("flight_start")
    flight_end = body.get("flight_end")
    if start_dt is None:
        raise err_invalid("Field 'flight_start' must be an ISO 8601 UTC timestamp")
    if end_dt is None:
        raise err_invalid("Field 'flight_end' must be an ISO 8601 UTC timestamp")
    booked_impressions = require_int(body, "booked_impressions", minimum=1)
    cpm_cents = require_int(body, "cpm_cents", minimum=1)
    billing_model = require_enum(body, "billing_model", BILLING_MODELS)

    ts = now_timestamp()
    campaign = {
        "id": new_id(),
        "advertiser_id": advertiser_id,
        "name": name,
        "flight_start": flight_start,
        "flight_end": flight_end,
        "booked_impressions": booked_impressions,
        "cpm_cents": cpm_cents,
        "billing_model": billing_model,
        "status": "DRAFT",
        "delivered_impressions": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.campaigns[campaign["id"]] = campaign
    return success_object(serialize(campaign), 201)


@bp.route("/adnet/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    require_roles(ALL_ROLES)
    return success_object(serialize(get_campaign_or_404(campaign_id)))


@bp.route("/adnet/campaigns", methods=["GET"])
def list_campaigns():
    require_roles(ALL_ROLES)
    items = list(db.campaigns.values())
    advertiser_id = request.args.get("advertiser_id")
    status = request.args.get("status")
    if advertiser_id is not None:
        items = [c for c in items if c["advertiser_id"] == advertiser_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, request.args)


@bp.route("/adnet/campaigns/<campaign_id>", methods=["PATCH"])
def patch_campaign(campaign_id):
    user_id, role = require_roles(WRITE_ROLES)
    campaign = get_campaign_or_404(campaign_id)
    check_campaign_scope(campaign, user_id, role)
    body = body_of(request)

    # OCC (priority 5): expected_campaign_version must match.
    expected = body.get("expected_campaign_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != campaign["version"]:
            raise err_stale("expected_campaign_version does not match the stored version")

    # State (priority 6): editable only while DRAFT or PAUSED.
    if campaign["status"] not in ("DRAFT", "PAUSED"):
        raise err_conflict(
            ERR_CAMPAIGN_NOT_EDITABLE,
            f"Campaign is {campaign['status']}; edits require DRAFT or PAUSED",
        )

    # Temporal (priority 9): the effective flight window stays valid.
    new_start_raw = body.get("flight_start", campaign["flight_start"])
    new_end_raw = body.get("flight_end", campaign["flight_end"])
    new_start = parse_dt(new_start_raw)
    new_end = parse_dt(new_end_raw)
    if new_start is not None and new_end is not None and not (new_end > new_start):
        raise ApiError(
            ERR_FLIGHT_WINDOW_INVALID, "flight_end must be strictly after flight_start", 422
        )

    # Immutability: billing_model (and identity fields) cannot change.
    for locked in ("billing_model", "advertiser_id", "name", "status", "id"):
        if locked in body and body[locked] != campaign.get(locked):
            raise err_invalid(f"Field '{locked}' is not editable")

    # Field shape (catch-all): OCC field required; editable fields validated.
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid(
            "Field 'expected_campaign_version' is required and must be an integer"
        )
    changes = {}
    if "flight_start" in body and body["flight_start"] is not None:
        if new_start is None:
            raise err_invalid("Field 'flight_start' must be an ISO 8601 UTC timestamp")
        changes["flight_start"] = body["flight_start"]
    if "flight_end" in body and body["flight_end"] is not None:
        if new_end is None:
            raise err_invalid("Field 'flight_end' must be an ISO 8601 UTC timestamp")
        changes["flight_end"] = body["flight_end"]
    if "booked_impressions" in body and body["booked_impressions"] is not None:
        value = body["booked_impressions"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise err_invalid("Field 'booked_impressions' must be an integer > 0")
        changes["booked_impressions"] = value
    if "cpm_cents" in body and body["cpm_cents"] is not None:
        value = body["cpm_cents"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise err_invalid("Field 'cpm_cents' must be an integer > 0")
        changes["cpm_cents"] = value

    flight_changed = "flight_start" in changes or "flight_end" in changes
    ch = Changes()
    ch.update(campaign, **changes)
    if flight_changed:
        # Slot occupancy depends on flight containment of the clock.
        touched = {
            li["episode_id"]
            for li in db.line_items.values()
            if li["campaign_id"] == campaign["id"] and li.get("episode_id")
        }
        for ep_id in touched:
            ep = db.episodes.get(ep_id)
            if ep is not None:
                recompute_episode_slots(ep, ch)
    ch.commit()
    return success_object(serialize(campaign))


@bp.route("/adnet/campaigns/<campaign_id>/transition", methods=["POST"])
def transition_campaign(campaign_id):
    require_roles({"AdOps"})
    campaign = get_campaign_or_404(campaign_id)
    body = body_of(request)
    action = body.get("action")
    if action not in ("ACTIVATE", "PAUSE", "END", "CANCEL"):
        raise err_invalid("Field 'action' must be one of ACTIVATE, PAUSE, END, CANCEL")

    status = campaign["status"]
    allowed = {
        "ACTIVATE": {"DRAFT", "PAUSED"},
        "PAUSE": {"ACTIVE"},
        "END": {"ACTIVE", "PAUSED"},
        "CANCEL": {"DRAFT"},
    }[action]
    if status not in allowed:
        raise err_conflict(
            ERR_CAMPAIGN_NOT_ACTIVATABLE,
            f"Campaign is {status}; {action} is not permitted from this state",
        )

    if action == "ACTIVATE":
        advertiser = db.advertisers.get(campaign["advertiser_id"])
        if advertiser is None or advertiser["status"] != "ACTIVE":
            raise err_conflict(
                ERR_ADVERTISER_SUSPENDED, "Advertiser must be ACTIVE to activate"
            )
        has_approved = any(
            c["campaign_id"] == campaign["id"] and c["status"] == "APPROVED"
            for c in db.ad_copies.values()
        )
        if not has_approved:
            raise err_conflict(
                ERR_NO_APPROVED_COPY, "Campaign has no APPROVED ad copy"
            )
        ch = Changes()
        ch.update(campaign, status="ACTIVE")
        ch.commit()
    elif action == "PAUSE":
        # Manual pause does NOT pause the campaign's ACTIVE line items.
        ch = Changes()
        ch.update(campaign, status="PAUSED")
        ch.commit()
    elif action == "END":
        ch = Changes()
        end_campaign(campaign, ch)
        ch.commit()
    else:  # CANCEL
        ch = Changes()
        ch.update(campaign, status="CANCELLED")
        ch.commit()
    return success_object(serialize(campaign))


@bp.route("/adnet/campaigns/<campaign_id>/report", methods=["GET"])
def get_campaign_report(campaign_id):
    require_roles(ALL_ROLES)
    campaign = get_campaign_or_404(campaign_id)
    return success_object(campaign_report(campaign))


@bp.route("/adnet/campaigns/<campaign_id>/attribution-events", methods=["GET"])
def list_campaign_attribution_events(campaign_id):
    require_roles(ATTRIBUTION_READ_ROLES)
    campaign = get_campaign_or_404(campaign_id)
    items = [e for e in db.attribution_events.values() if e["campaign_id"] == campaign["id"]]
    kind = request.args.get("kind")
    if kind is not None:
        items = [e for e in items if e["kind"] == kind]
    return list_response(items, request.args)
