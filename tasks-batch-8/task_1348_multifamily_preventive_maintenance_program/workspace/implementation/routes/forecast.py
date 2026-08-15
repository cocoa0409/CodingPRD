"""Capital forecast snapshots and the compliance summary (PRD §3.7)."""
from flask import Blueprint, request

import errors as E
from errors import ApiError
from db import store, new_append_fields, fmt_ts, now
from middleware import auth, require_role, body, v_str, v_int, v_enum, paginate
from response import ok_object, ok_list
from services.core import get_property, require_active_property
from services.forecast import compute_forecast
from services.compliance import compliance_summary
from services.serializers import forecast_view

bp = Blueprint("forecast", __name__)

PM = ("PropertyManager",)
ALL = ("PropertyManager", "Technician", "ComplianceAuditor")
FORECAST_READ = ("PropertyManager", "ComplianceAuditor")


@bp.route("/pm/capital-forecasts", methods=["POST"])
def create_forecast():
    _, role = auth()
    require_role(role, PM)
    data = body()
    prop = None
    if data.get("property_id") is not None:
        prop = get_property(data["property_id"])
        require_active_property(prop)
    pid = v_str(data, "property_id")
    horizon = v_int(data, "horizon_years", minv=1, maxv=10)
    variant = v_enum(data, "variant", ("AGE_BASED", "CONDITION_BASED"))
    if prop is None:
        prop = get_property(pid)
        require_active_property(prop)
    result = compute_forecast(prop["id"], horizon, variant)
    rec = new_append_fields()
    rec.update({
        "property_id": prop["id"],
        "horizon_years": horizon,
        "variant": variant,
        "total_projected_cents": result["total_projected_cents"],
        "per_year_cents": result["per_year_cents"],
        "asset_count_projected": result["asset_count_projected"],
        "computed_at": fmt_ts(now()),
    })
    store.forecasts[rec["id"]] = rec
    return ok_object(forecast_view(rec), 201)


@bp.route("/pm/properties/<property_id>/capital-forecasts", methods=["GET"])
def list_forecasts(property_id):
    _, role = auth()
    require_role(role, FORECAST_READ)
    prop = get_property(property_id)
    rows = [s for s in store.forecasts.values() if s["property_id"] == prop["id"]]
    variant = request.args.get("variant")
    if variant is not None:
        rows = [s for s in rows if s["variant"] == variant]
    page, limit, offset, total = paginate(rows)
    return ok_list([forecast_view(s) for s in page], limit, offset, total)


@bp.route("/pm/compliance-summary", methods=["GET"])
def compliance_summary_route():
    _, role = auth()
    require_role(role, ALL)
    pid = request.args.get("property_id")
    if pid is None or not pid:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "property_id query parameter is required")
    prop = get_property(pid)
    return ok_object(compliance_summary(prop["id"]), 200)
