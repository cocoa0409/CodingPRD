"""Product registration, pack facts, marketing launch and the risk profile read."""

from flask import Blueprint

import auth
import calc
import cascade
import db
import errors
import response
import serialize
import validate
from errors import fail
from routes.helpers import PREFIX, listing, path_row

bp = Blueprint("products", __name__)

READ_ROLES = (
    auth.ROLE_SPECIALIST,
    auth.ROLE_REVIEWER,
    auth.ROLE_APPROVAL,
    auth.ROLE_QA,
    auth.ROLE_AUDITOR,
)
RISK_ROLES = (auth.ROLE_SPECIALIST, auth.ROLE_APPROVAL, auth.ROLE_QA, auth.ROLE_AUDITOR)


@bp.route(PREFIX + "/products", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def create_product():
    body = validate.body()
    brand_name = validate.req_str(body, "brand_name")
    product_name = validate.req_str(body, "product_name")
    net_quantity_g = validate.req_number(body, "net_quantity_g", gt=0)
    servings_per_container = validate.req_int(body, "servings_per_container", gt=0)

    row = db.base_fields()
    row.update(
        {
            "brand_name": brand_name,
            "product_name": product_name,
            "net_quantity_g": net_quantity_g,
            "servings_per_container": servings_per_container,
            "lifecycle_status": "DRAFT",
            "label_posture": "OPEN",
            "marketing_start_date": None,
            "serious_ae_count": 0,
            "nonserious_ae_count": 0,
            "late_notification_count": 0,
            "rejected_coa_count": 0,
            "compliance_risk_index": calc.BASE_FLOOR,
            "active_claim_count": 0,
            "withdrawn_claim_count": 0,
            "requires_label_revision": False,
        }
    )
    db.insert("products", row)
    return response.object_response(serialize.product(row), 201)


@bp.route(PREFIX + "/products/<row_id>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def get_product(row_id):
    row = path_row("products", row_id, errors.ERR_PRODUCT_NOT_FOUND)
    return response.object_response(serialize.product(row))


@bp.route(PREFIX + "/products", methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_products():
    return listing(
        "products", serialize.product, filters=("lifecycle_status", "label_posture")
    )


@bp.route(PREFIX + "/products/<row_id>", methods=["PATCH"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def amend_product(row_id):
    row = path_row("products", row_id, errors.ERR_PRODUCT_NOT_FOUND)
    body = validate.body()

    sentinel = object()
    brand_name = validate.opt_str(body, "brand_name", default=sentinel, allow_null=False)
    product_name = validate.opt_str(body, "product_name", default=sentinel, allow_null=False)
    net_quantity_g = validate.opt_number(
        body, "net_quantity_g", default=sentinel, gt=0, allow_null=False
    )
    servings = validate.opt_int(
        body, "servings_per_container", default=sentinel, gt=0, allow_null=False
    )

    if row["lifecycle_status"] != "DRAFT":
        fail(
            errors.ERR_PRODUCT_STATE_INVALID,
            "Pack facts may only be amended while the product is in DRAFT.",
        )

    if brand_name is not sentinel:
        row["brand_name"] = brand_name
    if product_name is not sentinel:
        row["product_name"] = product_name
    if net_quantity_g is not sentinel:
        row["net_quantity_g"] = net_quantity_g
    if servings is not sentinel:
        row["servings_per_container"] = servings
    db.touch(row)
    return response.object_response(serialize.product(row))


@bp.route(PREFIX + "/products/<row_id>/start-marketing", methods=["POST"])
@auth.endpoint([auth.ROLE_APPROVAL])
def start_marketing(row_id):
    row = path_row("products", row_id, errors.ERR_PRODUCT_NOT_FOUND)
    body = validate.body()
    validate.req_date(body, "marketing_start_date")

    if row["lifecycle_status"] != "LABEL_LOCKED":
        fail(
            errors.ERR_PRODUCT_STATE_INVALID,
            "Marketing may only start from LABEL_LOCKED.",
        )
    if row["label_posture"] == "FROZEN":
        fail(errors.ERR_PRODUCT_LABEL_FROZEN, "A FROZEN product may not start marketing.")
    for supplier in cascade.derived_suppliers(row):
        if supplier["qualification_status"] != "QUALIFIED":
            fail(
                errors.ERR_SUPPLIER_NOT_QUALIFIED,
                "Supplier %s is not QUALIFIED." % supplier["id"],
            )

    # The stored date is the UTC calendar date of the logical clock at the transition.
    launch_date = db.today()
    row["lifecycle_status"] = "MARKETED"
    row["marketing_start_date"] = launch_date
    db.touch(row)

    for claim in cascade.claims_of(row["id"]):
        if claim["substantiation_status"] != "APPROVED":
            continue
        if claim["notification_status"] != "NOT_DUE":
            continue
        claim["notification_status"] = "DUE"
        claim["notification_due_basis"] = "PRODUCT_LAUNCH_BASIS"
        claim["notification_due_date"] = calc.add_days(
            launch_date, calc.NOTIFICATION_WINDOW_DAYS
        )
        db.touch(claim)

    return response.object_response(serialize.product(row))


@bp.route(PREFIX + "/products/<row_id>/risk-profile", methods=["GET"])
@auth.endpoint(RISK_ROLES)
def risk_profile(row_id):
    row = path_row("products", row_id, errors.ERR_PRODUCT_NOT_FOUND)
    base = calc.risk_base(row)
    surcharge = calc.escalation_surcharge(base)
    supplier_ids = cascade.derived_supplier_ids(row)
    return response.object_response(
        serialize.risk_profile(row, base, surcharge, supplier_ids)
    )
