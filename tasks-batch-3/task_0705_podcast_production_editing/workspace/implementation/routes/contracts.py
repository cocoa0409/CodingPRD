"""EngagementContract endpoints (PRD §3.1, §2.11)."""
from flask import Blueprint, request

import errors
import middleware as mw
from constants import CONTRACT_TIERS, ENGAGEMENT_TYPES, LOYALTY_DISCOUNT_MAX, LOYALTY_DISCOUNT_MIN
from db import db
from response import array_response, object_response
from routes.common import assert_show_owner, get_or_404
from serialize import serialize, serialize_list
from services import show_state

bp = Blueprint("contracts", __name__)


@bp.post("/contracts")
def create_contract():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin"})
    body = mw.get_json_body()
    # existence of show first (left-to-right)
    show_id = mw.require_string(body, "show_id")
    get_or_404(db.shows, show_id)
    tier = mw.require_enum(body, "tier", CONTRACT_TIERS)
    engagement_type = mw.require_enum(body, "engagement_type", ENGAGEMENT_TYPES)
    monthly_included = mw.optional_int(body, "monthly_included_episodes", 0)
    loyalty = mw.optional_number(body, "loyalty_discount_pct", 0.0)
    # constraints (PRD §3.1)
    if monthly_included < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "monthly_included_episodes must be >= 0")
    if engagement_type == "PER_EPISODE" and monthly_included != 0:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "monthly_included_episodes must be 0 for PER_EPISODE")
    if loyalty < LOYALTY_DISCOUNT_MIN or loyalty > LOYALTY_DISCOUNT_MAX:
        raise errors.err(errors.ERR_INVALID_REQUEST, "loyalty_discount_pct out of range")
    rec = db.contracts.create({
        "show_id": show_id,
        "tier": tier,
        "engagement_type": engagement_type,
        "monthly_included_episodes": monthly_included,
        "loyalty_discount_pct": loyalty,
        "status": "DRAFT",
        "activated_at": None,
    })
    return object_response(serialize(rec), status=201)


@bp.get("/contracts")
def list_contracts():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner"})
    limit, offset = mw.parse_pagination()
    records = db.contracts.all()
    show_id = request.args.get("show_id")
    status = request.args.get("status")
    if show_id is not None:
        records = [r for r in records if r["show_id"] == show_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if auth.role == "ShowOwner":
        records = [r for r in records if r["show_id"] == auth.user_id]
    page, meta = mw.paginate(records, limit, offset)
    return array_response(serialize_list(page), meta)


@bp.get("/contracts/<rid>")
def get_contract(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner"})
    rec = get_or_404(db.contracts, rid)
    assert_show_owner(auth, rec["show_id"])
    return object_response(serialize(rec))


@bp.post("/contracts/<rid>/activate")
def activate_contract(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin"})
    rec = get_or_404(db.contracts, rid)
    if rec["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Contract is not DRAFT")
    if rec["engagement_type"] == "RETAINER" and rec["monthly_included_episodes"] < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "RETAINER activation requires monthly_included_episodes >= 1")
    from clock import clock
    rec["status"] = "ACTIVE"
    rec["activated_at"] = clock.now()
    db.contracts.touch(rec)
    show = db.shows.get(rec["show_id"])
    if show is not None:
        show_state.recompute_posture(show)
    return object_response(serialize(rec))


@bp.post("/contracts/<rid>/terminate")
def terminate_contract(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin"})
    rec = get_or_404(db.contracts, rid)
    body = mw.get_json_body()
    # state legality before OCC (PRD §2.8)
    if rec["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Contract is not ACTIVE")
    expected = body.get("expected_engagementcontract_version")
    if expected is None:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "Missing required field: expected_engagementcontract_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "expected_engagementcontract_version must be an integer")
    if expected != rec["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Contract version is stale")
    rec["status"] = "TERMINATED"
    db.contracts.touch(rec)
    show = db.shows.get(rec["show_id"])
    if show is not None:
        show_state.recompute_posture(show)
    return object_response(serialize(rec))


@bp.post("/contracts/<rid>/expire")
def expire_contract(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin"})
    rec = get_or_404(db.contracts, rid)
    if rec["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Contract is not ACTIVE")
    rec["status"] = "EXPIRED"
    db.contracts.touch(rec)
    show = db.shows.get(rec["show_id"])
    if show is not None:
        show_state.recompute_posture(show)
    return object_response(serialize(rec))
