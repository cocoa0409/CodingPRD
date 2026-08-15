"""Accrual + MatterForecast endpoints."""

from flask import Blueprint, request

import db
import errors
import helpers
import response as resp
from middleware import require_auth, ROLE_LEGAL_OPS, ROLE_FIRM_USER
from services import invoice_service as svc

bp = Blueprint("accruals", __name__)


@bp.route("/legal-departments/<deptId>/matters/<matterId>/accruals", methods=["POST"])
def create_accrual(deptId, matterId):
    user_id, _ = require_auth([ROLE_FIRM_USER])
    _, matter = helpers.resolve_matter(deptId, matterId)
    body = helpers.get_body()
    helpers.require_fields(body, ["period_year", "period_month", "amount_cents"])
    try:
        py = int(body["period_year"])
        pm = int(body["period_month"])
    except (TypeError, ValueError):
        raise errors.invalid_temporal()
    if pm < 1 or pm > 12:
        raise errors.invalid_temporal()
    # Acting firm must match the matter's engaged firm.
    if user_id != matter.get("panel_firm_id"):
        raise errors.firm_mismatch()
    # Temporal: accrual period must not lie in the future.
    clock = db.get_clock()
    if (py, pm) > (clock.year, clock.month):
        raise errors.invalid_temporal()
    # Referential: a period already matched to an invoice cannot be filed again.
    for acc in db.accruals.values():
        if (
            acc.get("matter_id") == matterId
            and int(acc.get("period_year", 0)) == py
            and int(acc.get("period_month", 0)) == pm
            and acc.get("matched_invoice_id") is not None
        ):
            raise errors.referential_integrity("accrual period already matched to an invoice")
    rec = db.base_resource({
        "matter_id": matterId,
        "period_year": py,
        "period_month": pm,
        "amount_cents": int(body["amount_cents"]),
        "matched_invoice_id": None,
    })
    db.accruals[rec["id"]] = rec
    matter["accrual_outstanding_cents"] = int(matter.get("accrual_outstanding_cents", 0)) + int(rec["amount_cents"])
    db.touch(matter)
    svc.refresh_forecast(matterId)
    return resp.success_object(resp.public(rec), 201)


@bp.route("/legal-departments/<deptId>/matters/<matterId>/accruals/<accrualId>", methods=["GET"])
def get_accrual(deptId, matterId, accrualId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, _, acc = helpers.resolve_accrual(deptId, matterId, accrualId)
    return resp.success_object(resp.public(acc))


@bp.route("/legal-departments/<deptId>/matters/<matterId>/accruals", methods=["GET"])
def list_accruals(deptId, matterId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_matter(deptId, matterId)
    limit, offset = resp.parse_pagination(request.args)
    records = [a for a in db.accruals.values() if a.get("matter_id") == matterId]
    records = helpers.apply_filters(records, request.args, ["period_year", "period_month"])
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# MatterForecast (1:1 with Matter)
# ---------------------------------------------------------------------------

@bp.route("/legal-departments/<deptId>/matters/<matterId>/forecast", methods=["PUT"])
def put_forecast(deptId, matterId):
    require_auth([ROLE_LEGAL_OPS])
    _, matter = helpers.resolve_matter(deptId, matterId)
    body = helpers.get_body()
    helpers.require_fields(body, ["lifecycle_estimate_cents"])
    forecast = db.matter_forecasts.get(matterId)
    if forecast is None:
        forecast = db.base_resource({
            "matter_id": matterId,
            "lifecycle_estimate_cents": int(body["lifecycle_estimate_cents"]),
            "wip_estimate_cents": 0,
            "variance_cents": 0,
        })
        db.matter_forecasts[matterId] = forecast
    else:
        forecast["lifecycle_estimate_cents"] = int(body["lifecycle_estimate_cents"])
        db.touch(forecast)
    svc.refresh_forecast(matterId)
    return resp.success_object(resp.public(db.matter_forecasts[matterId]), 200)


@bp.route("/legal-departments/<deptId>/matters/<matterId>/forecast", methods=["GET"])
def get_forecast(deptId, matterId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_matter(deptId, matterId)
    forecast = db.matter_forecasts.get(matterId)
    if forecast is None:
        raise errors.not_found()
    svc.refresh_forecast(matterId)
    return resp.success_object(resp.public(db.matter_forecasts[matterId]))
