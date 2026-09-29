"""Buyers, credit terms and exposure control (PRD 3.2)."""

from flask import Blueprint, g

import db
import serializers
from db import store, touch
from errors import ApiError
from lookup import path_ref
from middleware import roles
from response import success, success_list
from services import calc
from validation import (
    apply_page,
    body,
    pagination,
    q_enum,
    v_decimal,
    v_enum,
    v_int,
    v_string,
)

bp = Blueprint("customers", __name__)

SETTLEMENT_BASES = ("SUPPLIER_FIGURES", "JOINT_SURVEY_MANDATORY")
CREDIT_STATUSES = ("OK", "WATCH", "HOLD")


@bp.post("/customers")
@roles("CreditController")
def create_customer():
    data = body()
    name = v_string(data, "name", min_len=1)
    credit_limit_usd = v_decimal(data, "credit_limit_usd", 2, min_value=0)
    payment_terms_days = v_int(data, "payment_terms_days", required=False, default=30, min_value=0)
    settlement_basis = v_enum(
        data, "settlement_basis", SETTLEMENT_BASES, required=False, default="SUPPLIER_FIGURES"
    )

    customer = db.new_record()
    customer.update(
        {
            "name": name,
            "credit_limit_usd": credit_limit_usd,
            "payment_terms_days": payment_terms_days,
            "settlement_basis": settlement_basis,
            "outstanding_balance_usd": None,
            "conservative_exposure_usd": None,
            "available_credit_usd": None,
            "open_commitment_count": 0,
            "credit_status": "OK",
        }
    )
    # No invoices or nominations can reference a brand-new customer, so this
    # simply writes the zero-exposure projection.
    calc.recompute_exposure(customer, strict=False)
    store.customers[customer["id"]] = customer
    return success(serializers.customer(customer), 201)


@bp.get("/customers/<rec_id>")
@roles("CreditController", "OpsCoordinator")
def get_customer(rec_id):
    customer = path_ref(store.customers, rec_id, "ERR_CUSTOMER_NOT_FOUND")
    return success(serializers.customer(customer))


@bp.get("/customers")
@roles("CreditController", "OpsCoordinator")
def list_customers():
    credit_status = q_enum("credit_status", CREDIT_STATUSES)
    limit, offset = pagination()
    rows = db.sorted_rows(
        store.customers,
        lambda r: credit_status is None or r["credit_status"] == credit_status,
    )
    page = apply_page(rows, limit, offset)
    return success_list([serializers.customer(r) for r in page], limit, offset, len(rows))


@bp.get("/customers/<rec_id>/credit-exposure")
@roles("CreditController", "CustomerRep")
def credit_exposure(rec_id):
    customer = path_ref(store.customers, rec_id, "ERR_CUSTOMER_NOT_FOUND")
    if g.role == "CustomerRep" and g.user_id != customer["id"]:
        raise ApiError("ERR_CUSTOMER_SCOPE_VIOLATION")
    # A computed read: all five projection fields are rewritten. A qualifying
    # nomination without a governing quote is a hard failure here (PRD 2.12).
    calc.recompute_exposure(customer, strict=True)
    return success(serializers.customer(customer))


@bp.post("/customers/<rec_id>/credit-review")
@roles("CreditController")
def credit_review(rec_id):
    customer = path_ref(store.customers, rec_id, "ERR_CUSTOMER_NOT_FOUND")
    data = body()
    credit_limit_usd = v_decimal(data, "credit_limit_usd", 2, required=False, min_value=0)
    settlement_basis = v_enum(data, "settlement_basis", SETTLEMENT_BASES, required=False)

    if credit_limit_usd is not None:
        customer["credit_limit_usd"] = credit_limit_usd
    if settlement_basis is not None:
        customer["settlement_basis"] = settlement_basis
    calc.recompute_settled(customer)
    touch(customer)
    return success(serializers.customer(customer))
