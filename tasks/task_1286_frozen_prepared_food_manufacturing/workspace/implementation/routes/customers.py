"""Co-pack customers (PRD §3.2)."""

from flask import request

import services as svc
from db import STORE, new_record
from errors import ApiError
from middleware import endpoint
from response import ok_object
from routes import bp
from serializers import customer_out
from util import (
    BILLING_METHODS,
    as_bool,
    as_enum,
    as_nonnegative_int,
    as_string,
    body_dict,
    opt_present,
    req_present,
)


@bp.route("/plant/copack-customers", methods=["POST"])
@endpoint({"PlantManager"})
def create_customer(user_id, role):
    body = body_dict(request.get_json(silent=True))
    name = as_string(req_present(body, "name"), "name")
    method = as_enum(req_present(body, "billing_method"), "billing_method", BILLING_METHODS)
    case_rate = body.get("case_rate_cents")
    kg_rate = body.get("kg_rate_cents")
    # Rate fields are conditional on billing_method: required iff matching,
    # null/absent otherwise; the wrong combination is a shape failure (PRD §3.2).
    if method == "PER_CASE":
        if case_rate is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "case_rate_cents is required when billing_method is PER_CASE"
            )
        case_rate = as_nonnegative_int(case_rate, "case_rate_cents")
        if kg_rate is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "kg_rate_cents must be null when billing_method is PER_CASE"
            )
    else:  # PER_KG
        if kg_rate is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "kg_rate_cents is required when billing_method is PER_KG"
            )
        kg_rate = as_nonnegative_int(kg_rate, "kg_rate_cents")
        if case_rate is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "case_rate_cents must be null when billing_method is PER_KG"
            )
    allergen = opt_present(body, "requires_allergen_changeover", False)
    allergen = as_bool(allergen, "requires_allergen_changeover")
    changeover = opt_present(body, "base_changeover_minutes", 45)
    changeover = as_nonnegative_int(changeover, "base_changeover_minutes")

    rec = new_record()
    rec.update(
        name=name,
        billing_method=method,
        case_rate_cents=case_rate if method == "PER_CASE" else None,
        kg_rate_cents=kg_rate if method == "PER_KG" else None,
        requires_allergen_changeover=allergen,
        base_changeover_minutes=changeover,
    )
    STORE["customers"][rec["id"]] = rec
    return ok_object(customer_out(rec), 201)


@bp.route("/plant/copack-customers/<customerId>", methods=["GET"])
@endpoint({"PlantManager", "ProductionPlanner", "CoPackCustomer"})
def get_customer(user_id, role, customerId):
    cust = svc.require_record("customers", customerId, "CoPackCustomer")
    if role == "CoPackCustomer" and cust["id"] != user_id:
        raise ApiError(
            "ERR_CROSS_CUSTOMER_ACCESS", "CoPackCustomer may read only its own record"
        )
    return ok_object(customer_out(cust))
