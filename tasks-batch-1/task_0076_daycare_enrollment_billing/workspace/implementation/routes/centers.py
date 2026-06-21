"""Center, sliding-scale, classroom endpoints."""
from __future__ import annotations

from flask import Blueprint

from db import db
from middleware import require_roles
from response import ok_object, ok_array
from common import (
    base_entity, public, get_or_404, get_body,
    require_str, require_enum, require_int, optional_int, parse_pagination, paginate,
)
from services.pricing import SLIDING_TIERS
from services.domain import recompute_classroom_status, AGE_BANDS

bp = Blueprint("centers", __name__)

CACFP_TIERS = {"TIER_I", "TIER_II"}


@bp.post("/centers")
@require_roles("CenterDirector")
def create_center():
    body = get_body()
    name = require_str(body, "name")
    cacfp_tier = require_enum(body, "cacfp_tier", CACFP_TIERS)
    grace = optional_int(body, "late_pickup_grace_minutes", 5, minimum=0)
    fee = optional_int(body, "late_pickup_fee_per_block_cents", 1500, minimum=0)
    block = optional_int(body, "late_pickup_block_minutes", 15, minimum=1)
    ent = base_entity()
    ent.update({
        "name": name,
        "cacfp_tier": cacfp_tier,
        "late_pickup_grace_minutes": grace,
        "late_pickup_fee_per_block_cents": fee,
        "late_pickup_block_minutes": block,
    })
    db.centers[ent["id"]] = ent
    return ok_object(public(ent), 201)


@bp.get("/centers/<cid>")
@require_roles("CenterDirector", "BillingAdmin", "Parent", "Teacher")
def get_center(cid):
    ent = get_or_404(db.centers, cid, "center")
    return ok_object(public(ent), 200)


@bp.post("/centers/<cid>/sliding-scale")
@require_roles("CenterDirector")
def add_sliding_scale(cid):
    get_or_404(db.centers, cid, "center")
    body = get_body()
    tier = require_enum(body, "tier", SLIDING_TIERS)
    max_fpl = require_int(body, "max_fpl_ratio_pct", minimum=0)
    parent_share = require_int(body, "parent_share_pct", minimum=0, maximum=100)
    ent = base_entity()
    ent.update({
        "center_id": cid,
        "tier": tier,
        "max_fpl_ratio_pct": max_fpl,
        "parent_share_pct": parent_share,
    })
    db.sliding_scale[ent["id"]] = ent
    return ok_object(public(ent), 201)


@bp.get("/centers/<cid>/sliding-scale")
@require_roles("CenterDirector", "BillingAdmin")
def list_sliding_scale(cid):
    get_or_404(db.centers, cid, "center")
    limit, offset = parse_pagination()
    rows = [r for r in db.sliding_scale.values() if r["center_id"] == cid]
    rows.sort(key=lambda r: r["_seq"])
    page, total = paginate(rows, limit, offset)
    return ok_array([public(r) for r in page], limit, offset, total, 200)


@bp.post("/centers/<cid>/classrooms")
@require_roles("CenterDirector")
def create_classroom(cid):
    get_or_404(db.centers, cid, "center")
    body = get_body()
    name = require_str(body, "name")
    age_band = require_enum(body, "age_band", AGE_BANDS)
    capacity = require_int(body, "licensed_capacity", minimum=1)
    base_tuition = require_int(body, "base_monthly_tuition_cents", minimum=0)
    ent = base_entity()
    ent.update({
        "center_id": cid,
        "name": name,
        "age_band": age_band,
        "licensed_capacity": capacity,
        "base_monthly_tuition_cents": base_tuition,
        "active_enrollment_count": 0,
        "status": "OPEN",
    })
    recompute_classroom_status(ent)
    db.classrooms[ent["id"]] = ent
    return ok_object(public(ent), 201)


@bp.get("/centers/<cid>/classrooms")
@require_roles("CenterDirector", "BillingAdmin", "Parent", "Teacher")
def list_classrooms(cid):
    get_or_404(db.centers, cid, "center")
    limit, offset = parse_pagination()
    rows = [r for r in db.classrooms.values() if r["center_id"] == cid]
    rows.sort(key=lambda r: r["_seq"])
    page, total = paginate(rows, limit, offset)
    return ok_array([public(r) for r in page], limit, offset, total, 200)


@bp.get("/classrooms/<rid>")
@require_roles("CenterDirector", "BillingAdmin", "Parent", "Teacher")
def get_classroom(rid):
    ent = get_or_404(db.classrooms, rid, "classroom")
    return ok_object(public(ent), 200)
