"""Offering instruments and the lazy expiry sweep (PRD 3.3)."""

from flask import Blueprint

import db
import errors
import response
import validation as v
from errors import fail
from middleware import (ALL_ROLES, SYNDICATION_COUNSEL, ctx, endpoint,
                        find_offering_document, find_production)

bp = Blueprint("offering_documents", __name__)

DOC_TYPES = ("LP_AGREEMENT", "LLC_OPERATING_AGREEMENT")
DOC_STATUSES = ("DRAFT", "EFFECTIVE", "EXPIRED", "WITHDRAWN")
REQUIRED_DOC_TYPE = {"LP": "LP_AGREEMENT", "LLC": "LLC_OPERATING_AGREEMENT"}


def sweep(document):
    """Lazy EFFECTIVE -> EXPIRED transition (PRD 3.3).

    Applied before the calling request's own validations run, so a lapsed
    instrument is already EXPIRED by the time the business rules read it.
    """
    if document["status"] != "EFFECTIVE":
        return document
    if db.logical_date() > db.parse_iso_date(document["expiration_date"]):
        ctx().watch(document)
        document["status"] = "EXPIRED"
    return document


def in_window(document):
    effective = db.parse_iso_date(document["effective_date"])
    expiration = db.parse_iso_date(document["expiration_date"])
    return effective <= db.logical_date() <= expiration


@bp.post("/offering-documents")
@endpoint((SYNDICATION_COUNSEL,))
def create_offering_document():
    data = v.body()
    production_id = v.req_id(data, "production_id")
    doc_type = v.req_enum(data, "doc_type", DOC_TYPES)
    offering_amount = v.req_int(data, "offering_amount_cents", 1)
    unit_price = v.req_int(data, "unit_price_cents", 1)
    max_investors = v.req_int(data, "max_investors", 1)
    effective_text, effective = v.req_date(data, "effective_date")
    expiration_text, expiration = v.req_date(data, "expiration_date")
    if expiration < effective:
        fail(errors.ERR_INVALID_REQUEST,
             "expiration_date must be on or after effective_date.")

    production = find_production(production_id)
    if REQUIRED_DOC_TYPE[production["offering_entity_type"]] != doc_type:
        fail(errors.ERR_OFFERING_TYPE_MISMATCH,
             "The instrument does not agree with the producing entity's legal form.")

    row = db.insert("offering_documents", {
        "production_id": production_id,
        "doc_type": doc_type,
        "offering_amount_cents": offering_amount,
        "unit_price_cents": unit_price,
        "max_investors": max_investors,
        "effective_date": effective_text,
        "expiration_date": expiration_text,
        "status": "DRAFT",
        "withdrawal_reason": None,
        "submitted_units_total": 0,
        "accepted_units_total": 0,
        "accepted_amount_cents": 0,
        "accepted_investor_count": 0,
    })
    return response.obj(row, 201)


@bp.post("/offering-documents/<document_id>/make-effective")
@endpoint((SYNDICATION_COUNSEL,))
def make_effective(document_id):
    document = find_offering_document(document_id)
    production = db.get("productions", document["production_id"])
    if document["status"] != "DRAFT":
        fail(errors.ERR_INVALID_OFFERING_DOCUMENT_STATE,
             "Only a DRAFT instrument may be made effective.")
    if production["offering_status"] != "OFFERING":
        fail(errors.ERR_PRODUCTION_NOT_OFFERING,
             "The production's syndication axis must read OFFERING.")
    if not in_window(document):
        fail(errors.ERR_OFFERING_EXPIRED,
             "The current logical date is outside the instrument's window.")

    ctx().watch(document)
    document["status"] = "EFFECTIVE"
    return response.obj(document)


@bp.post("/offering-documents/<document_id>/withdraw")
@endpoint((SYNDICATION_COUNSEL,))
def withdraw_offering_document(document_id):
    document = find_offering_document(document_id)
    data = v.body()
    reason = v.req_str(data, "withdrawal_reason")
    if document["status"] not in ("DRAFT", "EFFECTIVE"):
        fail(errors.ERR_INVALID_OFFERING_DOCUMENT_STATE,
             "Only a DRAFT or EFFECTIVE instrument may be withdrawn.")

    ctx().watch(document)
    document["status"] = "WITHDRAWN"
    document["withdrawal_reason"] = reason
    return response.obj(document)


@bp.get("/offering-documents/<document_id>")
@endpoint(ALL_ROLES)
def read_offering_document(document_id):
    return response.obj(sweep(find_offering_document(document_id)))


@bp.get("/offering-documents")
@endpoint(ALL_ROLES)
def list_offering_documents():
    production_id = v.q_str("production_id")
    status = v.q_enum("status", DOC_STATUSES)
    limit, offset = v.pagination()
    for document in db.all_rows("offering_documents"):
        sweep(document)
    rows = [r for r in db.all_rows("offering_documents")
            if (production_id is None or r["production_id"] == production_id)
            and (status is None or r["status"] == status)]
    return response.listing(rows, limit, offset)
