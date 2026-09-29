"""Chemical deliveries: the priced drop and its compensating void."""

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

bp = Blueprint("deliveries", __name__)

CLOSED_REVIEW_STATUSES = ("PUBLISHED", "ESCALATED", "CLOSED")


@bp.route("/chemical-deliveries", methods=["POST"])
def create_delivery():
    middleware.require_roles(ROLE_ACCOUNT_MANAGER)
    body = middleware.body_object()
    site_id = middleware.f_str(body, "site_id", required=True)
    product_id = middleware.f_str(body, "product_id", required=True)
    delivered_at = middleware.f_dt(body, "delivered_at", required=True)
    unit_count = middleware.f_int(body, "unit_count", required=True, minimum=1)
    expected_version = middleware.f_int(
        body, "expected_site_version", required=True, minimum=0
    )

    site = middleware.must_reference("sites", site_id, "site_id")
    product = middleware.must_reference(
        "chemical_products", product_id, "product_id"
    )
    middleware.check_parent_version(site, expected_version, "Site")

    if product_id not in derive.covered_product_ids_of_site(site):
        raise ApiError(
            "ERR_PRODUCT_NOT_ON_AGREEMENT",
            "The product is not covered by a live agreement of this account",
        )

    customer = db.get("customers", site["customer_id"])
    if customer is not None and customer["billing_status"] == "CREDIT_HOLD":
        raise ApiError(
            "ERR_CUSTOMER_CREDIT_HOLD", "The account is on credit hold"
        )

    quantity_ml, amount = calc.delivery_amount(product, unit_count)
    row = db.insert("chemical_deliveries", {
        "site_id": site_id,
        "product_id": product_id,
        "delivered_at": delivered_at,
        "unit_count": unit_count,
        "quantity_ml": quantity_ml,
        "amount_cents": amount,
        "status": "DELIVERED",
    })
    db.mark(site)
    return response.created(response.serialize(row))


@bp.route("/chemical-deliveries/<delivery_id>", methods=["GET"])
def read_delivery(delivery_id):
    user_id, role = middleware.require_roles(
        ROLE_ACCOUNT_MANAGER, ROLE_QUALITY_AUDITOR, ROLE_CUSTOMER_CONTACT
    )
    row = db.get("chemical_deliveries", delivery_id)
    if row is not None:
        site = db.get("sites", row["site_id"])
        middleware.scope_customer(
            role, user_id, site["customer_id"] if site else None
        )
    row = middleware.must_exist(
        "chemical_deliveries", delivery_id, "ChemicalDelivery"
    )
    return response.ok(response.serialize(row))


@bp.route("/chemical-deliveries", methods=["GET"])
def list_deliveries():
    user_id, role = middleware.require_roles(
        ROLE_ACCOUNT_MANAGER, ROLE_QUALITY_AUDITOR, ROLE_CUSTOMER_CONTACT
    )
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("chemical_deliveries"), (
        ("site_id", "site_id"),
        ("product_id", "product_id"),
        ("status", "status"),
    ))
    rows = common.scope_list_to_customer(
        rows, role, user_id, lambda row: common.owner_of_site(row["site_id"])
    )
    return common.listing(rows, limit, offset)


@bp.route("/chemical-deliveries/<delivery_id>/void", methods=["POST"])
def void_delivery(delivery_id):
    middleware.require_roles(ROLE_ACCOUNT_MANAGER)
    middleware.body_object()
    delivery = middleware.must_exist(
        "chemical_deliveries", delivery_id, "ChemicalDelivery"
    )
    if delivery["status"] != "DELIVERED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The delivery is %s, not DELIVERED" % delivery["status"],
        )

    moment = delivery["delivered_at"]
    for review in db.rows("usage_variance_reviews"):
        if review["site_id"] != delivery["site_id"]:
            continue
        if review["product_id"] != delivery["product_id"]:
            continue
        if review["status"] not in CLOSED_REVIEW_STATUSES:
            continue
        if review["period_start"] <= moment < review["period_end"]:
            raise ApiError(
                "ERR_DELIVERY_IN_CLOSED_PERIOD",
                "A published review's window contains this delivery",
            )

    delivery["status"] = "VOIDED"
    db.mark(delivery)
    site = db.get("sites", delivery["site_id"])
    if site is not None:
        db.mark(site)
    return response.ok(response.serialize(delivery))
