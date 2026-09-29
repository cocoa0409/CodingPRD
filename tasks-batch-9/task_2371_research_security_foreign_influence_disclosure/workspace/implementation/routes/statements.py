"""Sponsor support statements and their reconciliation (PRD 3.5)."""

from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import INVESTIGATOR, RSO, require, require_any
from routes.common import must_exist, render_list
from services import cascade, derive, enums as E, present, reconcile

bp = Blueprint("statements", __name__)


@bp.post("/support-statements")
def create_statement():
    user_id, role = require(INVESTIGATOR, RSO)
    data = validate.body()

    raw_investigator = data.get("investigator_id")
    if role == INVESTIGATOR and isinstance(raw_investigator, str) and \
            raw_investigator != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The acting investigator does not own this statement.")

    investigator = must_exist("investigator", raw_investigator)
    project = must_exist("project", data.get("project_id"))

    agency_code = validate.req_enum(data, "agency_code", E.AGENCY_CODES)
    document_type = validate.req_enum(data, "document_type", E.DOCUMENT_TYPES)
    declared_months = validate.req_decimal(data, "declared_person_months",
                                           minimum=0, max_places=2)
    declared_appointments = validate.req_int(data, "declared_appointment_count",
                                             minimum=0)
    declared_support = validate.req_int(data, "declared_support_count", minimum=0)

    record = db.base_record()
    record.update({
        "investigator_id": investigator["id"],
        "project_id": project["id"],
        "agency_code": agency_code,
        "document_type": document_type,
        "declared_person_months": declared_months,
        "declared_appointment_count": declared_appointments,
        "declared_support_count": declared_support,
        "status": "SUBMITTED",
        "applied_variant": None,
        "institutional_person_months": None,
        "variance_person_months": None,
        "omission_count": None,
        "verdict": None,
    })

    for existing in db.ordered(db.statements.values()):
        if existing["investigator_id"] != investigator["id"]:
            continue
        if existing["project_id"] != project["id"]:
            continue
        if existing["agency_code"] != agency_code:
            continue
        if existing["document_type"] != document_type:
            continue
        if existing["status"] in ("SUBMITTED", "RECONCILED", "INCONSISTENT"):
            existing["status"] = "SUPERSEDED"
            db.touch(existing)

    db.statements[record["id"]] = record
    cascade.recompute_investigator(investigator)
    cascade.recompute_project(project)
    return response.object_response(present.statement(record), 201)


@bp.get("/support-statements/<statement_id>")
def read_statement(statement_id):
    require_any()
    record = must_exist("statement", statement_id)
    return response.object_response(present.statement(record))


@bp.get("/support-statements")
def list_statements():
    require_any()
    investigator_id = validate.filter_value("investigator_id")
    project_id = validate.filter_value("project_id")
    status = validate.filter_enum("status", E.STATEMENT_STATUSES)

    rows = []
    for record in db.ordered(db.statements.values()):
        if investigator_id and record["investigator_id"] != investigator_id:
            continue
        if project_id and record["project_id"] != project_id:
            continue
        if status and record["status"] != status:
            continue
        rows.append(record)
    return render_list(rows, present.statement)


@bp.post("/support-statements/<statement_id>/reconcile")
def reconcile_statement(statement_id):
    require(RSO)
    data = validate.body()
    record = must_exist("statement", statement_id)

    variant = validate.req_enum(data, "variant", E.RECONCILE_VARIANTS)

    if record["status"] not in ("SUBMITTED", "RECONCILED", "INCONSISTENT"):
        raise ApiError("ERR_INVALID_STATEMENT_TRANSITION",
                       "A %s statement cannot be reconciled." % record["status"])

    if record["status"] == "SUBMITTED":
        if not derive.has_certified_disclosure(record["investigator_id"]):
            raise ApiError("ERR_NO_CERTIFIED_DISCLOSURE",
                           "The investigator holds no CERTIFIED disclosure.")

    reconcile.run(record, variant)
    db.touch(record)
    cascade.recompute_investigator(
        db.investigators.get(record["investigator_id"]))
    cascade.recompute_project(db.projects.get(record["project_id"]))
    return response.object_response(present.statement(record))
