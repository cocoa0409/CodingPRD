"""Presentation preparation and submission (PRD section 3.4)."""

from flask import Blueprint

import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize, check_principal_scope
from services import domain

bp = Blueprint("presentations", __name__)


def serialize(rec):
    return {
        "id": rec["id"],
        "review_id": rec["review_id"],
        "principal_id": rec["principal_id"],
        "item_ids": list(rec["item_ids"]),
        "prep_completeness_bps": rec["prep_completeness_bps"],
        "status": rec["status"],
        "submitted_at": rec["submitted_at"],
        "authorized_item_count": rec["authorized_item_count"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


@bp.post("/presentations")
def create_presentation():
    authorize("BrokerAccountManager")
    data = v.body()

    review_id = v.req_id(data, "review_id")
    principal_id = v.req_id(data, "principal_id")
    item_ids = v.req_id_array(data, "item_ids", 1, 5)

    review = db.get("reviews", review_id)
    principal = db.get("principals", principal_id)
    items = [db.get("items", item_id) for item_id in item_ids]

    for item in items:
        if item["principal_id"] != principal["id"]:
            raise ApiError("ERR_ITEM_PRINCIPAL_MISMATCH")

    for existing in db.ordered("presentations"):
        if existing["review_id"] == review["id"] and existing["principal_id"] == principal["id"]:
            raise ApiError("ERR_PRESENTATION_DUPLICATE")

    rec = db.base_record()
    rec.update({
        "review_id": review["id"],
        "principal_id": principal["id"],
        "item_ids": list(item_ids),
        "prep_completeness_bps": 0,
        "status": "DRAFT",
        "submitted_at": None,
        "authorized_item_count": 0,
    })
    db.insert("presentations", rec)
    domain.recompute_prep_completeness(rec)
    rec["version"] = 1
    rec["updated_at"] = rec["created_at"]
    return response.created(serialize(rec))


@bp.get("/presentations/<presentation_id>")
def read_presentation(presentation_id):
    user_id, role = authorize(*ALL_ROLES)
    rec = db.get("presentations", presentation_id)
    check_principal_scope(role, user_id, rec["principal_id"])
    return response.ok(serialize(rec))


@bp.get("/presentations")
def list_presentations():
    authorize(*ALL_ROLES)
    limit, offset = v.pagination()
    review_id = v.filter_value("review_id")
    principal_id = v.filter_value("principal_id")
    status = v.filter_value("status")
    rows = []
    for rec in db.ordered("presentations"):
        if review_id is not None and rec["review_id"] != review_id:
            continue
        if principal_id is not None and rec["principal_id"] != principal_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        rows.append(rec)
    return response.listing([serialize(r) for r in rows], limit, offset)


@bp.post("/presentations/<presentation_id>/submit")
def submit_presentation(presentation_id):
    authorize("BrokerAccountManager")
    rec = db.get("presentations", presentation_id)

    review = db.find("reviews", rec["review_id"])
    principal = db.find("principals", rec["principal_id"])

    # band 7 — state preconditions
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if review is None or review["status"] != "OPEN":
        raise ApiError("ERR_REVIEW_NOT_OPEN")
    if principal is None or principal["status"] != "ACTIVE":
        raise ApiError("ERR_PRINCIPAL_NOT_ACTIVE")

    # band 8 — submission deadline
    if clock.now() >= clock.parse_instant(review["submission_deadline"]):
        raise ApiError("ERR_REVIEW_SUBMISSION_CLOSED")

    # band 9 — safety and compliance
    occupied = set()
    for other in domain.presentations_of_review(review["id"]):
        if other["id"] == rec["id"]:
            continue
        if other["status"] in ("SUBMITTED", "ACCEPTED"):
            occupied.add(other["principal_id"])

    for rule in db.ordered("conflict_rules"):
        if rule["status"] != "ACTIVE":
            continue
        if rule["category_code"] != review["category_code"]:
            continue
        if rule["scope"] == "RETAILER_LEVEL" and rule["retailer_id"] != review["retailer_id"]:
            continue
        if rule["principal_a_id"] == principal["id"]:
            counterpart = rule["principal_b_id"]
        elif rule["principal_b_id"] == principal["id"]:
            counterpart = rule["principal_a_id"]
        else:
            continue
        if counterpart in occupied:
            raise ApiError("ERR_PRINCIPAL_CONFLICT")

    if domain.exclusive_blocker(principal["id"], review["retailer_id"], review["category_code"]) is not None:
        raise ApiError("ERR_CATEGORY_EXCLUSIVITY")

    # band 10 — business referential integrity
    if domain.active_agreement(principal["id"], review["retailer_id"], review["category_code"]) is None:
        raise ApiError("ERR_NO_ACTIVE_COMMISSION_AGREEMENT")

    for item_id in rec["item_ids"]:
        item = db.find("items", item_id)
        if item is None or item["catalog_state"] != "VALIDATED":
            raise ApiError("ERR_ITEM_CATALOG_NOT_VALIDATED")

    # band 12 — fiscal gate
    if principal["credit_posture"] == "RESTRICTED":
        raise ApiError("ERR_PRINCIPAL_CREDIT_RESTRICTED")

    rec["status"] = "SUBMITTED"
    rec["submitted_at"] = clock.iso_now()
    db.touch(rec)
    domain.recompute_prep_completeness(rec)
    return response.ok(serialize(rec))
