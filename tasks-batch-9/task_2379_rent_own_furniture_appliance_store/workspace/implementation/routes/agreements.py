"""Signing an agreement and rendering the mandated disclosure."""

from flask import Blueprint

import middleware
import response
import validators
from db import base_row, db, public, touch
from errors import ApiError
from routes import common
from services import calc, domain

bp = Blueprint("agreements", __name__)

TERM_TYPES = ("WEEKLY", "MONTHLY")


@bp.post("/agreements")
def create_agreement():
    user_id, _ = middleware.authenticate(
        (middleware.PLATFORM_ADMIN, middleware.STORE_MANAGER, middleware.SALES_ASSOCIATE)
    )
    body = validators.json_body()
    customer_id = validators.identifier(body, "customer_id")
    unit_id = validators.identifier(body, "unit_id")
    term_type = validators.enum(body, "term_type", TERM_TYPES)
    renewal_count = validators.integer(body, "renewal_count", minimum=1)
    acknowledged = validators.boolean(
        body, "disclosure_acknowledged", required=False, default=False
    )

    customer = domain.require_customer(customer_id)
    unit = domain.require_unit(unit_id)
    store = domain.require_store(unit["store_id"])
    rule = domain.require_rule_for_state(store["state_code"])

    if unit["status"] != "AVAILABLE":
        raise ApiError("ERR_UNIT_NOT_AVAILABLE")
    if rule["disclosure_requires_total_of_payments"] and not acknowledged:
        raise ApiError("ERR_DISCLOSURE_NOT_ACKNOWLEDGED")
    if customer["verification_status"] != "VERIFIED":
        raise ApiError("ERR_CUSTOMER_NOT_VERIFIED")
    if renewal_count > rule["max_term_renewals"]:
        raise ApiError("ERR_TERM_EXCEEDS_STATE_CAP")

    pricing = calc.agreement_pricing(unit, term_type, renewal_count, rule)

    agreement = base_row()
    agreement["customer_id"] = customer["id"]
    agreement["unit_id"] = unit["id"]
    agreement["store_id"] = store["id"]
    agreement["term_type"] = term_type
    agreement["renewal_count"] = renewal_count
    agreement["disclosure_acknowledged"] = acknowledged
    agreement["state_code_snapshot"] = store["state_code"]
    agreement["state_rule_version_snapshot"] = rule["version"]
    agreement["created_by_user_id"] = user_id
    agreement["adjusted_cash_price_cents"] = pricing["adjusted_cash_price_cents"]
    agreement["renewal_rate_cents"] = pricing["renewal_rate_cents"]
    agreement["rent_subtotal_cents"] = pricing["rent_subtotal_cents"]
    agreement["processing_fee_cents"] = pricing["processing_fee_cents"]
    agreement["total_of_payments_cents"] = pricing["total_of_payments_cents"]
    agreement["monthly_equivalent_rate_cents"] = pricing["monthly_equivalent_rate_cents"]
    agreement["payment_status"] = "CURRENT"
    agreement["possession_status"] = "PENDING_DELIVERY"
    agreement["collections_stage"] = "NONE"
    agreement["periods_paid"] = 0
    agreement["rent_applied_cents"] = 0
    agreement["partial_credit_cents"] = 0
    agreement["late_fee_assessed_cents"] = 0
    agreement["late_fee_paid_cents"] = 0
    agreement["late_fee_balance_cents"] = 0
    agreement["reinstatement_fee_assessed_cents"] = 0
    agreement["reinstatement_fee_paid_cents"] = 0
    agreement["reinstatement_fee_balance_cents"] = 0
    agreement["customer_credit_contributed_cents"] = 0
    agreement["early_purchase_paid_cents"] = 0
    agreement["paid_pct"] = 0.0
    agreement["cycle_anchor_at"] = None
    agreement["current_period_due_at"] = None
    agreement["late_fee_period_index_last"] = 0
    agreement["service_credit_days"] = 0
    agreement["swap_count"] = 0
    agreement["collection_contact_count_7d"] = 0
    db.agreements[agreement["id"]] = agreement

    unit["status"] = "RESERVED"
    touch(unit)
    domain.sync_store(store)
    return response.object_response(public(agreement), 201)


@bp.get("/agreements/<agreement_id>")
def read_agreement(agreement_id):
    user_id, role = middleware.authenticate(middleware.ALL_ROLES)
    agreement = domain.require_agreement(agreement_id)
    middleware.require_owner(role, user_id, agreement["customer_id"])
    return response.object_response(public(agreement))


@bp.get("/agreements")
def list_agreements():
    middleware.authenticate(middleware.STAFF_ROLES)
    return common.paged(
        list(db.agreements.values()),
        filters=(
            "customer_id",
            "unit_id",
            "store_id",
            "payment_status",
            "possession_status",
        ),
    )


@bp.get("/agreements/<agreement_id>/disclosure")
def read_disclosure(agreement_id):
    user_id, role = middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.CUSTOMER,
        )
    )
    agreement = domain.require_agreement(agreement_id)
    middleware.require_owner(role, user_id, agreement["customer_id"])
    rule = domain.pinned_rule(agreement)
    return response.object_response(
        {
            "agreement_id": agreement["id"],
            "term_type": agreement["term_type"],
            "renewal_count": agreement["renewal_count"],
            "adjusted_cash_price_cents": agreement["adjusted_cash_price_cents"],
            "renewal_rate_cents": agreement["renewal_rate_cents"],
            "rent_subtotal_cents": agreement["rent_subtotal_cents"],
            "processing_fee_cents": agreement["processing_fee_cents"],
            "total_of_payments_cents": agreement["total_of_payments_cents"],
            "monthly_equivalent_rate_cents": agreement["monthly_equivalent_rate_cents"],
            "cost_of_rental_cents": calc.cost_of_rental_cents(agreement),
            "early_purchase_formula": rule["early_purchase_formula"],
            "state_code": agreement["state_code_snapshot"],
        }
    )
