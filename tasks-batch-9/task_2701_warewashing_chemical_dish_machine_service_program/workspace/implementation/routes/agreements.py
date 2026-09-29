"""The chemical supply agreement: draft, activate, renew, terminate."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from middleware import (
    ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT, ROLE_QUALITY_AUDITOR,
)
from routes import common
from services import calc, derive
from util import add_months, midnight

bp = Blueprint("agreements", __name__)

LIVE = ("ACTIVE", "RENEWAL_PENDING")


@bp.route("/service-agreements", methods=["POST"])
def create_agreement():
    middleware.require_roles(ROLE_ACCOUNT_MANAGER)
    body = middleware.body_object()
    customer_id = middleware.f_str(body, "customer_id", required=True)
    code = middleware.f_str(
        body, "agreement_code", required=True, min_len=1, max_len=64
    )
    start_date = middleware.f_date(body, "start_date", required=True)
    term_months = middleware.f_int(
        body, "minimum_term_months", required=True, minimum=1
    )
    monthly_minimum = middleware.f_int(
        body, "monthly_minimum_spend_cents", required=True, minimum=0
    )
    product_ids = middleware.f_str_list(
        body, "covered_product_ids", required=True
    )
    notice_days = middleware.f_int(body, "renewal_notice_days", minimum=1)
    auto_renew = middleware.f_bool(body, "auto_renew", default=False)
    if "term_end_date" in body and body["term_end_date"] is not None:
        middleware.bad("term_end_date is derived and must not be supplied")

    middleware.must_reference("customers", customer_id, "customer_id")
    for product_id in product_ids:
        middleware.must_reference("chemical_products", product_id, "product_id")

    for existing in db.rows("service_agreements"):
        if existing["agreement_code"] == code:
            raise ApiError(
                "ERR_INVALID_REQUEST", "agreement_code is already in use"
            )

    row = db.insert("service_agreements", {
        "customer_id": customer_id,
        "agreement_code": code,
        "start_date": start_date,
        "minimum_term_months": term_months,
        "monthly_minimum_spend_cents": monthly_minimum,
        "covered_product_ids": list(product_ids),
        "renewal_notice_days": notice_days if notice_days is not None else 60,
        "auto_renew": bool(auto_renew),
        "status": "DRAFT",
        "term_end_date": None,
        "renewal_count": 0,
        "placement_count": 0,
        "early_termination_fee_cents": None,
        "termination_effective_date": None,
    })
    return response.created(response.serialize(row))


@bp.route("/service-agreements/<agreement_id>", methods=["GET"])
def read_agreement(agreement_id):
    user_id, role = middleware.require_roles(
        ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT, ROLE_QUALITY_AUDITOR
    )
    row = db.get("service_agreements", agreement_id)
    middleware.scope_customer(
        role, user_id, row["customer_id"] if row else None
    )
    row = middleware.must_exist(
        "service_agreements", agreement_id, "ServiceAgreement"
    )
    return response.ok(response.serialize(row))


@bp.route("/service-agreements", methods=["GET"])
def list_agreements():
    middleware.require_roles(ROLE_ACCOUNT_MANAGER, ROLE_QUALITY_AUDITOR)
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("service_agreements"), (
        ("customer_id", "customer_id"),
        ("status", "status"),
    ))
    return common.listing(rows, limit, offset)


@bp.route("/service-agreements/<agreement_id>/activate", methods=["POST"])
def activate_agreement(agreement_id):
    middleware.require_roles(ROLE_ACCOUNT_MANAGER)
    middleware.body_object()
    agreement = middleware.must_exist(
        "service_agreements", agreement_id, "ServiceAgreement"
    )
    if agreement["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a DRAFT agreement can be activated",
        )
    for product_id in agreement["covered_product_ids"]:
        middleware.must_reference("chemical_products", product_id, "product_id")

    agreement["status"] = "ACTIVE"
    agreement["term_end_date"] = calc.term_end_date(
        agreement["start_date"], agreement["minimum_term_months"]
    )
    db.mark(agreement)
    derive.recompute_customer(db.get("customers", agreement["customer_id"]))
    return response.ok(response.serialize(agreement))


@bp.route("/service-agreements/<agreement_id>/renewal", methods=["POST"])
def renew_agreement(agreement_id):
    middleware.require_roles(ROLE_ACCOUNT_MANAGER)
    body = middleware.body_object()
    extra_months = middleware.f_int(body, "renewal_term_months", minimum=1)
    agreement = middleware.must_exist(
        "service_agreements", agreement_id, "ServiceAgreement"
    )
    status = agreement["status"]
    if status not in LIVE:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "An agreement in %s cannot be renewed" % status,
        )
    end_date = agreement["term_end_date"]
    if status == "ACTIVE":
        now = db.now()
        end_instant = midnight(end_date)
        window_open = end_instant - timedelta(
            days=agreement["renewal_notice_days"]
        )
        if now < window_open or now >= end_instant:
            raise ApiError(
                "ERR_RENEWAL_WINDOW_NOT_OPEN",
                "The renewal notice window is not open",
            )
    months = extra_months
    if months is None:
        months = agreement["minimum_term_months"]
    agreement["term_end_date"] = add_months(end_date, months)
    agreement["renewal_count"] = agreement["renewal_count"] + 1
    agreement["status"] = "ACTIVE"
    db.mark(agreement)
    derive.recompute_customer(db.get("customers", agreement["customer_id"]))
    return response.ok(response.serialize(agreement))


@bp.route("/service-agreements/<agreement_id>/terminate", methods=["POST"])
def terminate_agreement(agreement_id):
    middleware.require_roles(ROLE_ACCOUNT_MANAGER)
    body = middleware.body_object()
    effective_date = middleware.f_date(body, "effective_date", required=True)
    agreement = middleware.must_exist(
        "service_agreements", agreement_id, "ServiceAgreement"
    )
    status = agreement["status"]
    if status == "DRAFT":
        agreement["status"] = "VOID"
        agreement["early_termination_fee_cents"] = 0
        agreement["termination_effective_date"] = effective_date
        db.mark(agreement)
        return response.ok(response.serialize(agreement))

    if status not in LIVE:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "An agreement in %s cannot be terminated" % status,
        )
    if effective_date < db.now().date():
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "effective_date must not be earlier than the current clock date",
        )

    agreement["termination_effective_date"] = effective_date
    fee, _months = calc.early_termination_fee(
        agreement,
        derive.placements_of_agreement(agreement["id"]),
        derive.model_of_placement,
    )
    agreement["early_termination_fee_cents"] = fee
    agreement["status"] = "TERMINATED"
    db.mark(agreement)
    derive.cascade_alpha(agreement, retrieval_due_days=30)
    return response.ok(response.serialize(agreement))
