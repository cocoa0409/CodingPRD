"""QualityMeasureResult endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DUPLICATE_MEASURE_RESULT,
    ERR_EMPTY_DENOMINATOR,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_NUMERATOR_EXCEEDS_DENOMINATOR,
    ERR_UNKNOWN_MEASURE_CODE,
    ERR_YEAR_LOCKED,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import calculations as calc
from services import engine
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("quality", __name__)


def _get_result_or_404(result_id: str) -> dict:
    result = db.quality_results.get(result_id)
    if result is None:
        raise_err(ERR_NOT_FOUND, "QualityMeasureResult id does not exist")
    return result


def _year_of_result(result: dict) -> dict:
    return db.performance_years[result["performance_year_id"]]


@bp.route("/vbc/quality-measure-results", methods=["POST"])
@require_roles("QualityAnalyst")
def create_result(_user_id: str, _role: str):
    body = get_json_body()
    raw_year = body.get("performance_year_id")
    if isinstance(raw_year, str) and raw_year != "" and raw_year not in db.performance_years:
        raise_err(ERR_NOT_FOUND, "performance_year_id does not exist")
    # Priority 5: shape.
    reject_unknown_fields(body, {"performance_year_id", "measure_code", "numerator_count", "denominator_count"})
    performance_year_id = require_string(body, "performance_year_id")
    measure_code = require_string(body, "measure_code")
    numerator_count = require_int(body, "numerator_count")
    denominator_count = require_int(body, "denominator_count")
    if numerator_count < 0 or denominator_count < 0:
        raise_err(ERR_INVALID_REQUEST, "numerator_count and denominator_count must be >= 0")
    if performance_year_id not in db.performance_years:
        raise_err(ERR_NOT_FOUND, "performance_year_id does not exist")

    year = db.performance_years[performance_year_id]
    contract = engine.contract_of_year(year)
    # Priority 11 (uniqueness family): catalog membership and one
    # non-EXCLUDED result per (year, measure_code).
    catalog_codes = {e["measure_code"] for e in contract["quality_measures"]}
    if measure_code not in catalog_codes:
        raise_err(ERR_UNKNOWN_MEASURE_CODE, "measure_code is not in the contract's quality_measures catalog")
    for result in db.quality_results.values():
        if (
            result["performance_year_id"] == performance_year_id
            and result["measure_code"] == measure_code
            and result["result_status"] != "EXCLUDED"
        ):
            raise_err(ERR_DUPLICATE_MEASURE_RESULT, "A non-EXCLUDED result already exists for (year, measure_code)")
    # Priority 13 (quality math): numerator must not exceed denominator.
    # (Zero denominator is allowed at create; validate rejects it.)
    if numerator_count > denominator_count:
        raise_err(ERR_NUMERATOR_EXCEEDS_DENOMINATOR, "numerator_count must not exceed denominator_count")

    result = {
        "performance_year_id": performance_year_id,
        "measure_code": measure_code,
        "numerator_count": numerator_count,
        "denominator_count": denominator_count,
        "rate_bp": None,
        "achievement_points": None,
        "result_status": "REPORTED",
    }
    db.stamp_new(result)
    db.quality_results[result["id"]] = result
    return success_object(result, 201)


@bp.route("/vbc/quality-measure-results", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_results(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.quality_results.values()))
    items = apply_filters(items, ["performance_year_id", "measure_code", "result_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/quality-measure-results/<result_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_result(result_id: str, _user_id: str, _role: str):
    return success_object(_get_result_or_404(result_id))


@bp.route("/vbc/quality-measure-results/<result_id>/validate", methods=["POST"])
@require_roles("QualityAnalyst")
def validate_result(result_id: str, _user_id: str, _role: str):
    result = _get_result_or_404(result_id)
    if result["result_status"] != "REPORTED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a REPORTED result can be validated")
    # Priority 13 (quality math guard): validate requires denominator >= 1.
    if result["denominator_count"] < 1:
        raise_err(ERR_EMPTY_DENOMINATOR, "Validate requires denominator_count >= 1")
    year = _year_of_result(result)
    contract = engine.contract_of_year(year)
    computed = calc.compute_achievement(
        contract, result["measure_code"], result["numerator_count"], result["denominator_count"]
    )
    result["rate_bp"] = computed["rate_bp"]
    result["achievement_points"] = computed["achievement_points"]
    result["result_status"] = "VALIDATED"
    db.touch(result)
    return success_object(result)


@bp.route("/vbc/quality-measure-results/<result_id>/return-for-correction", methods=["POST"])
@require_roles("QualityAnalyst")
def return_for_correction(result_id: str, _user_id: str, _role: str):
    result = _get_result_or_404(result_id)
    if result["result_status"] != "VALIDATED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a VALIDATED result can be returned for correction")
    year = _year_of_result(result)
    if year["year_status"] not in ("SETUP", "ATTRIBUTION_OPEN", "ATTRIBUTION_LOCKED", "MEASURING"):
        raise_err(ERR_YEAR_LOCKED, "Year has advanced past the correction window")
    result["rate_bp"] = None
    result["achievement_points"] = None
    result["result_status"] = "REPORTED"
    db.touch(result)
    return success_object(result)


@bp.route("/vbc/quality-measure-results/<result_id>/lock", methods=["POST"])
@require_roles("QualityAnalyst")
def lock_result(result_id: str, _user_id: str, _role: str):
    result = _get_result_or_404(result_id)
    if result["result_status"] != "VALIDATED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a VALIDATED result can be locked")
    year = _year_of_result(result)
    if year["year_status"] not in ("ATTRIBUTION_OPEN", "ATTRIBUTION_LOCKED", "MEASURING"):
        raise_err(ERR_YEAR_LOCKED, "Year is outside the locking window")
    result["result_status"] = "LOCKED"
    db.touch(result)
    return success_object(result)


@bp.route("/vbc/quality-measure-results/<result_id>/exclude", methods=["POST"])
@require_roles("QualityAnalyst")
def exclude_result(result_id: str, _user_id: str, _role: str):
    result = _get_result_or_404(result_id)
    if result["result_status"] not in ("REPORTED", "VALIDATED", "LOCKED"):
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a REPORTED, VALIDATED, or LOCKED result can be excluded")
    year = _year_of_result(result)
    if year["year_status"] in ("SETTLED", "CLOSED"):
        raise_err(ERR_YEAR_LOCKED, "Year is locked for data mutations")
    result["result_status"] = "EXCLUDED"
    db.touch(result)
    # Composite-dependent settlement fields may now be stale.
    engine.flag_settlement_needs_recompute(year["id"])
    return success_object(result)
