"""Show endpoints: create, get, list, OCC-guarded PATCH, tier transitions."""

from flask import Blueprint, request

import db
from errors import err_not_found, err_invalid, err_stale
from helpers import (
    body_of,
    new_id,
    now_timestamp,
    require_string,
    require_enum,
    require_int,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response, serialize
from services import Changes, recompute_show, cascade_show_suspended

bp = Blueprint("shows", __name__)

CONTENT_CATEGORIES = {"TECHNOLOGY", "BUSINESS", "COMEDY", "NEWS", "HEALTH", "SPORTS"}
ADVERTISER_CATEGORIES = {
    "AUTOMOTIVE",
    "CPG_FOOD",
    "FINTECH",
    "GAMBLING",
    "ALCOHOL",
    "HEALTH_PHARMA",
    "TECHNOLOGY",
}
TIERS = {"CLEAR", "FLAGGED", "SUSPENDED"}

# Allowed (from_state, to_tier) pairs per the Show brand-safety machine.
TIER_TRANSITIONS = {
    ("CLEAR", "FLAGGED"),
    ("CLEAR", "SUSPENDED"),
    ("FLAGGED", "CLEAR"),
    ("FLAGGED", "SUSPENDED"),
    ("SUSPENDED", "FLAGGED"),
}


def get_show_or_404(show_id):
    show = db.shows.get(show_id)
    if show is None:
        raise err_not_found(f"Show '{show_id}' not found")
    return show


def _validate_blocked_categories(value):
    if not isinstance(value, list):
        raise err_invalid("Field 'blocked_advertiser_categories' must be an array")
    for item in value:
        if not isinstance(item, str) or item not in ADVERTISER_CATEGORIES:
            raise err_invalid(
                "Field 'blocked_advertiser_categories' entries must be advertiser categories"
            )
    return value


@bp.route("/adnet/shows", methods=["POST"])
def create_show():
    require_roles({"AdOps"})
    body = body_of(request)
    title = require_string(body, "title")
    content_category = require_enum(body, "content_category", CONTENT_CATEGORIES)
    avg_downloads_30d = require_int(body, "avg_downloads_30d", minimum=0)
    blocked = body.get("blocked_advertiser_categories")
    if blocked is None:
        blocked = []
    else:
        blocked = _validate_blocked_categories(blocked)

    ts = now_timestamp()
    show = {
        "id": new_id(),
        "title": title,
        "content_category": content_category,
        "avg_downloads_30d": avg_downloads_30d,
        "blocked_advertiser_categories": blocked,
        "brand_safety_tier": "CLEAR",
        "forecast_impressions": 0,
        "reserved_impressions": 0,
        "available_impressions": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.shows[show["id"]] = show
    ch = Changes()
    recompute_show(show, ch)  # no episodes yet -> stays 0
    ch.commit()
    return success_object(serialize(show), 201)


@bp.route("/adnet/shows/<show_id>", methods=["GET"])
def get_show(show_id):
    require_roles(ALL_ROLES)
    return success_object(serialize(get_show_or_404(show_id)))


@bp.route("/adnet/shows", methods=["GET"])
def list_shows():
    require_roles(ALL_ROLES)
    items = list(db.shows.values())
    content_category = request.args.get("content_category")
    tier = request.args.get("brand_safety_tier")
    if content_category is not None:
        items = [s for s in items if s["content_category"] == content_category]
    if tier is not None:
        items = [s for s in items if s["brand_safety_tier"] == tier]
    return list_response(items, request.args)


@bp.route("/adnet/shows/<show_id>", methods=["PATCH"])
def patch_show(show_id):
    require_roles({"AdOps"})
    show = get_show_or_404(show_id)
    body = body_of(request)

    # OCC (priority 5): expected_show_version must match the stored version.
    expected = body.get("expected_show_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != show["version"]:
            raise err_stale("expected_show_version does not match the stored version")

    # Field shape (catch-all): OCC field required; editable fields validated.
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid("Field 'expected_show_version' is required and must be an integer")

    changes = {}
    if "avg_downloads_30d" in body and body["avg_downloads_30d"] is not None:
        value = body["avg_downloads_30d"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise err_invalid("Field 'avg_downloads_30d' must be an integer >= 0")
        changes["avg_downloads_30d"] = value
    if "blocked_advertiser_categories" in body and body["blocked_advertiser_categories"] is not None:
        changes["blocked_advertiser_categories"] = _validate_blocked_categories(
            body["blocked_advertiser_categories"]
        )
    # System/computed fields are not client-editable.
    for locked in (
        "brand_safety_tier",
        "forecast_impressions",
        "reserved_impressions",
        "available_impressions",
        "status",
        "id",
    ):
        if locked in body and body[locked] != show.get(locked):
            raise err_invalid(f"Field '{locked}' is not editable")

    ch = Changes()
    ch.update(show, **changes)
    recompute_show(show, ch)
    ch.commit()
    return success_object(serialize(show))


@bp.route("/adnet/shows/<show_id>/transition", methods=["POST"])
def transition_show(show_id):
    require_roles({"AdOps"})
    show = get_show_or_404(show_id)
    body = body_of(request)
    to_tier = body.get("to_tier")
    if not isinstance(to_tier, str) or to_tier not in TIERS:
        raise err_invalid("Field 'to_tier' must be one of CLEAR, FLAGGED, SUSPENDED")
    if (show["brand_safety_tier"], to_tier) not in TIER_TRANSITIONS:
        raise err_invalid(
            f"Brand-safety transition {show['brand_safety_tier']} -> {to_tier} is not permitted"
        )

    ch = Changes()
    ch.update(show, brand_safety_tier=to_tier)
    recompute_show(show, ch)
    if to_tier == "SUSPENDED":
        cascade_show_suspended(show, ch)
        recompute_show(show, ch)
    ch.commit()
    return success_object(serialize(show))
