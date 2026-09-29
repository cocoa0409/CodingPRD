"""Perpetual open-space deed restrictions, monitoring inspections, cures, terminations."""
from flask import Blueprint, g

import calc
import lookups
import store
import web
from core import clock_date, fail, fmt_date
from web import endpoint

bp = Blueprint("restrictions", __name__)


@bp.get("/deed-restrictions")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def list_restrictions():
    parcel_id = web.query_str("parcel_id")
    closing_id = web.query_str("closing_record_id")
    status = web.query_enum("status", store.RESTRICTION_STATUSES)
    rows = list(store.restrictions.values())
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if closing_id is not None:
        rows = [r for r in rows if r["closing_record_id"] == closing_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return web.list_response(rows)


@bp.get("/deed-restrictions/<restriction_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def read_restriction(restriction_id):
    return web.respond_object(lookups.get_restriction(restriction_id))


@bp.post("/deed-restrictions/<restriction_id>/monitoring-inspections")
@endpoint("ComplianceMonitor")
def create_inspection(restriction_id):
    restriction = lookups.get_restriction(restriction_id)
    body = web.get_body()
    inspection_date = web.req_date(body, "inspection_date")
    finding = web.req_enum(body, "finding", store.FINDINGS)
    code = web.opt_enum(body, "prohibited_use_code", store.PROHIBITED_USE_CODES)
    narrative = web.req_string(body, "narrative")
    if finding == "PROHIBITED_USE_OBSERVED" and code is None:
        web._bad("prohibited_use_code", "is required when the finding is PROHIBITED_USE_OBSERVED")
    if finding == "COMPLIANT" and code is not None:
        web._bad("prohibited_use_code", "must be null when the finding is COMPLIANT")
    if code is not None and code not in (restriction.get("prohibited_uses") or []):
        web._bad("prohibited_use_code", "must be one of the restriction's prohibited uses")

    if restriction["status"] not in ("RECORDED", "IN_COMPLIANCE", "VIOLATION_OPEN", "CURED"):
        fail("ERR_INVALID_RESTRICTION_STATE")
    if inspection_date > clock_date():
        fail("ERR_FUTURE_DATED_FINDING")
    if (restriction["status"] == "VIOLATION_OPEN" and finding == "PROHIBITED_USE_OBSERVED"
            and code != restriction.get("open_violation_code")):
        fail("ERR_PROHIBITED_USE_UNRESOLVED")

    record = store.new_record("MonitoringInspection", {
        "deed_restriction_id": restriction_id,
        "inspection_date": fmt_date(inspection_date),
        "finding": finding,
        "prohibited_use_code": code,
        "inspector_user_id": g.uid,
        "narrative": narrative,
    }, versioned=False)
    store.inspections[record["id"]] = record

    current = restriction["status"]
    if finding == "COMPLIANT":
        if current in ("RECORDED", "CURED"):
            restriction["status"] = "IN_COMPLIANCE"
            restriction["next_monitoring_due_date"] = calc.next_monitoring_due(inspection_date)
    else:
        if current in ("RECORDED", "IN_COMPLIANCE", "CURED"):
            restriction["status"] = "VIOLATION_OPEN"
            restriction["open_violation_code"] = code
            restriction["violation_reported_by_user_id"] = g.uid
            restriction["corrective_deadline_date"] = calc.corrective_deadline(inspection_date)
    store.touch(restriction)
    return web.respond_object(record, 201)


@bp.get("/monitoring-inspections")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def list_inspections():
    restriction_id = web.query_str("deed_restriction_id")
    finding = web.query_enum("finding", store.FINDINGS)
    rows = list(store.inspections.values())
    if restriction_id is not None:
        rows = [r for r in rows if r["deed_restriction_id"] == restriction_id]
    if finding is not None:
        rows = [r for r in rows if r["finding"] == finding]
    return web.list_response(rows)


@bp.get("/monitoring-inspections/<inspection_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def read_inspection(inspection_id):
    return web.respond_object(lookups.get_inspection(inspection_id))


@bp.post("/deed-restrictions/<restriction_id>/cure")
@endpoint("ComplianceMonitor")
def cure_restriction(restriction_id):
    restriction = lookups.get_restriction(restriction_id)
    # SoD-3 precedes structural validation (PRD 2.9 step 3).
    reporter = restriction.get("violation_reported_by_user_id")
    if reporter is not None and g.uid == reporter:
        fail("ERR_SEGREGATION_OF_DUTIES")
    body = web.get_body()
    cure_date = web.req_date(body, "cure_date")
    web.req_string(body, "cure_narrative")
    if restriction["status"] != "VIOLATION_OPEN":
        fail("ERR_INVALID_RESTRICTION_STATE")
    if cure_date > clock_date():
        fail("ERR_FUTURE_DATED_FINDING")

    restriction["status"] = "CURED"
    restriction["cured_on"] = fmt_date(cure_date)
    restriction["open_violation_code"] = None
    restriction["corrective_deadline_date"] = None
    restriction["next_monitoring_due_date"] = calc.next_monitoring_due(cure_date)
    store.touch(restriction)
    return web.respond_object(restriction)


@bp.post("/deed-restrictions/<restriction_id>/terminate")
@endpoint("ProgramAdministrator")
def terminate_restriction(restriction_id):
    restriction = lookups.get_restriction(restriction_id)
    body = web.get_body()
    reference = web.req_string(body, "termination_authorization_reference")
    if restriction["status"] not in ("RECORDED", "IN_COMPLIANCE", "CURED"):
        fail("ERR_INVALID_RESTRICTION_STATE")
    if not reference.startswith(store.OPEN_SPACE_TERMINATION_AUTH_PREFIX):
        fail("ERR_TERMINATION_NOT_AUTHORIZED")

    restriction["status"] = "TERMINATED"
    restriction["termination_authorization_reference"] = reference
    store.touch(restriction)
    parcel = store.parcels.get(restriction["parcel_id"])
    project = lookups.project_of_parcel(parcel) if parcel else None
    if project is not None:
        calc.recompute_protected_acres(project)
        store.touch(project)
    return web.respond_object(restriction)
