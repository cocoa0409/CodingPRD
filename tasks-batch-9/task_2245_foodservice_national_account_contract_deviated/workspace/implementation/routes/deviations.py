"""Deviated pricing agreements: drafting, manufacturer negotiation, activation."""

from flask import Blueprint

import errors
import middleware
import response
import validation
from db import db, insert, touch, values
from errors import fail
from routes.common import PREFIX, listing, require_contract_active, require_state
from services import pricing
from util import half_open_overlap

bp = Blueprint("deviations", __name__)

OVERLAP_STATUSES = (
    "DRAFT", "SUBMITTED", "MANUFACTURER_APPROVED", "REVISION_REQUESTED",
    "ACTIVE", "PRICE_CEILING_BREACHED",
)


@bp.post(PREFIX + "/deviation-agreements")
def create_deviation():
    middleware.authenticate(["PricingAnalyst"])
    data = validation.body((
        "contract_id", "product_id", "manufacturer_id", "bill_back_basis",
        "protected_discount_cents", "requested_net_price_cents",
        "max_operator_price_cents", "effective_from", "effective_to",
        "expected_contract_version"))
    contract = middleware.get_contract(db, validation.raw_fk(data, "contract_id"))
    product = middleware.get_product(db, validation.raw_fk(data, "product_id"))
    manufacturer = middleware.get_manufacturer(
        db, validation.raw_fk(data, "manufacturer_id"))

    bill_back_basis = validation.get_enum(data, "bill_back_basis",
                                          validation.BILL_BACK_BASES)
    protected_discount = validation.get_int(data, "protected_discount_cents",
                                            required=False, default=None, minimum=1)
    requested_net_price = validation.get_int(data, "requested_net_price_cents",
                                             required=False, default=None, minimum=1)
    max_operator_price = validation.get_int(data, "max_operator_price_cents", minimum=1)
    effective_from = validation.get_dt(data, "effective_from")
    effective_to = validation.get_dt(data, "effective_to")
    if effective_to <= effective_from:
        fail(errors.ERR_INVALID_REQUEST, "effective_to must be strictly after effective_from.")
    expected_version = validation.get_int(data, "expected_contract_version", minimum=1)

    if bill_back_basis == "FIXED_NET_PRICE":
        if requested_net_price is None or protected_discount is not None:
            fail(errors.ERR_INVALID_REQUEST,
                 "FIXED_NET_PRICE requires requested_net_price_cents and forbids "
                 "protected_discount_cents.")
    else:
        if protected_discount is None or requested_net_price is not None:
            fail(errors.ERR_INVALID_REQUEST,
                 "COST_PLUS_PROTECTED requires protected_discount_cents and forbids "
                 "requested_net_price_cents.")

    require_contract_active(contract)

    if expected_version != contract["version"]:
        fail(errors.ERR_STALE_CONTRACT_VERSION)

    if manufacturer["id"] != product["manufacturer_id"]:
        fail(errors.ERR_DEVIATION_MANUFACTURER_MISMATCH)

    if not pricing.has_active_tier(contract["id"], product["product_class_code"]):
        fail(errors.ERR_NO_TIER_FOR_PRODUCT_CLASS)

    deviated_price = pricing.resolve_deviated_price(
        contract["id"], product, bill_back_basis, requested_net_price, protected_discount)
    if deviated_price <= 0:
        fail(errors.ERR_INVALID_REQUEST,
             "The resolved deviated_price_cents must be greater than zero.")

    for other in values(db.deviation_agreements):
        if other["contract_id"] != contract["id"] or other["product_id"] != product["id"]:
            continue
        if other["status"] not in OVERLAP_STATUSES:
            continue
        if half_open_overlap(effective_from, effective_to,
                             other["effective_from"], other["effective_to"]):
            fail(errors.ERR_DEVIATION_PERIOD_OVERLAP)

    if deviated_price > max_operator_price:
        fail(errors.ERR_DEVIATED_PRICE_ABOVE_CEILING)

    record = insert(db.deviation_agreements, {
        "contract_id": contract["id"],
        "product_id": product["id"],
        "manufacturer_id": manufacturer["id"],
        "bill_back_basis": bill_back_basis,
        "protected_discount_cents": protected_discount,
        "requested_net_price_cents": requested_net_price,
        "deviated_price_cents": deviated_price,
        "max_operator_price_cents": max_operator_price,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
        "revision_round": 0,
        "price_revision_count": 0,
        "submitted_by_user_id": None,
        "manufacturer_decision_note": None,
    })
    touch(contract)
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/deviation-agreements/<deviation_agreement_id>")
def read_deviation(deviation_agreement_id):
    middleware.authenticate(["PricingAnalyst", "NationalAccountManager", "ManufacturerRep",
                             "RebateAccountant", "ContractAuditor", "OperatorBuyer"])
    record = middleware.get_deviation(db, deviation_agreement_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/deviation-agreements")
def list_deviations():
    middleware.authenticate(["PricingAnalyst", "NationalAccountManager", "ManufacturerRep",
                             "RebateAccountant", "ContractAuditor", "OperatorBuyer"])
    return listing(db.deviation_agreements, (
        ("contract_id", "contract_id", None),
        ("product_id", "product_id", None),
        ("manufacturer_id", "manufacturer_id", None),
        ("status", "status", validation.DEVIATION_STATUSES),
    ))


@bp.post(PREFIX + "/deviation-agreements/<deviation_agreement_id>/submit")
def submit_deviation(deviation_agreement_id):
    caller = middleware.authenticate(["PricingAnalyst"])
    deviation = middleware.get_deviation(db, deviation_agreement_id)
    validation.body(())
    require_state(deviation, ("DRAFT", "REVISION_REQUESTED"),
                  errors.ERR_DEVIATION_INVALID_STATE)
    contract = db.contracts[deviation["contract_id"]]
    require_contract_active(contract)
    if deviation["revision_round"] >= pricing.MAX_REVISION_ROUNDS:
        fail(errors.ERR_MAX_REVISION_ROUNDS_EXCEEDED)
    if deviation["status"] == "REVISION_REQUESTED":
        deviation["revision_round"] += 1
    deviation["status"] = "SUBMITTED"
    deviation["submitted_by_user_id"] = caller.user_id
    touch(deviation)
    return response.ok(response.serialize(deviation))


@bp.post(PREFIX + "/deviation-agreements/<deviation_agreement_id>/manufacturer-decision")
def decide_deviation(deviation_agreement_id):
    caller = middleware.authenticate(["ManufacturerRep"])
    deviation = middleware.get_deviation(db, deviation_agreement_id)
    middleware.require_owner(caller, deviation["manufacturer_id"])
    data = validation.body(("decision", "decision_note"))
    decision = validation.get_enum(data, "decision", validation.DECISIONS)
    note = validation.get_str(data, "decision_note", required=False, default=None,
                              allow_empty=True)
    require_state(deviation, ("SUBMITTED",), errors.ERR_DEVIATION_INVALID_STATE)
    manufacturer = db.manufacturers.get(deviation["manufacturer_id"])
    if manufacturer is None or manufacturer["status"] != "ACTIVE":
        fail(errors.ERR_MANUFACTURER_SUSPENDED)

    deviation["status"] = {
        "APPROVE": "MANUFACTURER_APPROVED",
        "REQUEST_REVISION": "REVISION_REQUESTED",
        "REJECT": "REJECTED",
    }[decision]
    deviation["manufacturer_decision_note"] = note
    touch(deviation)
    return response.ok(response.serialize(deviation))


@bp.post(PREFIX + "/deviation-agreements/<deviation_agreement_id>/activate")
def activate_deviation(deviation_agreement_id):
    caller = middleware.authenticate(["NationalAccountManager"])
    deviation = middleware.get_deviation(db, deviation_agreement_id)
    validation.body(())
    require_state(deviation, ("MANUFACTURER_APPROVED",), errors.ERR_DEVIATION_INVALID_STATE)
    contract = db.contracts[deviation["contract_id"]]
    require_contract_active(contract)
    if caller.user_id == deviation["submitted_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
    if contract["compliance_posture"] == "RESTRICTED":
        fail(errors.ERR_CONTRACT_POSTURE_RESTRICTED)

    deviated_price = deviation["deviated_price_cents"]
    if deviation["bill_back_basis"] == "COST_PLUS_PROTECTED":
        product = db.products.get(deviation["product_id"])
        if product is not None:
            tier = pricing.entry_tier(deviation["contract_id"],
                                      product["product_class_code"])
            if tier is not None:
                basis_cost = pricing.cost_on_basis(product, tier["cost_basis"])
                if basis_cost is not None:
                    deviated_price = basis_cost - deviation["protected_discount_cents"]
    if deviated_price > deviation["max_operator_price_cents"]:
        fail(errors.ERR_DEVIATED_PRICE_ABOVE_CEILING)

    deviation["deviated_price_cents"] = deviated_price
    deviation["status"] = "ACTIVE"
    touch(deviation)
    return response.ok(response.serialize(deviation))
