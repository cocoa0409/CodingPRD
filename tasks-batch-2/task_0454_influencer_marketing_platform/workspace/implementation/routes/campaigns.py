from datetime import timedelta

from flask import Blueprint, request

from db import db, base_fields, bump
from middleware import get_auth, require_role
from validators import (get_body, req_str, req_int, opt_bool, req_datetime)
from clock import parse_iso
from errors import err
from response import success
from pagination import paginate
import serializers as S
import services as svc
import derive
import calculations as calc

bp = Blueprint("campaigns", __name__)

CONTENT_TYPES = {"FEED_POST", "STORY", "REEL", "VIDEO"}


@bp.route("/campaigns", methods=["POST"])
def create_campaign():
    user_id, role = get_auth()
    require_role(role, {"Brand"})
    body = get_body()
    brand_id = req_str(body, "brand_id", allow_empty=False)
    # ownership: brand_id must match the acting brand (PRD 3.3)
    if brand_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "brand_id must match the acting brand")
    # existence of the brand
    svc.get_brand(brand_id)

    title = req_str(body, "title", allow_empty=False)
    campaign_budget_cents = req_int(body, "campaign_budget_cents", minimum=1)
    requires_ftc = opt_bool(body, "requires_ftc_disclosure", default=True)
    starts_at = req_datetime(body, "starts_at")
    ends_at = req_datetime(body, "ends_at")
    # end strictly after start, else ERR_VALIDATION (PRD 3.3)
    if not (starts_at < ends_at):
        raise err("ERR_VALIDATION", "ends_at must be strictly after starts_at")

    rec = base_fields()
    rec.update({
        "brand_id": brand_id,
        "title": title,
        "campaign_budget_cents": campaign_budget_cents,
        "requires_ftc_disclosure": requires_ftc,
        "starts_at": _iso(starts_at),
        "ends_at": _iso(ends_at),
        "status": "DRAFT",
        "committed_cents": 0,
        "actual_spend_cents": 0,
    })
    db.campaigns[rec["id"]] = rec
    return success(S.campaign_view(rec), status=201)


def _iso(dt):
    from clock import format_iso
    return format_iso(dt)


@bp.route("/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer", "Creator"})
    c = svc.get_campaign(campaign_id)
    derive.recompute_campaign_committed(c)
    return success(S.campaign_view(c), status=200)


@bp.route("/campaigns", methods=["GET"])
def list_campaigns():
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer", "Creator"})
    status = request.args.get("status")
    brand_id = request.args.get("brand_id")
    rows = list(db.campaigns.values())
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if brand_id is not None:
        rows = [c for c in rows if c["brand_id"] == brand_id]
    for c in rows:
        derive.recompute_campaign_committed(c)
    page, meta = paginate(rows)
    return success([S.campaign_view(c) for c in page], status=200, pagination=meta)


@bp.route("/campaigns/<campaign_id>/deliverables", methods=["POST"])
def add_deliverable(campaign_id):
    user_id, role = get_auth()
    require_role(role, {"Brand"})
    c = svc.get_campaign(campaign_id)
    if c["brand_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting brand does not own this campaign")
    body = get_body()
    content_type = _req_enum(body, "content_type", CONTENT_TYPES)
    quantity = req_int(body, "quantity", minimum=1)
    due_at = req_datetime(body, "due_at")
    base_rate_cents = req_int(body, "base_rate_cents", minimum=0)

    # only while DRAFT (PRD 3.3)
    if c["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Deliverables can only be added to a DRAFT campaign")

    rec = base_fields()
    rec.update({
        "campaign_id": campaign_id,
        "content_type": content_type,
        "quantity": quantity,
        "due_at": _iso(due_at),
        "base_rate_cents": base_rate_cents,
    })
    db.deliverables[rec["id"]] = rec
    return success(S.deliverable_view(rec), status=201)


def _req_enum(body, name, allowed):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


@bp.route("/campaigns/<campaign_id>/deliverables", methods=["GET"])
def list_deliverables(campaign_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer", "Creator"})
    svc.get_campaign(campaign_id)
    rows = [d for d in db.deliverables.values() if d["campaign_id"] == campaign_id]
    page, meta = paginate(rows)
    return success([S.deliverable_view(d) for d in page], status=200, pagination=meta)


def _check_campaign_version(campaign, body):
    expected = body.get("expected_campaign_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_campaign_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_campaign_version must be an integer")
    return expected


@bp.route("/campaigns/<campaign_id>/open", methods=["POST"])
def open_campaign(campaign_id):
    user_id, role = get_auth()
    require_role(role, {"Brand"})
    c = svc.get_campaign(campaign_id)
    if c["brand_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting brand does not own this campaign")
    body = get_body()
    _check_campaign_version(c, body)

    # state legality: only DRAFT -> OPEN
    if c["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT campaign can be opened")

    # preconditions (PRD 3.3): >= 1 deliverable; starts < ends; window spacing
    deliverables = [d for d in db.deliverables.values() if d["campaign_id"] == campaign_id]
    if len(deliverables) < 1:
        raise err("ERR_INVALID_STATE", "Campaign must have at least one deliverable to open")
    starts = parse_iso(c["starts_at"])
    ends = parse_iso(c["ends_at"])
    if not (starts < ends):
        raise err("ERR_VALIDATION", "Campaign window invalid: starts_at must be before ends_at")

    # window-spacing rule (buffer-expanded overlap, adjacency rejected)
    buffer = timedelta(days=calc.CAMPAIGN_BUFFER_DAYS)
    for other in db.campaigns.values():
        if other["id"] == campaign_id:
            continue
        if other["brand_id"] != c["brand_id"]:
            continue
        if other["status"] == "CANCELLED":
            continue
        o_start = parse_iso(other["starts_at"]) - buffer
        o_end = parse_iso(other["ends_at"]) + buffer
        # intersection test on half-open intervals: a_start < b_end AND b_start < a_end
        if starts < o_end and o_start < ends:
            raise err("ERR_CAMPAIGN_WINDOW_CONFLICT",
                      "Campaign window conflicts with another campaign of the same brand")

    c["status"] = "OPEN"
    bump(c)
    return success(S.campaign_view(c), status=200)


@bp.route("/campaigns/<campaign_id>/close", methods=["POST"])
def close_campaign(campaign_id):
    user_id, role = get_auth()
    require_role(role, {"Brand"})
    c = svc.get_campaign(campaign_id)
    if c["brand_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting brand does not own this campaign")
    body = get_body()
    _check_campaign_version(c, body)

    if c["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE campaign can be closed")

    # every contract for this campaign must be SETTLED or CANCELLED
    for ct in db.contracts.values():
        if ct["campaign_id"] == campaign_id and ct["status"] not in {"SETTLED", "CANCELLED"}:
            raise err("ERR_INVALID_STATE", "All contracts must be SETTLED or CANCELLED before close")

    c["status"] = "CLOSED"
    bump(c)
    derive.recompute_campaign_committed(c)
    return success(S.campaign_view(c), status=200)


@bp.route("/campaigns/<campaign_id>/cancel", methods=["POST"])
def cancel_campaign(campaign_id):
    user_id, role = get_auth()
    require_role(role, {"Brand"})
    c = svc.get_campaign(campaign_id)
    if c["brand_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting brand does not own this campaign")
    body = get_body()
    _check_campaign_version(c, body)

    if c["status"] == "DRAFT":
        c["status"] = "CANCELLED"
        bump(c)
        return success(S.campaign_view(c), status=200)

    if c["status"] == "OPEN":
        # no contract in ACTIVE/FULFILLED/SETTLED
        for ct in db.contracts.values():
            if ct["campaign_id"] == campaign_id and ct["status"] in {"ACTIVE", "FULFILLED", "SETTLED"}:
                raise err("ERR_INVALID_STATE", "Cannot cancel: a live contract exists for this campaign")
        c["status"] = "CANCELLED"
        bump(c)
        # cascade: expire every OFFERED/COUNTERED offer
        for o in db.offers.values():
            if o["campaign_id"] == campaign_id and o["status"] in {"OFFERED", "COUNTERED"}:
                o["status"] = "EXPIRED"
                bump(o)
        return success(S.campaign_view(c), status=200)

    raise err("ERR_INVALID_STATE", "Campaign cannot be cancelled from its current state")
