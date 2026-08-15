"""SupplyContract portfolio and LoadForecast snapshot endpoints."""

from flask import Blueprint, request

from auth import require_roles
from envelope import ok_object, paginate
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from serializers import ser_contract, ser_forecast, ser_rec
from services import (contract_termination_fee, forecast_compute, get_or_404,
                      reserve_debit)
from store import STORE
from util import as_enum, as_int, as_number, as_str, fmt_dt, get_body, parse_dt

bp = Blueprint("contracts", __name__)

CONTRACT_TYPES = {"ENERGY_BLOCK", "RA_CAPACITY", "REC_ONLY", "PPA"}
FORECAST_VARIANTS = {"ADOPTED_PLAN", "ACTUAL_TRUED"}


def _present(body, field):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field '{field}'")
    return body[field]


@bp.post("/cca/supply-contracts")
@require_roles("PortfolioManager")
def create_contract():
    body = get_body(request)
    counterparty = as_str(_present(body, "counterparty"), "counterparty")
    ctype = as_enum(_present(body, "contract_type"), "contract_type", CONTRACT_TYPES)
    dstart = parse_dt(_present(body, "delivery_start"), "delivery_start")
    dend = parse_dt(_present(body, "delivery_end"), "delivery_end")
    if dend <= dstart:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "delivery_end must be strictly after delivery_start")
    capacity = as_number(_present(body, "capacity_mw"), "capacity_mw")
    if float(capacity) <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "capacity_mw must be > 0")
    total_mwh = as_number(_present(body, "total_mwh"), "total_mwh")
    if float(total_mwh) < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "total_mwh must be >= 0")
    price = as_number(_present(body, "price_dollars_per_mwh"), "price_dollars_per_mwh")
    if float(price) < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "price_dollars_per_mwh must be >= 0")
    pct = as_number(_present(body, "rps_eligible_pct"), "rps_eligible_pct")
    if not (0 <= float(pct) <= 1.0):
        raise ApiError(ERR_INVALID_REQUEST, 400, "rps_eligible_pct must lie between 0 and 1.0")
    vintage = as_int(_present(body, "vintage_year"), "vintage_year")
    rec = STORE.new_record()
    rec.update({
        "counterparty": counterparty,
        "contract_type": ctype,
        "delivery_start": fmt_dt(dstart),
        "_delivery_start": dstart,
        "delivery_end": fmt_dt(dend),
        "_delivery_end": dend,
        "capacity_mw": capacity,
        "total_mwh": total_mwh,
        "price_dollars_per_mwh": price,
        "rps_eligible_pct": pct,
        "vintage_year": vintage,
        "status": "NEGOTIATING",
        "termination_fee_cents": 0,
    })
    STORE.contracts[rec["id"]] = rec
    return ok_object(ser_contract(rec), status=201)


@bp.get("/cca/supply-contracts")
@require_roles("PortfolioManager", "FinanceController", "ComplianceOfficer")
def list_contracts():
    items = list(STORE.contracts.values())
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    ct = request.args.get("contract_type")
    if ct is not None:
        items = [c for c in items if c["contract_type"] == ct]
    vy = request.args.get("vintage_year")
    if vy is not None:
        try:
            vy_i = int(vy)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "vintage_year filter must be an integer")
        items = [c for c in items if c["vintage_year"] == vy_i]
    items.sort(key=lambda c: (c["_created_dt"], c["_seq"]))
    return paginate(items, ser_contract)


@bp.get("/cca/supply-contracts/<cid>")
@require_roles("PortfolioManager", "FinanceController", "ComplianceOfficer")
def get_contract(cid):
    return ok_object(ser_contract(get_or_404(STORE.contracts, cid, "SupplyContract")))


@bp.post("/cca/supply-contracts/<cid>/execute")
@require_roles("PortfolioManager")
def execute_contract(cid):
    c = get_or_404(STORE.contracts, cid, "SupplyContract")
    if c["status"] != "NEGOTIATING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"SupplyContract in status {c['status']} cannot be executed")
    if c["_delivery_end"] <= c["_delivery_start"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "delivery_end must be strictly after delivery_start")
    if c["contract_type"] in ("REC_ONLY", "PPA") and float(c["rps_eligible_pct"]) <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "REC_ONLY and PPA contracts require rps_eligible_pct > 0")
    if c["contract_type"] == "RA_CAPACITY":
        if float(c["capacity_mw"]) <= 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "RA_CAPACITY contracts require capacity_mw > 0")
    elif float(c["total_mwh"]) <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Non-RA contracts require total_mwh > 0")
    c["status"] = "EXECUTED"
    STORE.touch(c)
    return ok_object(ser_contract(c))


@bp.post("/cca/supply-contracts/<cid>/terminate")
@require_roles("PortfolioManager")
def terminate_contract(cid):
    c = get_or_404(STORE.contracts, cid, "SupplyContract")
    if c["status"] not in ("EXECUTED", "DELIVERING"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"SupplyContract in status {c['status']} cannot be terminated")
    fee = contract_termination_fee(c, STORE.now())
    c["termination_fee_cents"] = fee
    c["status"] = "TERMINATED"
    STORE.touch(c)
    # Cascade: debit the reserve (clamped); the debit bumps Authority.version by 1.
    reserve_debit(fee)
    return ok_object(ser_contract(c))


@bp.get("/cca/supply-contracts/<cid>/rec-retirements")
@require_roles("ComplianceOfficer", "PortfolioManager")
def contract_recs(cid):
    c = get_or_404(STORE.contracts, cid, "SupplyContract")
    items = [r for r in STORE.recs.values() if r["supply_contract_id"] == c["id"]]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    return paginate(items, ser_rec)


# --- load forecasts -----------------------------------------------------------

@bp.post("/cca/load-forecasts")
@require_roles("PortfolioManager")
def create_forecast():
    body = get_body(request)
    label = as_str(_present(body, "snapshot_label"), "snapshot_label")
    variant = as_enum(_present(body, "forecast_variant"), "forecast_variant", FORECAST_VARIANTS)
    year = as_int(_present(body, "period_year"), "period_year")
    energy, peak, ra, gap = forecast_compute(variant, year)
    rec = STORE.new_record(with_version=False)
    rec.update({
        "snapshot_label": label,
        "forecast_variant": variant,
        "as_of": STORE.now_iso(),
        "period_year": year,
        "total_energy_mwh": energy,
        "coincident_peak_mw": peak,
        "ra_requirement_mw": ra,
        "coverage_gap_mwh": gap,
    })
    STORE.forecasts[rec["id"]] = rec
    return ok_object(ser_forecast(rec), status=201)


@bp.get("/cca/load-forecasts")
@require_roles("PortfolioManager", "RateAnalyst", "FinanceController")
def list_forecasts():
    items = list(STORE.forecasts.values())
    fv = request.args.get("forecast_variant")
    if fv is not None:
        items = [f for f in items if f["forecast_variant"] == fv]
    py = request.args.get("period_year")
    if py is not None:
        try:
            py_i = int(py)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "period_year filter must be an integer")
        items = [f for f in items if f["period_year"] == py_i]
    items.sort(key=lambda f: (f["_created_dt"], f["_seq"]))
    return paginate(items, ser_forecast)


@bp.get("/cca/load-forecasts/<fid>")
@require_roles("PortfolioManager", "RateAnalyst", "FinanceController")
def get_forecast(fid):
    return ok_object(ser_forecast(get_or_404(STORE.forecasts, fid, "LoadForecast")))
