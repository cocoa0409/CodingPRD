"""MarshalReport endpoints."""

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, MARSHAL_AND_ADMIN,
    ROLE_CONTRACTOR_ADMIN, ROLE_FIRE_MARSHAL,
)
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_str
from errors import (
    invalid_state, event_not_completed, posture_blocked,
    unresolved_overdue_deficiencies, report_revision_invalid,
)
from services.core import (
    base_record, public, touch,
    get_event, get_report,
    contractor_of_event, property_of_event,
    require_contractor_active, require_property_active,
)
from services import calc

bp = Blueprint("reports", __name__)


@bp.route("/fire-compliance/inspection-events/<eid>/marshal-reports", methods=["GET"])
def list_reports_of_event(eid):
    require_roles(MARSHAL_AND_ADMIN)
    ev = get_event(eid)
    rows = [r for r in store.reports.values() if r["event_id"] == ev["id"]]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/inspection-events/<eid>/marshal-reports", methods=["POST"])
def create_revision_report(eid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    ev = get_event(eid)
    body = get_body()
    check_unknown_fields(body, {"revision_of_id"})
    revision_of_id = req_str(body, "revision_of_id")
    prop = property_of_event(ev)
    con = contractor_of_event(ev)
    require_contractor_active(con)
    require_property_active(prop)
    # the pointer must reference a report that exists, is REJECTED, and belongs
    # to this same event
    prior = store.reports.get(revision_of_id)
    if prior is None or prior["status"] != "REJECTED" or prior["event_id"] != ev["id"]:
        raise report_revision_invalid(
            "revision_of_id must reference a REJECTED report on the same event")

    rec = base_record()
    rec.update({
        "event_id": ev["id"],
        "portal_submission_id": None,
        "submitted_at": None,
        "is_late": False,
        "revision_of_id": prior["id"],
        "status": "DRAFT",
    })
    store.reports[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/marshal-reports", methods=["GET"])
def list_reports_cross():
    require_roles(MARSHAL_AND_ADMIN)
    event_id = request.args.get("event_id")
    revision_of_id = request.args.get("revision_of_id")
    status = request.args.get("status")
    rows = list(store.reports.values())
    if event_id is not None:
        rows = [r for r in rows if r["event_id"] == event_id]
    if revision_of_id is not None:
        rows = [r for r in rows if r["revision_of_id"] == revision_of_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/marshal-reports/<rid>", methods=["GET"])
def fetch_report(rid):
    require_roles(MARSHAL_AND_ADMIN)
    return success_object(public(get_report(rid)))


@bp.route("/fire-compliance/marshal-reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    rep = get_report(rid)
    if rep["status"] != "DRAFT":
        raise invalid_state("MarshalReport is not DRAFT")
    ev = store.events.get(rep["event_id"])
    prop = property_of_event(ev) if ev else None
    con = contractor_of_event(ev) if ev else None
    require_contractor_active(con)
    require_property_active(prop)
    if ev is None or ev["status"] != "COMPLETED":
        raise event_not_completed("Parent event is not COMPLETED")
    if con is not None and con["posture"] == "SUSPENDED":
        raise posture_blocked("Contractor is SUSPENDED")

    now = store.now()
    rep["submitted_at"] = now
    rep["is_late"] = ev["report_due_date"] is not None and now.date() > ev["report_due_date"]
    rep["status"] = "SUBMITTED"
    touch(rep)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(rep))


@bp.route("/fire-compliance/marshal-reports/<rid>/accept", methods=["POST"])
def accept_report(rid):
    require_roles([ROLE_FIRE_MARSHAL])
    rep = get_report(rid)
    if rep["status"] != "SUBMITTED":
        raise invalid_state("MarshalReport is not SUBMITTED")
    ev = store.events.get(rep["event_id"])
    # every deficiency on the parent event must be VERIFIED/WAIVED or still
    # within its correction-deadline window
    today = store.today()
    for d in store.deficiencies.values():
        if d["event_id"] != rep["event_id"]:
            continue
        if d["status"] in ("VERIFIED", "WAIVED"):
            continue
        if d["correction_deadline"] is not None and today > d["correction_deadline"]:
            raise unresolved_overdue_deficiencies(
                "Event has deficiencies past their correction deadline and not VERIFIED/WAIVED")

    prop = property_of_event(ev) if ev else None
    jurisdiction = prop["jurisdiction_code"] if prop is not None else "UNKNOWN"
    counter = store.portal_counters.get(jurisdiction, 0) + 1
    store.portal_counters[jurisdiction] = counter
    rep["portal_submission_id"] = f"{jurisdiction}-{counter:08d}"
    rep["status"] = "ACCEPTED"
    touch(rep)
    con = contractor_of_event(ev) if ev else None
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(rep))


@bp.route("/fire-compliance/marshal-reports/<rid>/reject", methods=["POST"])
def reject_report(rid):
    require_roles([ROLE_FIRE_MARSHAL])
    rep = get_report(rid)
    if rep["status"] != "SUBMITTED":
        raise invalid_state("MarshalReport is not SUBMITTED")
    rep["status"] = "REJECTED"
    touch(rep)
    ev = store.events.get(rep["event_id"])
    con = contractor_of_event(ev) if ev else None
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(rep))
