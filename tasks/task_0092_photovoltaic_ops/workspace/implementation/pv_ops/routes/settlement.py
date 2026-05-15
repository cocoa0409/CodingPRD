"""Settlement period, metering, investor share, and revenue endpoints."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from flask import Blueprint, current_app, g

from pv_ops.auth import require_roles
from pv_ops.errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_INVESTOR_SHARES_INVALID,
    ERR_INVOICE_DUPLICATE,
    ERR_MARKET_PRICE_REQUIRED,
    ERR_MARKET_TRADING_DISABLED,
    ERR_NO_METERING_RECORDS,
    ERR_NOT_FOUND,
    ERR_PERIOD_NOT_ENDED,
    ERR_RECONCILIATION_OUT_OF_TOLERANCE,
    ERR_SETTLEMENT_PERIOD_OVERLAP,
    ERR_UNIQUE_VIOLATION,
    ERR_VALIDATION,
)
from pv_ops.responses import created, success
from pv_ops.services import serializers
from pv_ops.services.audit import write_audit
from pv_ops.services.settlement import (
    _InvestorSharesInvalid,
    compute_final_revenue,
    compute_provisional_revenue,
    distribute_revenue,
    distributions_for,
    metering_lines_for,
    overlapping_confirmed_exists,
)
from pv_ops.utils import (
    D,
    fmt_dt,
    get_body,
    opt_number,
    parse_dt,
    require_enum,
    require_field,
    require_number,
    require_str,
    round_half_up,
)


bp = Blueprint("settlement", __name__)


# ---- Settlement period creation ----
@bp.route("/pv-ops/stations/<station_id>/settlement-periods", methods=["POST"])
@require_roles("FinanceOfficer")
def create_period(station_id: str):
    body = get_body()
    period_start = parse_dt(body.get("period_start"), "period_start")
    period_end = parse_dt(body.get("period_end"), "period_end")
    if period_end <= period_start:
        raise APIError(ERR_VALIDATION, 422, "period_end must be after period_start")

    store = current_app.extensions["store"]
    with store.lock:
        if station_id not in store.stations:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")
        # Uniqueness on (station_id, period_start, period_end)
        for sp in store.settlement_periods.values():
            if sp.get("station_id") == station_id and sp.get("period_start") == fmt_dt(period_start) and sp.get("period_end") == fmt_dt(period_end):
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "Settlement period already exists")
        row = {
            "station_id": station_id,
            "period_start": fmt_dt(period_start),
            "period_end": fmt_dt(period_end),
            "provisional_revenue_cny": None,
            "final_revenue_cny": None,
            "grid_company_confirmed_kwh": None,
            "state": "DRAFT",
            "invoice_no": None,
        }
        store.insert_common(row)
        store.settlement_periods[row["id"]] = row
        return created(serializers.settlement_view(row, distributions=[]))


# ---- Metering records ----
@bp.route("/pv-ops/stations/<station_id>/metering", methods=["POST"])
@require_roles("FinanceOfficer")
def create_metering(station_id: str):
    body = get_body()
    settlement_period_id = require_str(body, "settlement_period_id")
    window_start = parse_dt(body.get("window_start"), "window_start")
    window_end = parse_dt(body.get("window_end"), "window_end")
    on_grid_kwh = require_number(body, "on_grid_kwh", ge=0.0)
    pricing_channel = require_enum(body, "pricing_channel", {"FEED_IN", "MARKET_TRADING"})
    market_price = opt_number(body, "market_price_cny_per_kwh", ge=0.0)

    store = current_app.extensions["store"]
    with store.lock:
        station = store.stations.get(station_id)
        if not station:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")
        period = store.settlement_periods.get(settlement_period_id)
        if not period:
            raise APIError(ERR_NOT_FOUND, 404, "Settlement period not found")
        if period.get("station_id") != station_id:
            raise APIError(ERR_NOT_FOUND, 404, "Settlement period does not belong to station")
        if window_end <= window_start:
            raise APIError(ERR_VALIDATION, 422, "window_end must be after window_start")
        if pricing_channel == "MARKET_TRADING":
            if not station.get("market_trading_enabled"):
                raise APIError(ERR_MARKET_TRADING_DISABLED, 422, "Market trading not enabled on station")
            if market_price is None:
                raise APIError(ERR_MARKET_PRICE_REQUIRED, 422, "market_price_cny_per_kwh required")
        row = {
            "station_id": station_id,
            "settlement_period_id": settlement_period_id,
            "window_start": fmt_dt(window_start),
            "window_end": fmt_dt(window_end),
            "on_grid_kwh": float(round_half_up(on_grid_kwh, 3)),
            "pricing_channel": pricing_channel,
            "market_price_cny_per_kwh": float(market_price) if market_price is not None else None,
        }
        store.insert_lite(row)
        store.metering_records[row["id"]] = row
        return created(serializers.metering_view(row))


# ---- Start reconciliation ----
@bp.route("/pv-ops/settlement-periods/<period_id>/start-reconciliation", methods=["POST"])
@require_roles("FinanceOfficer")
def start_reconciliation(period_id: str):
    body = get_body()
    confirmed_kwh = require_number(body, "grid_company_confirmed_kwh", ge=0.0)
    store = current_app.extensions["store"]
    with store.lock:
        period = store.settlement_periods.get(period_id)
        if not period:
            raise APIError(ERR_NOT_FOUND, 404, "Settlement period not found")
        if period.get("state") != "DRAFT":
            raise APIError(ERR_INVALID_STATE, 409, "Settlement period must be DRAFT")
        # period_end <= now
        now = store.clock.now()
        period_end = parse_dt(period["period_end"], "period_end")
        if now < period_end:
            raise APIError(ERR_PERIOD_NOT_ENDED, 422, "period_end has not been reached")
        # at least one MeteringRecord
        if not metering_lines_for(store, period_id):
            raise APIError(ERR_NO_METERING_RECORDS, 422, "No metering records for this period")
        period["grid_company_confirmed_kwh"] = float(round_half_up(confirmed_kwh, 3))
        period["state"] = "RECONCILING"
        provisional = compute_provisional_revenue(store, period)
        period["provisional_revenue_cny"] = float(provisional)
        store.bump(period)
        return success(serializers.settlement_view(period, distributions=distributions_for(store, period_id)))


# ---- Confirm ----
@bp.route("/pv-ops/settlement-periods/<period_id>/confirm", methods=["POST"])
@require_roles("FinanceOfficer")
def confirm_period(period_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        period = store.settlement_periods.get(period_id)
        if not period:
            raise APIError(ERR_NOT_FOUND, 404, "Settlement period not found")
        if period.get("state") != "RECONCILING":
            raise APIError(ERR_INVALID_STATE, 409, "Settlement period must be RECONCILING")
        # Tolerance check
        lines = metering_lines_for(store, period_id)
        raw_total = sum((D(m["on_grid_kwh"]) for m in lines), start=D(0))
        confirmed = D(period["grid_company_confirmed_kwh"])
        denom = raw_total if raw_total > D("0.001") else D("0.001")
        diff_ratio = abs(raw_total - confirmed) / denom
        if diff_ratio > D("0.005"):
            raise APIError(ERR_RECONCILIATION_OUT_OF_TOLERANCE, 422, "Reconciliation out of tolerance")
        # Overlap check
        if overlapping_confirmed_exists(store, period):
            raise APIError(ERR_SETTLEMENT_PERIOD_OVERLAP, 409, "Overlapping CONFIRMED period exists")

        before = {
            "state": period["state"],
            "provisional_revenue_cny": period.get("provisional_revenue_cny"),
            "final_revenue_cny": period.get("final_revenue_cny"),
        }

        # Compute final + distributions
        final = compute_final_revenue(store, period)
        try:
            dist_rows = distribute_revenue(store, period, final)
        except _InvestorSharesInvalid:
            raise APIError(ERR_INVESTOR_SHARES_INVALID, 422, "Active investor shares do not sum to 10000")

        period["state"] = "CONFIRMED"
        period["final_revenue_cny"] = float(final)
        store.bump(period)

        for d in dist_rows:
            store.insert_lite(d)
            store.revenue_distributions[d["id"]] = d

        write_audit(
            store,
            actor_id=g.user_id,
            actor_role=g.user_role,
            target_type="SETTLEMENT",
            target_id=period["id"],
            action="SETTLEMENT_CONFIRM",
            before_value=before,
            after_value={
                "state": period["state"],
                "provisional_revenue_cny": period.get("provisional_revenue_cny"),
                "final_revenue_cny": period.get("final_revenue_cny"),
            },
        )
        return success(serializers.settlement_view(period, distributions=distributions_for(store, period_id)))


# ---- Dispute ----
@bp.route("/pv-ops/settlement-periods/<period_id>/dispute", methods=["POST"])
@require_roles("FinanceOfficer")
def dispute_period(period_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        period = store.settlement_periods.get(period_id)
        if not period:
            raise APIError(ERR_NOT_FOUND, 404, "Settlement period not found")
        if period.get("state") != "RECONCILING":
            raise APIError(ERR_INVALID_STATE, 409, "Settlement period must be RECONCILING to dispute")
        before = {"state": period["state"]}
        period["state"] = "DISPUTED"
        store.bump(period)
        write_audit(
            store,
            actor_id=g.user_id,
            actor_role=g.user_role,
            target_type="SETTLEMENT",
            target_id=period["id"],
            action="SETTLEMENT_DISPUTE",
            before_value=before,
            after_value={"state": period["state"]},
        )
        return success(serializers.settlement_view(period, distributions=distributions_for(store, period_id)))


# ---- Issue invoice ----
@bp.route("/pv-ops/settlement-periods/<period_id>/issue-invoice", methods=["POST"])
@require_roles("FinanceOfficer")
def issue_invoice(period_id: str):
    body = get_body()
    invoice_no = require_str(body, "invoice_no")
    store = current_app.extensions["store"]
    with store.lock:
        period = store.settlement_periods.get(period_id)
        if not period:
            raise APIError(ERR_NOT_FOUND, 404, "Settlement period not found")
        if period.get("state") != "CONFIRMED":
            raise APIError(ERR_INVALID_STATE, 409, "Settlement period must be CONFIRMED")
        for sp in store.settlement_periods.values():
            if sp["id"] == period_id:
                continue
            if sp.get("invoice_no") == invoice_no:
                raise APIError(ERR_INVOICE_DUPLICATE, 409, "invoice_no already used")
        period["state"] = "INVOICED"
        period["invoice_no"] = invoice_no
        store.bump(period)
        return success(serializers.settlement_view(period, distributions=distributions_for(store, period_id)))


# ---- Revenue adjustment ----
@bp.route("/pv-ops/settlement-periods/<period_id>/revenue-adjust", methods=["POST"])
@require_roles("FinanceOfficer")
def revenue_adjust(period_id: str):
    body = get_body()
    reason = require_str(body, "reason")
    store = current_app.extensions["store"]
    with store.lock:
        period = store.settlement_periods.get(period_id)
        if not period:
            raise APIError(ERR_NOT_FOUND, 404, "Settlement period not found")
        if period.get("state") != "CONFIRMED":
            raise APIError(ERR_INVALID_STATE, 409, "Settlement period must be CONFIRMED")
        # Block if downstream subsidy declarations are active
        for decl in store.subsidy_declarations.values():
            if decl.get("settlement_period_id") == period_id and decl.get("state") in ("SUBMITTED", "APPROVED", "RECEIVED"):
                raise APIError(ERR_INVALID_STATE, 409, "Subsidy declaration locks this period")
        before = {
            "state": period["state"],
            "final_revenue_cny": period.get("final_revenue_cny"),
            "distributions": [
                deepcopy(d) for d in distributions_for(store, period_id)
            ],
        }
        # Delete distributions
        to_del = [d["id"] for d in distributions_for(store, period_id)]
        for did in to_del:
            del store.revenue_distributions[did]
        period["state"] = "RECONCILING"
        period["final_revenue_cny"] = None
        provisional = compute_provisional_revenue(store, period)
        period["provisional_revenue_cny"] = float(provisional)
        store.bump(period)
        write_audit(
            store,
            actor_id=g.user_id,
            actor_role=g.user_role,
            target_type="SETTLEMENT",
            target_id=period["id"],
            action="REVENUE_ADJUST",
            before_value=before,
            after_value={
                "state": period["state"],
                "final_revenue_cny": None,
                "provisional_revenue_cny": period.get("provisional_revenue_cny"),
                "reason": reason,
            },
        )
        return success(serializers.settlement_view(period, distributions=distributions_for(store, period_id)))


# ---- Get a period ----
@bp.route("/pv-ops/settlement-periods/<period_id>", methods=["GET"])
@require_roles("PlatformAdmin", "FinanceOfficer")
def get_period(period_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        period = store.settlement_periods.get(period_id)
        if not period:
            raise APIError(ERR_NOT_FOUND, 404, "Settlement period not found")
        return success(serializers.settlement_view(period, distributions=distributions_for(store, period_id)))


# ---- Investor shares ----
@bp.route("/pv-ops/stations/<station_id>/investor-shares", methods=["POST"])
@require_roles("PlatformAdmin")
def create_investor_share(station_id: str):
    body = get_body()
    investor_name = require_str(body, "investor_name")
    bps = require_field(body, "share_basis_points")
    if not isinstance(bps, int) or isinstance(bps, bool) or bps < 1 or bps > 10000:
        raise APIError(ERR_VALIDATION, 422, "share_basis_points must be 1..10000")
    effective_from = parse_dt(body.get("effective_from"), "effective_from")
    effective_to = body.get("effective_to")
    if effective_to is not None:
        effective_to = parse_dt(effective_to, "effective_to")
    store = current_app.extensions["store"]
    with store.lock:
        if station_id not in store.stations:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")
        row = {
            "station_id": station_id,
            "investor_name": investor_name,
            "share_basis_points": bps,
            "effective_from": fmt_dt(effective_from),
            "effective_to": fmt_dt(effective_to) if effective_to else None,
        }
        store.insert_common(row)
        store.investor_shares[row["id"]] = row
        return created(serializers.investor_share_view(row))
