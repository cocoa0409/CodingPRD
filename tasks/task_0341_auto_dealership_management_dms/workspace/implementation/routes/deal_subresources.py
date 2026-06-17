from flask import Blueprint

import db
import response
from errors import err
from middleware import require_roles
from routes.lookup import get_fk, get_path
from services import calc, serialize
from services import deal_service as ds
from util import (base_record, get_json_body, paginate, parse_pagination,
                  require_enum, require_int, require_str, touch)

bp = Blueprint("deal_subresources", __name__)


# --------------------------------------------------------------------------- #
# DealProduct: attach / list / void
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/products")
@require_roles("FinanceManager")
def attach_product(did):
    deal = get_path(db.deals, did)
    body = get_json_body()
    finance_product_id = require_str(body, "finance_product_id")
    sold_price_cents = require_int(body, "sold_price_cents", minimum=0)
    product = get_fk(db.finance_products, finance_product_id)
    if sold_price_cents > product["max_retail_cents"]:
        raise err("ERR_PRODUCT_PRICE_EXCEEDS_MAX", "Sold price exceeds max retail")

    rec = base_record()
    rec.update({
        "deal_id": did,
        "finance_product_id": finance_product_id,
        "sold_price_cents": sold_price_cents,
        "product_cost_cents": product["cost_cents"],
        "status": "ACTIVE",
    })
    db.deal_products[rec["id"]] = rec

    ds.recompute_money_only(deal)
    touch(deal)
    return response.success(serialize.deal_product(rec), status=201)


@bp.get("/deals/<did>/products")
@require_roles("FinanceManager", "SalesManager")
def list_products(did):
    get_path(db.deals, did)
    limit, offset = parse_pagination()
    items = [p for p in db.deal_products.values() if p["deal_id"] == did]
    page, total, has_more = paginate(items, limit, offset)
    return response.success_list([serialize.deal_product(p) for p in page], limit, offset, total, has_more)


@bp.delete("/deals/<did>/products/<dpid>")
@require_roles("FinanceManager")
def void_product(did, dpid):
    deal = get_path(db.deals, did)
    product = get_path(db.deal_products, dpid)
    if product["deal_id"] != did:
        raise err("ERR_NOT_FOUND", "Product line does not belong to this deal")
    if product["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Product line is not ACTIVE")
    product["status"] = "VOID"
    touch(product)
    ds.recompute_money_only(deal)
    touch(deal)
    return response.success(serialize.deal_product(product))


# --------------------------------------------------------------------------- #
# TradeIn: attach (replace) / list / get
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/trade-ins")
@require_roles("SalesManager", "InventoryClerk")
def attach_trade(did):
    deal = get_path(db.deals, did)
    body = get_json_body()
    vin = require_str(body, "vin")
    acv_cents = require_int(body, "acv_cents", minimum=0)
    allowance_cents = require_int(body, "allowance_cents", minimum=0)
    payoff_cents = require_int(body, "payoff_cents", minimum=0)

    # Replace any prior non-RELEASED trade on this deal.
    for t in db.trade_ins.values():
        if t["deal_id"] == did and t["status"] != "RELEASED":
            t["status"] = "RELEASED"
            touch(t)

    rec = base_record()
    rec.update({
        "deal_id": did,
        "vin": vin,
        "acv_cents": acv_cents,
        "allowance_cents": allowance_cents,
        "payoff_cents": payoff_cents,
        "gross_equity_cents": allowance_cents - payoff_cents,
        "status": "APPRAISED",
        "acquired_vehicle_id": None,
    })
    db.trade_ins[rec["id"]] = rec

    ds.recompute_money_only(deal)
    touch(deal)
    return response.success(serialize.trade_in(rec), status=201)


@bp.get("/deals/<did>/trade-ins")
@require_roles("SalesManager", "InventoryClerk", "FinanceManager")
def list_trades(did):
    get_path(db.deals, did)
    limit, offset = parse_pagination()
    items = [t for t in db.trade_ins.values() if t["deal_id"] == did]
    page, total, has_more = paginate(items, limit, offset)
    return response.success_list([serialize.trade_in(t) for t in page], limit, offset, total, has_more)


@bp.get("/trade-ins/<tid>")
@require_roles("SalesManager", "InventoryClerk", "FinanceManager")
def get_trade(tid):
    rec = get_path(db.trade_ins, tid)
    return response.success(serialize.trade_in(rec))


# --------------------------------------------------------------------------- #
# FinanceContract: create (OCC supersede) / list / get
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/finance-contracts")
@require_roles("FinanceManager")
def create_finance_contract(did):
    deal = get_path(db.deals, did)
    body = get_json_body()
    lender_program_id = require_str(body, "lender_program_id")
    markup_bps = require_int(body, "markup_bps", minimum=0)
    term_months = require_int(body, "term_months", gt=0)
    expected_deal_version = require_int(body, "expected_deal_version")

    program = get_fk(db.lender_programs, lender_program_id)

    # OCC (priority 8) before business constraints.
    if expected_deal_version != deal["version"]:
        raise err("ERR_STALE_VERSION", "Deal version has advanced")

    if markup_bps > program["max_markup_bps"] or term_months > program["max_term_months"]:
        raise err("ERR_MARKUP_EXCEEDS_MAX", "Markup or term exceeds lender program maximum")

    snapshot = calc.amount_financed(deal)
    sell_rate_bps = program["buy_rate_bps"] + markup_bps
    monthly = calc.monthly_payment(snapshot, sell_rate_bps, term_months)
    reserve = calc.finance_reserve(snapshot, markup_bps, program["max_markup_bps"])

    # Supersede prior ACTIVE contract.
    for c in db.finance_contracts.values():
        if c["deal_id"] == did and c["status"] == "ACTIVE":
            c["status"] = "SUPERSEDED"
            touch(c)

    rec = base_record()
    rec.update({
        "deal_id": did,
        "lender_program_id": lender_program_id,
        "markup_bps": markup_bps,
        "term_months": term_months,
        "sell_rate_bps": sell_rate_bps,
        "amount_financed_snapshot_cents": snapshot,
        "monthly_payment_cents": monthly,
        "finance_reserve_cents": reserve,
        "status": "ACTIVE",
    })
    db.finance_contracts[rec["id"]] = rec

    # Recompute back-end gross to fold in the new finance reserve.
    deal["back_gross_cents"] = calc.back_gross(deal)
    touch(deal)
    return response.success(serialize.finance_contract(rec), status=201)


@bp.get("/deals/<did>/finance-contracts")
@require_roles("FinanceManager", "SalesManager")
def list_finance_contracts(did):
    get_path(db.deals, did)
    limit, offset = parse_pagination()
    items = [c for c in db.finance_contracts.values() if c["deal_id"] == did]
    page, total, has_more = paginate(items, limit, offset)
    return response.success_list([serialize.finance_contract(c) for c in page], limit, offset, total, has_more)


@bp.get("/finance-contracts/<cid>")
@require_roles("FinanceManager", "SalesManager")
def get_finance_contract(cid):
    rec = get_path(db.finance_contracts, cid)
    return response.success(serialize.finance_contract(rec))


# --------------------------------------------------------------------------- #
# DealJacketDocument: upload (append-only) / list
# --------------------------------------------------------------------------- #
@bp.post("/deals/<did>/documents")
@require_roles("SalesManager", "FinanceManager", "TitleClerk")
def upload_document(did):
    get_path(db.deals, did)
    body = get_json_body()
    doc_type = require_enum(
        body, "doc_type",
        ("CREDIT_APP", "PROOF_OF_INCOME", "INSURANCE", "BILL_OF_SALE", "ODOMETER"),
    )
    uri = require_str(body, "uri")
    rec = base_record(common_fields=False)
    rec.update({"deal_id": did, "doc_type": doc_type, "uri": uri})
    db.deal_jacket_documents[rec["id"]] = rec
    return response.success(serialize.document(rec), status=201)


@bp.get("/deals/<did>/documents")
@require_roles("SalesManager", "FinanceManager", "TitleClerk")
def list_documents(did):
    get_path(db.deals, did)
    limit, offset = parse_pagination()
    items = [d for d in db.deal_jacket_documents.values() if d["deal_id"] == did]
    page, total, has_more = paginate(items, limit, offset)
    return response.success_list([serialize.document(d) for d in page], limit, offset, total, has_more)
