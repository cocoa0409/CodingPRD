"""Compliance findings: citation, response, closure and the reopen cycle."""

from flask import Blueprint

import schema
from db import db, insert, now
from errors import fail
from middleware import endpoint
from response import created, ok
from routes.common import by_created_at, load, reference, respond_list
from services import calc, derive
from services.tracking import touch
from util import add_days, new_id

bp = Blueprint("findings", __name__)

READERS = ["PlatformAdmin", "ComplianceManager", "RegulatoryInspector"]

CREATE_SPEC = {
    "facility_id": {"type": "string", "required": True},
    "storage_unit_id": {"type": "string"},
    "finding_class": {"type": "string", "required": True, "enum": calc.FINDING_CLASSES},
    "citation_code": {"type": "string", "required": True, "non_empty": True},
    "corrective_action_due_at": {"type": "datetime", "required": True},
    "is_prior_release": {"type": "bool", "default": False},
}


@bp.post("/tsdf/compliance-findings")
@endpoint(roles=["RegulatoryInspector"], mutating=True)
def create_finding():
    body = schema.body(CREATE_SPEC)
    f = reference("facilities", body["facility_id"])
    u = reference("units", body["storage_unit_id"]) if body["storage_unit_id"] else None
    if u is not None and u["facility_id"] != f["id"]:
        fail("ERR_FACILITY_SCOPE_MISMATCH")

    stamp = now()
    row = {
        "id": new_id(),
        "facility_id": f["id"],
        "storage_unit_id": u["id"] if u is not None else None,
        "finding_class": body["finding_class"],
        "citation_code": body["citation_code"],
        "corrective_action_due_at": body["corrective_action_due_at"],
        "is_prior_release": bool(body["is_prior_release"]),
        "status": "OPEN",
        "cited_at": stamp,
        "response_submitted_at": None,
        "corrective_action_completed_on": None,
        "reopen_count": 0,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    insert("findings", row)
    return created(derive.project_finding(row))


@bp.get("/tsdf/compliance-findings/<fid>")
@endpoint(roles=READERS)
def get_finding(fid):
    return ok(derive.project_finding(load("findings", fid)))


@bp.get("/tsdf/compliance-findings")
@endpoint(roles=READERS)
def list_findings():
    filters, limit, offset = schema.listing(
        filters=["facility_id", "storage_unit_id", "finding_class", "status"],
        enums={"finding_class": calc.FINDING_CLASSES, "status": calc.COMPLIANCE_FINDING_STATUSES})
    rows = by_created_at(list(db.findings.values()))
    for key in ("facility_id", "storage_unit_id", "finding_class", "status"):
        if key in filters:
            rows = [row for row in rows if row[key] == filters[key]]
    return respond_list(rows, derive.project_finding, limit, offset)


@bp.post("/tsdf/compliance-findings/<fid>/status")
@endpoint(roles=["ComplianceManager", "RegulatoryInspector"], mutating=True)
def set_finding_status(fid):
    body = schema.body({
        "to_status": {"type": "string", "required": True, "enum": calc.COMPLIANCE_FINDING_STATUSES},
        "corrective_action_completed_on": {"type": "date"},
        "reason_code": {"type": "string"},
    })
    target = body["to_status"]
    row = load("findings", fid)
    current = row["status"]

    if target == "RESPONDED":
        if current not in ("OPEN", "REOPENED"):
            fail("ERR_INVALID_STATE", "Only an open or reopened finding may be responded to")
        if body["corrective_action_completed_on"] is None:
            fail("ERR_INVALID_REQUEST", "corrective_action_completed_on is required for a response")
        row["response_submitted_at"] = now()
        row["corrective_action_completed_on"] = body["corrective_action_completed_on"]
        row["status"] = "RESPONDED"
    elif target == "CLOSED":
        if current != "RESPONDED":
            fail("ERR_INVALID_STATE", "Only a responded finding may be closed")
        row["status"] = "CLOSED"
    elif target == "REOPENED":
        if current != "CLOSED":
            fail("ERR_INVALID_STATE", "Only a closed finding may be reopened")
        if int(row["reopen_count"]) > calc.MAX_REOPENS:
            fail("ERR_INVALID_STATE", "The finding has exhausted its reopen cycles")
        row["reopen_count"] = int(row["reopen_count"]) + 1
        row["corrective_action_due_at"] = add_days(now(), calc.REOPEN_DUE_DAYS)
        row["status"] = "REOPENED"
    else:
        fail("ERR_INVALID_STATE", "Unsupported compliance finding transition")

    touch("findings", row)
    return ok(derive.project_finding(row))
