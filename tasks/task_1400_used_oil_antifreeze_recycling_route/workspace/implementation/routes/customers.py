"""Customer endpoints (PRD §3.1)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CUSTOMER_NOT_ACTIVE,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_CUSTOMER_NOT_PROSPECT,
    ERR_CUSTOMER_NOT_SUSPENDED,
    ERR_NO_SERVICEABLE_TANK,
    ERR_OUTSTANDING_BALANCE,
    ERR_UNRETURNED_PREPAID_BALANCE,
)
from middleware import get_body, req_enum, req_int, req_str, require_roles
from response import success_list, success_object
from services import cascades

bp = Blueprint("customers", __name__)

MARKET_ZONES = {"NORTH", "SOUTH", "COASTAL"}
CREDIT_TERMS = {"PREPAY", "NET30", "CHARGE_ONLY"}
READ_ROLES = ("RoutePlanner", "SettlementClerk", "EHSOfficer", "Regulator")


def get_customer_or_404(customer_id):
    customer = db.get("customers", customer_id)
    if customer is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "Customer id not found", 404)
    return customer


@bp.post("/customers")
@require_roles("RoutePlanner")
def create_customer():
    body = get_body()
    legal_name = req_str(body, "legal_name")
    epa_generator_id = req_str(body, "epa_generator_id")
    market_zone = req_enum(body, "market_zone", MARKET_ZONES)
    credit_terms = req_enum(body, "credit_terms", CREDIT_TERMS)
    customer = db.create_entity("customers", {
        "legal_name": legal_name,
        "epa_generator_id": epa_generator_id,
        "market_zone": market_zone,
        "credit_terms": credit_terms,
        "prepaid_balance_cents": 0,
        "outstanding_charge_cents": 0,
        "halogen_violation_count": 0,
        "status": "PROSPECT",
    })
    return success_object(db.serialize(customer), 201)


@bp.get("/customers")
@require_roles(*READ_ROLES)
def list_customers():
    items = db.all_entities("customers")
    status = request.args.get("status")
    market_zone = request.args.get("market_zone")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if market_zone is not None:
        items = [c for c in items if c["market_zone"] == market_zone]
    return success_list([db.serialize(c) for c in db.sorted_created(items)])


@bp.get("/customers/<customerId>")
@require_roles(*READ_ROLES)
def get_customer(customerId):
    return success_object(db.serialize(get_customer_or_404(customerId)))


@bp.post("/customers/<customerId>/activate")
@require_roles("RoutePlanner")
def activate_customer(customerId):
    customer = get_customer_or_404(customerId)
    if customer["status"] != "PROSPECT":
        raise ApiError(ERR_CUSTOMER_NOT_PROSPECT, "Activate requires PROSPECT", 409)
    serviceable = any(
        tank["ownership_status"] == "INSTALLED"
        for site in cascades.sites_of_customer(customer["id"])
        for tank in cascades.tanks_of_site(site["id"])
    )
    if not serviceable:
        raise ApiError(
            ERR_NO_SERVICEABLE_TANK,
            "Customer has no INSTALLED tank at any site",
            409,
        )
    customer["status"] = "ACTIVE"
    db.touch(customer)
    return success_object(db.serialize(customer))


@bp.post("/customers/<customerId>/suspend")
@require_roles("RoutePlanner")
def suspend_customer(customerId):
    customer = get_customer_or_404(customerId)
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_NOT_ACTIVE, "Suspend requires ACTIVE customer", 409)
    customer["status"] = "SUSPENDED"
    db.touch(customer)
    cascades.cascade_customer_suspend(customer)
    return success_object(db.serialize(customer))


@bp.post("/customers/<customerId>/reinstate")
@require_roles("RoutePlanner")
def reinstate_customer(customerId):
    customer = get_customer_or_404(customerId)
    if customer["status"] != "SUSPENDED":
        raise ApiError(ERR_CUSTOMER_NOT_SUSPENDED, "Reinstate requires SUSPENDED", 409)
    if customer["outstanding_charge_cents"] != 0:
        raise ApiError(
            ERR_OUTSTANDING_BALANCE,
            "Operation requires outstanding_charge_cents == 0",
            402,
        )
    customer["status"] = "ACTIVE"
    db.touch(customer)
    cascades.cascade_customer_reinstate(customer)
    return success_object(db.serialize(customer))


@bp.post("/customers/<customerId>/terminate")
@require_roles("RoutePlanner")
def terminate_customer(customerId):
    customer = get_customer_or_404(customerId)
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_NOT_ACTIVE, "Terminate requires ACTIVE customer", 409)
    if customer["outstanding_charge_cents"] != 0:
        raise ApiError(
            ERR_OUTSTANDING_BALANCE,
            "Operation requires outstanding_charge_cents == 0",
            402,
        )
    if customer["prepaid_balance_cents"] != 0:
        raise ApiError(
            ERR_UNRETURNED_PREPAID_BALANCE,
            "Terminate requires prepaid_balance_cents == 0",
            402,
        )
    customer["status"] = "TERMINATED"
    db.touch(customer)
    cascades.cascade_customer_terminate(customer)
    return success_object(db.serialize(customer))


@bp.post("/customers/<customerId>/top-up")
@require_roles("SettlementClerk")
def top_up_customer(customerId):
    customer = get_customer_or_404(customerId)
    body = get_body()
    amount = req_int(body, "amount_cents")
    customer["prepaid_balance_cents"] += amount
    db.touch(customer)
    return success_object(db.serialize(customer))


@bp.get("/customers/<customerId>/tank-sites")
@require_roles("RoutePlanner", "SettlementClerk", "EHSOfficer", "Regulator", "TankInstaller", "Driver")
def list_customer_tank_sites(customerId):
    get_customer_or_404(customerId)
    items = [s for s in db.all_entities("tank_sites") if s["customer_id"] == customerId]
    return success_list([db.serialize(s) for s in db.sorted_created(items)])
