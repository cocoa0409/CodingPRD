"""LossModel endpoints: lifecycle, activation, retirement, refresh, back-tests."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_REVERSION_CONFIG,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MODEL_IN_USE,
    ERR_NO_FINALIZED_RUN,
    ERR_REFRESH_NOT_REQUIRED,
)
from middleware import ALL_ROLES, require_roles
from response import success_response
from services import (
    BREACH_COUNT_THRESHOLD,
    BREACH_VARIANCE_THRESHOLD_BPS,
    IN_FLIGHT_RUN_STATUSES,
    MODEL_METHODS,
    REVERSION_METHODS,
    get_or_404,
    public,
    round_half_up_int,
    stamp_new,
    touch,
)
from validation import (
    get_body,
    paginate,
    parse_pagination,
    quarter_index,
    req_enum,
    req_int,
    req_period,
    req_str,
    sorted_by_creation,
)
from decimal import Decimal

bp = Blueprint("loss_models", __name__)


def _validate_reversion_config(method, forecast_q, reversion_method, reversion_q):
    if not (1 <= forecast_q <= 8):
        raise ApiError(
            ERR_INVALID_REVERSION_CONFIG,
            422,
            "forecast_period_quarters must be between 1 and 8",
        )
    if reversion_method == "IMMEDIATE":
        if reversion_q != 0:
            raise ApiError(
                ERR_INVALID_REVERSION_CONFIG,
                422,
                "IMMEDIATE reversion requires reversion_period_quarters == 0",
            )
    else:  # STRAIGHT_LINE
        if not (1 <= reversion_q <= 4):
            raise ApiError(
                ERR_INVALID_REVERSION_CONFIG,
                422,
                "STRAIGHT_LINE reversion requires reversion_period_quarters in 1..4",
            )
    if forecast_q + reversion_q > 8:
        raise ApiError(
            ERR_INVALID_REVERSION_CONFIG,
            422,
            "forecast_period_quarters + reversion_period_quarters must be <= 8",
        )


@bp.post("/cecl/loss-models")
def create_loss_model():
    require_roles(["ModelValidator"])
    body = get_body()
    name = req_str(body, "name")
    method = req_enum(body, "method", MODEL_METHODS)
    forecast_q = req_int(body, "forecast_period_quarters")
    reversion_method = req_enum(body, "reversion_method", REVERSION_METHODS)
    reversion_q = req_int(body, "reversion_period_quarters")
    lookback = req_int(body, "historical_lookback_quarters")
    _validate_reversion_config(method, forecast_q, reversion_method, reversion_q)
    if not (1 <= lookback <= 40):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "historical_lookback_quarters must be between 1 and 40",
        )
    model = stamp_new(
        {
            "name": name,
            "method": method,
            "forecast_period_quarters": forecast_q,
            "reversion_method": reversion_method,
            "reversion_period_quarters": reversion_q,
            "historical_lookback_quarters": lookback,
            "version_label": "v1",
            "parent_model_id": None,
            "status": "DRAFT",
            "consecutive_backtest_breach_count": 0,
            "refresh_required": False,
        }
    )
    db.loss_models[model["id"]] = model
    return success_response(public(model), 201)


@bp.get("/cecl/loss-models")
def list_loss_models():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.loss_models.values())
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    parent_id = request.args.get("parent_model_id")
    if parent_id is not None:
        items = [m for m in items if m["parent_model_id"] == parent_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success_response([public(m) for m in page], 200, "array", pagination)


@bp.get("/cecl/loss-models/<modelId>")
def get_loss_model(modelId):
    require_roles(ALL_ROLES)
    model = get_or_404(db.loss_models, modelId, "LossModel")
    return success_response(public(model), 200)


@bp.post("/cecl/loss-models/<modelId>/activate")
def activate_loss_model(modelId):
    require_roles(["ModelValidator"])
    get_body()
    model = get_or_404(db.loss_models, modelId, "LossModel")
    if model["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a DRAFT model can be activated",
        )
    # Auto-retire every other ACTIVE model
    for other in db.loss_models.values():
        if other["id"] != model["id"] and other["status"] == "ACTIVE":
            other["status"] = "RETIRED"
            touch(other)
    model["status"] = "ACTIVE"
    touch(model)
    return success_response(public(model), 200)


@bp.post("/cecl/loss-models/<modelId>/retire")
def retire_loss_model(modelId):
    require_roles(["ModelValidator"])
    get_body()
    model = get_or_404(db.loss_models, modelId, "LossModel")
    if model["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only an ACTIVE model can be retired",
        )
    for run in db.runs.values():
        if run["loss_model_id"] == model["id"] and run["status"] in IN_FLIGHT_RUN_STATUSES:
            raise ApiError(
                ERR_MODEL_IN_USE,
                409,
                "Model is referenced by an in-flight run and cannot be retired",
            )
    model["status"] = "RETIRED"
    touch(model)
    return success_response(public(model), 200)


@bp.post("/cecl/loss-models/<modelId>/refresh")
def refresh_loss_model(modelId):
    require_roles(["ModelValidator"])
    get_body()
    model = get_or_404(db.loss_models, modelId, "LossModel")
    if model["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only an ACTIVE model can be refreshed",
        )
    if not model["refresh_required"]:
        raise ApiError(
            ERR_REFRESH_NOT_REQUIRED,
            409,
            "Model does not require refresh (refresh_required is false)",
        )
    old_label = model["version_label"]
    try:
        n = int(old_label[1:])
    except (ValueError, IndexError):
        n = 1
    successor = stamp_new(
        {
            "name": model["name"],
            "method": model["method"],
            "forecast_period_quarters": model["forecast_period_quarters"],
            "reversion_method": model["reversion_method"],
            "reversion_period_quarters": model["reversion_period_quarters"],
            "historical_lookback_quarters": model["historical_lookback_quarters"],
            "version_label": "v%d" % (n + 1),
            "parent_model_id": model["id"],
            "status": "DRAFT",
            "consecutive_backtest_breach_count": 0,
            "refresh_required": False,
        }
    )
    db.loss_models[successor["id"]] = successor
    model["refresh_required"] = False
    model["consecutive_backtest_breach_count"] = 0
    touch(model)
    return success_response(public(successor), 201)


@bp.post("/cecl/loss-models/<modelId>/backtests")
def create_backtest(modelId):
    require_roles(["ModelValidator"])
    model = get_or_404(db.loss_models, modelId, "LossModel")
    body = get_body()
    backtest_period = req_period(body, "backtest_period")
    actual = req_int(body, "actual_loss_rate_bps")
    if not (0 <= actual <= 10000):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "actual_loss_rate_bps must be between 0 and 10000",
        )
    bt_idx = quarter_index(backtest_period)
    candidates = [
        r
        for r in db.runs.values()
        if r["loss_model_id"] == model["id"]
        and r["status"] == "FINALIZED"
        and quarter_index(r["as_of_period"]) <= bt_idx
    ]
    if not candidates:
        raise ApiError(
            ERR_NO_FINALIZED_RUN,
            409,
            "No FINALIZED run of this model exists at or before the backtest period",
        )
    candidates.sort(key=lambda r: quarter_index(r["as_of_period"]), reverse=True)
    selected = candidates[0]
    if selected["total_exposure_cents"] == 0:
        predicted = 0
    else:
        predicted = round_half_up_int(
            (Decimal(selected["total_allowance_cents"]) * Decimal(10000))
            / Decimal(selected["total_exposure_cents"])
        )
    variance = actual - predicted
    outcome = "BREACH" if abs(variance) > BREACH_VARIANCE_THRESHOLD_BPS else "PASS"
    result = stamp_new(
        {
            "loss_model_id": model["id"],
            "backtest_period": backtest_period,
            "actual_loss_rate_bps": actual,
            "backtested_run_id": selected["id"],
            "predicted_loss_rate_bps": predicted,
            "variance_bps": variance,
            "outcome": outcome,
        },
        with_version=False,
    )
    db.backtest_results[result["id"]] = result
    if outcome == "BREACH":
        model["consecutive_backtest_breach_count"] += 1
        if model["consecutive_backtest_breach_count"] >= BREACH_COUNT_THRESHOLD:
            model["refresh_required"] = True
    else:
        model["consecutive_backtest_breach_count"] = 0
    touch(model)
    return success_response(public(result), 201)


@bp.get("/cecl/loss-models/<modelId>/backtest-results")
def list_backtest_results(modelId):
    require_roles(ALL_ROLES)
    get_or_404(db.loss_models, modelId, "LossModel")
    limit, offset = parse_pagination()
    items = [b for b in db.backtest_results.values() if b["loss_model_id"] == modelId]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success_response([public(b) for b in page], 200, "array", pagination)
