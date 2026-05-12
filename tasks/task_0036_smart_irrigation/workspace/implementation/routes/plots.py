"""Plot CRUD routes."""

from flask import Blueprint, g, request

from db import DB, LOCK, new_id
from errors import forbidden, not_found, validation_error
from middleware import require_roles
from response import success_array, success_object
from services.common import (
    bump_version,
    check_occ,
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_str,
    stamp_create,
)
from services.serializers import plot_view


bp = Blueprint("plots", __name__)


VALID_CROP_TYPES = {"WHEAT", "CORN", "RICE", "COTTON", "VEGETABLE"}
VALID_CROP_STAGES = {"SEEDLING", "VEGETATIVE", "FLOWERING", "FRUITING", "MATURE"}
VALID_PLOT_STATUSES = {"ACTIVE", "FALLOW"}


@bp.route("/plots", methods=["POST"])
@require_roles("WaterAdmin")
def create_plot():
    body = get_json_body()
    tenant_id = require_str(body, "tenant_id")
    name = require_str(body, "name")
    pump_id = require_str(body, "pump_id")
    crop_type = require_str(body, "crop_type")
    crop_stage = require_str(body, "crop_stage")
    if crop_type not in VALID_CROP_TYPES:
        raise validation_error("crop_type invalid")
    if crop_stage not in VALID_CROP_STAGES:
        raise validation_error("crop_stage invalid")
    if "area_hectares" not in body or body["area_hectares"] is None:
        raise validation_error("area_hectares is required")
    area = body["area_hectares"]
    if isinstance(area, bool) or not isinstance(area, (int, float)):
        raise validation_error("area_hectares must be a number")
    area = float(area)
    if area <= 0:
        raise validation_error("area_hectares must be > 0")

    with LOCK:
        if tenant_id not in DB.tenants:
            raise validation_error("tenant_id does not exist")
        rec = stamp_create({
            "id": new_id(),
            "tenant_id": tenant_id,
            "name": name,
            "area_hectares": area,
            "crop_type": crop_type,
            "crop_stage": crop_stage,
            "pump_id": pump_id,
            "status": "ACTIVE",
            "last_irrigated_at": None,
        })
        DB.plots[rec["id"]] = rec
    return success_object(plot_view(rec), status=201)


@bp.route("/plots/<plot_id>", methods=["GET"])
def read_plot(plot_id):
    role = g.role
    if role not in {"PlatformAdmin", "WaterAdmin", "Operator", "Tenant"}:
        raise forbidden()
    with LOCK:
        rec = fetch_or_404(DB.plots, plot_id)
        if role == "Tenant" and rec.get("tenant_id") != g.user_id:
            raise forbidden()
    return success_object(plot_view(rec))


@bp.route("/plots/<plot_id>", methods=["PATCH"])
@require_roles("WaterAdmin")
def update_plot(plot_id):
    body = get_json_body()
    with LOCK:
        rec = fetch_or_404(DB.plots, plot_id)
        check_occ(rec, body)

        if "crop_stage" in body and body["crop_stage"] is not None:
            cs = body["crop_stage"]
            if cs not in VALID_CROP_STAGES:
                raise validation_error("crop_stage invalid")
            rec["crop_stage"] = cs
        if "pump_id" in body and body["pump_id"] is not None:
            pid = body["pump_id"]
            if not isinstance(pid, str) or not pid.strip():
                raise validation_error("pump_id must be non-empty string")
            rec["pump_id"] = pid
        if "status" in body and body["status"] is not None:
            st = body["status"]
            if st not in VALID_PLOT_STATUSES:
                raise validation_error("status invalid")
            rec["status"] = st
        bump_version(rec)
    return success_object(plot_view(rec))


@bp.route("/plots", methods=["GET"])
def list_plots():
    role = g.role
    if role not in {"PlatformAdmin", "WaterAdmin", "Operator", "Tenant"}:
        raise forbidden()
    limit, offset = parse_pagination()
    tenant_filter = request.args.get("tenant_id")
    with LOCK:
        items = list(DB.plots.values())
        if tenant_filter:
            items = [p for p in items if p.get("tenant_id") == tenant_filter]
        if role == "Tenant":
            items = [p for p in items if p.get("tenant_id") == g.user_id]
        items.sort(key=lambda r: r.get("created_at"))
        page, total, has_more = paginate(items, limit, offset)
        data = [plot_view(p) for p in page]
    return success_array(data, limit, offset, total, has_more)
