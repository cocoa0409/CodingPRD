"""Authentication, role authorization and entity lookup (PRD sections 2.1, 2.8)."""

from flask import request

import errors
from errors import fail

ROLES = (
    "SystemAdmin",
    "NationalAccountManager",
    "PricingAnalyst",
    "OperatorBuyer",
    "ManufacturerRep",
    "RebateAccountant",
    "ContractAuditor",
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Priority 1 then priority 2 (role membership) of the rejection ladder."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail(errors.ERR_UNAUTHENTICATED)
    if allowed_roles is not None and role not in allowed_roles:
        fail(errors.ERR_UNAUTHORIZED)
    return Caller(user_id, role)


def require_owner(caller, expected_id):
    """Entity-backed ownership comparison (priority 2)."""
    if caller.user_id != expected_id:
        fail(errors.ERR_UNAUTHORIZED)


# --- existence lookups ------------------------------------------------------

def _lookup(collection, entity_id, error_id):
    if not isinstance(entity_id, str) or entity_id not in collection:
        fail(error_id)
    return collection[entity_id]


def get_operator(store, operator_id):
    return _lookup(store.operators, operator_id, errors.ERR_OPERATOR_NOT_FOUND)


def get_manufacturer(store, manufacturer_id):
    return _lookup(store.manufacturers, manufacturer_id, errors.ERR_MANUFACTURER_NOT_FOUND)


def get_dc(store, dc_id):
    return _lookup(store.distribution_centers, dc_id, errors.ERR_DISTRIBUTION_CENTER_NOT_FOUND)


def get_product(store, product_id):
    return _lookup(store.products, product_id, errors.ERR_PRODUCT_NOT_FOUND)


def get_contract(store, contract_id):
    return _lookup(store.contracts, contract_id, errors.ERR_CONTRACT_NOT_FOUND)


def get_tier(store, tier_id):
    return _lookup(store.contract_tiers, tier_id, errors.ERR_CONTRACT_TIER_NOT_FOUND)


def get_coverage(store, coverage_id):
    return _lookup(store.dc_coverages, coverage_id, errors.ERR_DC_COVERAGE_NOT_FOUND)


def get_deviation(store, deviation_id):
    return _lookup(store.deviation_agreements, deviation_id, errors.ERR_DEVIATION_NOT_FOUND)


def get_rule(store, rule_id):
    return _lookup(store.substitution_rules, rule_id, errors.ERR_SUBSTITUTION_RULE_NOT_FOUND)


def get_notice(store, notice_id):
    return _lookup(store.price_change_notices, notice_id, errors.ERR_PRICE_CHANGE_NOTICE_NOT_FOUND)


def get_order_line(store, line_id):
    return _lookup(store.order_lines, line_id, errors.ERR_ORDER_LINE_NOT_FOUND)


def get_claim(store, claim_id):
    return _lookup(store.bill_back_claims, claim_id, errors.ERR_BILL_BACK_CLAIM_NOT_FOUND)


def get_remittance(store, remittance_id):
    return _lookup(store.bill_back_remittances, remittance_id, errors.ERR_BILL_BACK_REMITTANCE_NOT_FOUND)


def get_period(store, period_id):
    return _lookup(store.rebate_periods, period_id, errors.ERR_REBATE_PERIOD_NOT_FOUND)


def get_dispute(store, dispute_id):
    return _lookup(store.pricing_disputes, dispute_id, errors.ERR_PRICING_DISPUTE_NOT_FOUND)
