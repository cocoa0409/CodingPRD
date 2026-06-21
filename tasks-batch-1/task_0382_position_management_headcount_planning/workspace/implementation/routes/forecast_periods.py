"""ForecastPeriod endpoints: create (nested), snapshot (OCC-guarded), get, list
(PRD §3.9)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from response import success, list_success
from services import serialize, calc
from services.common import (
    get_body, require_string, validate_nonneg_fte, fetch, paginate,
    base_common_fields, bump,
)

bp = Blueprint("forecast_periods", __name__)

ALL_ROLES = ["HRBP", "HRDirector", "FinanceController", "CompensationAnalyst"]


@bp.post("/cost-centers/<cost_center_id>/forecast-periods")
def create_forecast_period(cost_center_id):
    require_auth(["FinanceController"])
    fetch(db.cost_centers, cost_center_id)
    body = get_body()
    fiscal_label = require_string(body, "fiscal_label")
    if body.get("planned_fte") is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: planned_fte")
    planned_fte = validate_nonneg_fte(body.get("planned_fte"))

    # fiscal_label unique per cost center (PRD §3.9).
    for fp in db.forecast_periods.values():
        if fp["cost_center_id"] == cost_center_id and fp["fiscal_label"] == fiscal_label:
            raise err("ERR_INVALID_REQUEST", "fiscal_label must be unique per cost center")

    rec = base_common_fields()
    rec.update({
        "cost_center_id": cost_center_id,
        "fiscal_label": fiscal_label,
        "planned_fte": planned_fte,
        "actual_fte": None,
        "variance_fte": None,
        "status": "DRAFT",
    })
    db.forecast_periods[rec["id"]] = rec
    return success(serialize.forecast_period_out(rec), status=201)


@bp.get("/cost-centers/<cost_center_id>/forecast-periods")
def list_cc_forecast_periods(cost_center_id):
    require_auth(ALL_ROLES)
    fetch(db.cost_centers, cost_center_id)
    records = [r for r in db.forecast_periods.values() if r["cost_center_id"] == cost_center_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.forecast_period_out(r) for r in page], limit, offset, total)


@bp.get("/forecast-periods/<forecast_period_id>")
def get_forecast_period(forecast_period_id):
    require_auth(ALL_ROLES)
    rec = fetch(db.forecast_periods, forecast_period_id)
    return success(serialize.forecast_period_out(rec))


@bp.get("/forecast-periods")
def list_forecast_periods():
    require_auth(ALL_ROLES)
    records = list(db.forecast_periods.values())
    for field in ("cost_center_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.forecast_period_out(r) for r in page], limit, offset, total)


@bp.post("/forecast-periods/<forecast_period_id>/snapshot")
def snapshot_forecast_period(forecast_period_id):
    require_auth(["FinanceController"])
    fp = fetch(db.forecast_periods, forecast_period_id)
    body = get_body()
    cc = db.cost_centers.get(fp["cost_center_id"])

    # OCC (priority 5): expected_cost_center_version vs cost center version.
    expected = body.get("expected_cost_center_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err("ERR_INVALID_REQUEST", "expected_cost_center_version must be an integer")
        if cc is None or expected != cc["version"]:
            raise err("ERR_STALE_VERSION", "cost center version is stale")

    # State (priority 6): must be DRAFT.
    if fp["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "forecast period must be DRAFT to snapshot")

    actual_fte = calc.filled_fte(cc["id"])
    from decimal import Decimal, ROUND_HALF_UP
    variance = float(
        (Decimal(str(actual_fte)) - Decimal(str(fp["planned_fte"])))
        .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )
    fp["actual_fte"] = actual_fte
    fp["variance_fte"] = variance
    fp["status"] = "SNAPSHOTTED"
    bump(fp)
    # Stamps the cost center headcount baseline: bump its version (PRD §3.9).
    bump(cc)
    return success(serialize.forecast_period_out(fp))
