"""Contracts, their lifecycle, the compliance report, markup tiers, coverage
mappings and substitution rules."""

from flask import Blueprint

import errors
import middleware
import response
import validation
from db import db, clock, insert, touch, values
from errors import fail
from routes.common import (
    PREFIX, listing, owned_contract, require_contract_active, require_state,
    unique_or_reject,
)
from services import cascade
from services.compliance import compliance_report, recompute_posture
from services.pricing import DC_COVERAGE_BUFFER_DAYS, active_tiers
from util import add_days, band_overlap, dec

bp = Blueprint("contracts", __name__)

CONTRACT_TERMS = ("notice_period_days", "contracted_purchase_pct_target",
                  "compliance_basis", "allow_out_of_market")


def _read_terms(data):
    return {
        "notice_period_days": validation.get_int(
            data, "notice_period_days", required=False, default=30, minimum=1),
        "contracted_purchase_pct_target": validation.get_decimal(
            data, "contracted_purchase_pct_target", required=False,
            default=dec("85.00"), minimum=0, maximum=100),
        "compliance_basis": validation.get_enum(
            data, "compliance_basis", validation.COMPLIANCE_BASES,
            required=False, default="DOLLAR_WEIGHTED"),
        "allow_out_of_market": validation.get_bool(
            data, "allow_out_of_market", required=False, default=False),
    }


# --- contracts -------------------------------------------------------------

@bp.post(PREFIX + "/contracts")
def create_contract():
    middleware.authenticate(["NationalAccountManager"])
    data = validation.body(("operator_id", "contract_code", "rebate_funding_manufacturer_id",
                            "effective_from", "effective_to") + CONTRACT_TERMS)
    middleware.get_operator(db, validation.raw_fk(data, "operator_id"))
    middleware.get_manufacturer(db, validation.raw_fk(data, "rebate_funding_manufacturer_id"))

    operator_id = validation.get_str(data, "operator_id")
    contract_code = validation.get_str(data, "contract_code")
    funder_id = validation.get_str(data, "rebate_funding_manufacturer_id")
    effective_from = validation.get_dt(data, "effective_from")
    effective_to = validation.get_dt(data, "effective_to")
    if effective_to <= effective_from:
        fail(errors.ERR_INVALID_REQUEST, "effective_to must be strictly after effective_from.")
    terms = _read_terms(data)
    unique_or_reject(db.contracts, "contract_code", contract_code)

    record = insert(db.contracts, dict({
        "operator_id": operator_id,
        "contract_code": contract_code,
        "amends_contract_id": None,
        "rebate_funding_manufacturer_id": funder_id,
        "status": "DRAFT",
        "effective_from": effective_from,
        "effective_to": effective_to,
        "compliance_posture": "OPEN",
        "deviation_breach_count": 0,
        "rebate_payable_cents": 0,
        "rebate_settled_total_cents": 0,
        "signed_at": None,
        "signed_by_user_id": None,
    }, **terms))
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/contracts/<contract_id>")
def read_contract(contract_id):
    middleware.authenticate(["NationalAccountManager", "PricingAnalyst", "OperatorBuyer",
                             "RebateAccountant", "ContractAuditor", "SystemAdmin"])
    record = middleware.get_contract(db, contract_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/contracts")
def list_contracts():
    middleware.authenticate(["NationalAccountManager", "PricingAnalyst", "OperatorBuyer",
                             "RebateAccountant", "ContractAuditor", "SystemAdmin"])
    return listing(db.contracts, (
        ("operator_id", "operator_id", None),
        ("rebate_funding_manufacturer_id", "rebate_funding_manufacturer_id", None),
        ("amends_contract_id", "amends_contract_id", None),
        ("status", "status", validation.CONTRACT_STATUSES),
    ))


@bp.post(PREFIX + "/contracts/<contract_id>/submit-for-signature")
def submit_for_signature(contract_id):
    middleware.authenticate(["NationalAccountManager"])
    contract = middleware.get_contract(db, contract_id)
    validation.body(())
    require_state(contract, ("DRAFT",), errors.ERR_CONTRACT_INVALID_STATE)
    has_tier = any(t["contract_id"] == contract_id and t["status"] == "ACTIVE"
                   for t in db.contract_tiers.values())
    has_coverage = any(c["contract_id"] == contract_id and c["status"] == "ACTIVE"
                       for c in db.dc_coverages.values())
    if not has_tier or not has_coverage:
        fail(errors.ERR_CONTRACT_INVALID_STATE,
             "The contract needs an ACTIVE markup tier and an ACTIVE coverage row.")
    contract["status"] = "PENDING_SIGNATURE"
    touch(contract)
    return response.ok(response.serialize(contract))


@bp.post(PREFIX + "/contracts/<contract_id>/return-to-draft")
def return_to_draft(contract_id):
    caller = middleware.authenticate(["OperatorBuyer"])
    contract = middleware.get_contract(db, contract_id)
    owned_contract(caller, contract)
    validation.body(("note",))
    require_state(contract, ("PENDING_SIGNATURE",), errors.ERR_CONTRACT_INVALID_STATE)
    contract["status"] = "DRAFT"
    touch(contract)
    return response.ok(response.serialize(contract))


@bp.post(PREFIX + "/contracts/<contract_id>/sign")
def sign_contract(contract_id):
    caller = middleware.authenticate(["OperatorBuyer"])
    contract = middleware.get_contract(db, contract_id)
    owned_contract(caller, contract)
    validation.body(())
    require_state(contract, ("PENDING_SIGNATURE",), errors.ERR_CONTRACT_INVALID_STATE)

    parent_id = contract.get("amends_contract_id")
    if parent_id:
        parent = db.contracts.get(parent_id)
        if parent is None or parent["status"] != "AMENDING":
            fail(errors.ERR_PARENT_CONTRACT_NOT_AMENDING)

    operator = db.operators.get(contract["operator_id"])
    if operator is None or operator["status"] != "ACTIVE":
        fail(errors.ERR_CONTRACT_INVALID_STATE, "The operator is not ACTIVE.")

    contract["status"] = "ACTIVE"
    contract["signed_at"] = clock()
    contract["signed_by_user_id"] = caller.user_id
    recompute_posture(contract)
    touch(contract)
    if parent_id:
        cascade.expire_parent_on_amendment_signature(contract)
    return response.ok(response.serialize(contract))


@bp.post(PREFIX + "/contracts/<contract_id>/amendments")
def open_amendment(contract_id):
    middleware.authenticate(["NationalAccountManager"])
    parent = middleware.get_contract(db, contract_id)
    data = validation.body(("contract_code", "effective_from", "effective_to") + CONTRACT_TERMS)
    contract_code = validation.get_str(data, "contract_code")
    effective_from = validation.get_dt(data, "effective_from")
    effective_to = validation.get_dt(data, "effective_to")
    if effective_to <= effective_from:
        fail(errors.ERR_INVALID_REQUEST, "effective_to must be strictly after effective_from.")
    terms = _read_terms(data)

    require_state(parent, ("ACTIVE",), errors.ERR_CONTRACT_INVALID_STATE)
    if parent["compliance_posture"] == "RESTRICTED":
        fail(errors.ERR_CONTRACT_POSTURE_RESTRICTED)
    for row in db.contracts.values():
        if (row.get("amends_contract_id") == parent["id"]
                and row["status"] in ("DRAFT", "PENDING_SIGNATURE")):
            fail(errors.ERR_CONTRACT_INVALID_STATE,
                 "An amendment of this contract is already outstanding.")
    unique_or_reject(db.contracts, "contract_code", contract_code)

    draft = insert(db.contracts, dict({
        "operator_id": parent["operator_id"],
        "contract_code": contract_code,
        "amends_contract_id": parent["id"],
        "rebate_funding_manufacturer_id": parent["rebate_funding_manufacturer_id"],
        "status": "DRAFT",
        "effective_from": effective_from,
        "effective_to": effective_to,
        "compliance_posture": "OPEN",
        "deviation_breach_count": 0,
        "rebate_payable_cents": 0,
        "rebate_settled_total_cents": 0,
        "signed_at": None,
        "signed_by_user_id": None,
    }, **terms))
    parent["status"] = "AMENDING"
    touch(parent)
    return response.created(response.serialize(draft))


@bp.post(PREFIX + "/contracts/<contract_id>/suspend")
def suspend_contract(contract_id):
    middleware.authenticate(["NationalAccountManager"])
    contract = middleware.get_contract(db, contract_id)
    validation.body(("note",))
    require_state(contract, ("ACTIVE", "AMENDING"), errors.ERR_CONTRACT_INVALID_STATE)
    contract["status"] = "SUSPENDED"
    touch(contract)
    return response.ok(response.serialize(contract))


@bp.post(PREFIX + "/contracts/<contract_id>/reinstate")
def reinstate_contract(contract_id):
    middleware.authenticate(["NationalAccountManager"])
    contract = middleware.get_contract(db, contract_id)
    validation.body(())
    require_state(contract, ("SUSPENDED",), errors.ERR_CONTRACT_INVALID_STATE)
    if clock() > contract["effective_to"]:
        fail(errors.ERR_CONTRACT_INVALID_STATE,
             "The contract term has already run out.")
    contract["status"] = "ACTIVE"
    recompute_posture(contract)
    touch(contract)
    return response.ok(response.serialize(contract))


@bp.post(PREFIX + "/contracts/<contract_id>/terminate")
def terminate_contract(contract_id):
    middleware.authenticate(["NationalAccountManager"])
    contract = middleware.get_contract(db, contract_id)
    validation.body(("reason",))
    require_state(contract, ("DRAFT", "PENDING_SIGNATURE", "ACTIVE", "SUSPENDED"),
                  errors.ERR_CONTRACT_INVALID_STATE)
    if contract["rebate_payable_cents"] != 0:
        fail(errors.ERR_REBATE_PAYABLE_OUTSTANDING)
    contract["status"] = "TERMINATED"
    touch(contract)
    cascade.terminate_contract_cascade(contract)
    return response.ok(response.serialize(contract))


@bp.get(PREFIX + "/contracts/<contract_id>/compliance-report")
def read_compliance_report(contract_id):
    middleware.authenticate(["NationalAccountManager", "OperatorBuyer",
                             "RebateAccountant", "ContractAuditor"])
    contract = middleware.get_contract(db, contract_id)
    return response.ok(compliance_report(contract, clock()))


# --- markup tiers ----------------------------------------------------------

@bp.post(PREFIX + "/contract-tiers")
def create_contract_tier():
    middleware.authenticate(["NationalAccountManager"])
    data = validation.body(("contract_id", "product_class_code", "cost_basis", "markup_type",
                            "markup_value", "min_case_volume", "max_case_volume",
                            "counts_as_contracted"))
    contract = middleware.get_contract(db, validation.raw_fk(data, "contract_id"))
    product_class_code = validation.get_enum(data, "product_class_code",
                                             validation.PRODUCT_CLASSES)
    cost_basis = validation.get_enum(data, "cost_basis", validation.COST_BASES)
    markup_type = validation.get_enum(data, "markup_type", validation.MARKUP_TYPES)
    markup_value = validation.get_decimal(data, "markup_value", minimum=0)
    min_case_volume = validation.get_int(data, "min_case_volume", minimum=0)
    max_case_volume = validation.get_int(data, "max_case_volume", required=False, default=None)
    counts = validation.get_bool(data, "counts_as_contracted", required=False, default=True)
    if max_case_volume is not None and max_case_volume <= min_case_volume:
        fail(errors.ERR_INVALID_REQUEST,
             "max_case_volume must be strictly greater than min_case_volume.")

    require_contract_active(contract, allow_draft=True)
    for tier in active_tiers(contract["id"], product_class_code):
        if band_overlap(min_case_volume, max_case_volume,
                        tier["min_case_volume"], tier["max_case_volume"]):
            fail(errors.ERR_TIER_BAND_OVERLAP)

    record = insert(db.contract_tiers, {
        "contract_id": contract["id"],
        "product_class_code": product_class_code,
        "cost_basis": cost_basis,
        "markup_type": markup_type,
        "markup_value": markup_value,
        "min_case_volume": min_case_volume,
        "max_case_volume": max_case_volume,
        "counts_as_contracted": counts,
        "status": "ACTIVE",
    })
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/contract-tiers/<contract_tier_id>")
def read_contract_tier(contract_tier_id):
    middleware.authenticate(["NationalAccountManager", "PricingAnalyst", "OperatorBuyer",
                             "ContractAuditor", "RebateAccountant"])
    record = middleware.get_tier(db, contract_tier_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/contract-tiers")
def list_contract_tiers():
    middleware.authenticate(["NationalAccountManager", "PricingAnalyst", "OperatorBuyer",
                             "ContractAuditor", "RebateAccountant"])
    return listing(db.contract_tiers, (
        ("contract_id", "contract_id", None),
        ("product_class_code", "product_class_code", validation.PRODUCT_CLASSES),
        ("status", "status", validation.TIER_STATUSES),
    ))


# --- coverage mappings -----------------------------------------------------

@bp.post(PREFIX + "/dc-coverages")
def create_dc_coverage():
    middleware.authenticate(["NationalAccountManager"])
    data = validation.body(("contract_id", "distribution_center_id", "coverage_type",
                            "coverage_from", "coverage_to", "service_fee_waived"))
    contract = middleware.get_contract(db, validation.raw_fk(data, "contract_id"))
    dc = middleware.get_dc(db, validation.raw_fk(data, "distribution_center_id"))
    coverage_type = validation.get_enum(data, "coverage_type", validation.COVERAGE_TYPES)
    coverage_from = validation.get_dt(data, "coverage_from")
    coverage_to = validation.get_dt(data, "coverage_to")
    if coverage_to <= coverage_from:
        fail(errors.ERR_INVALID_REQUEST, "coverage_to must be strictly after coverage_from.")
    waived = validation.get_bool(data, "service_fee_waived", required=False, default=False)
    if dc["status"] != "ACTIVE":
        fail(errors.ERR_INVALID_REQUEST,
             "Only an ACTIVE distribution center may be mapped into coverage.")

    require_contract_active(contract, allow_draft=True)

    for row in values(db.dc_coverages):
        if row["contract_id"] != contract["id"] or row["status"] != "ACTIVE":
            continue
        if row["distribution_center_id"] != dc["id"]:
            continue
        if coverage_from <= row["coverage_to"] and row["coverage_from"] <= coverage_to:
            fail(errors.ERR_DC_COVERAGE_BUFFER_CONFLICT)
        if coverage_from > row["coverage_to"]:
            gap_start, gap_end = row["coverage_to"], coverage_from
        else:
            gap_start, gap_end = coverage_to, row["coverage_from"]
        if gap_end <= add_days(gap_start, DC_COVERAGE_BUFFER_DAYS):
            fail(errors.ERR_DC_COVERAGE_BUFFER_CONFLICT)

    if coverage_type == "OUT_OF_MARKET" and not contract["allow_out_of_market"]:
        fail(errors.ERR_OUT_OF_MARKET_NOT_PERMITTED)

    record = insert(db.dc_coverages, {
        "contract_id": contract["id"],
        "distribution_center_id": dc["id"],
        "coverage_type": coverage_type,
        "coverage_from": coverage_from,
        "coverage_to": coverage_to,
        "service_fee_waived": waived,
        "status": "ACTIVE",
    })
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/dc-coverages/<dc_coverage_id>")
def read_dc_coverage(dc_coverage_id):
    middleware.authenticate(["NationalAccountManager", "OperatorBuyer", "ContractAuditor"])
    record = middleware.get_coverage(db, dc_coverage_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/dc-coverages")
def list_dc_coverages():
    middleware.authenticate(["NationalAccountManager", "OperatorBuyer", "ContractAuditor"])
    return listing(db.dc_coverages, (
        ("contract_id", "contract_id", None),
        ("distribution_center_id", "distribution_center_id", None),
        ("coverage_type", "coverage_type", validation.COVERAGE_TYPES),
        ("status", "status", validation.COVERAGE_STATUSES),
    ))


# --- substitution rules ----------------------------------------------------

@bp.post(PREFIX + "/substitution-rules")
def create_substitution_rule():
    middleware.authenticate(["NationalAccountManager"])
    data = validation.body(("contract_id", "primary_product_id", "substitute_product_id",
                            "rank", "price_protection_mode", "max_price_delta_pct"))
    contract = middleware.get_contract(db, validation.raw_fk(data, "contract_id"))
    primary = middleware.get_product(db, validation.raw_fk(data, "primary_product_id"))
    substitute = middleware.get_product(db, validation.raw_fk(data, "substitute_product_id"))
    rank = validation.get_int(data, "rank", minimum=1)
    mode = validation.get_enum(data, "price_protection_mode",
                               validation.PRICE_PROTECTION_MODES)
    max_delta = validation.get_decimal(data, "max_price_delta_pct", minimum=0)

    require_contract_active(contract, allow_draft=True)

    if (primary["id"] == substitute["id"]
            or primary.get("substitution_group_code") is None
            or substitute.get("substitution_group_code") is None
            or primary["substitution_group_code"] != substitute["substitution_group_code"]
            or primary["product_class_code"] != substitute["product_class_code"]):
        fail(errors.ERR_SUBSTITUTE_GROUP_MISMATCH)

    record = insert(db.substitution_rules, {
        "contract_id": contract["id"],
        "primary_product_id": primary["id"],
        "substitute_product_id": substitute["id"],
        "rank": rank,
        "price_protection_mode": mode,
        "max_price_delta_pct": max_delta,
        "status": "ACTIVE",
    })
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/substitution-rules/<substitution_rule_id>")
def read_substitution_rule(substitution_rule_id):
    middleware.authenticate(["NationalAccountManager", "OperatorBuyer", "ContractAuditor",
                             "PricingAnalyst"])
    record = middleware.get_rule(db, substitution_rule_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/substitution-rules")
def list_substitution_rules():
    middleware.authenticate(["NationalAccountManager", "OperatorBuyer", "ContractAuditor",
                             "PricingAnalyst"])
    return listing(db.substitution_rules, (
        ("contract_id", "contract_id", None),
        ("primary_product_id", "primary_product_id", None),
        ("substitute_product_id", "substitute_product_id", None),
        ("status", "status", validation.RULE_STATUSES),
    ))
