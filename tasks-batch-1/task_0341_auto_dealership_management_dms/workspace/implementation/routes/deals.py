from flask import Blueprint, request

import db
import response
from errors import err
from middleware import require_roles
from routes.lookup import get_fk, get_path
from services import calc, serialize
from services import deal_service as ds
from util import (base_record, get_json_body, paginate, parse_iso, parse_pagination,
                  require_enum, require_int, require_str, touch)

bp = Blueprint("deals", __name__)


def _has_document(deal_id, doc_type):
    return any(
        d["deal_id"] == deal_id and d["doc_type"] == doc_type
        for d in db.deal_jacket_documents.values()
    )


# --------------------------------------------------------------------------- #
# Create / read / list
# --------------------------------------------------------------------------- #
@bp.post("/deals")
@require_roles("SalesManager")
def create_deal():
    body = get_json_body()
    vehicle_id = require_str(body, "vehicle_id")
    customer_id = require_str(body, "customer_id")
    deal_type = require_enum(body, "deal_type", ("FINANCE", "CASH"), required=False, default="FINANCE")
    sale_price_cents = require_int(body, "sale_price_cents", minimum=0)
    accessories_cents = require_int(body, "accessories_cents", required=False, minimum=0, default=0)
    doc_fee_cents = require_int(body, "doc_fee_cents", required=False, minimum=0, default=0)
    title_fee_cents = require_int(body, "title_fee_cents", required=False, minimum=0, default=0)
    registration_fee_cents = require_int(body, "registration_fee_cents", required=False, minimum=0, default=0)
    tax_rate_bps = require_int(body, "tax_rate_bps", minimum=0)
    cash_down_cents = require_int(body, "cash_down_cents", required=False, minimum=0, default=0)

    # Body FK existence (priority 4).
    get_fk(db.vehicles, vehicle_id)
    get_fk(db.customers, customer_id)

    rec = base_record()
    rec.update({
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "deal_type": deal_type,
        "sale_price_cents": sale_price_cents,
        "accessories_cents": accessories_cents,
        "doc_fee_cents": doc_fee_cents,
        "title_fee_cents": title_fee_cents,
        "registration_fee_cents": registration_fee_cents,
        "tax_rate_bps": tax_rate_bps,
        "cash_down_cents": cash_down_cents,
        "applied_incentive_id": None,
        "rebate_cents": 0,
        "trade_allowance_cents": 0,
        "trade_equity_cents": 0,
        "total_tax_cents": 0,
        "fi_products_total_cents": 0,
        "amount_financed_cents": 0,
        "front_gross_cents": 0,
        "back_gross_cents": 0,
        "estimated_payment_cents": 0,
        "status": "DRAFT",
        "approved_lender_program_id": None,
    })
    db.deals[rec["id"]] = rec
    return response.success(serialize.deal(rec), status=201)


@bp.get("/deals/<did>")
@require_roles("SalesManager", "FinanceManager", "TitleClerk")
def get_deal(did):
    rec = get_path(db.deals, did)
    return response.success(serialize.deal(rec))


@bp.get("/deals")
@require_roles("SalesManager", "FinanceManager", "TitleClerk")
def list_deals():
    limit, offset = parse_pagination()
    items = list(db.deals.values())
    for key in ("vehicle_id", "customer_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d[key] == val]
    page, total, has_more = paginate(items, limit, offset)
    return response.success_list([serialize.deal(d) for d in page], limit, offset, total, has_more)


# --------------------------------------------------------------------------- #
# desk / re-desk  (DRAFT->DESKING, DESKING->DESKING, APPROVED->DESKING)
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/desk")
@require_roles("SalesManager")
def desk_deal(did):
    deal = get_path(db.deals, did)
    status = deal["status"]
    if status not in ("DRAFT", "DESKING", "APPROVED"):
        raise err("ERR_INVALID_STATE", "Deal cannot be desked from its current state")

    vehicle = db.vehicles.get(deal["vehicle_id"])

    if status == "DRAFT":
        # First desk reserves the vehicle: it must be AVAILABLE. (A DRAFT deal has
        # never reserved a vehicle, so ON_DEAL here means it is held by another deal.)
        if vehicle is None or vehicle["status"] != "AVAILABLE":
            raise err("ERR_VEHICLE_NOT_AVAILABLE", "Vehicle is not available to desk")
        vehicle["status"] = "ON_DEAL"
        touch(vehicle)
        deal["status"] = "DESKING"
    else:
        # DESKING->DESKING or APPROVED->DESKING: vehicle must still be ON_DEAL for this deal.
        if vehicle is None or vehicle["status"] != "ON_DEAL":
            raise err("ERR_VEHICLE_NOT_AVAILABLE", "Vehicle is no longer ON_DEAL for this deal")
        if status == "APPROVED":
            deal["approved_lender_program_id"] = None
            for c in db.finance_contracts.values():
                if c["deal_id"] == did and c["status"] == "ACTIVE":
                    c["status"] = "SUPERSEDED"
                    touch(c)
        deal["status"] = "DESKING"

    ds.recompute_quote(deal)
    touch(deal)
    return response.success(serialize.deal(deal))


# --------------------------------------------------------------------------- #
# apply-incentive
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/apply-incentive")
@require_roles("SalesManager", "FinanceManager")
def apply_incentive(did):
    deal = get_path(db.deals, did)
    body = get_json_body()
    oem_incentive_id = require_str(body, "oem_incentive_id")
    incentive = get_fk(db.oem_incentives, oem_incentive_id)
    vehicle = db.vehicles.get(deal["vehicle_id"])
    if not calc.incentive_eligible(incentive, vehicle, deal):
        raise err("ERR_INCENTIVE_NOT_ELIGIBLE", "OEM incentive is not eligible for this deal")
    deal["applied_incentive_id"] = incentive["id"]
    deal["rebate_cents"] = incentive["rebate_cents"]
    ds.recompute_money_only(deal)
    touch(deal)
    return response.success(serialize.deal(deal))


# --------------------------------------------------------------------------- #
# submit-to-lender (DESKING -> SUBMITTED_TO_LENDER)
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/submit-to-lender")
@require_roles("SalesManager")
def submit_to_lender(did):
    deal = get_path(db.deals, did)
    if deal["status"] != "DESKING":
        raise err("ERR_INVALID_STATE", "Deal is not in DESKING")
    if deal["deal_type"] != "FINANCE":
        raise err("ERR_DEAL_TYPE_NOT_FINANCE", "Deal is not a FINANCE deal")
    if not _has_document(did, "CREDIT_APP"):
        raise err("ERR_CREDIT_APP_MISSING", "No CREDIT_APP document in the jacket")
    deal["status"] = "SUBMITTED_TO_LENDER"
    touch(deal)
    return response.success(serialize.deal(deal))


# --------------------------------------------------------------------------- #
# lender-decision (SUBMITTED_TO_LENDER -> APPROVED / DESKING)
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/lender-decision")
@require_roles("FinanceManager")
def lender_decision(did):
    deal = get_path(db.deals, did)
    body = get_json_body()
    decision = require_enum(body, "decision", ("APPROVE", "DECLINE"))

    if deal["status"] != "SUBMITTED_TO_LENDER":
        raise err("ERR_INVALID_STATE", "Deal is not awaiting a lender decision")

    if decision == "APPROVE":
        lender_program_id = require_str(body, "lender_program_id")
        program = get_fk(db.lender_programs, lender_program_id)
        customer = db.customers.get(deal["customer_id"])
        if not program["active"] or program["tier"] != customer["credit_tier"]:
            raise err("ERR_LENDER_TIER_MISMATCH", "Lender program tier mismatch or inactive")
        deal["approved_lender_program_id"] = lender_program_id
        deal["status"] = "APPROVED"
    else:
        deal["approved_lender_program_id"] = None
        deal["status"] = "DESKING"
    touch(deal)
    return response.success(serialize.deal(deal))


# --------------------------------------------------------------------------- #
# contract (APPROVED -> CONTRACTED) — trade-acceptance cascade
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/contract")
@require_roles("FinanceManager")
def contract_deal(did):
    deal = get_path(db.deals, did)
    if deal["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Deal is not APPROVED")
    vehicle = db.vehicles.get(deal["vehicle_id"])
    if vehicle is None or vehicle["status"] != "ON_DEAL":
        raise err("ERR_VEHICLE_NOT_AVAILABLE", "Vehicle is not ON_DEAL for this deal")
    if calc._active_finance_contract(deal) is None:
        raise err("ERR_NO_ACTIVE_CONTRACT", "No ACTIVE finance contract on the deal")
    if not _has_document(did, "INSURANCE"):
        raise err("ERR_STIP_MISSING", "INSURANCE document missing")

    # CASCADE: accept attached APPRAISED trade-in -> create RECON USED vehicle.
    trade = ds.attached_trade(deal)
    if trade is not None and trade["status"] == "APPRAISED":
        trade["status"] = "ACCEPTED"
        used = base_record()
        used.update({
            "vin": trade["vin"],
            "condition": "USED",
            "make": None,
            "model": None,
            "model_year": None,
            "msrp_cents": 0,
            "list_price_cents": 0,
            "status": "RECON",
            "acquired_from_trade_in_id": trade["id"],
            "active_floor_plan_line_id": None,
        })
        db.vehicles[used["id"]] = used
        trade["acquired_vehicle_id"] = used["id"]
        touch(trade)

    deal["status"] = "CONTRACTED"
    touch(deal)
    return response.success(serialize.deal(deal))


# --------------------------------------------------------------------------- #
# fund (CONTRACTED -> FUNDED) — sale cascade, OCC on vehicle, LTV/PTI gates
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/fund")
@require_roles("FinanceManager")
def fund_deal(did):
    deal = get_path(db.deals, did)
    body = get_json_body()
    expected_vehicle_version = require_int(body, "expected_vehicle_version")

    if deal["status"] != "CONTRACTED":
        raise err("ERR_INVALID_STATE", "Deal is not CONTRACTED")

    vehicle = db.vehicles.get(deal["vehicle_id"])
    # expected_vehicle_version precedes the vehicle-status / fiscal gates (PRD §3.6).
    if vehicle is None or expected_vehicle_version != vehicle["version"]:
        raise err("ERR_STALE_VERSION", "Vehicle version does not match expected")
    if vehicle["status"] != "ON_DEAL":
        raise err("ERR_VEHICLE_NOT_AVAILABLE", "Vehicle is not ON_DEAL for this deal")

    program = db.lender_programs.get(deal.get("approved_lender_program_id"))
    contract = calc._active_finance_contract(deal)
    customer = db.customers.get(deal["customer_id"])

    # LTV cap (<=).
    from decimal import Decimal
    ltv_cap = Decimal(program["max_ltv_bps"]) / Decimal(10000) * Decimal(vehicle["list_price_cents"])
    if Decimal(deal["amount_financed_cents"]) > ltv_cap:
        raise err("ERR_LTV_EXCEEDED", "Amount financed exceeds the LTV cap")

    # PTI cap (<=).
    pti_cap = Decimal(program["max_pti_bps"]) / Decimal(10000) * Decimal(customer["monthly_income_cents"])
    if Decimal(contract["monthly_payment_cents"]) > pti_cap:
        raise err("ERR_PTI_EXCEEDED", "Monthly payment exceeds the PTI cap")

    # CASCADE link1: vehicle ON_DEAL -> SOLD.
    vehicle["status"] = "SOLD"
    touch(vehicle)

    # CASCADE link2: vehicle's ACTIVE floor-plan line -> PAID_OFF.
    line = calc.active_floor_plan_line(vehicle["id"])
    if line is not None:
        line["status"] = "PAID_OFF"
        line["principal_outstanding_cents"] = 0
        touch(line)
        # Track which line this funding paid off, for unwind reinstatement.
        deal["_paid_floor_plan_line_id"] = line["id"]

    # CASCADE link3: auto-create TitleRegistration (PENDING).
    title = base_record()
    title.update({
        "deal_id": did,
        "owner_name": None,
        "plate_type": None,
        "rejection_reason": None,
        "resubmit_count": 0,
        "status": "PENDING",
    })
    db.title_registrations[title["id"]] = title

    deal["status"] = "FUNDED"
    touch(deal)
    return response.success(serialize.deal(deal))


# --------------------------------------------------------------------------- #
# unwind (FUNDED -> UNWOUND) — compensation cascade
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/unwind")
@require_roles("FinanceManager")
def unwind_deal(did):
    deal = get_path(db.deals, did)
    if deal["status"] != "FUNDED":
        raise err("ERR_INVALID_STATE", "Deal is not FUNDED")
    # Blocked if any title registration for the deal is ACCEPTED.
    for t in db.title_registrations.values():
        if t["deal_id"] == did and t["status"] == "ACCEPTED":
            raise err("ERR_TITLE_ALREADY_ACCEPTED", "A title registration is already ACCEPTED")

    vehicle = db.vehicles.get(deal["vehicle_id"])
    # COMPENSATION link1: vehicle SOLD -> AVAILABLE.
    if vehicle is not None:
        vehicle["status"] = "AVAILABLE"
        touch(vehicle)

    # COMPENSATION link2: the floor-plan line this funding paid off -> REINSTATED.
    paid_line_id = deal.get("_paid_floor_plan_line_id")
    if paid_line_id is not None:
        line = db.floor_plan_lines.get(paid_line_id)
        if line is not None and line["status"] == "PAID_OFF":
            reductions = calc.curtailment_reduction(line["principal_cents"]) * line["curtailments_applied"]
            line["status"] = "REINSTATED"
            line["principal_outstanding_cents"] = line["principal_cents"] - reductions
            touch(line)

    # Any ACTIVE finance contract -> CANCELLED.
    for c in db.finance_contracts.values():
        if c["deal_id"] == did and c["status"] == "ACTIVE":
            c["status"] = "CANCELLED"
            touch(c)

    # Any ACCEPTED trade-in -> RELEASED; its acquired USED vehicle unlinked.
    for t in db.trade_ins.values():
        if t["deal_id"] == did and t["status"] == "ACCEPTED":
            t["status"] = "RELEASED"
            acquired_id = t.get("acquired_vehicle_id")
            if acquired_id is not None:
                acquired = db.vehicles.get(acquired_id)
                if acquired is not None:
                    acquired["acquired_from_trade_in_id"] = None
                    touch(acquired)
            t["acquired_vehicle_id"] = None
            touch(t)

    deal["status"] = "UNWOUND"
    touch(deal)
    return response.success(serialize.deal(deal))


# --------------------------------------------------------------------------- #
# kill (DRAFT -> DEAD, DESKING -> DEAD)
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/kill")
@require_roles("SalesManager")
def kill_deal(did):
    deal = get_path(db.deals, did)
    status = deal["status"]
    if status not in ("DRAFT", "DESKING"):
        raise err("ERR_INVALID_STATE", "Deal cannot be killed from its current state")

    if status == "DESKING":
        vehicle = db.vehicles.get(deal["vehicle_id"])
        if vehicle is not None and vehicle["status"] == "ON_DEAL":
            vehicle["status"] = "AVAILABLE"
            touch(vehicle)
        trade = ds.attached_trade(deal)
        if trade is not None and trade["status"] == "APPRAISED":
            trade["status"] = "RELEASED"
            touch(trade)
            ds.recompute_money_only(deal)

    deal["status"] = "DEAD"
    touch(deal)
    return response.success(serialize.deal(deal))
