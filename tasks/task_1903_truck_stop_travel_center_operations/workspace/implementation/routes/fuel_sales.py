"""Fuel sale lifecycle (PRD 3.2): authorize, dispensing, finalize, pay, void."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_CONTRACT_DISCOUNT_SHORTFALL, ERR_CONTRACT_FUEL_TYPE,
    ERR_CONTRACT_NOT_ACTIVE, ERR_CREDIT_LIMIT_EXCEEDED, ERR_FLEET_NOT_ACTIVE,
    ERR_INVALID_PRICING_MODE, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_MEMBER_NOT_ACTIVE, ERR_NO_ACTIVE_PRICE, ERR_NO_POINTS,
    ERR_NOT_FOUND, ERR_PUMP_NOT_AVAILABLE, ERR_SHIFT_NOT_OPEN,
)
from middleware import authorized, scope_fleet, scope_member
from response import success_object
from routes.helpers import list_response, public
from services import loyalty, pricing
from services.core import (
    FUEL_TYPES, diesel_tank_for_site, new_record,
    recompute_fleet_rolling_and_tier, select_active_price, stamp, touch,
    adjust_shift_expected,
)
from util import CLOCK, dec, parse_dt, rhu_float
from validate import (
    get_body, query_filter, require_path_resource, valid_enum, valid_int,
    valid_nonneg_int, valid_pos_number,
)

bp = Blueprint("fuel_sales", __name__)

PRICING_MODES = ["RETAIL", "CONTRACT"]
TENDER_TYPES = ["CASH", "CARD", "FLEET_BILLING"]
SALE_STATUSES = ["AUTHORIZED", "FUELING", "PENDING_FINALIZE", "COMPLETED", "VOIDED"]
READ_ROLES = ["GeneralManager", "FuelDeskLead", "ShiftManager", "Cashier"]


def _fk(collection, body, field):
    """Priority 6: present-but-unresolvable body FK -> 404; absent -> None."""
    v = body.get(field)
    if v is None:
        return None
    obj = db[collection].get(v) if isinstance(v, str) else None
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"body reference {field} does not resolve: {v}")
    return obj


@bp.post("/sites/<sid>/fuel-sales")
def authorize_fuel_sale(sid):
    caller = authorized(["Cashier", "FuelDeskLead"])
    # Priority 5: path existence
    site = require_path_resource("sites", sid)
    body = get_body()

    # Priority 6: body FK existence
    pump = _fk("pumps", body, "pump_id")
    shift = _fk("shifts", body, "shift_id")
    member = _fk("loyalty_members", body, "loyalty_member_id")
    fleet = _fk("fleet_accounts", body, "fleet_account_id")
    contract = _fk("contracts", body, "contract_id")

    pricing_mode = body.get("pricing_mode")
    fuel_type = body.get("fuel_type")
    tender_type = body.get("tender_type")
    requested = body.get("requested_redeem_points")
    max_gallons = body.get("max_gallons")
    now = CLOCK.now()

    # --- State guards (SCAFFOLD priorities 7-14) -----------------------------
    # p8: pump IDLE and serves the requested fuel type
    if pump is not None:
        if pump["status"] != "IDLE":
            raise_error(ERR_PUMP_NOT_AVAILABLE, "pump is not IDLE")
        if valid_enum(fuel_type, FUEL_TYPES) and fuel_type not in pump["fuel_types"]:
            raise_error(ERR_PUMP_NOT_AVAILABLE, "pump does not serve the requested fuel type")
    # p9: attribution shift must be OPEN
    if shift is not None and shift["status"] != "OPEN":
        raise_error(ERR_SHIFT_NOT_OPEN, "attribution shift is not OPEN")
    # p11: contract sale requires an ACTIVE fleet
    if pricing_mode == "CONTRACT" and fleet is not None and fleet["status"] != "ACTIVE":
        raise_error(ERR_FLEET_NOT_ACTIVE, "fleet account is not ACTIVE")
    # p12: contract must be ACTIVE with the clock inside its window
    if pricing_mode == "CONTRACT" and contract is not None:
        if contract["status"] != "ACTIVE":
            raise_error(ERR_CONTRACT_NOT_ACTIVE, "contract is not ACTIVE")
        if not (parse_dt(contract["effective_from"]) <= now < parse_dt(contract["effective_to"])):
            raise_error(ERR_CONTRACT_NOT_ACTIVE, "current clock outside the contract window")
    # p14: member must be ACTIVE when points are requested
    if member is not None and valid_nonneg_int(requested) and requested > 0 \
            and member["status"] != "ACTIVE":
        raise_error(ERR_MEMBER_NOT_ACTIVE, "loyalty member is not ACTIVE")

    # --- Business rules (SCAFFOLD priorities 15-40) --------------------------
    # p16: pricing-mode coherence
    if valid_enum(pricing_mode, PRICING_MODES):
        if pricing_mode == "CONTRACT" and (fleet is None or contract is None):
            raise_error(ERR_INVALID_PRICING_MODE,
                        "CONTRACT pricing requires fleet_account_id and contract_id")
        if pricing_mode == "RETAIL" and (fleet is not None or contract is not None):
            raise_error(ERR_INVALID_PRICING_MODE,
                        "RETAIL pricing forbids fleet_account_id and contract_id")
        if tender_type == "FLEET_BILLING" and pricing_mode != "CONTRACT":
            raise_error(ERR_INVALID_PRICING_MODE,
                        "FLEET_BILLING tender is lawful only on a CONTRACT sale")
    # p18: contract fuel type coverage
    if pricing_mode == "CONTRACT" and contract is not None \
            and valid_enum(fuel_type, FUEL_TYPES) \
            and fuel_type not in contract["applicable_fuel_types"]:
        raise_error(ERR_CONTRACT_FUEL_TYPE,
                    "requested fuel_type is not covered by the contract")
    # p23: price existence — retail pump price / contract diesel rack
    retail_price = None
    tank = None
    if pricing_mode == "RETAIL" and valid_enum(fuel_type, FUEL_TYPES):
        retail_price = select_active_price(site["id"], fuel_type, now)
        if retail_price is None:
            raise_error(ERR_NO_ACTIVE_PRICE,
                        "no ACTIVE effective-now price for the requested fuel type")
    if pricing_mode == "CONTRACT":
        tank = diesel_tank_for_site(site["id"])
        if tank is None or tank.get("rack_price_cents_per_gallon_4dp") is None:
            raise_error(ERR_NO_ACTIVE_PRICE, "no diesel rack price available at the site")
    # p33: redeemable balance covers requested points
    if member is not None and valid_nonneg_int(requested) and requested > 0:
        if loyalty.redeemable_balance(member["id"], now) < requested:
            raise_error(ERR_NO_POINTS, "requested points exceed the redeemable balance")
    # p34: contract discount may not exceed the tier margin
    if pricing_mode == "CONTRACT" and contract is not None:
        if pricing.discount_exceeds_tier_margin(contract["discount_per_gallon_off"],
                                                contract["pricing_tier"]):
            raise_error(ERR_CONTRACT_DISCOUNT_SHORTFALL,
                        "discount_per_gallon_off exceeds the tier margin")

    # --- Final shape validation (priority 41) --------------------------------
    if pump is None:
        raise_error(ERR_INVALID_REQUEST, "pump_id is required")
    if shift is None:
        raise_error(ERR_INVALID_REQUEST, "shift_id is required")
    if not valid_enum(pricing_mode, PRICING_MODES):
        raise_error(ERR_INVALID_REQUEST, "pricing_mode must be RETAIL or CONTRACT")
    if not valid_enum(fuel_type, FUEL_TYPES):
        raise_error(ERR_INVALID_REQUEST, "fuel_type must be a declared fuel type")
    if not valid_enum(tender_type, TENDER_TYPES):
        raise_error(ERR_INVALID_REQUEST, "tender_type must be CASH, CARD or FLEET_BILLING")
    if max_gallons is not None and not valid_pos_number(max_gallons):
        raise_error(ERR_INVALID_REQUEST, "max_gallons must be a positive number")
    if requested is not None and not valid_nonneg_int(requested):
        raise_error(ERR_INVALID_REQUEST, "requested_redeem_points must be a non-negative integer")
    max_gallons = 200.0 if max_gallons is None else rhu_float(max_gallons, 3)
    requested = 0 if requested is None else requested
    if requested > 0 and member is None:
        raise_error(ERR_INVALID_REQUEST,
                    "requested_redeem_points requires a loyalty_member_id")

    # --- Quote computation (snapshots pinned at authorize) -------------------
    points_capped = pricing.capped_points(requested, member)
    if pricing_mode == "RETAIL":
        network_disc = pricing.network_discount_for(member["id"], fuel_type) if member else dec("0")
        unit = pricing.retail_unit_cents(retail_price["retail_cents_per_gallon"],
                                         network_disc, points_capped)
        snapshots = {
            "retail_price_snapshot": retail_price["retail_cents_per_gallon"],
            "network_discount_snapshot": float(network_disc),
            "contract_discount_snapshot": None,
            "contract_rate_snapshot_cents": None,
        }
    else:
        rate_cents = pricing.contract_rate_cents(tank["rack_price_cents_per_gallon_4dp"],
                                                 contract["pricing_tier"])
        unit = pricing.contract_unit_cents(rate_cents, contract["discount_per_gallon_off"],
                                           points_capped)
        snapshots = {
            "retail_price_snapshot": None,
            "network_discount_snapshot": 0,
            "contract_discount_snapshot": contract["discount_per_gallon_off"],
            "contract_rate_snapshot_cents": rate_cents,
        }
    provisional_total = pricing.fuel_amount_cents(unit, max_gallons)

    # p35: fleet credit ceiling on the projected balance
    if pricing_mode == "CONTRACT":
        if fleet["current_balance_cents"] + provisional_total > fleet["credit_limit_cents"]:
            raise_error(ERR_CREDIT_LIMIT_EXCEEDED,
                        "projected balance exceeds the fleet credit limit")

    sale = new_record("fuel_sales", {
        "site_id": site["id"],
        "pump_id": pump["id"],
        "shift_id": shift["id"],
        "loyalty_member_id": member["id"] if member else None,
        "fleet_account_id": fleet["id"] if fleet else None,
        "contract_id": contract["id"] if contract else None,
        "pricing_mode": pricing_mode,
        "fuel_type": fuel_type,
        "tender_type": tender_type,
        "status": "AUTHORIZED",
        "payment_status": "UNPAID",
        "max_gallons": max_gallons,
        "requested_redeem_points": requested,
        "stack_cap_snapshot": member["stack_cap_points"] if member else None,
        "authorized_quote_cents_per_gallon": unit,
        "provisional_fuel_total_cents": provisional_total,
        "dispensed_gallons": None,
        "final_unit_price_cents": None,
        "fuel_amount_cents": None,
        "total_cents": None,
        "tax_cents": 0,
        "points_redeemed": None,
        "points_discount_cents": None,
        "points_earned": None,
        "finalized_at": None,
        "void_reason": None,
        "_pay_tender": None,
        **snapshots,
    })
    pump["status"] = "IN_USE"
    touch(pump)
    return success_object(public(sale), status=201)


@bp.get("/sites/<sid>/fuel-sales")
def list_fuel_sales(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {
        "site_id": sid,
        "status": query_filter("status", SALE_STATUSES),
        "pricing_mode": query_filter("pricing_mode", PRICING_MODES),
    }
    return list_response("fuel_sales", filters)


@bp.get("/fuel-sales/<rid>")
def get_fuel_sale(rid):
    caller = authorized(READ_ROLES + ["LoyaltyMember", "FleetManager"])
    sale = require_path_resource("fuel_sales", rid)
    scope_member(caller, sale["loyalty_member_id"])
    scope_fleet(caller, sale["fleet_account_id"])
    return success_object(public(sale))


@bp.post("/fuel-sales/<rid>/dispensing-start")
def dispensing_start(rid):
    authorized(["Cashier", "FuelDeskLead"])
    sale = require_path_resource("fuel_sales", rid)
    if sale["status"] != "AUTHORIZED":
        raise_error(ERR_INVALID_STATE, "sale is not AUTHORIZED")
    sale["status"] = "FUELING"
    touch(sale)
    return success_object(public(sale))


@bp.post("/fuel-sales/<rid>/dispensing-complete")
def dispensing_complete(rid):
    authorized(["Cashier", "FuelDeskLead"])
    sale = require_path_resource("fuel_sales", rid)
    if sale["status"] != "FUELING":
        raise_error(ERR_INVALID_STATE, "sale is not FUELING")
    body = get_body()
    dispensed = body.get("dispensed_gallons")
    if not valid_pos_number(dispensed):
        raise_error(ERR_INVALID_REQUEST, "dispensed_gallons must be a positive number")
    if dec(dispensed) > dec(sale["max_gallons"]):
        raise_error(ERR_INVALID_REQUEST, "dispensed_gallons exceeds the authorized max_gallons")
    sale["dispensed_gallons"] = rhu_float(dispensed, 3)
    sale["status"] = "PENDING_FINALIZE"
    touch(sale)
    pump = db["pumps"].get(sale["pump_id"])
    if pump is not None and pump["status"] == "IN_USE":
        pump["status"] = "IDLE"
        touch(pump)
    return success_object(public(sale))


def _final_unit_from_snapshots(sale):
    """Recompute the final unit price exclusively from pinned snapshots."""
    points = pricing.capped_points(sale["requested_redeem_points"],
                                   {"stack_cap_points": sale["stack_cap_snapshot"]}
                                   if sale["stack_cap_snapshot"] is not None else None)
    if sale["pricing_mode"] == "RETAIL":
        return pricing.retail_unit_cents(sale["retail_price_snapshot"],
                                         sale["network_discount_snapshot"], points)
    return pricing.contract_unit_cents(sale["contract_rate_snapshot_cents"],
                                       sale["contract_discount_snapshot"], points)


@bp.post("/fuel-sales/<rid>/finalize")
def finalize_sale(rid):
    authorized(["Cashier", "FuelDeskLead"])
    sale = require_path_resource("fuel_sales", rid)
    if sale["status"] != "PENDING_FINALIZE":
        raise_error(ERR_INVALID_STATE, "sale is not PENDING_FINALIZE")
    member = db["loyalty_members"].get(sale["loyalty_member_id"]) \
        if sale["loyalty_member_id"] else None
    requested = sale["requested_redeem_points"]
    if member is not None and requested > 0:
        if member["status"] != "ACTIVE":
            raise_error(ERR_MEMBER_NOT_ACTIVE, "loyalty member is not ACTIVE")
        if loyalty.redeemable_balance(member["id"]) < requested:
            raise_error(ERR_NO_POINTS, "redeemable balance drained below requested points")

    unit = _final_unit_from_snapshots(sale)
    sale["final_unit_price_cents"] = unit
    sale["fuel_amount_cents"] = pricing.fuel_amount_cents(unit, sale["dispensed_gallons"])
    sale["tax_cents"] = 0
    sale["total_cents"] = sale["fuel_amount_cents"]
    stamp(sale, "finalized_at")

    # Loyalty settlement: burn FEFO, then earn on the post-redemption total.
    # The burn count matches the frozen snapshot arithmetic (stack cap pinned).
    if sale["stack_cap_snapshot"] is not None:
        points_capped = min(requested, sale["stack_cap_snapshot"])
    else:
        points_capped = 0
    if member is not None and points_capped > 0:
        loyalty.burn_fefo(member["id"], points_capped)
    sale["points_redeemed"] = points_capped
    sale["points_discount_cents"] = pricing.points_discount_cents(points_capped)
    sale["points_earned"] = loyalty.earn_points_for(member, sale["total_cents"],
                                                    "FUEL_SALE", sale["id"])
    sale["status"] = "COMPLETED"
    touch(sale)

    # Contract cascade: volume -> fleet rolling volume -> tier recompute
    if sale["pricing_mode"] == "CONTRACT":
        contract = db["contracts"].get(sale["contract_id"])
        if contract is not None:
            contract["volume_delivered_gallons"] = rhu_float(
                dec(contract["volume_delivered_gallons"]) + dec(sale["dispensed_gallons"]), 3)
            touch(contract)
        fleet = db["fleet_accounts"].get(sale["fleet_account_id"])
        if fleet is not None:
            recompute_fleet_rolling_and_tier(fleet)
    return success_object(public(sale))


@bp.post("/fuel-sales/<rid>/pay")
def pay_sale(rid):
    authorized(["Cashier"])
    sale = require_path_resource("fuel_sales", rid)
    body = get_body()
    if sale["status"] != "COMPLETED" or sale["payment_status"] != "UNPAID":
        raise_error(ERR_INVALID_STATE, "sale must be COMPLETED with payment UNPAID")
    tender = body.get("tender_type")
    if tender == "CASH":
        shift = db["shifts"].get(sale["shift_id"])
        if shift is None or shift["status"] != "OPEN":
            raise_error(ERR_SHIFT_NOT_OPEN, "cash payment requires an OPEN shift")
    if tender == "FLEET_BILLING" and sale["pricing_mode"] != "CONTRACT":
        raise_error(ERR_INVALID_PRICING_MODE,
                    "FLEET_BILLING tender is lawful only on a CONTRACT sale")
    if not valid_enum(tender, TENDER_TYPES):
        raise_error(ERR_INVALID_REQUEST, "tender_type must be CASH, CARD or FLEET_BILLING")

    if tender == "FLEET_BILLING":
        sale["payment_status"] = "BILLED"
        fleet = db["fleet_accounts"].get(sale["fleet_account_id"])
        if fleet is not None:
            fleet["current_balance_cents"] += sale["total_cents"]
            touch(fleet)
    else:
        sale["payment_status"] = "PAID"
        if tender == "CASH":
            shift = db["shifts"].get(sale["shift_id"])
            adjust_shift_expected(shift, sale["total_cents"])
    sale["_pay_tender"] = tender
    touch(sale)
    return success_object(public(sale))


@bp.post("/fuel-sales/<rid>/void")
def void_sale(rid):
    authorized(["ShiftManager"])
    sale = require_path_resource("fuel_sales", rid)
    body = get_body()
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise_error(ERR_INVALID_REQUEST, "reason must be a string")

    if sale["status"] in ("AUTHORIZED", "FUELING", "PENDING_FINALIZE"):
        if sale["payment_status"] != "UNPAID":
            raise_error(ERR_INVALID_STATE, "live sale must be UNPAID to void")
        sale["status"] = "VOIDED"
        sale["void_reason"] = reason
        touch(sale)
        pump = db["pumps"].get(sale["pump_id"])
        if pump is not None and pump["status"] == "IN_USE":
            pump["status"] = "IDLE"
            touch(pump)
        return success_object(public(sale))

    if sale["status"] != "COMPLETED":
        raise_error(ERR_INVALID_STATE, "sale cannot be voided from its current state")
    if sale["payment_status"] not in ("PAID", "BILLED", "UNPAID"):
        raise_error(ERR_INVALID_STATE, "sale payment state cannot be voided")

    # Refund-void (PRD 3.2): money, points and contract-volume reversals
    if sale["payment_status"] in ("PAID", "BILLED"):
        sale["payment_status"] = "REFUNDED"
    if sale["_pay_tender"] == "CASH" and sale["payment_status"] == "REFUNDED":
        shift = db["shifts"].get(sale["shift_id"])
        if shift is not None:
            adjust_shift_expected(shift, -sale["total_cents"])
    if sale["_pay_tender"] == "FLEET_BILLING" and sale["payment_status"] == "REFUNDED":
        fleet = db["fleet_accounts"].get(sale["fleet_account_id"])
        if fleet is not None:
            fleet["current_balance_cents"] -= sale["total_cents"]
            touch(fleet)
    member = db["loyalty_members"].get(sale["loyalty_member_id"]) \
        if sale["loyalty_member_id"] else None
    if member is not None:
        if sale.get("points_redeemed"):
            loyalty.grant_lot(member["id"], sale["points_redeemed"], "ADJUSTMENT", sale["id"])
        if sale.get("points_earned"):
            loyalty.clawback_newest(member["id"], sale["points_earned"],
                                    "ADJUSTMENT", sale["id"])
    if sale["pricing_mode"] == "CONTRACT":
        contract = db["contracts"].get(sale["contract_id"])
        if contract is not None:
            contract["volume_delivered_gallons"] = rhu_float(
                dec(contract["volume_delivered_gallons"]) - dec(sale["dispensed_gallons"]), 3)
            touch(contract)
        fleet = db["fleet_accounts"].get(sale["fleet_account_id"])
        if fleet is not None:
            recompute_fleet_rolling_and_tier(fleet)
    sale["status"] = "VOIDED"
    sale["void_reason"] = reason
    touch(sale)
    return success_object(public(sale))
