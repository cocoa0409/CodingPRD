"""Reference data (operators, manufacturers, distribution centers, products)
and the logical clock."""

from flask import Blueprint

import errors
import middleware
import response
import validation
from db import db, clock, insert, set_clock, touch
from errors import fail
from routes.common import PREFIX, listing, unique_or_reject
from services import cascade

bp = Blueprint("reference", __name__)


# --- operators --------------------------------------------------------------

@bp.post(PREFIX + "/operators")
def create_operator():
    middleware.authenticate(["SystemAdmin"])
    data = validation.body(("legal_name", "operator_code", "status", "rebate_remit_method"))
    legal_name = validation.get_str(data, "legal_name")
    operator_code = validation.get_code(data, "operator_code")
    status = validation.get_enum(data, "status", validation.PARTY_STATUSES,
                                 required=False, default="ACTIVE")
    remit = validation.get_enum(data, "rebate_remit_method", validation.REMIT_METHODS,
                                required=False, default="CREDIT_MEMO")
    unique_or_reject(db.operators, "operator_code", operator_code)
    record = insert(db.operators, {
        "legal_name": legal_name,
        "operator_code": operator_code,
        "status": status,
        "rebate_remit_method": remit,
    })
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/operators/<operator_id>")
def read_operator(operator_id):
    middleware.authenticate(["SystemAdmin", "NationalAccountManager", "OperatorBuyer",
                             "ContractAuditor", "RebateAccountant"])
    record = middleware.get_operator(db, operator_id)
    return response.ok(response.serialize(record))


# --- manufacturers ---------------------------------------------------------

@bp.post(PREFIX + "/manufacturers")
def create_manufacturer():
    middleware.authenticate(["SystemAdmin"])
    data = validation.body(("name", "manufacturer_code", "status", "bill_back_terms_days"))
    name = validation.get_str(data, "name")
    code = validation.get_code(data, "manufacturer_code")
    status = validation.get_enum(data, "status", validation.PARTY_STATUSES,
                                 required=False, default="ACTIVE")
    terms = validation.get_int(data, "bill_back_terms_days", required=False,
                               default=45, minimum=1)
    unique_or_reject(db.manufacturers, "manufacturer_code", code)
    record = insert(db.manufacturers, {
        "name": name,
        "manufacturer_code": code,
        "status": status,
        "bill_back_terms_days": terms,
        "open_claim_exposure_cents": 0,
        "unapplied_credit_cents": 0,
        "total_remitted_cents": 0,
        "rebate_funding_payable_cents": 0,
    })
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/manufacturers/<manufacturer_id>")
def read_manufacturer(manufacturer_id):
    middleware.authenticate(["SystemAdmin", "NationalAccountManager", "PricingAnalyst",
                             "RebateAccountant", "ContractAuditor", "ManufacturerRep"])
    record = middleware.get_manufacturer(db, manufacturer_id)
    return response.ok(response.serialize(record))


# --- distribution centers --------------------------------------------------

@bp.post(PREFIX + "/distribution-centers")
def create_distribution_center():
    middleware.authenticate(["SystemAdmin"])
    data = validation.body(("dc_code", "name", "in_market_state_codes",
                            "out_of_market_fee_per_case_cents", "status"))
    code = validation.get_code(data, "dc_code")
    name = validation.get_str(data, "name")
    states = validation.get_state_list(data, "in_market_state_codes")
    fee = validation.get_int(data, "out_of_market_fee_per_case_cents", minimum=0)
    status = validation.get_enum(data, "status", validation.PARTY_STATUSES,
                                 required=False, default="ACTIVE")
    unique_or_reject(db.distribution_centers, "dc_code", code)
    record = insert(db.distribution_centers, {
        "dc_code": code,
        "name": name,
        "in_market_state_codes": states,
        "out_of_market_fee_per_case_cents": fee,
        "status": status,
    })
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/distribution-centers/<distribution_center_id>")
def read_distribution_center(distribution_center_id):
    middleware.authenticate(["SystemAdmin", "NationalAccountManager", "OperatorBuyer",
                             "ContractAuditor"])
    record = middleware.get_dc(db, distribution_center_id)
    return response.ok(response.serialize(record))


# --- products --------------------------------------------------------------

PRODUCT_INPUT = ("sku", "description", "product_class_code", "manufacturer_id", "pack_size",
                 "last_cost_cents", "avg_cost_cents", "replacement_cost_cents",
                 "stock_status", "substitution_group_code", "is_market_indexed",
                 "index_baseline_value", "index_baseline_cost_cents", "status")


@bp.post(PREFIX + "/products")
def create_product():
    middleware.authenticate(["SystemAdmin"])
    data = validation.body(PRODUCT_INPUT)
    middleware.get_manufacturer(db, validation.raw_fk(data, "manufacturer_id"))

    sku = validation.get_str(data, "sku")
    description = validation.get_str(data, "description")
    product_class_code = validation.get_enum(data, "product_class_code",
                                             validation.PRODUCT_CLASSES)
    manufacturer_id = validation.get_str(data, "manufacturer_id")
    pack_size = validation.get_int(data, "pack_size", minimum=1)
    last_cost = validation.get_int(data, "last_cost_cents", minimum=0)
    avg_cost = validation.get_int(data, "avg_cost_cents", minimum=0)
    replacement_cost = validation.get_int(data, "replacement_cost_cents", minimum=0)
    stock_status = validation.get_enum(data, "stock_status", validation.STOCK_STATUSES,
                                       required=False, default="IN_STOCK")
    group = validation.get_str(data, "substitution_group_code", required=False, default=None)
    is_indexed = validation.get_bool(data, "is_market_indexed", required=False, default=False)
    baseline_value = validation.get_decimal(data, "index_baseline_value", required=False,
                                            default=None, exclusive_minimum=0)
    baseline_cost = validation.get_int(data, "index_baseline_cost_cents", required=False,
                                       default=None, minimum=1)
    status = validation.get_enum(data, "status", validation.PRODUCT_STATUSES,
                                 required=False, default="ACTIVE")

    if is_indexed:
        if baseline_value is None or baseline_cost is None:
            fail(errors.ERR_INVALID_REQUEST,
                 "index_baseline_value and index_baseline_cost_cents are required "
                 "for a market-indexed product.")
    else:
        if baseline_value is not None or baseline_cost is not None:
            fail(errors.ERR_INVALID_REQUEST,
                 "index baseline fields must be absent on a non-indexed product.")

    unique_or_reject(db.products, "sku", sku)
    record = insert(db.products, {
        "sku": sku,
        "description": description,
        "product_class_code": product_class_code,
        "manufacturer_id": manufacturer_id,
        "pack_size": pack_size,
        "last_cost_cents": last_cost,
        "avg_cost_cents": avg_cost,
        "replacement_cost_cents": replacement_cost,
        "cost_effective_at": None,
        "stock_status": stock_status,
        "substitution_group_code": group,
        "is_market_indexed": is_indexed,
        "index_baseline_value": baseline_value,
        "index_baseline_cost_cents": baseline_cost,
        "status": status,
    })
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/products/<product_id>")
def read_product(product_id):
    middleware.authenticate(["SystemAdmin", "NationalAccountManager", "PricingAnalyst",
                             "OperatorBuyer", "ContractAuditor", "RebateAccountant",
                             "ManufacturerRep"])
    record = middleware.get_product(db, product_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/products")
def list_products():
    middleware.authenticate(["SystemAdmin", "NationalAccountManager", "PricingAnalyst",
                             "OperatorBuyer", "ContractAuditor"])
    return listing(db.products, (
        ("manufacturer_id", "manufacturer_id", None),
        ("product_class_code", "product_class_code", validation.PRODUCT_CLASSES),
        ("substitution_group_code", "substitution_group_code", None),
        ("stock_status", "stock_status", validation.STOCK_STATUSES),
        ("status", "status", validation.PRODUCT_STATUSES),
    ))


@bp.post(PREFIX + "/products/<product_id>/availability")
def set_availability(product_id):
    middleware.authenticate(["SystemAdmin"])
    record = middleware.get_product(db, product_id)
    data = validation.body(("stock_status", "status"))
    stock_status = validation.get_enum(data, "stock_status", validation.STOCK_STATUSES,
                                       required=False, default=None)
    status = validation.get_enum(data, "status", validation.PRODUCT_STATUSES,
                                 required=False, default=None)
    if stock_status is not None:
        record["stock_status"] = stock_status
    if status is not None:
        record["status"] = status
    touch(record)
    return response.ok(response.serialize(record))


# --- logical clock ---------------------------------------------------------

@bp.post(PREFIX + "/_clock/set_current_utc")
def set_current_utc():
    middleware.authenticate(["SystemAdmin"])
    data = validation.body(("to_iso8601",))
    moment = validation.get_dt(data, "to_iso8601")
    set_clock(moment)
    expired_contract_ids, expired_deviation_ids = cascade.clock_sweep(clock())
    return response.ok({
        "current_utc": clock(),
        "expired_contract_ids": expired_contract_ids,
        "expired_deviation_ids": expired_deviation_ids,
    })
