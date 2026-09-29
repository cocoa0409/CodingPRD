"""Statutory rent-to-own rule profiles (PRD 2.5)."""

from flask import Blueprint

import middleware
import response
import validators
from db import base_row, db, public
from errors import ApiError
from routes import common
from services import domain

bp = Blueprint("state_rules", __name__)

FORMULAS = ("PCT_OF_REMAINING", "CASH_PRICE_MINUS_CREDIT")


@bp.post("/state-rto-rules")
def create_state_rule():
    middleware.authenticate((middleware.PLATFORM_ADMIN,))
    body = validators.json_body()

    code = validators.state_code(body, "state_code")
    grace_days = validators.integer(body, "late_fee_grace_days", minimum=0)
    late_fee_pct = validators.number(body, "late_fee_pct", minimum=0, maximum=0.25)
    late_fee_max = validators.integer(body, "late_fee_max_cents", minimum=0)
    threshold_months = validators.integer(
        body, "reinstate_threshold_months", required=False, default=2, minimum=1
    )
    days_short = validators.integer(body, "reinstate_days_short", minimum=1)
    days_long = validators.integer(body, "reinstate_days_long", minimum=1)
    if days_long < days_short:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "reinstate_days_long may not be shorter than reinstate_days_short.",
        )
    reinstatement_fee = validators.integer(body, "reinstatement_fee_cents", minimum=0)
    formula = validators.enum(body, "early_purchase_formula", FORMULAS)
    early_pct = validators.number(
        body, "early_purchase_pct", exclusive_minimum=0, maximum=1
    )
    rent_credit_pct = validators.number(
        body, "rent_credit_pct", exclusive_minimum=0, maximum=1
    )
    processing_fee_max = validators.integer(body, "processing_fee_max_cents", minimum=0)
    disclosure_required = validators.boolean(
        body, "disclosure_requires_total_of_payments", required=False, default=True
    )
    max_contacts = validators.integer(
        body, "max_collection_contacts_per_week", minimum=0
    )
    quiet_start = validators.integer(
        body, "quiet_hours_start_utc_hour", required=False, default=20,
        minimum=0, maximum=23,
    )
    quiet_end = validators.integer(
        body, "quiet_hours_end_utc_hour", required=False, default=8,
        minimum=0, maximum=23,
    )
    repossession_limit = validators.number(
        body, "repossession_paid_pct_limit", exclusive_minimum=0, maximum=1
    )
    credit_prohibited = validators.boolean(
        body, "credit_inquiry_prohibited", required=False, default=True
    )
    max_renewals = validators.integer(body, "max_term_renewals", minimum=1)

    if domain.rule_for_state(code) is not None:
        raise ApiError("ERR_DUPLICATE_STATE_RULE")

    rule = base_row()
    rule["state_code"] = code
    rule["late_fee_grace_days"] = grace_days
    rule["late_fee_pct"] = late_fee_pct
    rule["late_fee_max_cents"] = late_fee_max
    rule["reinstate_threshold_months"] = threshold_months
    rule["reinstate_days_short"] = days_short
    rule["reinstate_days_long"] = days_long
    rule["reinstatement_fee_cents"] = reinstatement_fee
    rule["early_purchase_formula"] = formula
    rule["early_purchase_pct"] = early_pct
    rule["rent_credit_pct"] = rent_credit_pct
    rule["processing_fee_max_cents"] = processing_fee_max
    rule["disclosure_requires_total_of_payments"] = disclosure_required
    rule["max_collection_contacts_per_week"] = max_contacts
    rule["quiet_hours_start_utc_hour"] = quiet_start
    rule["quiet_hours_end_utc_hour"] = quiet_end
    rule["repossession_paid_pct_limit"] = repossession_limit
    rule["credit_inquiry_prohibited"] = credit_prohibited
    rule["max_term_renewals"] = max_renewals
    db.state_rules[rule["id"]] = rule
    return response.object_response(public(rule), 201)


@bp.get("/state-rto-rules/<rule_id>")
def read_state_rule(rule_id):
    middleware.authenticate(middleware.STAFF_ROLES)
    rule = domain.require_state_rule_row(rule_id)
    return response.object_response(public(rule))


@bp.get("/state-rto-rules")
def list_state_rules():
    middleware.authenticate(middleware.STAFF_ROLES)
    return common.paged(
        list(db.state_rules.values()), primary="state_code", filters=("state_code",)
    )
