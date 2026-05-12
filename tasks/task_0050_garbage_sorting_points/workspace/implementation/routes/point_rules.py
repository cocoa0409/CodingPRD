"""PointRule endpoints: create, activate, retire, effectiveness, list."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, g

from db import db
from errors import (
    ERR_INVALID_STATE,
    ERR_RULE_ALREADY_ACTIVE,
    ERR_RULE_BACKDATING,
    ERR_VALIDATION,
    raise_api_error,
)
from middleware import require_roles
from response import list_response, success_response
from services.calculations import compute_rule_effectiveness
from services.common import (
    check_version,
    get_json_body,
    iso_z,
    optional_int,
    optional_number,
    paginate,
    parse_iso8601_utc,
    parse_pagination,
    require_enum,
    require_number,
)
from services.lookup import get_community, get_point_rule
from services.ledger import append_audit_log

bp = Blueprint("point_rules", __name__)

CATEGORIES = {"RECYCLABLE", "HAZARDOUS", "KITCHEN", "OTHER"}


@bp.post("/communities/<community_id>/point-rules")
@require_roles("CommunityAdmin")
def create_rule(community_id: str):
    get_community(community_id)
    body = get_json_body()
    category = require_enum(body, "category", CATEGORIES)
    base_rate_per_kg = require_number(body, "base_rate_per_kg", minimum=0.0, maximum=1000.0)
    bonus_consecutive_threshold_days = optional_int(
        body, "bonus_consecutive_threshold_days", minimum=1, maximum=365,
    )
    if bonus_consecutive_threshold_days is None:
        bonus_consecutive_threshold_days = 7
    bonus_consecutive_multiplier = optional_number(
        body, "bonus_consecutive_multiplier", minimum=1.0, maximum=5.0,
    )
    if bonus_consecutive_multiplier is None:
        bonus_consecutive_multiplier = 1.20
    peak_period_start_hour = optional_int(
        body, "peak_period_start_hour", minimum=0, maximum=23,
    )
    if peak_period_start_hour is None:
        peak_period_start_hour = 7
    peak_period_end_hour = optional_int(
        body, "peak_period_end_hour", minimum=0, maximum=23,
    )
    if peak_period_end_hour is None:
        peak_period_end_hour = 9
    peak_period_bonus_flat = optional_int(body, "peak_period_bonus_flat")
    if peak_period_bonus_flat is None:
        peak_period_bonus_flat = 5
    category_bonus_flat = optional_int(body, "category_bonus_flat")
    if category_bonus_flat is None:
        category_bonus_flat = 0
    daily_cap_points = optional_int(body, "daily_cap_points")
    if daily_cap_points is None:
        daily_cap_points = 200

    # Compute next version number for (community_id, category)
    next_version = 1
    for r in db.point_rules.values():
        if r["community_id"] == community_id and r["category"] == category:
            if r["version"] >= next_version:
                next_version = r["version"] + 1

    from db import gen_id

    obj = {
        "id": gen_id(),
        "community_id": community_id,
        "category": category,
        "version": next_version,
        "base_rate_per_kg": float(base_rate_per_kg),
        "bonus_consecutive_threshold_days": bonus_consecutive_threshold_days,
        "bonus_consecutive_multiplier": float(bonus_consecutive_multiplier),
        "peak_period_start_hour": peak_period_start_hour,
        "peak_period_end_hour": peak_period_end_hour,
        "peak_period_bonus_flat": peak_period_bonus_flat,
        "category_bonus_flat": category_bonus_flat,
        "daily_cap_points": daily_cap_points,
        "status": "DRAFT",
        "activated_at": None,
        "retired_at": None,
    }
    obj["created_at"] = db.now_iso()
    # PointRule has no updated_at and no OCC version (its `version` field is
    # the domain rule-generation number per (community, category)).
    db.point_rules[obj["id"]] = obj
    return jsonify(success_response(obj)), 201


@bp.post("/communities/<community_id>/point-rules/<rule_id>/activate")
@require_roles("CommunityAdmin")
def activate_rule(community_id: str, rule_id: str):
    rule = get_point_rule(community_id, rule_id)
    body = get_json_body()

    if rule["status"] != "DRAFT":
        raise_api_error(ERR_INVALID_STATE, "Rule must be DRAFT to activate.")

    if "activated_at" not in body or body["activated_at"] is None:
        raise_api_error(ERR_VALIDATION, "Field 'activated_at' is required.")
    activated_at = parse_iso8601_utc(body["activated_at"])

    # Priority §1.4 #15: no other ACTIVE rule with same (community, category)
    for r in db.point_rules.values():
        if (
            r["community_id"] == community_id
            and r["category"] == rule["category"]
            and r["status"] == "ACTIVE"
            and r["id"] != rule["id"]
        ):
            raise_api_error(
                ERR_RULE_ALREADY_ACTIVE,
                "Another rule is already ACTIVE for this category.",
            )

    # Priority §1.4 #16: activated_at >= now()
    if activated_at < db.now():
        raise_api_error(ERR_RULE_BACKDATING, "activated_at must not be earlier than now().")

    rule["status"] = "ACTIVE"
    rule["activated_at"] = iso_z(activated_at)

    append_audit_log(
        actor_role=g.user_role,
        actor_id=g.user_id,
        action="RULE_PUBLISHED",
        subject_kind="POINT_RULE",
        subject_id=rule["id"],
        before={"status": "DRAFT"},
        after={"status": "ACTIVE", "activated_at": rule["activated_at"]},
        reason=None,
    )
    return jsonify(success_response(rule)), 200


@bp.post("/communities/<community_id>/point-rules/<rule_id>/retire")
@require_roles("CommunityAdmin")
def retire_rule(community_id: str, rule_id: str):
    rule = get_point_rule(community_id, rule_id)
    if rule["status"] != "ACTIVE":
        raise_api_error(ERR_INVALID_STATE, "Rule must be ACTIVE to retire.")
    rule["status"] = "RETIRED"
    rule["retired_at"] = db.now_iso()
    return jsonify(success_response(rule)), 200


@bp.get("/communities/<community_id>/point-rules/<rule_id>/effectiveness")
@require_roles("CommunityAdmin")
def rule_effectiveness(community_id: str, rule_id: str):
    rule = get_point_rule(community_id, rule_id)
    return jsonify(success_response(compute_rule_effectiveness(rule))), 200


@bp.get("/communities/<community_id>/point-rules")
@require_roles("CommunityAdmin")
def list_rules(community_id: str):
    get_community(community_id)
    limit, offset = parse_pagination()
    category = request.args.get("category")
    status = request.args.get("status")
    items = [
        r
        for r in db.point_rules.values()
        if r["community_id"] == community_id
        and (category is None or r["category"] == category)
        and (status is None or r["status"] == status)
    ]
    items.sort(key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return jsonify(list_response(page, limit, offset, total)), 200
