"""DocPackage lifecycle (PRD 3.6): DRAFT -> SUBMITTED -> APPROVED -> FILED."""
from flask import Blueprint, request

import errors
from db import store, new_resource, touch, public, clock_iso
from errors import ApiError
from middleware import (
    require_auth, get_body, get_path, require_fk, shape_str, shape_enum,
    list_page, ALL_ROLES,
)
from response import ok_object, ok_list

bp = Blueprint("doc_packages", __name__)

DOC_TYPES = ["MASTER_FILE", "LOCAL_FILE", "CBC_REPORT"]


@bp.post("/tp/doc_packages")
def create_doc_package():
    require_auth(["TaxAnalyst"])
    body = get_body()
    fyid = body.get("fiscal_year_id")
    entity_id = body.get("entity_id")
    # (3) existence of body FKs in declared order.
    require_fk(store.fiscal_years, fyid, "fiscal_year_id")
    require_fk(store.legal_entities, entity_id, "entity_id")
    # (6) a referenced entity must be ACTIVE.
    if (isinstance(entity_id, str) and entity_id in store.legal_entities
            and store.legal_entities[entity_id]["status"] != "ACTIVE"):
        raise ApiError(errors.ENTITY_INACTIVE, 409,
                       "Referenced legal entity is not ACTIVE")
    # (8) at most one CBC_REPORT per fiscal year.
    if body.get("doc_type") == "CBC_REPORT" and isinstance(fyid, str):
        for d in store.doc_packages.values():
            if d["fiscal_year_id"] == fyid and d["doc_type"] == "CBC_REPORT":
                raise ApiError(errors.DUPLICATE_CBC_REPORT, 409,
                               "A CBC_REPORT package already exists for this fiscal year")
    # (10) shape.
    shape_str(body, "fiscal_year_id")
    doc_type = shape_enum(body, "doc_type", DOC_TYPES)
    if doc_type == "LOCAL_FILE":
        if not isinstance(entity_id, str) or not entity_id:
            raise ApiError(errors.INVALID_REQUEST, 400,
                           "LOCAL_FILE requires entity_id")
    else:
        if entity_id is not None:
            raise ApiError(errors.INVALID_REQUEST, 400,
                           "MASTER_FILE and CBC_REPORT must not carry an entity_id")
    d = new_resource()
    d.update({
        "fiscal_year_id": fyid,
        "entity_id": entity_id,
        "doc_type": doc_type,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "filed_at": None,
    })
    store.doc_packages[d["id"]] = d
    return ok_object(public(d), 201)


@bp.get("/tp/doc_packages/<docPackageId>")
def get_doc_package(docPackageId):
    require_auth(ALL_ROLES)
    d = get_path(store.doc_packages, docPackageId)
    return ok_object(public(d), 200)


@bp.get("/tp/doc_packages")
def list_doc_packages():
    require_auth(ALL_ROLES)
    filters = [
        ("fiscal_year_id", request.args.get("fiscal_year_id")),
        ("entity_id", request.args.get("entity_id")),
        ("doc_type", request.args.get("doc_type")),
        ("status", request.args.get("status")),
    ]
    page, limit, offset, total = list_page(list(store.doc_packages.values()), filters)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.post("/tp/doc_packages/<docPackageId>/submit")
def submit_doc_package(docPackageId):
    uid, _ = require_auth(["TaxAnalyst"])
    d = get_path(store.doc_packages, docPackageId)
    if d["status"] != "DRAFT":
        raise ApiError(errors.INVALID_STATE, 409,
                       "submit requires the package to be DRAFT")
    d["submitted_by_user_id"] = uid
    d["status"] = "SUBMITTED"
    touch(d)
    return ok_object(public(d), 200)


@bp.post("/tp/doc_packages/<docPackageId>/approve")
def approve_doc_package(docPackageId):
    uid, _ = require_auth(["TaxManager"])
    d = get_path(store.doc_packages, docPackageId)
    if d["status"] != "SUBMITTED":
        raise ApiError(errors.INVALID_STATE, 409,
                       "approve requires the package to be SUBMITTED")
    if uid == d["submitted_by_user_id"]:
        raise ApiError(errors.SEGREGATION, 409,
                       "Approver must differ from the package submitter")
    d["approved_by_user_id"] = uid
    d["status"] = "APPROVED"
    touch(d)
    return ok_object(public(d), 200)


@bp.post("/tp/doc_packages/<docPackageId>/file")
def file_doc_package(docPackageId):
    require_auth(["TaxManager"])
    d = get_path(store.doc_packages, docPackageId)
    if d["status"] != "APPROVED":
        raise ApiError(errors.INVALID_STATE, 409,
                       "file requires the package to be APPROVED")
    fy = store.fiscal_years.get(d["fiscal_year_id"])
    # (8) LOCAL_FILE: no ACTIVE agreement of the entity under pricing review.
    if d["doc_type"] == "LOCAL_FILE":
        for a in store.agreements.values():
            if (a["status"] == "ACTIVE" and a["pricing_review_required"]
                    and (a["provider_entity_id"] == d["entity_id"]
                         or a["recipient_entity_id"] == d["entity_id"])):
                raise ApiError(errors.STALE_BENCHMARK, 409,
                               "An ACTIVE agreement of this entity requires pricing review")
    # (9) fiscal obligations: books open, then CbC obligation.
    if fy is not None and fy["status"] == "CLOSED":
        raise ApiError(errors.BOOKS_CLOSED, 409, "The fiscal year is CLOSED")
    if d["doc_type"] == "CBC_REPORT" and fy is not None and not fy["cbc_required"]:
        raise ApiError(errors.CBC_NOT_REQUIRED, 409,
                       "CbC reporting is not required for this fiscal year")
    d["filed_at"] = clock_iso()
    d["status"] = "FILED"
    touch(d)
    return ok_object(public(d), 200)
