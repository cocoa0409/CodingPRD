"""Disposal endpoints: submit, correct, void, list, read."""

from __future__ import annotations

import datetime as dt

from flask import Blueprint, g, jsonify, request

from db import db
from errors import (
    ERR_DISPOSAL_TIME_INVALID,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NO_ACTIVE_RULE,
    ERR_RANKING_PERIOD_CLOSED,
    ERR_RESIDENT_INACTIVE,
    ERR_VALIDATION,
    ERR_WEIGHT_VOLUME_EXCLUSIVITY,
    raise_api_error,
)
from middleware import require_roles
from response import list_response, success_response
from services.calculations import (
    compute_consecutive_disposal_days,
    compute_disposal_points,
    compute_effective_weight_kg,
)
from services.common import (
    check_version,
    get_json_body,
    iso_z,
    optional_enum,
    optional_number,
    optional_str,
    paginate,
    parse_iso8601_utc,
    parse_pagination,
    require_datetime,
    require_enum,
    require_number,
    require_str,
)
from services.ledger import append_audit_log, append_transaction
from services.lookup import (
    get_community,
    get_disposal,
    get_household,
    get_resident_by_id,
)
from services.ranking_invalidate import invalidate_periods_overlapping

bp = Blueprint("disposals", __name__)

CATEGORIES = {"RECYCLABLE", "HAZARDOUS", "KITCHEN", "OTHER"}
SCORING_METHODS = {"MANUAL", "AI", "SCALE"}


def _find_active_rule(community_id: str, category: str, at_utc: dt.datetime):
    for r in db.point_rules.values():
        if r["community_id"] != community_id:
            continue
        if r["category"] != category:
            continue
        if r["status"] != "ACTIVE":
            continue
        activated_at = parse_iso8601_utc(r["activated_at"]) if r.get("activated_at") else None
        if activated_at is None or activated_at > at_utc:
            continue
        retired_at = parse_iso8601_utc(r["retired_at"]) if r.get("retired_at") else None
        if retired_at is not None and retired_at <= at_utc:
            continue
        return r
    return None


def _find_rule_by_id_for_recompute(rule_id: str):
    return db.point_rules.get(rule_id)


def _ranking_period_blocks(community_id: str, at_utc: dt.datetime) -> bool:
    for p in db.ranking_periods.values():
        if p["community_id"] != community_id:
            continue
        if p["status"] not in ("CLOSED", "PUBLISHED"):
            continue
        ws = parse_iso8601_utc(p["window_start"])
        we = parse_iso8601_utc(p["window_end"])
        if ws <= at_utc < we:
            return True
    return False


@bp.post("/communities/<community_id>/households/<household_id>/disposals")
@require_roles("Resident")
def create_disposal(community_id: str, household_id: str):
    household = get_household(community_id, household_id)
    community = db.communities[community_id]
    body = get_json_body()

    # Ownership: resident in body must equal X-User-ID, and that resident must live here
    resident_id = require_str(body, "resident_id", min_len=1, max_len=200)
    if resident_id != g.user_id:
        raise_api_error(ERR_FORBIDDEN, "resident_id must equal X-User-ID.")
    resident = get_resident_by_id(g.user_id)
    if resident is None or resident.get("household_id") != household_id:
        raise_api_error(ERR_FORBIDDEN, "Resident does not belong to this household.")

    # Inputs we always need for body-shape validation
    location_code = require_str(body, "location_code", min_len=1, max_len=32)
    declared_category = require_enum(body, "declared_category", CATEGORIES)
    actual_category = require_enum(body, "actual_category", CATEGORIES)
    scoring_method = require_enum(body, "scoring_method", SCORING_METHODS)
    accuracy_score = require_number(body, "accuracy_score", minimum=0.0, maximum=1.0)
    evidence_uri = require_str(body, "evidence_uri", min_len=1, max_len=500)
    disposal_time = require_datetime(body, "disposal_time")

    # weight_kg / volume_liters validation happens after structural checks,
    # but exclusivity is a business-constraint priority (#10) coming after
    # resident-active and active-rule checks. We parse them now (with type
    # validation) and defer the exclusivity check below.
    weight_kg = optional_number(body, "weight_kg", minimum=0.0, maximum=500.0)
    volume_liters = optional_number(body, "volume_liters", minimum=0.0, maximum=5000.0)

    # Priority 8 — ERR_RESIDENT_INACTIVE
    if not (resident["identity_status"] == "VERIFIED" and resident["account_status"] == "ACTIVE"):
        raise_api_error(ERR_RESIDENT_INACTIVE, "Resident must be VERIFIED+ACTIVE.")

    # Priority 9 — ERR_NO_ACTIVE_RULE
    rule = _find_active_rule(community_id, actual_category, disposal_time)
    if rule is None:
        raise_api_error(ERR_NO_ACTIVE_RULE, "No ACTIVE PointRule for this category at disposal_time.")

    # Priority 10 — ERR_WEIGHT_VOLUME_EXCLUSIVITY
    have_w = weight_kg is not None
    have_v = volume_liters is not None
    if have_w == have_v:
        raise_api_error(
            ERR_WEIGHT_VOLUME_EXCLUSIVITY,
            "Exactly one of weight_kg, volume_liters must be supplied.",
        )

    # Priority 11 — ERR_DISPOSAL_TIME_INVALID (<= now, >= now - 24h)
    now = db.now()
    if disposal_time > now:
        raise_api_error(ERR_DISPOSAL_TIME_INVALID, "disposal_time is in the future.")
    if disposal_time < now - dt.timedelta(hours=24):
        raise_api_error(ERR_DISPOSAL_TIME_INVALID, "disposal_time is earlier than 24h ago.")

    # Ranking-period close block
    if _ranking_period_blocks(community_id, disposal_time):
        raise_api_error(
            ERR_RANKING_PERIOD_CLOSED,
            "disposal_time falls inside a CLOSED-or-PUBLISHED ranking period.",
        )

    # Compute points
    effective_weight = compute_effective_weight_kg(weight_kg, volume_liters, actual_category)

    award = compute_disposal_points(
        rule=rule,
        scoring_method=scoring_method,
        accuracy_score=accuracy_score,
        effective_weight_kg=effective_weight,
        consecutive_disposal_days=resident["consecutive_disposal_days"],
        disposal_time_utc=disposal_time,
        community_timezone=community["timezone"],
        household_id=household_id,
        exclude_disposal_id=None,
    )

    # Build & persist the Disposal
    obj = {
        "household_id": household_id,
        "resident_id": resident_id,
        "community_id": community_id,
        "disposal_time": iso_z(disposal_time),
        "location_code": location_code,
        "declared_category": declared_category,
        "actual_category": actual_category,
        "scoring_method": scoring_method,
        "accuracy_score": float(accuracy_score),
        "weight_kg": float(weight_kg) if weight_kg is not None else None,
        "volume_liters": float(volume_liters) if volume_liters is not None else None,
        "evidence_uri": evidence_uri,
        "applied_rule_id": rule["id"],
        "awarded_points": int(award["awarded_points"]),
        "cap_overflow_points": int(award["cap_overflow_points"]),
        "status": "COMMITTED",
    }
    db.stamp_create(obj)
    db.disposals[obj["id"]] = obj

    # Update household balance
    household["points_balance"] += award["awarded_points"]
    household["lifetime_points_earned"] += award["awarded_points"]
    db.stamp_update(household)

    # Append PointsTransaction
    append_transaction(
        household,
        kind="DISPOSAL_CREDIT",
        amount=award["awarded_points"],
        related_entity_kind="DISPOSAL",
        related_entity_id=obj["id"],
    )

    # Recompute consecutive_disposal_days on resident
    resident["consecutive_disposal_days"] = compute_consecutive_disposal_days(
        resident_id, community["timezone"], now_utc=db.now(),
    )
    db.stamp_update(resident)

    return jsonify(success_response(obj)), 201


def _recompute_after_correction(disposal: dict, household: dict, community: dict, resident: dict):
    """Recompute award using SAME applied_rule_id but with current actual_category/accuracy_score."""
    rule = _find_rule_by_id_for_recompute(disposal["applied_rule_id"])
    if rule is None:
        raise_api_error(ERR_INVALID_STATE, "Pinned PointRule no longer exists.")
    effective_weight = compute_effective_weight_kg(
        disposal.get("weight_kg"), disposal.get("volume_liters"), disposal["actual_category"],
    )
    disposal_time_utc = parse_iso8601_utc(disposal["disposal_time"])
    award = compute_disposal_points(
        rule=rule,
        scoring_method=disposal["scoring_method"],
        accuracy_score=disposal["accuracy_score"],
        effective_weight_kg=effective_weight,
        consecutive_disposal_days=resident["consecutive_disposal_days"],
        disposal_time_utc=disposal_time_utc,
        community_timezone=community["timezone"],
        household_id=household["id"],
        exclude_disposal_id=disposal["id"],
    )
    return award


@bp.post("/communities/<community_id>/households/<household_id>/disposals/<disposal_id>/correct")
@require_roles("CommunityAdmin")
def correct_disposal(community_id: str, household_id: str, disposal_id: str):
    disposal = get_disposal(community_id, household_id, disposal_id)
    household = db.households[household_id]
    community = db.communities[community_id]
    resident = db.residents.get(disposal["resident_id"])

    body = get_json_body()
    check_version(body, disposal)

    if disposal["status"] != "COMMITTED":
        raise_api_error(ERR_INVALID_STATE, "Disposal must be COMMITTED to be corrected.")

    new_actual_category = optional_enum(body, "actual_category", CATEGORIES)
    new_accuracy_score = optional_number(body, "accuracy_score", minimum=0.0, maximum=1.0)
    reason = require_str(body, "reason", min_len=1, max_len=500)
    if new_actual_category is None and new_accuracy_score is None:
        raise_api_error(ERR_VALIDATION, "Provide actual_category and/or accuracy_score.")

    old_awarded = int(disposal["awarded_points"])

    # Apply overrides to working disposal then recompute
    if new_actual_category is not None:
        disposal["actual_category"] = new_actual_category
    if new_accuracy_score is not None:
        disposal["accuracy_score"] = float(new_accuracy_score)

    award = _recompute_after_correction(disposal, household, community, resident)
    new_awarded = int(award["awarded_points"])

    delta = new_awarded - old_awarded

    # Update household balance
    household["points_balance"] += delta
    household["lifetime_points_earned"] += delta
    db.stamp_update(household)

    # Append MISJUDGMENT_ADJUSTMENT transaction
    append_transaction(
        household,
        kind="MISJUDGMENT_ADJUSTMENT",
        amount=delta,
        related_entity_kind="DISPOSAL",
        related_entity_id=disposal["id"],
    )

    disposal["awarded_points"] = new_awarded
    disposal["cap_overflow_points"] = int(award["cap_overflow_points"])
    disposal["status"] = "CORRECTED"
    db.stamp_update(disposal)

    invalidate_periods_overlapping(
        community_id=community_id,
        affected_time_utc=parse_iso8601_utc(disposal["disposal_time"]),
    )

    append_audit_log(
        actor_role=g.user_role,
        actor_id=g.user_id,
        action="POINTS_ADJUSTMENT",
        subject_kind="DISPOSAL",
        subject_id=disposal["id"],
        before={"awarded_points": old_awarded, "status": "COMMITTED"},
        after={"awarded_points": new_awarded, "status": "CORRECTED"},
        reason=reason,
    )
    return jsonify(success_response(disposal)), 200


@bp.post("/communities/<community_id>/households/<household_id>/disposals/<disposal_id>/void")
@require_roles("CommunityAdmin")
def void_disposal(community_id: str, household_id: str, disposal_id: str):
    disposal = get_disposal(community_id, household_id, disposal_id)
    household = db.households[household_id]
    community = db.communities[community_id]
    resident = db.residents.get(disposal["resident_id"])

    body = get_json_body()
    check_version(body, disposal)

    if disposal["status"] not in ("COMMITTED", "CORRECTED"):
        raise_api_error(ERR_INVALID_STATE, "Disposal must be COMMITTED or CORRECTED to be voided.")

    reason = require_str(body, "reason", min_len=1, max_len=500)

    awarded = int(disposal["awarded_points"])
    household["points_balance"] -= awarded
    household["lifetime_points_earned"] -= awarded
    db.stamp_update(household)

    append_transaction(
        household,
        kind="MISJUDGMENT_ADJUSTMENT",
        amount=-awarded,
        related_entity_kind="DISPOSAL",
        related_entity_id=disposal["id"],
    )

    old_status = disposal["status"]
    disposal["status"] = "VOIDED"
    db.stamp_update(disposal)

    # Recompute consecutive streak (this disposal no longer contributes)
    if resident is not None:
        resident["consecutive_disposal_days"] = compute_consecutive_disposal_days(
            resident["id"], community["timezone"], now_utc=db.now(),
        )
        db.stamp_update(resident)

    invalidate_periods_overlapping(
        community_id=community_id,
        affected_time_utc=parse_iso8601_utc(disposal["disposal_time"]),
    )

    append_audit_log(
        actor_role=g.user_role,
        actor_id=g.user_id,
        action="POINTS_ADJUSTMENT",
        subject_kind="DISPOSAL",
        subject_id=disposal["id"],
        before={"awarded_points": awarded, "status": old_status},
        after={"awarded_points": awarded, "status": "VOIDED"},
        reason=reason,
    )
    return jsonify(success_response(disposal)), 200


@bp.get("/communities/<community_id>/households/<household_id>/disposals")
@require_roles("CommunityAdmin", "Resident")
def list_disposals(community_id: str, household_id: str):
    get_household(community_id, household_id)
    if g.user_role == "Resident":
        me = get_resident_by_id(g.user_id)
        if me is None or me.get("household_id") != household_id:
            raise_api_error(ERR_FORBIDDEN, "Resident does not own this household.")

    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    from_raw = request.args.get("from")
    to_raw = request.args.get("to")
    from_utc = parse_iso8601_utc(from_raw) if from_raw else None
    to_utc = parse_iso8601_utc(to_raw) if to_raw else None

    items = []
    for d in db.disposals.values():
        if d["household_id"] != household_id:
            continue
        if status_filter is not None and d["status"] != status_filter:
            continue
        d_time = parse_iso8601_utc(d["disposal_time"])
        if from_utc is not None and d_time < from_utc:
            continue
        if to_utc is not None and d_time >= to_utc:
            continue
        items.append(d)
    items.sort(key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return jsonify(list_response(page, limit, offset, total)), 200


@bp.get("/communities/<community_id>/households/<household_id>/disposals/<disposal_id>")
@require_roles("CommunityAdmin", "Resident")
def read_disposal(community_id: str, household_id: str, disposal_id: str):
    d = get_disposal(community_id, household_id, disposal_id)
    if g.user_role == "Resident":
        me = get_resident_by_id(g.user_id)
        if me is None or me.get("household_id") != household_id:
            raise_api_error(ERR_FORBIDDEN, "Resident does not own this household.")
    return jsonify(success_response(d)), 200
