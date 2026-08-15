"""EasementDocument endpoints (nested + record/reject-defective)."""

from __future__ import annotations

from flask import Blueprint

import db
from constants import (
    DOC_KINDS,
    ROLE_DEPARTMENT_DIRECTOR as DD,
    ROLE_LITIGATION_COUNSEL as LC,
    ROLE_RIGHT_OF_WAY_AGENT as RoWA,
    ROLE_TITLE_EXAMINER as TE,
)
from errors import raise_err
from middleware import require_roles
from response import success_list, success_object
from services import calculations, domain
from services.serializers import serialize_document, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    paginate,
    parse_pagination,
    require_enum,
    require_number,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("documents", __name__)

READERS = (RoWA, TE, LC, DD)


@bp.route("/easement-cases/<case_id>/documents", methods=["POST"])
@require_roles(TE)
def create_document(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    domain.ensure_case_not_closed(case)
    body = get_json_body()
    doc_kind = require_enum(body, "doc_kind", DOC_KINDS)
    instrument_number = require_string(body, "instrument_number")
    recording_date_dt = require_ts(body, "recording_date")
    grantor_name = require_string(body, "grantor_name")
    grantee_name = require_string(body, "grantee_name")
    gis_polygon_wkt = require_string(body, "gis_polygon_wkt")
    width_ft = require_number(body, "width_ft")
    supersedes_document_id = optional_field(body, "supersedes_document_id", None)

    # Referenced-document integrity (creation time): must exist, belong to
    # this case, and itself be RECORDED.
    if supersedes_document_id is not None:
        target = db.documents.get(supersedes_document_id)
        if target is None:
            raise_err("ERR_DOCUMENT_NOT_FOUND", "supersedes_document_id does not exist")
        if target["case_id"] != case_id:
            raise_err("ERR_CROSS_CASE_REFERENCE", "supersedes_document_id belongs to a different case")
        if target["status"] != "RECORDED":
            raise_err("ERR_DOCUMENT_NOT_RECORDED", "supersedes_document_id must be RECORDED")

    # Temporal validity: recording_date may not lie in the future.
    if recording_date_dt > db.get_clock_dt():
        raise_err("ERR_INVALID_DATE_RANGE", "recording_date may not be in the future")

    doc = {
        "case_id": case_id,
        "doc_kind": doc_kind,
        "instrument_number": instrument_number,
        "recording_date": db.fmt_dt(recording_date_dt),
        "grantor_name": grantor_name,
        "grantee_name": grantee_name,
        "gis_polygon_wkt": gis_polygon_wkt,
        "encumbrance_rank": None,
        "width_ft": float(width_ft) if width_ft % 1 else int(width_ft),
        "supersedes_document_id": supersedes_document_id,
        "status": "DRAFT",
    }
    db.stamp_new(doc)
    db.documents[doc["id"]] = doc
    return success_object(serialize_document(doc), 201)


@bp.route("/easement-cases/<case_id>/documents", methods=["GET"])
@require_roles(*READERS)
def list_documents(case_id: str, _user_id: str, _role: str):
    domain.get_case_or_404(case_id)
    limit, offset = parse_pagination()
    items = [d for d in db.documents.values() if d["case_id"] == case_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status", "doc_kind"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page, serialize_document), limit, offset, total)


@bp.route("/easement-cases/<case_id>/documents/<doc_id>", methods=["GET"])
@require_roles(*READERS)
def get_document(case_id: str, doc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    doc = domain.get_document_or_404(case, doc_id)
    return success_object(serialize_document(doc))


@bp.route("/easement-cases/<case_id>/documents/<doc_id>/record", methods=["POST"])
@require_roles(TE)
def record_document(case_id: str, doc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    doc = domain.get_document_or_404(case, doc_id)
    domain.ensure_case_not_closed(case)
    if doc["status"] != "DRAFT":
        raise_err("ERR_DOCUMENT_NOT_DRAFT", "Document must be DRAFT to record")

    # instrument_number must remain unique across the county among RECORDED
    # documents.
    county = case["county"]
    county_case_ids = {c["id"] for c in db.cases.values() if c["county"] == county}
    for other in db.documents.values():
        if (
            other["id"] != doc_id
            and other["case_id"] in county_case_ids
            and other["status"] == "RECORDED"
            and other["instrument_number"] == doc["instrument_number"]
        ):
            raise_err(
                "ERR_DUPLICATE_INSTRUMENT_NUMBER",
                "instrument_number already recorded in this county",
            )

    doc["status"] = "RECORDED"
    db.touch(doc)

    # Supersession cascade: the named earlier document leaves the active
    # inventory, and encroachments pointing at it re-derive severity against
    # this document's width.
    superseded_id = doc.get("supersedes_document_id")
    if superseded_id:
        target = db.documents.get(superseded_id)
        if target is not None and target["status"] == "RECORDED":
            target["status"] = "SUPERSEDED"
            target["encumbrance_rank"] = None
            db.touch(target)
            new_width = str(doc["width_ft"])
            from decimal import Decimal
            for enc in db.encroachments.values():
                if enc["case_id"] != case_id or enc["encroaches_document_id"] != superseded_id:
                    continue
                new_tier = calculations.severity_tier(
                    enc["encroachment_type"],
                    Decimal(str(enc["encroachment_area_sqft"])),
                    Decimal(str(enc["depth_into_easement_ft"])),
                    Decimal(new_width),
                    Decimal(str(case["easement_area_sqft"])),
                )
                if enc["severity_tier"] != new_tier:
                    enc["severity_tier"] = new_tier
                    db.touch(enc)

    calculations.recompute_encumbrance_ranks(case_id)
    domain.reconcile_case(case, bump=True)
    return success_object(serialize_document(doc))


@bp.route("/easement-cases/<case_id>/documents/<doc_id>/reject-defective", methods=["POST"])
@require_roles(TE)
def reject_defective_document(case_id: str, doc_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    doc = domain.get_document_or_404(case, doc_id)
    domain.ensure_case_not_closed(case)
    if doc["status"] != "DRAFT":
        raise_err("ERR_DOCUMENT_NOT_DRAFT", "Document must be DRAFT to reject")
    doc["status"] = "REJECTED_DEFECTIVE"
    db.touch(doc)
    return success_object(serialize_document(doc))
