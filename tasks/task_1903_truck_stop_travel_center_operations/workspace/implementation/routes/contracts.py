"""Fleet fuel contracts (PRD 3.3; OCC rule contract-amend-stale-version)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_CONTRACT_DISCOUNT_SHORTFALL, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_STALE_VERSION,
)
from middleware import authorized, scope_fleet
from response import success_object
from routes.helpers import list_from, public
from services import pricing
from services.core import FUEL_TYPES, new_record, touch
from util import CLOCK, fmt_dt, parse_dt
from validate import (
    get_body, require_path_resource, valid_dt, valid_int,
)

bp = Blueprint("contracts", __name__)

TIERS = ["T1", "T2", "T3"]
READ_ROLES = ["GeneralManager", "FleetManager"]


def _window_contains_now(contract):
    now = CLOCK.now()
    return parse_dt(contract["effective_from"]) <= now < parse_dt(contract["effective_to"])


@bp.post("/fleet-accounts/<fid>/contracts")
def create_contract(fid):
    authorized(["GeneralManager"])
    fleet = require_path_resource("fleet_accounts", fid)
    body = get_body()
    code = body.get("contract_code")
    if isinstance(code, str) and code:
        for c in db["contracts"].values():
            if c["fleet_account_id"] == fleet["id"] and c["contract_code"] == code:
                raise_error(ERR_INVALID_REQUEST, "contract_code must be unique within the fleet")
    # Final shape validation
    if not isinstance(code, str) or not code:
        raise_error(ERR_INVALID_REQUEST, "contract_code is required")
    tier = body.get("pricing_tier")
    if tier not in TIERS:
        raise_error(ERR_INVALID_REQUEST, "pricing_tier must be T1, T2 or T3")
    discount = body.get("discount_per_gallon_off")
    if not isinstance(discount, (int, float)) or isinstance(discount, bool) or discount < 0:
        raise_error(ERR_INVALID_REQUEST, "discount_per_gallon_off must be a non-negative number")
    fuel_types = body.get("applicable_fuel_types")
    if not isinstance(fuel_types, list) or not fuel_types \
            or any(f not in FUEL_TYPES for f in fuel_types):
        raise_error(ERR_INVALID_REQUEST,
                    "applicable_fuel_types must be a non-empty subset of fuel types")
    eff_from = body.get("effective_from")
    eff_to = body.get("effective_to")
    if not valid_dt(eff_from) or not valid_dt(eff_to):
        raise_error(ERR_INVALID_REQUEST, "effective_from/effective_to must be ISO 8601 datetimes")
    if parse_dt(eff_to) <= parse_dt(eff_from):
        raise_error(ERR_INVALID_REQUEST, "effective_to must be after effective_from")
    rec = new_record("contracts", {
        "fleet_account_id": fleet["id"],
        "contract_code": code,
        "pricing_tier": tier,
        "discount_per_gallon_off": discount,
        "applicable_fuel_types": list(fuel_types),
        "effective_from": fmt_dt(parse_dt(eff_from)),
        "effective_to": fmt_dt(parse_dt(eff_to)),
        "status": "PENDING",
        "volume_delivered_gallons": 0.0,
    })
    return success_object(public(rec), status=201)


@bp.get("/contracts/<rid>")
def get_contract(rid):
    caller = authorized(READ_ROLES)
    contract = require_path_resource("contracts", rid)
    scope_fleet(caller, contract["fleet_account_id"])
    return success_object(public(contract))


@bp.patch("/contracts/<rid>")
def amend_contract(rid):
    authorized(["GeneralManager"])
    contract = require_path_resource("contracts", rid)
    body = get_body()
    # OCC guard: expected_contract_version required; stale -> 412
    if valid_int(body.get("expected_contract_version")):
        if body["expected_contract_version"] != contract["version"]:
            raise_error(ERR_STALE_VERSION,
                        "expected_contract_version does not match contract version")
    new_discount = body.get("discount_per_gallon_off")
    new_to = body.get("effective_to")
    # p34: an amended discount is re-checked against the contract's tier margin
    if isinstance(new_discount, (int, float)) and not isinstance(new_discount, bool) \
            and new_discount >= 0:
        if pricing.discount_exceeds_tier_margin(new_discount, contract["pricing_tier"]):
            raise_error(ERR_CONTRACT_DISCOUNT_SHORTFALL,
                        "discount_per_gallon_off exceeds the tier margin")
    if not valid_int(body.get("expected_contract_version")):
        raise_error(ERR_INVALID_REQUEST, "expected_contract_version is required")
    if new_discount is not None and (not isinstance(new_discount, (int, float))
                                     or isinstance(new_discount, bool) or new_discount < 0):
        raise_error(ERR_INVALID_REQUEST, "discount_per_gallon_off must be a non-negative number")
    if new_to is not None and not valid_dt(new_to):
        raise_error(ERR_INVALID_REQUEST, "effective_to must be an ISO 8601 datetime")
    changed = False
    if new_discount is not None and new_discount != contract["discount_per_gallon_off"]:
        contract["discount_per_gallon_off"] = new_discount
        changed = True
    if new_to is not None and fmt_dt(parse_dt(new_to)) != contract["effective_to"]:
        contract["effective_to"] = fmt_dt(parse_dt(new_to))
        changed = True
    # A carried amendment bumps the contract version by exactly 1 (SCAFFOLD 1.2.1)
    touch(contract)
    return success_object(public(contract))


@bp.post("/contracts/<rid>/activate")
def activate_contract(rid):
    authorized(["GeneralManager"])
    contract = require_path_resource("contracts", rid)
    if contract["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "contract is not PENDING")
    if not _window_contains_now(contract):
        raise_error(ERR_INVALID_STATE, "current clock is outside the contract window")
    fleet = db["fleet_accounts"].get(contract["fleet_account_id"])
    if fleet is None or fleet["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "owning fleet is not ACTIVE")
    contract["status"] = "ACTIVE"
    touch(contract)
    return success_object(public(contract))


@bp.post("/contracts/<rid>/suspend")
def suspend_contract(rid):
    authorized(["GeneralManager"])
    contract = require_path_resource("contracts", rid)
    if contract["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "contract is not ACTIVE")
    contract["status"] = "SUSPENDED"
    touch(contract)
    return success_object(public(contract))


@bp.post("/contracts/<rid>/resume")
def resume_contract(rid):
    authorized(["GeneralManager"])
    contract = require_path_resource("contracts", rid)
    if contract["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "contract is not SUSPENDED")
    if not _window_contains_now(contract):
        raise_error(ERR_INVALID_STATE, "current clock is outside the contract window")
    fleet = db["fleet_accounts"].get(contract["fleet_account_id"])
    if fleet is None or fleet["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "owning fleet is not ACTIVE")
    contract["status"] = "ACTIVE"
    touch(contract)
    return success_object(public(contract))


@bp.post("/contracts/<rid>/expire")
def expire_contract(rid):
    authorized(["GeneralManager"])
    contract = require_path_resource("contracts", rid)
    if contract["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_INVALID_STATE, "contract is not ACTIVE or SUSPENDED")
    contract["status"] = "EXPIRED"
    touch(contract)
    return success_object(public(contract))


@bp.post("/contracts/<rid>/terminate")
def terminate_contract(rid):
    authorized(["GeneralManager"])
    contract = require_path_resource("contracts", rid)
    if contract["status"] not in ("PENDING", "ACTIVE", "SUSPENDED"):
        raise_error(ERR_INVALID_STATE, "contract cannot be terminated from its current state")
    contract["status"] = "TERMINATED"
    touch(contract)
    return success_object(public(contract))


@bp.get("/contracts/<rid>/fuel-sales")
def contract_fuel_sales(rid):
    caller = authorized(READ_ROLES)
    contract = require_path_resource("contracts", rid)
    scope_fleet(caller, contract["fleet_account_id"])
    sales = [s for s in db["fuel_sales"].values() if s["contract_id"] == contract["id"]]
    return list_from(sales)
