"""Complaint endpoints (PRD §3.3)."""

from flask import Blueprint

from db import db, common_fields, touch
from errors import err
from middleware import require_roles
from response import success, list_success
from services import domain, serialize
from services.helpers import (
    get_body,
    lookup,
    pagination_params,
    paginate,
    require_enum,
    require_fields,
    resolve_ref,
    sort_by_created,
)

bp = Blueprint("complaints", __name__)

REPORTER_KINDS = {"RESIDENT", "ANONYMOUS", "OFFICER_OBSERVED"}


@bp.post("/complaints")
@require_roles("CodeOfficer", "Registrant")
def create_complaint():
    body = get_body()
    require_fields(body, "case_id", "narrative")
    require_enum(body, "reporter_kind", REPORTER_KINDS)
    resolve_ref(db.cases, body["case_id"])

    record = common_fields()
    record.update({
        "case_id": body["case_id"],
        "reporter_kind": body["reporter_kind"],
        "narrative": body["narrative"],
        "status": "RECEIVED",
    })
    db.complaints[record["id"]] = record
    return success(serialize.complaint_out(record), status=201)


@bp.get("/cases/<cid>/complaints")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk")
def list_case_complaints(cid):
    lookup(db.cases, cid)
    limit, offset = pagination_params()
    items = [c for c in db.complaints.values() if c["case_id"] == cid]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize.complaint_out(c) for c in page], limit, offset, total)


@bp.post("/complaints/<comp_id>/triage")
@require_roles("CodeOfficer")
def triage_complaint(comp_id):
    comp = lookup(db.complaints, comp_id)
    if comp["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", "complaint is not RECEIVED")
    # Precondition: narrative present (it is required at creation, but guard anyway).
    if not comp.get("narrative"):
        raise err("ERR_INVALID_REQUEST", "narrative required to triage")
    comp["status"] = "TRIAGED"
    touch(comp)
    return success(serialize.complaint_out(comp), status=200)


@bp.post("/complaints/<comp_id>/dismiss")
@require_roles("CodeOfficer")
def dismiss_complaint(comp_id):
    comp = lookup(db.complaints, comp_id)
    if comp["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", "complaint is not RECEIVED")
    # Dismiss blocked if any inspection with VIOLATION_FOUND on this complaint's case.
    for insp in db.inspections.values():
        if insp["case_id"] == comp["case_id"] and insp["outcome"] == "VIOLATION_FOUND":
            raise err("ERR_INVALID_STATE", "case already has substantiated grounds")
    comp["status"] = "DISMISSED"
    touch(comp)
    return success(serialize.complaint_out(comp), status=200)
