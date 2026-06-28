"""Tier endpoints + state machine (PRD §3.1, SCAFFOLD §1.2 Tier)."""
from flask import Blueprint, request

import errors
import response
from db import db
from middleware import require_auth, require_role
from services import serialize
from services.common import (init_common, touch, get_body, require_string,
                             require_enum, require_int, parse_pagination, paginate)
from services.lookups import get_creator, get_tier, require_creator_owner

bp = Blueprint("tiers", __name__)

BILLING_MODELS = {"MONTHLY", "PER_CREATION"}


@bp.post("/tiers")
def create_tier():
    ctx = require_auth()
    require_role(ctx, {"Creator"})
    body = get_body()
    # body FK existence (priority 5) before request well-formedness on optionals.
    creator_id = body.get("creator_id")
    if creator_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: creator_id")
    creator = get_creator(creator_id)
    # ownership: a Creator may only create tiers for itself (PRD §2.1).
    require_creator_owner(ctx, creator_id)

    name = require_string(body, "name")
    billing_model = require_enum(body, "billing_model", BILLING_MODELS)
    rank = require_int(body, "rank", minimum=1)

    monthly_fee_cents = body.get("monthly_fee_cents")
    per_creation_fee_cents = body.get("per_creation_fee_cents")
    per_creation_monthly_cap_cents = body.get("per_creation_monthly_cap_cents")

    # Range constraints on present pricing fields (PRD §3.1).
    if monthly_fee_cents is not None:
        _int_field(monthly_fee_cents, "monthly_fee_cents")
        if monthly_fee_cents < 100:
            errors.fail(errors.ERR_INVALID_REQUEST, "monthly_fee_cents must be >= 100")
    if per_creation_fee_cents is not None:
        _int_field(per_creation_fee_cents, "per_creation_fee_cents")
        if per_creation_fee_cents < 50:
            errors.fail(errors.ERR_INVALID_REQUEST, "per_creation_fee_cents must be >= 50")
    if per_creation_monthly_cap_cents is not None:
        _int_field(per_creation_monthly_cap_cents, "per_creation_monthly_cap_cents")
        if per_creation_fee_cents is not None and \
                per_creation_monthly_cap_cents < per_creation_fee_cents:
            errors.fail(errors.ERR_INVALID_REQUEST,
                        "per_creation_monthly_cap_cents must be >= per_creation_fee_cents")

    benefit_labels = body.get("benefit_labels", [])
    if benefit_labels is None:
        benefit_labels = []
    if not isinstance(benefit_labels, list):
        errors.fail(errors.ERR_INVALID_REQUEST, "benefit_labels must be an array")

    rec = init_common({
        "creator_id": creator_id,
        "name": name,
        "monthly_fee_cents": monthly_fee_cents,
        "per_creation_fee_cents": per_creation_fee_cents,
        "per_creation_monthly_cap_cents": per_creation_monthly_cap_cents,
        "billing_model": billing_model,
        "rank": rank,
        "benefit_labels": benefit_labels,
        "active_pledge_count": 0,
        "status": "DRAFT",
    })
    db.tiers[rec["id"]] = rec
    return response.success(serialize.tier(rec), status=201)


def _int_field(val, name):
    if isinstance(val, bool) or not isinstance(val, int):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % name)


@bp.get("/tiers")
def list_tiers():
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    limit, offset = parse_pagination()
    creator_id = request.args.get("creator_id")
    status = request.args.get("status")
    items = list(db.tiers.values())
    if creator_id is not None:
        items = [t for t in items if t["creator_id"] == creator_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, total = paginate(items, limit, offset)
    return response.list_success([serialize.tier(r) for r in page], limit, offset, total)


@bp.get("/tiers/<tier_id>")
def get_one_tier(tier_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    rec = get_tier(tier_id)
    return response.success(serialize.tier(rec))


@bp.post("/tiers/<tier_id>/publish")
def publish_tier(tier_id):
    ctx = require_auth()
    require_role(ctx, {"Creator"})
    tier = get_tier(tier_id)
    require_creator_owner(ctx, tier["creator_id"])

    # State: only a DRAFT tier can be published (PRD §3.1).
    if tier["status"] != "DRAFT":
        errors.fail(errors.ERR_TIER_NOT_PUBLISHED, "Tier is not DRAFT")

    # Pricing fields appropriate to the billing model must be present
    # (ERR_TIER_FIELDS_INCOMPLETE, PRD §3.1).
    if tier["billing_model"] == "MONTHLY":
        if tier.get("monthly_fee_cents") is None:
            errors.fail(errors.ERR_TIER_FIELDS_INCOMPLETE,
                        "MONTHLY tier requires monthly_fee_cents")
    else:  # PER_CREATION
        if tier.get("per_creation_fee_cents") is None or \
                tier.get("per_creation_monthly_cap_cents") is None:
            errors.fail(errors.ERR_TIER_FIELDS_INCOMPLETE,
                        "PER_CREATION tier requires per_creation_fee_cents and "
                        "per_creation_monthly_cap_cents")

    # Rank uniqueness among non-RETIRED tiers of the creator (ERR_TIER_RANK_TAKEN).
    for other in db.tiers.values():
        if other["id"] == tier["id"]:
            continue
        if other["creator_id"] != tier["creator_id"]:
            continue
        if other["status"] == "RETIRED":
            continue
        if other["rank"] == tier["rank"]:
            errors.fail(errors.ERR_TIER_RANK_TAKEN,
                        "Another non-RETIRED tier already holds this rank")

    tier["status"] = "PUBLISHED"
    touch(tier)
    return response.success(serialize.tier(tier))


@bp.post("/tiers/<tier_id>/retire")
def retire_tier(tier_id):
    ctx = require_auth()
    require_role(ctx, {"Creator"})
    tier = get_tier(tier_id)
    require_creator_owner(ctx, tier["creator_id"])

    # Only a PUBLISHED tier can be retired (PRD §3.1).
    if tier["status"] != "PUBLISHED":
        errors.fail(errors.ERR_TIER_NOT_PUBLISHED, "Tier is not PUBLISHED")

    # No ACTIVE/PAUSED member may remain (ERR_TIER_HAS_MEMBERS).
    for p in db.pledges.values():
        if p["tier_id"] == tier["id"] and p["lifecycle_status"] in ("ACTIVE", "PAUSED"):
            errors.fail(errors.ERR_TIER_HAS_MEMBERS,
                        "Cannot retire a tier with ACTIVE/PAUSED members")

    tier["status"] = "RETIRED"
    touch(tier)
    return response.success(serialize.tier(tier))
