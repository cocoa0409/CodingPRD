"""Order lines: tier pricing, service fees, substitution, invoicing, repricing."""

from flask import Blueprint

import errors
import middleware
import response
import validation
from db import db, clock, insert, touch, values
from errors import fail
from routes.common import PREFIX, listing, owned_contract, require_contract_active, require_state
from services import pricing
from util import closed_contains, half_open_contains

bp = Blueprint("order_lines", __name__)


def _open_period(contract_id, moment):
    for period in values(db.rebate_periods):
        if period["contract_id"] != contract_id or period["status"] != "OPEN":
            continue
        if half_open_contains(period["period_start"], period["period_end"], moment):
            return period
    return None


@bp.post(PREFIX + "/order-lines")
def create_order_line():
    caller = middleware.authenticate(["OperatorBuyer"])
    data = validation.body(("contract_id", "product_id", "distribution_center_id",
                            "quantity_cases"))
    contract = middleware.get_contract(db, validation.raw_fk(data, "contract_id"))
    owned_contract(caller, contract)
    product = middleware.get_product(db, validation.raw_fk(data, "product_id"))
    dc = middleware.get_dc(db, validation.raw_fk(data, "distribution_center_id"))
    quantity_cases = validation.get_int(data, "quantity_cases", minimum=1)
    if product["status"] != "ACTIVE":
        fail(errors.ERR_INVALID_REQUEST, "A DISCONTINUED product may not be ordered.")

    require_contract_active(contract)

    order_date = clock()
    line = {
        "contract_id": contract["id"],
        "product_id": product["id"],
        "distribution_center_id": dc["id"],
        "rebate_period_id": None,
        "deviation_agreement_id": None,
        "substituted_from_product_id": None,
        "substitution_rule_id": None,
        "applied_tier_id": None,
        "bill_back_claim_id": None,
        "quantity_cases": quantity_cases,
        "order_date": order_date,
        "cost_basis_snapshot_cents": None,
        "list_unit_price_cents": None,
        "invoiced_unit_price_cents": None,
        "extended_price_cents": None,
        "service_fee_cents": 0,
        "invoice_total_cents": None,
        "is_contracted_item": None,
        "pricing_status": "DRAFT_PRICED",
        "billback_status": "NOT_APPLICABLE",
        "credited_amount_cents": 0,
        "id": None,
    }

    pricing.resolve_tier_for_line(line, contract)

    if not closed_contains(contract["effective_from"], contract["effective_to"], order_date):
        fail(errors.ERR_ORDER_DATE_OUTSIDE_CONTRACT_TERM)

    if pricing.active_coverage(contract["id"], dc["id"], order_date) is None:
        fail(errors.ERR_DC_NOT_COVERED)

    period = _open_period(contract["id"], order_date)
    if period is None:
        fail(errors.ERR_NO_OPEN_REBATE_PERIOD)
    line["rebate_period_id"] = period["id"]

    pricing.price_line_full(line, contract)
    record = insert(db.order_lines, line)
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/order-lines/<order_line_id>")
def read_order_line(order_line_id):
    middleware.authenticate(["OperatorBuyer", "NationalAccountManager", "PricingAnalyst",
                             "RebateAccountant", "ContractAuditor", "ManufacturerRep"])
    record = middleware.get_order_line(db, order_line_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/order-lines")
def list_order_lines():
    middleware.authenticate(["OperatorBuyer", "NationalAccountManager", "PricingAnalyst",
                             "RebateAccountant", "ContractAuditor", "ManufacturerRep"])
    return listing(db.order_lines, (
        ("contract_id", "contract_id", None),
        ("product_id", "product_id", None),
        ("distribution_center_id", "distribution_center_id", None),
        ("rebate_period_id", "rebate_period_id", None),
        ("deviation_agreement_id", "deviation_agreement_id", None),
        ("substituted_from_product_id", "substituted_from_product_id", None),
        ("substitution_rule_id", "substitution_rule_id", None),
        ("applied_tier_id", "applied_tier_id", None),
        ("bill_back_claim_id", "bill_back_claim_id", None),
        ("pricing_status", "pricing_status", validation.PRICING_STATUSES),
        ("billback_status", "billback_status", validation.BILLBACK_STATUSES),
    ))


@bp.post(PREFIX + "/order-lines/<order_line_id>/substitute")
def substitute_order_line(order_line_id):
    caller = middleware.authenticate(["OperatorBuyer"])
    line = middleware.get_order_line(db, order_line_id)
    contract = db.contracts[line["contract_id"]]
    owned_contract(caller, contract)
    validation.body(("reason",))

    if line["pricing_status"] != "DRAFT_PRICED":
        fail(errors.ERR_ORDER_LINE_INVALID_STATE)
    require_contract_active(contract)
    pricing.resolve_tier_for_line(line, contract)

    if pricing.active_coverage(contract["id"], line["distribution_center_id"],
                               line["order_date"]) is None:
        fail(errors.ERR_DC_NOT_COVERED)

    product = db.products[line["product_id"]]
    if product["stock_status"] != "OUT_OF_STOCK":
        fail(errors.ERR_PRODUCT_IN_STOCK)

    rule = pricing.select_substitute(line, contract)

    line["substituted_from_product_id"] = line["product_id"]
    line["product_id"] = rule["substitute_product_id"]
    line["substitution_rule_id"] = rule["id"]
    pricing.price_line_full(line, contract)
    touch(line)
    return response.ok(response.serialize(line))


@bp.post(PREFIX + "/order-lines/<order_line_id>/invoice")
def invoice_order_line(order_line_id):
    middleware.authenticate(["NationalAccountManager"])
    line = middleware.get_order_line(db, order_line_id)
    validation.body(())
    if line["pricing_status"] not in ("DRAFT_PRICED", "REPRICED"):
        fail(errors.ERR_ORDER_LINE_INVALID_STATE)
    contract = db.contracts[line["contract_id"]]
    require_contract_active(contract)

    line["pricing_status"] = "INVOICED"
    if line["billback_status"] == "NOT_APPLICABLE" and line["deviation_agreement_id"]:
        line["billback_status"] = "ACCRUED"
    touch(line)
    return response.ok(response.serialize(line))


@bp.post(PREFIX + "/order-lines/<order_line_id>/reprice")
def reprice_order_line(order_line_id):
    middleware.authenticate(["NationalAccountManager"])
    line = middleware.get_order_line(db, order_line_id)
    validation.body(())
    if line["pricing_status"] != "INVOICED":
        fail(errors.ERR_ORDER_LINE_INVALID_STATE)
    period = db.rebate_periods.get(line["rebate_period_id"])
    if period is None or period["status"] != "OPEN":
        fail(errors.ERR_REBATE_PERIOD_INVALID_STATE)
    contract = db.contracts[line["contract_id"]]
    require_contract_active(contract)

    pricing.reprice_line(line, contract)
    line["pricing_status"] = "REPRICED"
    touch(line)
    return response.ok(response.serialize(line))
