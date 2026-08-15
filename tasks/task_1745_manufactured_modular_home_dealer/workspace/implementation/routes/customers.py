"""Customers (PRD 3.2)."""

from flask import Blueprint

from db import create_record, store
from errors import fail
from middleware import ALL_ROLES, require
from response import ok
from services import get_or_404, ser
from validate import Shape, get_body

bp = Blueprint("customers", __name__)

CREDIT_TIERS = ["TIER_A", "TIER_B", "TIER_C"]


@bp.post("/customers")
@require("SalesConsultant")
def create_customer(actor_id, actor_role):
    shape = Shape(get_body())
    shape.req_str("full_name")
    shape.req_str("email")
    shape.req_str("phone")
    shape.req_enum("credit_tier", CREDIT_TIERS)
    # (18) uniqueness: email across all customers
    if shape.ok("email"):
        email = shape.value("email")
        if any(c["email"] == email for c in store.customers.values()):
            fail("ERR_DUPLICATE_RESOURCE", "email already registered")
    shape.raise_if_errors()
    rec = create_record(store.customers, {
        "full_name": shape.value("full_name"),
        "email": shape.value("email"),
        "phone": shape.value("phone"),
        "credit_tier": shape.value("credit_tier"),
        "status": "ACTIVE",
    })
    return ok(ser(rec), 201)


@bp.get("/customers/<rid>")
@require(*ALL_ROLES)
def get_customer(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.customers, rid, "ERR_CUSTOMER_NOT_FOUND", "Customer")))
