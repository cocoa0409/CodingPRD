"""RiskExposure endpoints."""

from __future__ import annotations

from flask import Blueprint

from db import risk_exposures, reporting_periods, stamp_new
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_CROSS_BANK_REFERENCE,
    ERR_INVALID_STATE_TRANSITION, ERR_INVALID_RISK_PARAMETER,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    ser_exposure, get_bank, get_period, get_exposure,
    rwa_line_standardized, rwa_line_advanced,
    EXPOSURE_CLASSES, OBLIGOR_GRADES,
)
from util import get_body, req_int, req_enum, apply_filters, sorted_page

bp = Blueprint("exposures", __name__)


@bp.route("/banks/<bankId>/reporting-periods/<periodId>/risk-exposures", methods=["POST"])
@require_roles("CapitalAnalyst")
def create_exposure(bankId: str, periodId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    body = get_body()
    exposure_class = req_enum(body, "exposure_class", EXPOSURE_CLASSES)
    ead = req_int(body, "exposure_at_default_cents")
    risk_weight = req_int(body, "risk_weight_bps")
    grade = req_enum(body, "obligor_grade", OBLIGOR_GRADES)
    haircut = body.get("collateral_haircut_bps", 0)
    if haircut is None:
        haircut = 0
    if isinstance(haircut, bool) or not isinstance(haircut, int):
        raise_err(ERR_INVALID_REQUEST, "collateral_haircut_bps must be an integer")
    # Cross-bank referential integrity (priority 4): body reporting_period_id
    # must resolve to a period owned by this bank.
    body_period_id = body.get("reporting_period_id")
    if body_period_id is not None:
        if not isinstance(body_period_id, str):
            raise_err(ERR_INVALID_REQUEST, "reporting_period_id must be a string")
        ref = reporting_periods.get(body_period_id)
        if ref is None or ref["bank_id"] != bank["id"] or ref["id"] != period["id"]:
            raise_err(ERR_CROSS_BANK_REFERENCE,
                      "reporting_period_id does not resolve to this bank and path period")
    # State check (priority 5): period must be OPEN or FILING_DUE.
    if period["status"] not in ("OPEN", "FILING_DUE"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "RiskExposures may only be recorded against OPEN or FILING_DUE periods")
    # Risk-parameter bands (priority 17).
    if ead <= 0:
        raise_err(ERR_INVALID_RISK_PARAMETER, "exposure_at_default_cents must be positive")
    if risk_weight < 0:
        raise_err(ERR_INVALID_RISK_PARAMETER,
                  "risk_weight_bps outside the allowable band for the exposure class")
    if haircut < 0 or haircut > 10000:
        raise_err(ERR_INVALID_RISK_PARAMETER, "collateral_haircut_bps must lie in [0, 10000]")
    exposure = {
        "bank_id": bank["id"],
        "reporting_period_id": period["id"],
        "exposure_class": exposure_class,
        "exposure_at_default_cents": ead,
        "risk_weight_bps": risk_weight,
        "obligor_grade": grade,
        "collateral_haircut_bps": haircut,
    }
    stamp_new(exposure)
    exposure["rwa_cents_standardized"] = rwa_line_standardized(exposure)
    exposure["rwa_cents_advanced"] = rwa_line_advanced(exposure)
    risk_exposures[exposure["id"]] = exposure
    return success_object(ser_exposure(exposure), 201)



@bp.route("/banks/<bankId>/reporting-periods/<periodId>/risk-exposures/<exposureId>", methods=["GET"])
@require_roles("Any")
def get_one_exposure(bankId: str, periodId: str, exposureId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    return success_object(ser_exposure(get_exposure(period, exposureId)))


@bp.route("/banks/<bankId>/reporting-periods/<periodId>/risk-exposures", methods=["GET"])
@require_roles("Any")
def list_exposures(bankId: str, periodId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    period = get_period(bank, periodId)
    items = [e for e in risk_exposures.values() if e["reporting_period_id"] == period["id"]]
    items = apply_filters(items, {
        "exposure_class": "exposure_class",
        "obligor_grade": "obligor_grade",
    })
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_exposure(e) for e in page], limit, offset, total)


@bp.route("/banks/<bankId>/risk-exposures", methods=["GET"])
@require_roles("Any")
def list_bank_exposures(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    items = [e for e in risk_exposures.values() if e["bank_id"] == bank["id"]]
    items = apply_filters(items, {
        "reporting_period_id": "reporting_period_id",
        "exposure_class": "exposure_class",
    })
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_exposure(e) for e in page], limit, offset, total)
