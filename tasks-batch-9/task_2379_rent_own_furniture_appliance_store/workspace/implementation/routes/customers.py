"""Renters, personal references, verification and the loyalty ledger."""

from flask import Blueprint

import clock
import middleware
import response
import validators
from db import base_row, db, public, touch
from errors import ApiError
from routes import common
from services import calc, domain

bp = Blueprint("customers", __name__)

RELATIONSHIPS = ("FAMILY", "EMPLOYER", "LANDLORD", "PERSONAL")
CHECK_RESULTS = ("VERIFIED", "UNREACHABLE", "REFUSED")
DECISIONS = ("APPROVE", "REJECT")


@bp.post("/customers")
def create_customer():
    middleware.authenticate(
        (middleware.PLATFORM_ADMIN, middleware.STORE_MANAGER, middleware.SALES_ASSOCIATE)
    )
    body = validators.json_body()
    full_name = validators.string(body, "full_name", min_len=1, max_len=120)
    email = validators.string(body, "email", min_len=0)
    phone = validators.string(body, "phone", min_len=0)
    code = validators.state_code(body, "state_code")
    employer_name = validators.string(
        body, "employer_name", required=False, default="", min_len=0
    )
    employer_verified = validators.boolean(
        body, "employer_verified", required=False, default=False
    )
    income = validators.integer(body, "monthly_income_cents", minimum=0)
    residence = validators.integer(body, "residence_months", minimum=0)
    gov_id = validators.boolean(
        body, "government_id_verified", required=False, default=False
    )
    consent = validators.boolean(
        body, "in_person_contact_consent", required=False, default=False
    )

    customer = base_row()
    customer["full_name"] = full_name
    customer["email"] = email
    customer["phone"] = phone
    customer["state_code"] = code
    customer["employer_name"] = employer_name
    customer["employer_verified"] = employer_verified
    customer["monthly_income_cents"] = income
    customer["residence_months"] = residence
    customer["government_id_verified"] = gov_id
    customer["in_person_contact_consent"] = consent
    customer["verification_status"] = "PENDING"
    customer["verification_score"] = 0
    customer["verified_reference_count"] = 0
    customer["verified_by_user_id"] = ""
    customer["loyalty_points_balance"] = 0
    customer["loyalty_points_lifetime"] = 0
    customer["loyalty_tier"] = "STANDARD"
    customer["credit_balance_cents"] = 0
    customer["account_flag"] = "NORMAL"
    customer["adverse_agreement_count"] = 0
    customer["lifetime_delinquency_count"] = 0
    db.customers[customer["id"]] = customer
    return response.object_response(public(customer), 201)


@bp.get("/customers/<customer_id>")
def read_customer(customer_id):
    user_id, role = middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.COLLECTIONS_AGENT,
            middleware.CUSTOMER,
        )
    )
    customer = domain.require_customer(customer_id)
    middleware.require_owner(role, user_id, customer["id"])
    return response.object_response(public(customer))


@bp.get("/customers")
def list_customers():
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.COLLECTIONS_AGENT,
        )
    )
    return common.paged(
        list(db.customers.values()),
        filters=("verification_status", "state_code", "account_flag"),
    )


# ----------------------------------------------------------------- references


@bp.post("/customers/<customer_id>/references")
def create_reference(customer_id):
    middleware.authenticate(
        (middleware.PLATFORM_ADMIN, middleware.STORE_MANAGER, middleware.SALES_ASSOCIATE)
    )
    customer = domain.require_customer(customer_id)
    body = validators.json_body()
    name = validators.string(body, "reference_name", min_len=1, max_len=120)
    relationship = validators.enum(body, "relationship", RELATIONSHIPS)
    phone = validators.string(body, "phone", min_len=0)

    reference = base_row()
    reference["customer_id"] = customer["id"]
    reference["reference_name"] = name
    reference["relationship"] = relationship
    reference["phone"] = phone
    reference["check_status"] = "PENDING"
    reference["checked_at"] = None
    reference["checked_by_user_id"] = ""
    db.references[reference["id"]] = reference
    return response.object_response(public(reference), 201)


@bp.get("/customers/<customer_id>/references")
def list_references(customer_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
        )
    )
    customer = domain.require_customer(customer_id)
    rows = [
        r for r in db.references.values() if r["customer_id"] == customer["id"]
    ]
    return common.paged(rows, filters=("check_status",))


@bp.post("/customer-references/<reference_id>/check")
def check_reference(reference_id):
    user_id, _ = middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
        )
    )
    reference = domain.require_reference(reference_id)
    body = validators.json_body()
    result = validators.enum(body, "result", CHECK_RESULTS)
    if reference["check_status"] != "PENDING":
        raise ApiError("ERR_REFERENCE_ALREADY_CHECKED")

    reference["check_status"] = result
    reference["checked_at"] = clock.now_str()
    reference["checked_by_user_id"] = user_id
    touch(reference)
    customer = db.customers.get(reference["customer_id"])
    if customer is not None:
        domain.sync_customer(customer)
    return response.object_response(public(reference))


@bp.post("/customers/<customer_id>/verify")
def verify_customer(customer_id):
    user_id, _ = middleware.authenticate((middleware.COMPLIANCE_OFFICER,))
    customer = domain.require_customer(customer_id)
    body = validators.json_body()
    decision = validators.enum(body, "decision", DECISIONS)
    credit_score = validators.integer(
        body, "credit_score", required=False, default=None
    )

    rule = domain.require_rule_for_state(customer["state_code"])
    if credit_score is not None and rule["credit_inquiry_prohibited"]:
        raise ApiError("ERR_CREDIT_REPORT_PROHIBITED")

    # every call, including one that ends in rejection, stores the fresh score
    score = calc.verification_score(customer)
    if customer["verification_score"] != score:
        customer["verification_score"] = score
        touch(customer)

    if decision == "APPROVE":
        if (
            not customer["government_id_verified"]
            or customer["verified_reference_count"] < calc.MIN_VERIFIED_REFERENCES
        ):
            raise ApiError("ERR_INSUFFICIENT_REFERENCES")
        if score < calc.VERIFICATION_PASS_SCORE:
            raise ApiError("ERR_VERIFICATION_SCORE_TOO_LOW")
        customer["verification_status"] = "VERIFIED"
        customer["verified_by_user_id"] = user_id
    else:
        customer["verification_status"] = "REJECTED"
    touch(customer)
    return response.object_response(public(customer))


# -------------------------------------------------------------- loyalty ledger


@bp.get("/loyalty-ledger-entries/<entry_id>")
def read_ledger_entry(entry_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.CUSTOMER,
        )
    )
    entry = domain.require_ledger_entry(entry_id)
    return response.object_response(public(entry))


@bp.get("/loyalty-ledger-entries")
def list_ledger_entries():
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.CUSTOMER,
        )
    )
    return common.paged(
        list(db.ledger.values()),
        primary="occurred_at",
        filters=("customer_id", "agreement_id", "source_payment_id", "entry_type"),
    )
