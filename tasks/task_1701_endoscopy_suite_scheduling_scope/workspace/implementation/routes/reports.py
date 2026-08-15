"""Quality metric reports and the room-utilization computed read (PRD 3.9)."""
from flask import Blueprint, request

from errors import (
    raise_error,
    ERR_PROVIDER_NOT_FOUND,
    ERR_QUALITY_REPORT_NOT_FOUND,
    ERR_INVALID_PERIOD,
    ERR_INVALID_REQUEST,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public
from services.quality import compute_quality_report, room_utilization_report
from util import parse_date
from validate import get_body, req_datetime, req_enum, req_str, resolve_ref

bp = Blueprint("reports", __name__)

METRIC_VARIANTS = {"STRICT", "EXPANDED"}


@bp.post("/endoscopy/quality-reports")
def create_quality_report():
    authorized(["QualityOfficer"])
    body = get_body()
    # Rung 3 (existence)
    provider = resolve_ref("providers", body.get("provider_id"), ERR_PROVIDER_NOT_FOUND)
    # Rung 4 (schema)
    req_str(body, "provider_id")
    period_start = req_datetime(body, "period_start")
    period_end = req_datetime(body, "period_end")
    metric_variant = req_enum(body, "metric_variant", METRIC_VARIANTS)
    # Rung 9 (temporal): the period bounds are a closed interval.
    if period_start > period_end:
        raise_error(ERR_INVALID_PERIOD, "period_start must not fall after period_end")
    metrics = compute_quality_report(provider["id"], period_start, period_end, metric_variant)
    # Immutable snapshot: no updated_at, no version (PRD 2.5).
    rec = new_record("quality_reports", {
        "provider_id": provider["id"],
        "period_start": period_start,
        "period_end": period_end,
        "metric_variant": metric_variant,
        **metrics,
    }, with_version=False)
    return success_object(public(rec), status=201)


@bp.get("/endoscopy/quality-reports")
def list_quality_reports():
    return list_response("quality_reports", {
        "provider_id": request.args.get("provider_id"),
        "metric_variant": request.args.get("metric_variant"),
    })


@bp.get("/endoscopy/quality-reports/<rid>")
def get_quality_report(rid):
    return get_one("quality_reports", rid, ERR_QUALITY_REPORT_NOT_FOUND)


@bp.get("/endoscopy/reports/room-utilization")
def room_utilization():
    authorized(["QualityOfficer", "UnitAdmin"])
    date_raw = request.args.get("date")
    if date_raw is None or date_raw == "":
        raise_error(ERR_INVALID_REQUEST, "date query parameter is required (YYYY-MM-DD)")
    day = parse_date(date_raw)
    if day is None:
        raise_error(ERR_INVALID_REQUEST, "date must be YYYY-MM-DD")
    return success_object(room_utilization_report(day))
