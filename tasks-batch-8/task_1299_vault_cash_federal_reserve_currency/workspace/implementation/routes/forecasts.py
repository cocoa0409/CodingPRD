"""AtmForecast endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB, new_id, clock_date_str
from errors import ApiError
from middleware import auth, ALL_ROLES, SITE_SCOPED_STAFF_ROLES, require_site_scope
from response import ok, ok_list
from services import (
    stamp_new, touch, public, append_ledger, derive_atm_posture,
    seasonal_window_for, ATM_LOAD_STRAP_CENTS, MIN_RESIDUAL_CENTS,
    RESIDUAL_PCT_BPS,
)
from util import (
    body, required, as_int, as_str, as_ymd, pagination_args,
    round_half_up_cents,
)

bp = Blueprint("forecasts", __name__)


def _get_forecast_or_404(forecast_id):
    forecast = DB["atm_forecasts"].get(forecast_id)
    if forecast is None:
        raise ApiError("ERR_ATM_FORECAST_NOT_FOUND", 404, "ATM forecast not found")
    return forecast


def _get_atm_or_404(atm_id):
    atm = DB["atm_machines"].get(atm_id)
    if atm is None:
        raise ApiError("ERR_ATM_NOT_FOUND", 404, "ATM not found")
    return atm


def _site_or_404(site_id):
    site = DB["vault_sites"].get(site_id)
    if site is None:
        raise ApiError("ERR_VAULT_SITE_NOT_FOUND", 404, "Vault site not found")
    return site


@bp.post("/vault-cash/atm-forecasts")
def create_forecast():
    principal = auth(["AtmAnalyst"])
    data = body()
    atm_id = as_str(required(data, "atm_id"), "atm_id")
    atm = _get_atm_or_404(atm_id)  # body FK existence
    require_site_scope(principal, atm["site_id"])
    forecast_date = as_ymd(required(data, "forecast_date"), "forecast_date")
    w1 = as_int(required(data, "w1_cents"), "w1_cents")
    w2 = as_int(required(data, "w2_cents"), "w2_cents")
    w3 = as_int(required(data, "w3_cents"), "w3_cents")

    # calculations.atm_forecast_projection: round-half-up at each starred step.
    base = round_half_up_cents(
        Decimal("0.5") * w1 + Decimal("0.3") * w2 + Decimal("0.2") * w3
    )
    window = seasonal_window_for(atm["site_id"], forecast_date)
    if window is not None:
        variant = "SEASONAL"
        final = round_half_up_cents(
            Decimal(base) * window["multiplier_bps"] / 10000
        )
    else:
        variant = "TRAILING"
        final = base
    # Ceiling to whole straps; exact multiples stay unchanged.
    load = -(-final // ATM_LOAD_STRAP_CENTS) * ATM_LOAD_STRAP_CENTS

    # calculations.atm_residual_target (mode a combinatorial).
    if atm["cash_posture"] == "CRITICAL":
        residual_target = 0
    else:
        raw = max(
            MIN_RESIDUAL_CENTS,
            round_half_up_cents(Decimal(final) * RESIDUAL_PCT_BPS / 10000),
        )
        headroom = max(0, atm["cash_capacity_cents"] - load)
        residual_target = min(raw, headroom)

    forecast = stamp_new({
        "id": new_id(),
        "atm_id": atm_id,
        "forecast_date": forecast_date,
        "w1_cents": w1,
        "w2_cents": w2,
        "w3_cents": w3,
        "variant_applied": variant,
        "projected_base_cents": base,
        "projected_final_cents": final,
        "recommended_load_cents": load,
        "residual_target_cents": residual_target,
        "actual_withdrawals_cents": None,
        "residual_balance_cents": None,
        "status": "DRAFT",
    })
    DB["atm_forecasts"][forecast["id"]] = forecast
    return ok(public(forecast), status=201)


@bp.get("/vault-cash/atm-forecasts")
def list_forecasts():
    principal = auth(ALL_ROLES)
    limit, offset = pagination_args()
    atm_id = request.args.get("atm_id")
    status = request.args.get("status")
    forecast_date = request.args.get("forecast_date")
    rows = list(DB["atm_forecasts"].values())
    if atm_id is not None:
        rows = [f for f in rows if f["atm_id"] == atm_id]
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    if forecast_date is not None:
        rows = [f for f in rows if f["forecast_date"] == forecast_date]
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        hs = principal.home_site_id
        rows = [
            f for f in rows
            if DB["atm_machines"].get(f["atm_id"], {}).get("site_id") == hs
        ]
    rows.sort(key=lambda f: (f["created_at"], f["_seq"]))
    total = len(rows)
    return ok_list([public(f) for f in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/vault-cash/atm-forecasts/<forecastId>")
def get_forecast(forecastId):
    principal = auth(ALL_ROLES)
    forecast = _get_forecast_or_404(forecastId)
    atm = _get_atm_or_404(forecast["atm_id"])
    require_site_scope(principal, atm["site_id"])
    return ok(public(forecast))


@bp.post("/vault-cash/atm-forecasts/<forecastId>/publish")
def publish_forecast(forecastId):
    principal = auth(["AtmAnalyst"])
    forecast = _get_forecast_or_404(forecastId)
    atm = _get_atm_or_404(forecast["atm_id"])
    require_site_scope(principal, atm["site_id"])
    data = body()
    expected = as_int(required(data, "expected_atm_version"), "expected_atm_version")

    if forecast["status"] != "DRAFT":
        raise ApiError(
            "ERR_FORECAST_INVALID_STATE", 409, "Only DRAFT forecasts may publish"
        )
    if atm["service_status"] != "ACTIVE":
        raise ApiError(
            "ERR_ATM_OUT_OF_SERVICE", 409, "ATM service_status is not ACTIVE"
        )
    if expected != atm["version"]:
        raise ApiError(
            "ERR_STALE_ATM_VERSION",
            412,
            "expected_atm_version does not match current ATM version",
        )
    # Exclusive per (atm, forecast_date): prior PUBLISHED becomes SUPERSEDED.
    for other in DB["atm_forecasts"].values():
        if (
            other["id"] != forecast["id"]
            and other["atm_id"] == forecast["atm_id"]
            and other["forecast_date"] == forecast["forecast_date"]
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    forecast["status"] = "PUBLISHED"
    touch(forecast)
    atm["current_forecast_id"] = forecast["id"]
    touch(atm)
    return ok(public(forecast))


@bp.post("/vault-cash/atm-forecasts/<forecastId>/load")
def load_forecast(forecastId):
    principal = auth(["AtmAnalyst"])
    forecast = _get_forecast_or_404(forecastId)
    atm = _get_atm_or_404(forecast["atm_id"])
    require_site_scope(principal, atm["site_id"])
    if forecast["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_FORECAST_INVALID_STATE", 409, "Only PUBLISHED forecasts may load"
        )
    site = _site_or_404(atm["site_id"])
    load = forecast["recommended_load_cents"]
    if site["on_hand_fit_cents"] < load:
        raise ApiError(
            "ERR_INSUFFICIENT_FIT_BALANCE",
            422,
            "Site fit balance does not cover the recommended load",
        )
    forecast["status"] = "LOADED"
    touch(forecast)
    atm["current_balance_cents"] = atm.get("current_balance_cents", 0) + load
    derive_atm_posture(atm)
    touch(atm)
    append_ledger(
        site["id"], clock_date_str(), "ATM_LOAD", -load, "FIT",
        note=f"ATM {atm['id']} forecast {forecast['id']} load",
    )
    return ok(public(forecast))


@bp.post("/vault-cash/atm-forecasts/<forecastId>/settle")
def settle_forecast(forecastId):
    principal = auth(["AtmAnalyst"])
    forecast = _get_forecast_or_404(forecastId)
    atm = _get_atm_or_404(forecast["atm_id"])
    require_site_scope(principal, atm["site_id"])
    data = body()
    actual = as_int(
        required(data, "actual_withdrawals_cents"), "actual_withdrawals_cents"
    )
    if forecast["status"] != "LOADED":
        raise ApiError(
            "ERR_FORECAST_INVALID_STATE", 409, "Only LOADED forecasts may settle"
        )
    if actual > atm.get("current_balance_cents", 0):
        raise ApiError(
            "ERR_WITHDRAWAL_EXCEEDS_BALANCE",
            422,
            "Settled withdrawals exceed the ATM current balance",
        )
    site = _site_or_404(atm["site_id"])
    residual = atm.get("current_balance_cents", 0) - actual
    forecast["actual_withdrawals_cents"] = actual
    forecast["residual_balance_cents"] = residual
    forecast["status"] = "SETTLED"
    touch(forecast)
    atm["current_balance_cents"] = 0
    derive_atm_posture(atm)
    touch(atm)
    if residual > 0:
        append_ledger(
            site["id"], clock_date_str(), "ATM_RESIDUAL_RETURN", residual, "FIT",
            note=f"ATM {atm['id']} forecast {forecast['id']} residual return",
        )
    return ok(public(forecast))
