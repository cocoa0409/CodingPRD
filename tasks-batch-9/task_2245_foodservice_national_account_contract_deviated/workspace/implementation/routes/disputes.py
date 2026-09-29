"""Invoice pricing disputes, retroactive audit repricing and the credit cascade."""

from flask import Blueprint

import errors
import middleware
import response
import validation
from db import db, clock, insert, touch
from errors import fail
from routes.common import PREFIX, listing, owned_contract, require_state
from services import cascade
from services.pricing import (
    AUDIT_TOLERANCE_PCT, class_cases_retroactive, cost_on_basis, list_price, select_tier,
)
from util import dec, pct

bp = Blueprint("disputes", __name__)

LIVE_DISPUTE_STATUSES = ("OPEN", "UNDER_AUDIT", "UPHELD")


def _audit_price(dispute, line, contract, period):
    """dispute_audit_repricing: the frozen cost basis under a retroactive tier."""
    product = db.products[line["product_id"]]
    product_class = product["product_class_code"]
    class_cases = class_cases_retroactive(contract, product_class, period["period_end"])
    tier = select_tier(contract["id"], product_class, class_cases)
    if tier is None:
        tier = db.contract_tiers.get(line["applied_tier_id"])
    if tier is None:
        fail(errors.ERR_NO_TIER_FOR_PRODUCT_CLASS)

    audited = list_price(line["cost_basis_snapshot_cents"], tier)

    deviation_id = line["deviation_agreement_id"]
    if deviation_id:
        deviation = db.deviation_agreements.get(deviation_id)
        if deviation is not None:
            audited = deviation["deviated_price_cents"]
    else:
        rule = db.substitution_rules.get(line["substitution_rule_id"])
        if rule is not None and rule["price_protection_mode"] == "HOLD_CONTRACT_PRICE":
            original = db.products.get(line["substituted_from_product_id"])
            if original is not None:
                original_cost = cost_on_basis(original, tier["cost_basis"])
                if original_cost is not None:
                    audited = list_price(original_cost, tier)

    invoiced = line["invoiced_unit_price_cents"]
    variance = invoiced - audited
    if invoiced == 0:
        variance_pct = dec("0.00")
    else:
        variance_pct = pct(dec(abs(variance)) * dec(100) / dec(invoiced))
    return audited, variance, variance_pct


@bp.post(PREFIX + "/pricing-disputes")
def create_dispute():
    caller = middleware.authenticate(["OperatorBuyer"])
    data = validation.body(("order_line_id", "claimed_correct_unit_price_cents",
                            "dispute_reason"))
    line = middleware.get_order_line(db, validation.raw_fk(data, "order_line_id"))
    contract = db.contracts[line["contract_id"]]
    owned_contract(caller, contract)
    claimed_price = validation.get_int(data, "claimed_correct_unit_price_cents", minimum=0)
    dispute_reason = validation.get_enum(data, "dispute_reason", validation.DISPUTE_REASONS)

    for other in db.pricing_disputes.values():
        if other["order_line_id"] == line["id"] and other["status"] in LIVE_DISPUTE_STATUSES:
            fail(errors.ERR_DISPUTE_ALREADY_EXISTS_FOR_LINE)

    if line["pricing_status"] not in ("INVOICED", "REPRICED"):
        fail(errors.ERR_ORDER_LINE_INVALID_STATE)

    record = insert(db.pricing_disputes, {
        "order_line_id": line["id"],
        "contract_id": contract["id"],
        "claimed_correct_unit_price_cents": claimed_price,
        "dispute_reason": dispute_reason,
        "audited_correct_unit_price_cents": None,
        "variance_cents_per_case": None,
        "variance_pct": None,
        "credit_amount_cents": None,
        "status": "OPEN",
        "opened_by_user_id": caller.user_id,
        "audited_by_user_id": None,
        "audit_note": None,
    })
    return response.created(response.serialize(record))


@bp.get(PREFIX + "/pricing-disputes/<pricing_dispute_id>")
def read_dispute(pricing_dispute_id):
    middleware.authenticate(["OperatorBuyer", "ContractAuditor", "NationalAccountManager",
                             "RebateAccountant", "PricingAnalyst"])
    record = middleware.get_dispute(db, pricing_dispute_id)
    return response.ok(response.serialize(record))


@bp.get(PREFIX + "/pricing-disputes")
def list_disputes():
    middleware.authenticate(["OperatorBuyer", "ContractAuditor", "NationalAccountManager",
                             "RebateAccountant", "PricingAnalyst"])
    return listing(db.pricing_disputes, (
        ("contract_id", "contract_id", None),
        ("order_line_id", "order_line_id", None),
        ("status", "status", validation.DISPUTE_STATUSES),
    ))


@bp.post(PREFIX + "/pricing-disputes/<pricing_dispute_id>/start-audit")
def start_audit(pricing_dispute_id):
    caller = middleware.authenticate(["ContractAuditor"])
    dispute = middleware.get_dispute(db, pricing_dispute_id)
    validation.body(())
    require_state(dispute, ("OPEN",), errors.ERR_DISPUTE_INVALID_STATE)
    line = db.order_lines[dispute["order_line_id"]]
    period = db.rebate_periods.get(line["rebate_period_id"])
    if period is None or period["status"] not in ("CLOSED", "SETTLED"):
        fail(errors.ERR_REBATE_PERIOD_NOT_CLOSED)

    contract = db.contracts[line["contract_id"]]
    audited, variance, variance_pct = _audit_price(dispute, line, contract, period)

    dispute["status"] = "UNDER_AUDIT"
    dispute["audited_correct_unit_price_cents"] = audited
    dispute["variance_cents_per_case"] = variance
    dispute["variance_pct"] = variance_pct
    dispute["audited_by_user_id"] = caller.user_id
    touch(dispute)
    return response.ok(response.serialize(dispute))


@bp.post(PREFIX + "/pricing-disputes/<pricing_dispute_id>/request-info")
def request_info(pricing_dispute_id):
    middleware.authenticate(["ContractAuditor"])
    dispute = middleware.get_dispute(db, pricing_dispute_id)
    data = validation.body(("note",))
    note = validation.get_str(data, "note")
    require_state(dispute, ("UNDER_AUDIT",), errors.ERR_DISPUTE_INVALID_STATE)

    dispute["status"] = "OPEN"
    dispute["audit_note"] = note
    dispute["audited_correct_unit_price_cents"] = None
    dispute["variance_cents_per_case"] = None
    dispute["variance_pct"] = None
    touch(dispute)
    return response.ok(response.serialize(dispute))


@bp.post(PREFIX + "/pricing-disputes/<pricing_dispute_id>/resolve")
def resolve_dispute(pricing_dispute_id):
    caller = middleware.authenticate(["ContractAuditor"])
    dispute = middleware.get_dispute(db, pricing_dispute_id)
    data = validation.body(("resolution", "note"))
    resolution = validation.get_enum(data, "resolution", validation.RESOLUTIONS)
    note = validation.get_str(data, "note", required=False, default=None, allow_empty=True)
    require_state(dispute, ("UNDER_AUDIT",), errors.ERR_DISPUTE_INVALID_STATE)

    if resolution == "UPHELD":
        variance_pct = dispute["variance_pct"]
        variance = dispute["variance_cents_per_case"]
        if (variance_pct is None or variance is None
                or dec(variance_pct) < AUDIT_TOLERANCE_PCT or variance <= 0):
            fail(errors.ERR_VARIANCE_BELOW_AUDIT_TOLERANCE)

    dispute["status"] = resolution
    dispute["audit_note"] = note
    dispute["audited_by_user_id"] = caller.user_id
    touch(dispute)
    return response.ok(response.serialize(dispute))


@bp.post(PREFIX + "/pricing-disputes/<pricing_dispute_id>/issue-credit")
def issue_credit(pricing_dispute_id):
    middleware.authenticate(["ContractAuditor"])
    dispute = middleware.get_dispute(db, pricing_dispute_id)
    validation.body(())
    require_state(dispute, ("UPHELD",), errors.ERR_DISPUTE_INVALID_STATE)
    line = db.order_lines[dispute["order_line_id"]]
    period = db.rebate_periods.get(line["rebate_period_id"])
    if period is not None and period["status"] == "SETTLED":
        fail(errors.ERR_SETTLED_PERIOD_IMMUTABLE)

    dispute["status"] = "CREDIT_ISSUED"
    dispute["credit_amount_cents"] = (
        dispute["variance_cents_per_case"] * line["quantity_cases"])
    touch(dispute)

    cascade.credit_issue_cascade(dispute, line, clock())
    return response.ok(response.serialize(dispute))


@bp.post(PREFIX + "/pricing-disputes/<pricing_dispute_id>/withdraw")
def withdraw_dispute(pricing_dispute_id):
    caller = middleware.authenticate(["OperatorBuyer"])
    dispute = middleware.get_dispute(db, pricing_dispute_id)
    owned_contract(caller, db.contracts[dispute["contract_id"]])
    validation.body(("reason",))
    require_state(dispute, ("OPEN", "UNDER_AUDIT"), errors.ERR_DISPUTE_INVALID_STATE)
    dispute["status"] = "WITHDRAWN"
    touch(dispute)
    return response.ok(response.serialize(dispute))
