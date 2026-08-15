"""Product offerings and product certifications."""

from flask import Blueprint, request

from db import store, base_record, touch, audit
from errors import (ApiError, ERR_DUPLICATE_PRODUCT_CODE,
                    ERR_PRODUCT_NOT_PROPOSED, ERR_PRODUCT_NOT_LAUNCHED,
                    ERR_PRODUCT_TRAINING_CONTENT_NOT_APPROVED,
                    ERR_CERTIFICATION_NOT_SUSPENDED, ERR_REINSTATEMENT_BLOCKED)
from middleware import require_roles, actor, json_body, require_fields
from response import success, paginate
from services import (get_or_404, by_seq, launch_product, withdraw_product)
from util import require_str, view

bp = Blueprint("products", __name__)

ANY = ("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")


@bp.post("/products")
@require_roles("ComplianceOfficer")
def create_product():
    body = json_body()
    content = None
    if body.get("required_training_content_id") is not None:
        content = get_or_404(store.contents,
                             body["required_training_content_id"],
                             "TrainingContent")
    require_fields(body, "product_code", "name", "required_training_content_id")
    product_code = require_str(body["product_code"], "product_code")
    name = require_str(body["name"], "name")
    for p in store.products.values():
        if p["product_code"] == product_code:
            raise ApiError(ERR_DUPLICATE_PRODUCT_CODE, 409,
                           "product_code '%s' already exists" % product_code)
    rec = base_record()
    rec.update({
        "product_code": product_code,
        "name": name,
        "required_training_content_id": content["id"],
        "product_status": "PROPOSED",
        "launched_at": None,
    })
    store.products[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/products")
@require_roles(*ANY)
def list_products():
    items = by_seq(store.products.values())
    product_status = request.args.get("product_status")
    if product_status is not None:
        items = [p for p in items if p["product_status"] == product_status]
    rtc = request.args.get("required_training_content_id")
    if rtc is not None:
        items = [p for p in items if p["required_training_content_id"] == rtc]
    items = sorted(items, key=lambda p: (p["created_at"], p["_seq"]))
    page, pagination = paginate(items)
    return success([view(p) for p in page], is_list=True, pagination=pagination)


@bp.get("/products/<productId>")
@require_roles(*ANY)
def get_product(productId):
    rec = get_or_404(store.products, productId, "ProductOffering")
    return success(view(rec))


@bp.post("/products/<productId>/launch")
@require_roles("ComplianceOfficer")
def launch_product_route(productId):
    rec = get_or_404(store.products, productId, "ProductOffering")
    if rec["product_status"] != "PROPOSED":
        raise ApiError(ERR_PRODUCT_NOT_PROPOSED, 409,
                       "launch requires product_status == PROPOSED")
    content = store.contents.get(rec["required_training_content_id"])
    if content is None or content["content_status"] != "APPROVED":
        raise ApiError(ERR_PRODUCT_TRAINING_CONTENT_NOT_APPROVED, 409,
                       "Required training content is not APPROVED")
    launch_product(rec, actor())
    return success(view(rec))


@bp.post("/products/<productId>/withdraw")
@require_roles("ComplianceOfficer")
def withdraw_product_route(productId):
    rec = get_or_404(store.products, productId, "ProductOffering")
    if rec["product_status"] != "LAUNCHED":
        raise ApiError(ERR_PRODUCT_NOT_LAUNCHED, 409,
                       "withdraw requires product_status == LAUNCHED")
    withdraw_product(rec, actor())
    return success(view(rec))


@bp.get("/product-certifications")
@require_roles(*ANY)
def list_certifications():
    items = by_seq(store.certifications.values())
    for param in ("rep_id", "product_id", "enrollment_id", "cert_status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    items = sorted(items, key=lambda c: (c["created_at"], c["_seq"]))
    page, pagination = paginate(items)
    return success([view(c) for c in page], is_list=True, pagination=pagination)


@bp.get("/product-certifications/<certId>")
@require_roles(*ANY)
def get_certification(certId):
    rec = get_or_404(store.certifications, certId, "ProductCertification")
    return success(view(rec))


@bp.post("/product-certifications/<certId>/reinstate")
@require_roles("ComplianceOfficer")
def reinstate_certification(certId):
    rec = get_or_404(store.certifications, certId, "ProductCertification")
    if rec["cert_status"] != "SUSPENDED":
        raise ApiError(ERR_CERTIFICATION_NOT_SUSPENDED, 409,
                       "reinstate requires cert_status == SUSPENDED")
    rep = store.representatives.get(rec["rep_id"])
    product = store.products.get(rec["product_id"])
    enrollment = store.enrollments.get(rec["enrollment_id"]) \
        if rec["enrollment_id"] else None
    content = store.contents.get(enrollment["content_id"]) \
        if enrollment else None
    blocked = (
        rep is None or rep["registration_status"] != "ACTIVE"
        or product is None or product["product_status"] != "LAUNCHED"
        or enrollment is None
        or enrollment["enrollment_status"] != "COMPLETED"
        or content is None or content["content_status"] != "APPROVED"
    )
    if blocked:
        raise ApiError(ERR_REINSTATEMENT_BLOCKED, 409,
                       "Reinstatement requires rep ACTIVE, product LAUNCHED, "
                       "and the fulfilling enrollment COMPLETED with APPROVED "
                       "content")
    rec["cert_status"] = "CERTIFIED"
    rec["suspended_reason"] = None
    touch(rec)
    a = actor()
    audit("CERTIFICATION_STATUS_CHANGED", "ProductCertification", rec["id"],
          a[0], a[1], "cert_status: SUSPENDED -> CERTIFIED (reinstated)")
    return success(view(rec))
