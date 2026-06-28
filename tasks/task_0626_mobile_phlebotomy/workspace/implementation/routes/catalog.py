"""Test panels and lab partners (PRD 3.1)."""
from flask import Blueprint

import common
import serializers
from db import db, stamp_common, touch
from middleware import require_roles

bp = Blueprint("catalog", __name__)

ALL_ROLES = ("OrderingProvider", "Dispatcher", "Phlebotomist", "LabOps", "BillingAgent")


# ---------------------------------------------------------------------------
# Test Panels
# ---------------------------------------------------------------------------
@bp.post("/test-panels")
@require_roles("LabOps")
def create_panel():
    body = common.get_body()
    panel_code = common.require_str(body, "panel_code")
    name = common.require_str(body, "name")
    required_tube_count = common.require_int_min(body, "required_tube_count", 1)
    base_lab_fee_cents = common.require_int_nonneg(body, "base_lab_fee_cents")
    fasting_required = common.require_bool_optional(body, "fasting_required", False)

    rec = {
        "panel_code": panel_code,
        "name": name,
        "required_tube_count": required_tube_count,
        "base_lab_fee_cents": base_lab_fee_cents,
        "fasting_required": fasting_required,
        "status": "ACTIVE",
    }
    stamp_common(rec)
    db.test_panels[rec["id"]] = rec
    return common.object_response_201(serializers.panel(rec))


@bp.get("/test-panels")
@require_roles(*ALL_ROLES)
def list_panels():
    from flask import request
    limit, offset = common.get_pagination()
    items = list(db.test_panels.values())
    code_filter = request.args.get("panel_code")
    if code_filter is not None:
        items = [p for p in items if p["panel_code"] == code_filter]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.panel(p) for p in page], limit, offset, total)


@bp.get("/test-panels/<rid>")
@require_roles(*ALL_ROLES)
def get_panel(rid):
    rec = common.find_panel(rid)
    return common.object_response(serializers.panel(rec))


@bp.post("/test-panels/<rid>/retire")
@require_roles("LabOps")
def retire_panel(rid):
    rec = common.find_panel(rid)
    rec["status"] = "RETIRED"
    touch(rec)
    return common.object_response(serializers.panel(rec))


# ---------------------------------------------------------------------------
# Lab Partners
# ---------------------------------------------------------------------------
@bp.post("/lab-partners")
@require_roles("LabOps")
def create_partner():
    body = common.get_body()
    name = common.require_str(body, "name")
    courier_sla_hours = common.require_int_min(body, "courier_sla_hours", 1)
    accepted_panel_codes = common.require_str_array(body, "accepted_panel_codes")
    stat_surcharge_cents = common.optional_int_nonneg(body, "stat_surcharge_cents", 0)

    rec = {
        "name": name,
        "courier_sla_hours": courier_sla_hours,
        "accepted_panel_codes": list(accepted_panel_codes),
        "stat_surcharge_cents": stat_surcharge_cents,
        "status": "ACTIVE",
    }
    stamp_common(rec)
    db.lab_partners[rec["id"]] = rec
    return common.object_response_201(serializers.partner(rec))


@bp.get("/lab-partners")
@require_roles(*ALL_ROLES)
def list_partners():
    limit, offset = common.get_pagination()
    items = common.sort_by_created(list(db.lab_partners.values()))
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.partner(p) for p in page], limit, offset, total)


@bp.get("/lab-partners/<rid>")
@require_roles(*ALL_ROLES)
def get_partner(rid):
    rec = common.find_partner(rid)
    return common.object_response(serializers.partner(rec))


@bp.post("/lab-partners/<rid>/suspend")
@require_roles("LabOps")
def suspend_partner(rid):
    rec = common.find_partner(rid)
    rec["status"] = "SUSPENDED"
    touch(rec)
    return common.object_response(serializers.partner(rec))
