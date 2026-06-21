"""Post endpoints + per-creation billing + content-access gate (PRD §3.6, §3.8)."""
from flask import Blueprint, request

import errors
import response
from db import db
from middleware import require_auth, require_role
from services import serialize
from services.common import (init_common, init_audit, touch, get_body,
                             require_string, parse_pagination, paginate)
from services.lookups import (get_creator, get_patron, get_post,
                              require_creator_owner, require_patron_owner)
from services import calc
from services.ledger import create_charge

bp = Blueprint("posts", __name__)


@bp.post("/posts")
def create_post():
    ctx = require_auth()
    require_role(ctx, {"Creator"})
    body = get_body()

    creator_id = body.get("creator_id")
    if creator_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: creator_id")
    creator = get_creator(creator_id)
    require_creator_owner(ctx, creator_id)

    title = require_string(body, "title")
    body_text = require_string(body, "body")

    min_tier_rank = body.get("min_tier_rank", 0)
    if min_tier_rank is None:
        min_tier_rank = 0
    if isinstance(min_tier_rank, bool) or not isinstance(min_tier_rank, int) or min_tier_rank < 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "min_tier_rank must be an integer >= 0")

    is_paid_creation = body.get("is_paid_creation", False)
    if is_paid_creation is None:
        is_paid_creation = False
    if not isinstance(is_paid_creation, bool):
        errors.fail(errors.ERR_INVALID_REQUEST, "is_paid_creation must be a boolean")

    rec = init_common({
        "creator_id": creator_id,
        "title": title,
        "body": body_text,
        "min_tier_rank": min_tier_rank,
        "is_paid_creation": is_paid_creation,
        "status": "DRAFT",
    })
    db.posts[rec["id"]] = rec
    return response.success(serialize.post(rec), status=201)


@bp.get("/posts")
def list_posts():
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    limit, offset = parse_pagination()
    items = list(db.posts.values())
    creator_id = request.args.get("creator_id")
    status = request.args.get("status")
    if creator_id is not None:
        items = [p for p in items if p["creator_id"] == creator_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return response.list_success([serialize.post(r) for r in page], limit, offset, total)


@bp.get("/posts/<post_id>")
def get_one_post(post_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    rec = get_post(post_id)
    return response.success(serialize.post(rec))


@bp.post("/posts/<post_id>/publish")
def publish_post(post_id):
    ctx = require_auth()
    require_role(ctx, {"Creator"})
    post = get_post(post_id)
    require_creator_owner(ctx, post["creator_id"])

    # A post is born DRAFT and is moved to PUBLISHED by its creator (PRD §3.6).
    # No error code is defined for re-publishing; the catalog has no such id.
    creator = get_creator(post["creator_id"])

    # Paid-creation publish is only meaningful for PER_CREATION creators
    # (ERR_BILLING_MODEL_MISMATCH, PRD §3.6). Checked before transition.
    if post["is_paid_creation"] and creator["billing_mode"] != "PER_CREATION":
        errors.fail(errors.ERR_BILLING_MODEL_MISMATCH,
                    "Paid-creation publish requires a PER_CREATION creator")

    post["status"] = "PUBLISHED"
    touch(post)

    # Bill eligible pledges (calc per_creation_charge, PRD §3.6).
    if post["is_paid_creation"] and creator["billing_mode"] == "PER_CREATION":
        _bill_per_creation(post, creator)

    return response.success(serialize.post(post))


def _bill_per_creation(post, creator):
    """For each eligible ACTIVE PER_CREATION pledge, create a PER_CREATION
    charge respecting the per-cycle cap (PRD §3.6)."""
    from db import db as _db
    eligible = []
    for pledge in _db.pledges.values():
        if pledge["creator_id"] != creator["id"]:
            continue
        if pledge["lifecycle_status"] != "ACTIVE":
            continue
        if pledge["billing_model"] != "PER_CREATION":
            continue
        tier = _db.tiers.get(pledge["tier_id"])
        if tier is None:
            continue
        # Qualifying tier: rank meets the post's min_tier_rank (PRD §3.6/§3.8).
        if tier["rank"] < post["min_tier_rank"]:
            continue
        eligible.append((pledge, tier))

    # Deterministic order by pledge creation order.
    eligible.sort(key=lambda pt: pt[0]["_created_seq"])
    for pledge, tier in eligible:
        amount = calc.per_creation_charge(
            tier["per_creation_fee_cents"],
            tier["per_creation_monthly_cap_cents"],
            pledge.get("current_cycle_charged_cents", 0),
        )
        if amount == 0:
            # Cap exhausted: no charge row created this cycle (normal outcome).
            continue
        patron = _db.patrons.get(pledge["patron_id"])
        anchor = _parse_iso(pledge["cycle_anchor_date"]) or _db.now()
        create_charge(pledge, creator, patron, "PER_CREATION", amount, anchor)
        # Publishing a paid creation triggers billing (PRD §3.6); the per-creation
        # charge raises the pledge's running total billed this cycle
        # (current_cycle_charged_cents, PRD §3.2), which the cap formula in §3.6
        # reads on the next eligible publish so the monthly cap is enforced
        # cumulatively across publishes. That derived-field adjustment is itself a
        # mutation (PRD §2.4).
        pledge["current_cycle_charged_cents"] = \
            pledge.get("current_cycle_charged_cents", 0) + amount
        touch(pledge)


def _parse_iso(s):
    from datetime import datetime, timezone
    if s is None:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@bp.post("/posts/<post_id>/access")
def request_access(post_id):
    ctx = require_auth()
    require_role(ctx, {"Patron"})
    post = get_post(post_id)
    body = get_body()

    patron_id = body.get("patron_id")
    if patron_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: patron_id")
    patron = get_patron(patron_id)
    require_patron_owner(ctx, patron_id)

    # The post must be PUBLISHED (PRD §3.8).
    if post["status"] != "PUBLISHED":
        errors.fail(errors.ERR_POST_NOT_FOUND, "Post is not PUBLISHED")

    min_rank = post["min_tier_rank"]

    # Public post (min_tier_rank 0): admit any patron; record the granting
    # pledge if one exists, else snapshot rank 0.
    granting_pledge = None
    granted_rank = 0
    best_rank = -1
    for pledge in db.pledges.values():
        if pledge["patron_id"] != patron_id:
            continue
        if pledge["creator_id"] != post["creator_id"]:
            continue
        if pledge["lifecycle_status"] != "ACTIVE":
            continue
        tier = db.tiers.get(pledge["tier_id"])
        if tier is None:
            continue
        if tier["rank"] > best_rank:
            best_rank = tier["rank"]
            granting_pledge = pledge
            granted_rank = tier["rank"]

    if min_rank == 0:
        # Public post: anyone may view (PRD §3.8). granted_tier_rank snapshots
        # the patron's tier rank if they have an ACTIVE pledge, else 0.
        pass
    else:
        # Gated: requires an ACTIVE pledge on a tier with rank >= min_tier_rank.
        if granting_pledge is None or best_rank < min_rank:
            errors.fail(errors.ERR_TIER_TOO_LOW,
                        "Patron's active tier rank is below the post's min_tier_rank")

    rec = init_audit({
        "post_id": post_id,
        "patron_id": patron_id,
        "pledge_id": granting_pledge["id"] if granting_pledge else None,
        "granted_tier_rank": granted_rank,
    })
    db.post_accesses[rec["id"]] = rec
    return response.success(serialize.post_access(rec), status=201)


@bp.get("/post-accesses")
def list_post_accesses():
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    limit, offset = parse_pagination()
    items = list(db.post_accesses.values())
    for key in ("post_id", "patron_id", "pledge_id"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    page, total = paginate(items, limit, offset)
    return response.list_success([serialize.post_access(r) for r in page], limit, offset, total)


@bp.get("/post-accesses/<access_id>")
def get_one_post_access(access_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    from services.lookups import get_post_access
    rec = get_post_access(access_id)
    return response.success(serialize.post_access(rec))
