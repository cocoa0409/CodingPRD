"""AuditCase lifecycle (PRD 3.7).

OPENED -> (first attach) ACTIVE_PREP -> SUBMITTED_TO_AUTHORITY ->
  CLOSED_RESOLVED (AUDIT) | CLOSED_AGREED (APA; locks covered pricing).
"""
from datetime import date

from flask import Blueprint, request

import errors
from db import store, new_resource, touch, public
from errors import ApiError
from middleware import (
    require_auth, get_body, get_path, require_fk, is_int, parse_date,
    shape_str, shape_enum, list_page, ALL_ROLES,
)
from response import ok_object, ok_list

bp = Blueprint("audit_cases", __name__)

CASE_TYPES = ["AUDIT", "APA"]
_BLOCKING_APA_STATUSES = ("OPENED", "ACTIVE_PREP", "SUBMITTED_TO_AUTHORITY", "CLOSED_AGREED")


@bp.post("/tp/audit_cases")
def create_audit_case():
    require_auth(["TransferPricingLead"])
    body = get_body()
    entity_id = body.get("entity_id")
    # (3) existence.
    require_fk(store.legal_entities, entity_id, "entity_id")
    # (6) the audited entity must be ACTIVE.
    if (isinstance(entity_id, str) and entity_id in store.legal_entities
            and store.legal_entities[entity_id]["status"] != "ACTIVE"):
        raise ApiError(errors.ENTITY_INACTIVE, 409,
                       "The audited legal entity is not ACTIVE")
    # (7) APA covered-year disjointness per entity (needs a parseable year list).
    case_type = body.get("case_type")
    years = body.get("covered_year_indexes")
    years_ok = isinstance(years, list) and all(is_int(y) for y in years)
    if case_type == "APA" and years_ok and isinstance(entity_id, str):
        wanted = set(years)
        for c in store.audit_cases.values():
            if (c["case_type"] == "APA" and c["entity_id"] == entity_id
                    and c["status"] in _BLOCKING_APA_STATUSES):
                if wanted & set(c.get("covered_year_indexes") or []):
                    raise ApiError(errors.APA_YEAR_OVERLAP, 409,
                                   "Covered years intersect another APA case for this entity")
    # (10) shape.
    shape_str(body, "entity_id")
    shape_enum(body, "case_type", CASE_TYPES)
    shape_str(body, "authority_country")
    if case_type == "APA":
        if not years_ok or not years:
            raise ApiError(errors.INVALID_REQUEST, 400,
                           "covered_year_indexes is required for APA cases and must be "
                           "a list of integer year indexes")
    elif years is not None and not years_ok:
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "covered_year_indexes must be a list of integer year indexes")
    c = new_resource()
    c.update({
        "entity_id": entity_id,
        "case_type": case_type,
        "authority_country": body.get("authority_country"),
        "covered_year_indexes": list(years) if years_ok else None,
        "defense_doc_ids": [],
        "status": "OPENED",
    })
    store.audit_cases[c["id"]] = c
    return ok_object(public(c), 201)


@bp.get("/tp/audit_cases/<auditCaseId>")
def get_audit_case(auditCaseId):
    require_auth(ALL_ROLES)
    c = get_path(store.audit_cases, auditCaseId)
    return ok_object(public(c), 200)


@bp.get("/tp/audit_cases")
def list_audit_cases():
    require_auth(ALL_ROLES)
    filters = [
        ("entity_id", request.args.get("entity_id")),
        ("case_type", request.args.get("case_type")),
        ("status", request.args.get("status")),
    ]
    page, limit, offset, total = list_page(list(store.audit_cases.values()), filters)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.post("/tp/audit_cases/<auditCaseId>/attach_doc")
def attach_doc(auditCaseId):
    require_auth(["TransferPricingLead"])
    c = get_path(store.audit_cases, auditCaseId)
    body = get_body()
    doc_id = body.get("doc_package_id")
    require_fk(store.doc_packages, doc_id, "doc_package_id")
    if c["status"] not in ("OPENED", "ACTIVE_PREP"):
        raise ApiError(errors.INVALID_STATE, 409,
                       "attach_doc requires the case to be OPENED or ACTIVE_PREP")
    doc = store.doc_packages.get(doc_id) if isinstance(doc_id, str) else None
    if doc is None or doc["status"] not in ("APPROVED", "FILED"):
        raise ApiError(errors.DOC_NOT_FINAL, 409,
                       "Only APPROVED or FILED packages may join the defense file")
    if not isinstance(doc_id, str) or not doc_id:
        raise ApiError(errors.INVALID_REQUEST, 400, "doc_package_id is required")
    c["defense_doc_ids"].append(doc_id)
    if c["status"] == "OPENED":
        c["status"] = "ACTIVE_PREP"  # first successful attachment auto-advances
    touch(c)
    return ok_object(public(c), 200)


@bp.post("/tp/audit_cases/<auditCaseId>/submit_response")
def submit_response(auditCaseId):
    require_auth(["TransferPricingLead"])
    c = get_path(store.audit_cases, auditCaseId)
    if c["status"] not in ("OPENED", "ACTIVE_PREP"):
        raise ApiError(errors.INVALID_STATE, 409,
                       "submit_response requires the case to be OPENED or ACTIVE_PREP")
    # Business error, raised even from OPENED (the transition is defined from both).
    if not c["defense_doc_ids"]:
        raise ApiError(errors.DEFENSE_FILE_EMPTY, 409,
                       "The defense file is empty")
    c["status"] = "SUBMITTED_TO_AUTHORITY"
    touch(c)
    return ok_object(public(c), 200)


@bp.post("/tp/audit_cases/<auditCaseId>/resolve")
def resolve_audit_case(auditCaseId):
    require_auth(["TransferPricingLead"])
    c = get_path(store.audit_cases, auditCaseId)
    if c["status"] != "SUBMITTED_TO_AUTHORITY":
        raise ApiError(errors.INVALID_STATE, 409,
                       "resolve requires the case to be SUBMITTED_TO_AUTHORITY")
    if c["case_type"] == "APA":
        c["status"] = "CLOSED_AGREED"
        # Lock pricing on covered agreements: provider or recipient is the case
        # entity, agreement ACTIVE/UNDER_AMENDMENT, and the effective window
        # covers January 1 of at least one covered year.
        years = c.get("covered_year_indexes") or []
        jan1s = [date(y, 1, 1) for y in years if is_int(y)]
        for a in store.agreements.values():
            if a["status"] not in ("ACTIVE", "UNDER_AMENDMENT"):
                continue
            if (a["provider_entity_id"] != c["entity_id"]
                    and a["recipient_entity_id"] != c["entity_id"]):
                continue
            ef = parse_date(a["effective_from"])
            et = parse_date(a["effective_to"])
            if any(ef <= j1 < et for j1 in jan1s):
                if not a["apa_locked"]:
                    a["apa_locked"] = True
                    touch(a)
    else:
        c["status"] = "CLOSED_RESOLVED"
    touch(c)
    return ok_object(public(c), 200)
