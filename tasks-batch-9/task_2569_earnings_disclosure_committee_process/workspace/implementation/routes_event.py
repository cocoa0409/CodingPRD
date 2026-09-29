"""Material events: logging, assessment and disclosure."""
from flask import Blueprint, request

import calc
from authz import (
    ALL_ROLES,
    ROLE_COMPLIANCE_ADMIN,
    ROLE_LEGAL,
    authorize,
    gate_action,
    require_action,
)
from core import TouchLog, bad, fmt_instant, public, store, success_object
from helpers import apply_eq, paged, sort_created_asc
from validate import (
    as_enum,
    as_instant,
    as_number,
    as_string,
    body_of,
    enum_filter,
    opt_string,
    pagination,
    present,
    req_present,
    str_filter,
)

bp = Blueprint("event", __name__)

EVENT_CATEGORIES = (
    "ACQUISITION",
    "DIVESTITURE",
    "DEBT_COVENANT_BREACH",
    "LITIGATION_JUDGMENT",
    "AUDITOR_CHANGE",
    "IMPAIRMENT",
)
EVENT_STATUSES = ("UNASSESSED", "NOT_REPORTABLE", "REPORTABLE", "DISCLOSED", "SUPERSEDED")
NARROW_ROLES = [r for r in ALL_ROLES if r != "BusinessLeader"]


@bp.get("/disclosure/material-events")
def list_events():
    authorize(request, NARROW_ROLES)
    limit, offset = pagination(request.args)
    rows = store.all_rows("event")
    rows = apply_eq(rows, "cycle_id", str_filter(request.args, "cycle_id"))
    rows = apply_eq(rows, "linked_document_id", str_filter(request.args, "linked_document_id"))
    rows = apply_eq(
        rows, "assessment_status", enum_filter(request.args, "assessment_status", EVENT_STATUSES)
    )
    rows = apply_eq(rows, "category", enum_filter(request.args, "category", EVENT_CATEGORIES))
    return paged(sort_created_asc(rows), limit, offset)


@bp.get("/disclosure/material-events/<event_id>")
def get_event(event_id):
    authorize(request, NARROW_ROLES)
    return success_object(public(store.must_get("event", event_id)))


@bp.post("/disclosure/reporting-cycles/<cycle_id>/material-events")
def create_event(cycle_id):
    authorize(request, [ROLE_COMPLIANCE_ADMIN, ROLE_LEGAL])
    cycle = store.must_get("cycle", cycle_id)
    body = body_of(request)
    category = as_enum(req_present(body, "category"), "category", EVENT_CATEGORIES)
    occurred_utc = as_instant(req_present(body, "occurred_utc"), "occurred_utc")
    discovered_utc = as_instant(req_present(body, "discovered_utc"), "discovered_utc")
    magnitude_amount = as_number(
        req_present(body, "magnitude_amount"), "magnitude_amount", minimum=0
    )
    description = as_string(req_present(body, "description"), "description", 400)
    if discovered_utc < occurred_utc:
        bad("ERR_INVALID_REQUEST", "'discovered_utc' must be at or after 'occurred_utc'")

    if cycle["status"] == "ABANDONED":
        bad("ERR_ENTITY_TERMINAL", "cycle is ABANDONED")

    log = TouchLog()
    row = store.new_row(
        "event",
        {
            "cycle_id": cycle["id"],
            "linked_document_id": None,
            "category": category,
            "occurred_utc": fmt_instant(occurred_utc),
            "discovered_utc": fmt_instant(discovered_utc),
            "magnitude_amount": magnitude_amount,
            "description": description,
            "severity_score": calc.event_severity_score(
                magnitude_amount, cycle["materiality_base_amount"]
            ),
            "assessment_status": "UNASSESSED",
            "determination_note": None,
            "current_report_deadline_utc": None,
        },
    )
    calc.recompute_open_material_event_count(cycle)
    calc.block_eligible_certifications(cycle, log)
    log.touch(cycle)
    return success_object(public(row), 201)


@bp.post("/disclosure/material-events/<event_id>/transitions")
def transition_event(event_id):
    actor = authorize(request, [ROLE_LEGAL])
    body = body_of(request)
    gate_action(actor, "event", body)
    event = store.must_get("event", event_id)
    linked_document = None
    if present(body, "linked_document_id"):
        linked_document = store.must_get("document", body["linked_document_id"])
    action = require_action("event", body)
    determination = None
    if action == "ASSESS":
        determination = as_enum(
            req_present(body, "determination"), "determination", ("NOT_REPORTABLE", "REPORTABLE")
        )
    determination_note = opt_string(body, "determination_note", 2000, allow_empty=True)
    if action == "DISCLOSE" and linked_document is None:
        req_present(body, "linked_document_id")

    if event["assessment_status"] in ("DISCLOSED", "SUPERSEDED"):
        bad("ERR_ENTITY_TERMINAL", "the event is %s" % event["assessment_status"])
    cycle = store.get("cycle", event["cycle_id"])

    log = TouchLog()
    if action == "ASSESS":
        if event["assessment_status"] not in ("UNASSESSED", "NOT_REPORTABLE"):
            bad("ERR_INVALID_STATE", "ASSESS is not available from REPORTABLE")
        if determination == "NOT_REPORTABLE":
            if event["assessment_status"] != "UNASSESSED":
                bad("ERR_INVALID_STATE", "NOT_REPORTABLE is only available from UNASSESSED")
            if calc.dec(event["severity_score"]) >= calc.MATERIALITY_REPORTABLE_PCT:
                bad(
                    "ERR_EVENT_DETERMINATION_CONFLICT",
                    "an event at or above the 5.00 percent floor cannot be NOT_REPORTABLE",
                )
            event["assessment_status"] = "NOT_REPORTABLE"
            event["determination_note"] = determination_note
            event["current_report_deadline_utc"] = None
            log.touch(event)
            if cycle is not None:
                calc.recompute_open_material_event_count(cycle)
                calc.release_blocked_certifications(cycle, log)
                log.touch(cycle)
            return success_object(public(event))

        event["assessment_status"] = "REPORTABLE"
        event["determination_note"] = determination_note
        event["current_report_deadline_utc"] = calc.current_report_deadline(
            calc.parse_instant(event["discovered_utc"])
        )
        log.touch(event)
        if cycle is not None:
            calc.recompute_open_material_event_count(cycle)
            calc.block_eligible_certifications(cycle, log)
            log.touch(cycle)
        return success_object(public(event))

    # DISCLOSE
    if event["assessment_status"] != "REPORTABLE":
        bad("ERR_INVALID_STATE", "DISCLOSE requires a REPORTABLE event")
    if (
        linked_document["doc_type"] != "CURRENT_REPORT"
        or linked_document["cycle_id"] != event["cycle_id"]
        or linked_document["status"] != "APPROVED"
    ):
        bad(
            "ERR_FILING_DOCUMENT_INVALID",
            "linked_document_id must name an APPROVED CURRENT_REPORT on the same cycle",
        )
    event["assessment_status"] = "DISCLOSED"
    event["linked_document_id"] = linked_document["id"]
    if determination_note is not None:
        event["determination_note"] = determination_note
    log.touch(event)
    if cycle is not None:
        calc.recompute_open_material_event_count(cycle)
        calc.release_blocked_certifications(cycle, log)
        log.touch(cycle)
    return success_object(public(event))
