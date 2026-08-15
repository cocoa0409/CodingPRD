"""Classification endpoints (OCC-guarded creation, review gate, revision loop)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
)
from middleware import (
    auth,
    get_body,
    no_unknown,
    need,
    v_str,
    v_int,
    v_enum,
    find,
    check_body_fks,
    page_params,
    filtered_sorted,
)
from response import ok, list_response
from services.audit import write_audit

bp = Blueprint("classifications", __name__)

JURISDICTIONS = ("EAR", "ITAR")
BASES = ("SELF_CLASSIFICATION", "CCATS", "CJ_DETERMINATION")


@bp.post("/compliance/classifications")
def create_classification():
    auth("ComplianceAnalyst")
    body = get_body()
    # Priority 3: body FK existence
    check_body_fks(body, (("product_id", db.PRODUCTS),))
    # Priority 4: request shape
    no_unknown(
        body,
        {"product_id", "expected_product_version", "jurisdiction", "classification_code", "determination_basis"},
    )
    product_id = v_str(need(body, "product_id"), "product_id")
    expected_version = v_int(need(body, "expected_product_version"), "expected_product_version")
    jurisdiction = v_enum(need(body, "jurisdiction"), "jurisdiction", JURISDICTIONS)
    code = v_str(need(body, "classification_code"), "classification_code")
    basis = v_enum(need(body, "determination_basis"), "determination_basis", BASES)
    product = find(db.PRODUCTS, product_id, "Product")
    # Priority 5: optimistic concurrency on Product.version
    if expected_version != product["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_product_version %s does not match current Product.version %s"
            % (expected_version, product["version"]),
            412,
        )
    product["classification_count"] += 1
    classification = {
        "product_id": product_id,
        "jurisdiction": jurisdiction,
        "classification_code": code,
        "determination_basis": basis,
        "sequence": product["classification_count"],
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
    }
    db.stamp_new(classification)
    db.CLASSIFICATIONS[classification["id"]] = classification
    db.touch(product)  # Product.version += 1
    return ok(db.pub(classification), "object", 201)


@bp.get("/compliance/classifications/<cid>")
def get_classification(cid):
    auth()
    classification = find(db.CLASSIFICATIONS, cid, "Classification")
    return ok(db.pub(classification), "object", 200)


@bp.get("/compliance/classifications")
def list_classifications():
    auth()
    filters = {
        "product_id": request.args.get("product_id"),
        "status": request.args.get("status"),
    }
    items = filtered_sorted(db.CLASSIFICATIONS, filters)
    limit, offset = page_params()
    return list_response(items, limit, offset)


@bp.post("/compliance/classifications/<cid>/submit")
def submit_classification(cid):
    uid, _ = auth("ComplianceAnalyst")
    classification = find(db.CLASSIFICATIONS, cid, "Classification")
    if classification["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Classification is not DRAFT", 409)
    classification["status"] = "SUBMITTED"
    classification["submitted_by_user_id"] = uid
    db.touch(classification)
    return ok(db.pub(classification), "object", 200)


@bp.post("/compliance/classifications/<cid>/review")
def review_classification(cid):
    uid, role = auth("ComplianceManager")
    classification = find(db.CLASSIFICATIONS, cid, "Classification")
    body = get_body()
    no_unknown(body, {"decision"})
    decision = v_enum(need(body, "decision"), "decision", ("APPROVE", "REJECT"))
    if classification["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Classification is not SUBMITTED", 409)
    if uid == classification["submitted_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Reviewer must differ from the submitting user",
            409,
        )
    classification["reviewed_by_user_id"] = uid
    if decision == "APPROVE":
        classification["status"] = "ACTIVE"
        db.touch(classification)
        product = find(db.PRODUCTS, classification["product_id"], "Product")
        for other in db.CLASSIFICATIONS.values():
            if (
                other["product_id"] == product["id"]
                and other["id"] != classification["id"]
                and other["status"] == "ACTIVE"
            ):
                other["status"] = "SUPERSEDED"
                db.touch(other)
        product["active_classification_id"] = classification["id"]
        product["status"] = "CLASSIFIED"
        db.touch(product)
        write_audit(
            "CLASSIFICATION_ACTIVATED",
            "Classification",
            classification["id"],
            role,
            uid,
            "Classification %s activated for product %s" % (classification["id"], product["id"]),
        )
    else:  # REJECT
        classification["status"] = "REJECTED"
        db.touch(classification)
    return ok(db.pub(classification), "object", 200)


@bp.post("/compliance/classifications/<cid>/revise")
def revise_classification(cid):
    auth("ComplianceAnalyst")
    classification = find(db.CLASSIFICATIONS, cid, "Classification")
    if classification["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, "Classification is not REJECTED", 409)
    classification["status"] = "DRAFT"
    db.touch(classification)
    return ok(db.pub(classification), "object", 200)
