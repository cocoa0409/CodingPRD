"""Deal routes: creation, quoting, finance, PDI pipeline, delivery (PRD 3.3-3.6)."""

from flask import Blueprint, request

import db
import errors
import calculations as calc
from common import (body, new_entity, touch, require_str, require_int, opt_int,
                    require_enum, paginate, get_or_404, find_dealership,
                    CLASS_TYPES, invalid)
from middleware import get_auth, require_role
from response import ok, created, ok_list
from services import (place_hold, release_hold, mark_sold, has_open_stop_sale)

bp = Blueprint("deals", __name__)

SETTLED_FINANCE = {"CASH", "APPROVED"}


# ---------------------------------------------------------------------------
@bp.post("/deals")
def create_deal():
    user_id, role = get_auth()
    require_role(role, {"SalesAgent"})
    data = body()
    did = data.get("dealership_id")
    find_dealership(did)
    unit = get_or_404("units", data.get("unit_id"))
    customer = get_or_404("customers", data.get("customer_id"))

    # OCC on Unit.version (priority 4) — before state/business rules.
    if "expected_unit_version" not in data or data.get("expected_unit_version") is None:
        invalid("expected_unit_version is required.")
    expected = data.get("expected_unit_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        invalid("expected_unit_version must be an integer.")
    if expected != unit["version"]:
        errors.err("ERR_STALE_UNIT_VERSION", "Unit version is stale.")

    # State legality (priority 5): unit must be AVAILABLE.
    if unit["status"] != "AVAILABLE":
        errors.err("ERR_UNIT_NOT_AVAILABLE", "Unit is not available for a hold.")

    # Field validation (priority 13).
    sale_price = require_int(data, "sale_price_cents", minimum=0)
    down_payment = opt_int(data, "down_payment_cents", default=0, minimum=0)
    term_months = data.get("term_months")
    if term_months is not None:
        if isinstance(term_months, bool) or not isinstance(term_months, int):
            invalid("term_months must be an integer.")

    rec = new_entity({
        "dealership_id": did,
        "unit_id": unit["id"],
        "customer_id": customer["id"],
        "sales_agent_user_id": user_id,
        "sale_price_cents": sale_price,
        "trade_unit_id": None,
        "trade_allowance_cents": 0,
        "trade_payoff_cents": 0,
        "trade_recon_cost_cents": 0,
        "net_trade_equity_cents": 0,
        "dealer_book_equity_cents": 0,
        "down_payment_cents": down_payment,
        "doc_fee_cents": 0,
        "tax_cents": 0,
        "amount_financed_cents": 0,
        "apr_bps": None,
        "term_months": term_months,
        "monthly_payment_cents": None,
        "sale_status": "DRAFT",
        "finance_status": "NONE",
        "pdi_passed": False,
    })
    db.store["deals"][rec["id"]] = rec
    # Cascade: place hold on the unit.
    place_hold(unit, rec["id"])
    return created(rec)


@bp.get("/deals")
def list_deals():
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent"})
    items = list(db.store["deals"].values())
    a = request.args
    for field in ("dealership_id", "unit_id", "customer_id", "trade_unit_id",
                  "sale_status", "finance_status"):
        val = a.get(field)
        if val is not None:
            items = [d for d in items if d.get(field) == val]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/deals/<deal_id>")
def get_deal(deal_id):
    user_id, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "Customer"})
    rec = get_or_404("deals", deal_id)
    if role == "Customer" and rec["customer_id"] != user_id:
        errors.err("ERR_DEAL_NOT_FOUND", "Deal not found.")
    return ok(rec)


@bp.get("/deals/<deal_id>/equity-summary")
def equity_summary(deal_id):
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent"})
    rec = get_or_404("deals", deal_id)
    return ok(rec)


@bp.post("/deals/<deal_id>/appraise-trade")
def appraise_trade(deal_id):
    _, role = get_auth()
    require_role(role, {"SalesAgent", "DealerManager"})
    deal = get_or_404("deals", deal_id)
    data = body()

    vin = require_str(data, "vin")
    model_year = require_int(data, "model_year", minimum=1990, maximum=2100)
    class_type = require_enum(data, "class_type", CLASS_TYPES)
    list_price = require_int(data, "list_price_cents", minimum=0)
    allowance = require_int(data, "trade_allowance_cents", minimum=0)
    payoff = opt_int(data, "trade_payoff_cents", default=0, minimum=0)
    recon = opt_int(data, "trade_recon_cost_cents", default=0, minimum=0)

    # vin unique per dealership
    for u in db.store["units"].values():
        if u["dealership_id"] == deal["dealership_id"] and u["vin"] == vin:
            errors.err("ERR_DUPLICATE_VIN", "vin already used in this dealership.")

    trade_unit = new_entity({
        "dealership_id": deal["dealership_id"],
        "vin": vin,
        "model_year": model_year,
        "class_type": class_type,
        "acquisition": "TRADE_IN",
        "consignor_customer_id": None,
        "trade_in_origin_unit_id": deal["unit_id"],
        "list_price_cents": list_price,
        "consignment_floor_cents": None,
        "consignment_fee_bps": None,
        "open_recall_count": 0,
        "status": "AVAILABLE",
        "active_hold_deal_id": None,
    })
    # Recall scan for the new trade unit (same logic as unit create).
    from routes.units import _scan_recalls_for_new_unit
    _scan_recalls_for_new_unit(trade_unit)
    db.store["units"][trade_unit["id"]] = trade_unit

    deal["trade_unit_id"] = trade_unit["id"]
    deal["trade_allowance_cents"] = allowance
    deal["trade_payoff_cents"] = payoff
    deal["trade_recon_cost_cents"] = recon
    touch(deal)
    return created(trade_unit)


@bp.post("/deals/<deal_id>/quote")
def quote(deal_id):
    _, role = get_auth()
    require_role(role, {"SalesAgent"})
    deal = get_or_404("deals", deal_id)
    if deal["sale_status"] != "DRAFT":
        errors.err("ERR_DEAL_BAD_SALE_STATE", "Deal is not in DRAFT.")
    dealership = db.store["dealerships"][deal["dealership_id"]]
    amounts = calc.quote_amounts(deal, dealership)
    deal.update(amounts)
    deal["sale_status"] = "QUOTED"
    if deal.get("term_months") is None and deal["finance_status"] == "NONE":
        deal["finance_status"] = "CASH"
    touch(deal)
    return ok(deal)


@bp.post("/deals/<deal_id>/request-finance")
def request_finance(deal_id):
    _, role = get_auth()
    require_role(role, {"SalesAgent"})
    deal = get_or_404("deals", deal_id)
    data = body()

    # Finance-state legality (priority 5): NONE or DECLINED -> REQUESTED.
    if deal["finance_status"] not in ("NONE", "DECLINED"):
        errors.err("ERR_FINANCE_BAD_STATE", "Finance status does not allow a request.")
    if deal["sale_status"] not in ("DRAFT", "QUOTED"):
        errors.err("ERR_DEAL_BAD_SALE_STATE", "Sale status does not allow a finance request.")

    # term: supply or reuse; range 12..240 (priority 13).
    term = data.get("term_months")
    if term is None:
        term = deal.get("term_months")
    if term is None or isinstance(term, bool) or not isinstance(term, int):
        errors.err("ERR_INVALID_TERM", "term_months is required (12..240).")
    if term < 12 or term > 240:
        errors.err("ERR_INVALID_TERM", "term_months must be in 12..240.")

    deal["term_months"] = term
    deal["finance_status"] = "REQUESTED"
    deal["apr_bps"] = None
    touch(deal)
    return ok(deal)


@bp.post("/deals/<deal_id>/finance-decision")
def finance_decision(deal_id):
    _, role = get_auth()
    require_role(role, {"DealerManager"})
    deal = get_or_404("deals", deal_id)
    data = body()
    decision = data.get("decision")
    if decision not in ("APPROVE", "DECLINE"):
        invalid("decision must be APPROVE or DECLINE.")

    if deal["finance_status"] != "REQUESTED":
        errors.err("ERR_FINANCE_BAD_STATE", "Finance status is not REQUESTED.")

    if decision == "DECLINE":
        deal["finance_status"] = "DECLINED"
        touch(deal)
        return ok(deal)

    # APPROVE: LTV guard (priority 11) then compute payment.
    unit = db.store["units"][deal["unit_id"]]
    customer = db.store["customers"][deal["customer_id"]]
    tier = customer["credit_tier"]
    ltv = calc.ltv_bps(deal["amount_financed_cents"], unit["list_price_cents"])
    max_ltv = calc.MAX_LTV_BPS[tier]
    if ltv is None or ltv > max_ltv:
        errors.err("ERR_LTV_EXCEEDED", "Loan-to-value exceeds the tier ceiling.")
    deal["apr_bps"] = calc.APR_BAND[tier]
    deal["monthly_payment_cents"] = calc.monthly_payment(
        deal["amount_financed_cents"], deal["term_months"], tier)
    deal["finance_status"] = "APPROVED"
    touch(deal)
    return ok(deal)


@bp.post("/deals/<deal_id>/start-pdi")
def start_pdi(deal_id):
    _, role = get_auth()
    require_role(role, {"SalesAgent"})
    deal = get_or_404("deals", deal_id)
    if deal["sale_status"] != "QUOTED":
        errors.err("ERR_DEAL_BAD_SALE_STATE", "Deal is not QUOTED.")
    if deal["finance_status"] not in SETTLED_FINANCE:
        errors.err("ERR_FINANCE_NOT_SETTLED", "Finance is not settled.")
    deal["sale_status"] = "PDI_PENDING"
    touch(deal)
    return ok(deal)


@bp.post("/deals/<deal_id>/deliver")
def deliver(deal_id):
    _, role = get_auth()
    require_role(role, {"SalesAgent", "DealerManager"})
    deal = get_or_404("deals", deal_id)

    # State (priority 5).
    if deal["sale_status"] != "WALKTHROUGH":
        errors.err("ERR_DEAL_BAD_SALE_STATE", "Deal is not in WALKTHROUGH.")
    if not deal["pdi_passed"]:
        errors.err("ERR_PDI_NOT_PASSED", "A passing PDI is required.")
    if deal["finance_status"] not in SETTLED_FINANCE:
        errors.err("ERR_FINANCE_NOT_SETTLED", "Finance is not settled.")

    unit = db.store["units"][deal["unit_id"]]
    # Stop-sale recall safety (priority 7).
    if has_open_stop_sale(unit):
        errors.err("ERR_STOP_SALE_RECALL_OPEN",
                   "Delivery blocked by an open STOP_SALE recall.")

    deal["sale_status"] = "DELIVERED"
    touch(deal)
    # Cascade: unit HELD -> SOLD.
    mark_sold(unit)
    # Consignment settlement (recorded; figures derivable from unit/deal).
    if unit["acquisition"] == "CONSIGNMENT":
        settlement = calc.consignor_proceeds(
            deal["sale_price_cents"], unit["consignment_fee_bps"],
            unit["consignment_floor_cents"])
        deal["consignor_proceeds"] = settlement
        touch(deal)
    return ok(deal)


@bp.post("/deals/<deal_id>/cancel")
def cancel(deal_id):
    _, role = get_auth()
    require_role(role, {"SalesAgent", "DealerManager"})
    deal = get_or_404("deals", deal_id)
    if deal["sale_status"] in ("DELIVERED", "CANCELLED"):
        errors.err("ERR_DEAL_TERMINAL", "Deal is already terminal.")
    deal["sale_status"] = "CANCELLED"
    touch(deal)
    # Cascade: release the unit hold if this deal holds it.
    unit = db.store["units"].get(deal["unit_id"])
    if unit and unit.get("active_hold_deal_id") == deal["id"]:
        release_hold(unit)
    return ok(deal)
