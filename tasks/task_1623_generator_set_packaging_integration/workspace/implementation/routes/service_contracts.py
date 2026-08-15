"""ServiceContract endpoints."""

from datetime import date, timedelta

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services.calculations as calc

bp = Blueprint("service_contracts", __name__)

VALID_PRICING_VARIANTS = {"FLAT_RISK_PREMIUM", "TIME_AND_MATERIALS_EV"}


@bp.route("/genset-packaging/service-contracts", methods=["POST"])
def create_service_contract():
    mw.require_roles("SalesEngineer")
    body = mw.get_json_body()

    order_id = mw.require_string(body, "order_id")
    pricing_variant = mw.require_enum(body, "pricing_variant", VALID_PRICING_VARIANTS)
    term_years = mw.require_int(body, "term_years", minimum=1, maximum=10)
    nameplate_kw = mw.require_int(body, "nameplate_kw", minimum=1)
    pm_interval_days = body.get("pm_interval_days", 90)
    if not isinstance(pm_interval_days, int) or isinstance(pm_interval_days, bool) or pm_interval_days < 30:
        raise errors.invalid_request("pm_interval_days must be an integer >= 30")

    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Package order not found")

    annual_price, total_price = calc.compute_contract_prices(
        pricing_variant, nameplate_kw, term_years, order["site_locale"]
    )

    record = {
        "order_id": order_id,
        "pricing_variant": pricing_variant,
        "term_years": term_years,
        "nameplate_kw": nameplate_kw,
        "pm_interval_days": pm_interval_days,
        "annual_price_cents": annual_price,
        "total_price_cents": total_price,
        "next_pm_due_date": None,
        "end_date": None,
        "status": "QUOTED",
    }
    db.stamp_new(record)
    db.service_contracts[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/service-contracts/<contractId>", methods=["GET"])
def get_service_contract(contractId):
    mw.authenticate()
    record = db.service_contracts.get(contractId)
    if record is None:
        raise errors.not_found("Service contract not found")
    return resp.success_object(record)


@bp.route("/genset-packaging/service-contracts", methods=["GET"])
def list_service_contracts():
    mw.authenticate()
    limit, offset = mw.parse_pagination()

    items = list(db.service_contracts.values())
    val = mw.request.args.get("order_id")
    if val:
        items = [c for c in items if c["order_id"] == val]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.success_list(page, limit, offset, total)


@bp.route("/genset-packaging/service-contracts/<contractId>/bind", methods=["POST"])
def bind_contract(contractId):
    mw.require_roles("SalesEngineer")

    contract = db.service_contracts.get(contractId)
    if contract is None:
        raise errors.not_found("Service contract not found")

    if contract["status"] != "QUOTED":
        raise errors.ApiError(
            errors.ERR_CONTRACT_STATE_INVALID, 409,
            "Contract must be QUOTED to bind",
        )

    order = db.orders.get(contract["order_id"])
    if order is None:
        raise errors.not_found("Package order not found")
    if order["build_status"] == "CANCELLED":
        raise errors.ApiError(
            errors.ERR_INVALID_BUILD_STATE, 409,
            "Order build_status is CANCELLED",
        )

    contract["status"] = "BOUND"
    db.touch(contract)
    return resp.success_object(contract)


@bp.route("/genset-packaging/service-contracts/<contractId>/activate", methods=["POST"])
def activate_contract(contractId):
    mw.require_roles("SalesEngineer")

    contract = db.service_contracts.get(contractId)
    if contract is None:
        raise errors.not_found("Service contract not found")

    if contract["status"] != "BOUND":
        raise errors.ApiError(
            errors.ERR_CONTRACT_STATE_INVALID, 409,
            "Contract must be BOUND to activate",
        )

    # Gate: a CommissioningEvent for this order must be ACCEPTED
    has_accepted = any(
        e["order_id"] == contract["order_id"] and e["status"] == "ACCEPTED"
        for e in db.commissioning_events.values()
    )
    if not has_accepted:
        raise errors.ApiError(
            errors.ERR_COMMISSIONING_NOT_ACCEPTED, 409,
            "A commissioning event for this order must be ACCEPTED to activate a contract",
        )

    today = date.fromisoformat(db.logical_today())
    contract["next_pm_due_date"] = (today + timedelta(days=contract["pm_interval_days"])).isoformat()
    contract["end_date"] = (today + timedelta(days=contract["term_years"] * 365)).isoformat()
    contract["status"] = "ACTIVE"
    db.touch(contract)
    return resp.success_object(contract)


@bp.route("/genset-packaging/service-contracts/<contractId>/cancel", methods=["POST"])
def cancel_contract(contractId):
    mw.require_roles("SalesEngineer")

    contract = db.service_contracts.get(contractId)
    if contract is None:
        raise errors.not_found("Service contract not found")

    if contract["status"] not in ("QUOTED", "BOUND"):
        raise errors.ApiError(
            errors.ERR_CONTRACT_STATE_INVALID, 409,
            "Contract must be QUOTED or BOUND to cancel",
        )

    contract["status"] = "CANCELLED"
    db.touch(contract)
    return resp.success_object(contract)


@bp.route("/genset-packaging/service-contracts/<contractId>/lapse-check", methods=["POST"])
def lapse_check_contract(contractId):
    mw.require_roles("PlatformAdmin")

    contract = db.service_contracts.get(contractId)
    if contract is None:
        raise errors.not_found("Service contract not found")

    if contract["status"] != "ACTIVE":
        raise errors.ApiError(
            errors.ERR_CONTRACT_STATE_INVALID, 409,
            "Contract must be ACTIVE for lapse-check",
        )

    today = date.fromisoformat(db.logical_today())

    if contract["end_date"] is not None and today > date.fromisoformat(contract["end_date"]):
        contract["status"] = "EXPIRED"
        db.touch(contract)
    elif (
        contract["next_pm_due_date"] is not None
        and today > date.fromisoformat(contract["next_pm_due_date"])
        and contract["end_date"] is not None
        and today <= date.fromisoformat(contract["end_date"])
    ):
        contract["status"] = "LAPSED"
        db.touch(contract)
    else:
        raise errors.ApiError(
            errors.ERR_CONTRACT_NOT_LAPSABLE, 422,
            "Neither lapse nor expiry condition holds for the current logical-clock date",
        )

    return resp.success_object(contract)
