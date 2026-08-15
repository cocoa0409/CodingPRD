"""License application endpoints: draft, submit/resubmit, three-way review,
director revocation with downstream hold cascade."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CLASSIFICATION_REQUIRED,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VALIDATION,
)
from middleware import (
    auth,
    get_body,
    no_unknown,
    need,
    v_str,
    v_int,
    v_enum,
    v_date,
    find,
    check_body_fks,
    page_params,
    filtered_sorted,
)
from response import ok, list_response
from services.audit import write_audit
from services.cascade import cascade_order_hold

bp = Blueprint("licenses", __name__)

AUTHORITIES = ("BIS", "DDTC", "OFAC")
CONDITIONS = ("NO_REEXPORT", "NO_MILITARY_END_USE", "QUARTERLY_REPORTING")


@bp.post("/compliance/licenses")
def create_license():
    auth("ComplianceAnalyst")
    body = get_body()
    # Priority 3: body FK existence
    check_body_fks(body, (("product_id", db.PRODUCTS),))
    # Priority 4: request shape
    no_unknown(
        body,
        {"product_id", "issuing_authority", "approved_value_cents", "approved_quantity",
         "valid_from", "valid_until", "conditions"},
    )
    product_id = v_str(need(body, "product_id"), "product_id")
    authority = v_enum(need(body, "issuing_authority"), "issuing_authority", AUTHORITIES)
    value = v_int(need(body, "approved_value_cents"), "approved_value_cents")
    if value <= 0:
        raise ApiError(ERR_VALIDATION, "approved_value_cents must be > 0", 400)
    qty = v_int(need(body, "approved_quantity"), "approved_quantity")
    if qty <= 0:
        raise ApiError(ERR_VALIDATION, "approved_quantity must be > 0", 400)
    valid_from = v_date(need(body, "valid_from"), "valid_from")
    valid_until = v_date(need(body, "valid_until"), "valid_until")
    if valid_from > valid_until:
        raise ApiError(ERR_VALIDATION, "valid_from must not be after valid_until", 400)
    conditions = []
    if "conditions" in body:
        raw = body["conditions"]
        if not isinstance(raw, list):
            raise ApiError(ERR_VALIDATION, "conditions must be an array", 400)
        for entry in raw:
            v_enum(entry, "conditions", CONDITIONS)
        conditions = list(raw)
    find(db.PRODUCTS, product_id, "Product")
    license_ = {
        "product_id": product_id,
        "issuing_authority": authority,
        "approved_value_cents": value,
        "approved_quantity": qty,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "conditions": conditions,
        "license_number": None,
        "remaining_value_cents": None,
        "remaining_quantity": None,
        "consumed_value_cents": 0,
        "consumed_quantity": 0,
        "applicant_user_id": None,
        "reviewed_by_user_id": None,
        "status": "DRAFT",
    }
    db.stamp_new(license_)
    db.LICENSES[license_["id"]] = license_
    return ok(db.pub(license_), "object", 201)


@bp.get("/compliance/licenses/<lid>")
def get_license(lid):
    auth()
    license_ = find(db.LICENSES, lid, "License")
    return ok(db.pub(license_), "object", 200)


@bp.get("/compliance/licenses")
def list_licenses():
    auth()
    filters = {
        "product_id": request.args.get("product_id"),
        "status": request.args.get("status"),
    }
    items = filtered_sorted(db.LICENSES, filters)
    limit, offset = page_params()
    return list_response(items, limit, offset)


@bp.post("/compliance/licenses/<lid>/submit")
def submit_license(lid):
    uid, _ = auth("ComplianceAnalyst")
    license_ = find(db.LICENSES, lid, "License")
    if license_["status"] == "DRAFT":
        product = find(db.PRODUCTS, license_["product_id"], "Product")
        if product["status"] != "CLASSIFIED":
            raise ApiError(
                ERR_CLASSIFICATION_REQUIRED,
                "Product %s has no ACTIVE classification" % product["id"],
                409,
            )
    elif license_["status"] != "RETURNED_FOR_INFO":
        raise ApiError(ERR_INVALID_STATE, "License is not DRAFT or RETURNED_FOR_INFO", 409)
    license_["status"] = "SUBMITTED"
    license_["applicant_user_id"] = uid  # (re-)anchors SoD on every submission
    db.touch(license_)
    return ok(db.pub(license_), "object", 200)


@bp.post("/compliance/licenses/<lid>/review")
def review_license(lid):
    uid, role = auth("ComplianceManager")
    license_ = find(db.LICENSES, lid, "License")
    body = get_body()
    no_unknown(body, {"decision"})
    decision = v_enum(need(body, "decision"), "decision", ("APPROVE", "DENY", "RETURN"))
    if license_["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "License is not SUBMITTED", 409)
    if uid == license_["applicant_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES, "Reviewer must differ from the applicant", 409
        )
    license_["reviewed_by_user_id"] = uid
    if decision == "APPROVE":
        license_["status"] = "APPROVED"
        license_["license_number"] = db.next_license_number()
        license_["remaining_value_cents"] = license_["approved_value_cents"]
        license_["remaining_quantity"] = license_["approved_quantity"]
        db.touch(license_)
        write_audit(
            "LICENSE_APPROVED", "License", license_["id"], role, uid,
            "License %s approved as %s" % (license_["id"], license_["license_number"]),
        )
    elif decision == "DENY":
        license_["status"] = "DENIED"
        db.touch(license_)
    else:  # RETURN
        license_["status"] = "RETURNED_FOR_INFO"
        db.touch(license_)
    return ok(db.pub(license_), "object", 200)


@bp.post("/compliance/licenses/<lid>/revoke")
def revoke_license(lid):
    uid, role = auth("ComplianceDirector")
    license_ = find(db.LICENSES, lid, "License")
    if license_["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "License is not APPROVED", 409)
    license_["status"] = "REVOKED"
    db.touch(license_)
    # Cascade: attached LICENSED orders -> HELD (license reference retained);
    # their PLANNED|SCREENED shipments -> HELD.
    for order in db.ORDERS.values():
        if order["license_id"] == license_["id"] and order["status"] == "LICENSED":
            cascade_order_hold(order)
    write_audit(
        "LICENSE_REVOKED", "License", license_["id"], role, uid,
        "License %s revoked" % license_["id"],
    )
    return ok(db.pub(license_), "object", 200)
