"""Reporting cycles, the readiness dashboard, and milestones."""
from datetime import timedelta

from flask import Blueprint, request

import calc
from authz import (
    ALL_ROLES,
    ROLE_CHAIR,
    ROLE_COMPLIANCE_ADMIN,
    ROLE_CONTROLLER,
    authorize,
    gate_action,
    require_action,
)
from core import TouchLog, bad, dec, fmt_instant, parse_instant, public, store, success_object
from helpers import apply_eq, paged, sort_created_asc, sort_milestones
from validate import (
    as_day,
    as_enum,
    as_instant,
    as_number,
    as_string,
    body_of,
    enum_filter,
    opt_integer,
    opt_string,
    pagination,
    req_present,
    str_filter,
)

bp = Blueprint("cycle", __name__)

CYCLE_STATUSES = (
    "PLANNING",
    "CLOSE_OPEN",
    "REVIEW_OPEN",
    "CERTIFICATION_OPEN",
    "FILING_READY",
    "FILED",
    "AMENDED",
    "ABANDONED",
)
FORM_TYPES = ("FORM_10Q", "FORM_10K")
FILER_STATUSES = ("LARGE_ACCELERATED", "ACCELERATED", "NON_ACCELERATED")
MILESTONE_KINDS = ("CLOSE", "REVIEW", "CERTIFICATION", "FILING")
MILESTONE_STATUSES = ("PLANNED", "IN_PROGRESS", "COMPLETE", "BREACHED")
READINESS_ROLES = [r for r in ALL_ROLES if r != "BusinessLeader"]


@bp.get("/disclosure/reporting-cycles")
def list_cycles():
    authorize(request, ALL_ROLES)
    limit, offset = pagination(request.args)
    rows = store.all_rows("cycle")
    rows = apply_eq(rows, "charter_id", str_filter(request.args, "charter_id"))
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", CYCLE_STATUSES))
    rows = apply_eq(rows, "form_type", enum_filter(request.args, "form_type", FORM_TYPES))
    return paged(sort_created_asc(rows), limit, offset)


@bp.get("/disclosure/reporting-cycles/<cycle_id>")
def get_cycle(cycle_id):
    authorize(request, ALL_ROLES)
    return success_object(public(store.must_get("cycle", cycle_id)))


@bp.post("/disclosure/reporting-cycles")
def create_cycle():
    authorize(request, [ROLE_COMPLIANCE_ADMIN])
    body = body_of(request)
    charter = None
    if "charter_id" in body and body["charter_id"] is not None:
        charter = store.must_get("charter", body["charter_id"])
    fiscal_period_label = as_string(req_present(body, "fiscal_period_label"), "fiscal_period_label", 40)
    form_type = as_enum(req_present(body, "form_type"), "form_type", FORM_TYPES)
    period_end_day = as_day(req_present(body, "period_end_date"), "period_end_date")
    filer_status = as_enum(req_present(body, "filer_status"), "filer_status", FILER_STATUSES)
    materiality_base_amount = as_number(
        req_present(body, "materiality_base_amount"), "materiality_base_amount", exclusive_min=0
    )
    if charter is None:
        req_present(body, "charter_id")
    internal_buffer_days = opt_integer(body, "internal_buffer_days", 5, 0, 30)

    if charter["status"] != "ADOPTED":
        bad("ERR_CHARTER_NOT_ADOPTED", "the pinned charter is not ADOPTED")

    statutory, internal = calc.cycle_deadlines(
        form_type, filer_status, period_end_day, internal_buffer_days
    )
    row = store.new_row(
        "cycle",
        {
            "fiscal_period_label": fiscal_period_label,
            "form_type": form_type,
            "period_end_date": period_end_day.isoformat(),
            "filer_status": filer_status,
            "materiality_base_amount": materiality_base_amount,
            "internal_buffer_days": internal_buffer_days,
            "charter_id": charter["id"],
            "statutory_deadline_utc": fmt_instant(statutory),
            "internal_target_utc": fmt_instant(internal),
            "status": "PLANNING",
            "restatement_stage": "NONE",
            "min_slack_days_calendar": calc.NO_SLACK_SENTINEL,
            "min_slack_days_business": calc.NO_SLACK_SENTINEL,
            "total_assigned_scope_weight": 0.00,
            "certification_coverage_pct": 0.00,
            "open_material_event_count": 0,
            "unresolved_deficiency_weight": 0.00,
        },
    )
    return success_object(public(row), 201)


@bp.get("/disclosure/reporting-cycles/<cycle_id>/readiness")
def cycle_readiness(cycle_id):
    authorize(request, READINESS_ROLES)
    cycle = store.must_get("cycle", cycle_id)
    log = TouchLog()
    calc.breach_sweep(cycle, log)
    blockers = calc.filing_ready_blockers(cycle)
    payload = {
        "cycle_id": cycle["id"],
        "cycle_status": cycle["status"],
        "restatement_stage": cycle["restatement_stage"],
        "statutory_deadline_utc": cycle["statutory_deadline_utc"],
        "internal_target_utc": cycle["internal_target_utc"],
        "min_slack_days_calendar": cycle["min_slack_days_calendar"],
        "min_slack_days_business": cycle["min_slack_days_business"],
        "total_assigned_scope_weight": cycle["total_assigned_scope_weight"],
        "certification_coverage_pct": cycle["certification_coverage_pct"],
        "open_material_event_count": cycle["open_material_event_count"],
        "unresolved_deficiency_weight": cycle["unresolved_deficiency_weight"],
        "missing_milestone_kinds": calc.missing_milestone_kinds(cycle),
        "unsigned_cert_types": calc.unsigned_cert_types(cycle),
        "blocking_error_ids": blockers,
        "filing_ready_eligible": len(blockers) == 0,
    }
    return success_object(payload)


CYCLE_TRANSITION_SOURCES = {
    "OPEN_CLOSE": ["PLANNING"],
    "OPEN_REVIEW": ["CLOSE_OPEN"],
    "OPEN_CERTIFICATION": ["REVIEW_OPEN"],
    "DECLARE_FILING_READY": ["CERTIFICATION_OPEN"],
    "ABANDON": ["PLANNING", "CLOSE_OPEN", "REVIEW_OPEN", "CERTIFICATION_OPEN", "FILING_READY"],
}
CYCLE_TRANSITION_TARGETS = {
    "OPEN_CLOSE": "CLOSE_OPEN",
    "OPEN_REVIEW": "REVIEW_OPEN",
    "OPEN_CERTIFICATION": "CERTIFICATION_OPEN",
    "DECLARE_FILING_READY": "FILING_READY",
    "ABANDON": "ABANDONED",
}


@bp.post("/disclosure/reporting-cycles/<cycle_id>/transitions")
def transition_cycle(cycle_id):
    actor = authorize(request, [ROLE_CONTROLLER, ROLE_CHAIR])
    body = body_of(request)
    gate_action(actor, "cycle", body)
    cycle = store.must_get("cycle", cycle_id)
    action = require_action("cycle", body)
    opt_string(body, "note", 2000, None, True)

    if cycle["status"] == "ABANDONED":
        bad("ERR_ENTITY_TERMINAL", "cycle is ABANDONED")
    if cycle["status"] not in CYCLE_TRANSITION_SOURCES[action]:
        bad("ERR_INVALID_STATE", "%s is not declared from %s" % (action, cycle["status"]))

    log = TouchLog()
    calc.breach_sweep(cycle, log)

    charter = store.get("charter", cycle["charter_id"])
    if charter is None or charter["status"] != "ADOPTED":
        bad("ERR_CHARTER_NOT_ADOPTED", "the pinned charter is not ADOPTED")

    if action == "OPEN_CLOSE":
        if not calc.has_milestone_of_kind(cycle, "CLOSE"):
            bad("ERR_MILESTONE_MISSING", "the cycle carries no CLOSE milestone")
    elif action == "OPEN_REVIEW":
        if not calc.has_milestone_of_kind(cycle, "CLOSE"):
            bad("ERR_MILESTONE_MISSING", "the cycle carries no CLOSE milestone")
        if not calc.all_milestones_of_kind_complete(cycle, "CLOSE"):
            bad("ERR_MILESTONE_INCOMPLETE", "every CLOSE milestone must be COMPLETE")
    elif action == "OPEN_CERTIFICATION":
        if not calc.has_milestone_of_kind(cycle, "REVIEW"):
            bad("ERR_MILESTONE_MISSING", "the cycle carries no REVIEW milestone")
        if not calc.all_milestones_of_kind_complete(cycle, "REVIEW"):
            bad("ERR_MILESTONE_INCOMPLETE", "every REVIEW milestone must be COMPLETE")
        approved = [
            d
            for d in store.where("document", cycle_id=cycle["id"])
            if d["doc_type"] == "PERIODIC_FILING" and d["status"] == "APPROVED"
        ]
        if not approved:
            bad("ERR_FILING_DOCUMENT_INVALID", "no APPROVED PERIODIC_FILING document on the cycle")
    elif action == "DECLARE_FILING_READY":
        if not calc.charter_quorum_ok(charter):
            bad("ERR_QUORUM_NOT_MET", "active voting members below min_quorum_count")
        if not calc.charter_coverage_ok(charter):
            bad("ERR_FUNCTION_COVERAGE_GAP", "required_functions are not fully covered")
        if cycle["open_material_event_count"] != 0:
            bad("ERR_OPEN_MATERIAL_EVENT", "the cycle carries open material events")
        if calc.deficiency_gate_blocked(cycle):
            bad("ERR_DEFICIENCY_OPEN", "unresolved deficiency weight or an open restatement")
        if not calc.has_milestone_of_kind(cycle, "FILING"):
            bad("ERR_MILESTONE_MISSING", "the cycle carries no FILING milestone")
        if not calc.certifications_complete(cycle):
            bad("ERR_CERTIFICATIONS_INCOMPLETE", "a required officer certification is unsigned")
        if cycle["min_slack_days_business"] < calc.REQUIRED_FILING_SLACK_BUSINESS_DAYS:
            bad("ERR_MILESTONE_SLACK_EXHAUSTED", "min_slack_days_business is below 1")

    cycle["status"] = CYCLE_TRANSITION_TARGETS[action]

    if action == "OPEN_CERTIFICATION":
        for cert in store.where("officer_cert", cycle_id=cycle["id"]):
            if cert["status"] == "BLOCKED" and cycle["open_material_event_count"] == 0:
                cert["status"] = "ELIGIBLE"
                log.touch(cert)
        for cert in store.where("officer_cert", cycle_id=cycle["id"]):
            if cert["status"] == "REVOKED":
                cert["status"] = "BLOCKED"
                log.touch(cert)
        calc.recompute_certification_coverage_pct(cycle)
    elif action == "ABANDON":
        for row in store.where("subcert", cycle_id=cycle["id"]):
            if row["status"] in ("PENDING", "SUBMITTED", "EXCEPTION_NOTED"):
                row["status"] = "VOID"
                log.touch(row)
        for cert in store.where("officer_cert", cycle_id=cycle["id"]):
            if cert["status"] in ("BLOCKED", "ELIGIBLE", "SIGNED", "REVOKED"):
                cert["status"] = "VOID"
                log.touch(cert)
        for document in store.where("document", cycle_id=cycle["id"]):
            if document["status"] in ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED"):
                document["status"] = "SUPERSEDED"
                log.touch(document)
        for event in store.where("event", cycle_id=cycle["id"]):
            if event["assessment_status"] in ("UNASSESSED", "NOT_REPORTABLE", "REPORTABLE"):
                event["assessment_status"] = "SUPERSEDED"
                log.touch(event)
        calc.recompute_open_material_event_count(cycle)
        calc.recompute_total_assigned_scope_weight(cycle)
        calc.recompute_certification_coverage_pct(cycle)

    log.touch(cycle)
    return success_object(public(cycle))


@bp.get("/disclosure/reporting-cycles/<cycle_id>/milestones")
def list_milestones(cycle_id):
    authorize(request, ALL_ROLES)
    cycle = store.must_get("cycle", cycle_id)
    limit, offset = pagination(request.args)
    rows = store.where("milestone", cycle_id=cycle["id"])
    rows = apply_eq(rows, "kind", enum_filter(request.args, "kind", MILESTONE_KINDS))
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", MILESTONE_STATUSES))
    return paged(sort_milestones(rows), limit, offset)


@bp.post("/disclosure/reporting-cycles/<cycle_id>/milestones")
def create_milestone(cycle_id):
    authorize(request, [ROLE_CONTROLLER])
    body = body_of(request)
    cycle = store.must_get("cycle", cycle_id)
    kind = as_enum(req_present(body, "kind"), "kind", MILESTONE_KINDS)
    planned_start = as_instant(req_present(body, "planned_start_utc"), "planned_start_utc")
    planned_end = as_instant(req_present(body, "planned_end_utc"), "planned_end_utc")

    if cycle["status"] == "ABANDONED":
        bad("ERR_ENTITY_TERMINAL", "cycle is ABANDONED")
    if cycle["status"] not in ("PLANNING", "CLOSE_OPEN"):
        bad("ERR_INVALID_STATE", "the cycle no longer accepts milestones")

    siblings = [m for m in store.where("milestone", cycle_id=cycle["id"]) if m["kind"] == kind]
    for sibling in siblings:
        sibling_start = parse_instant(sibling["planned_start_utc"])
        sibling_end = parse_instant(sibling["planned_end_utc"])
        if planned_start < sibling_end and sibling_start < planned_end:
            bad("ERR_MILESTONE_WINDOW_OVERLAP", "candidate window overlaps a same-kind milestone")

    pred = calc.predecessor_kind(kind)
    if pred is not None:
        pred_rows = [m for m in store.where("milestone", cycle_id=cycle["id"]) if m["kind"] == pred]
        if pred_rows:
            latest_end = max(parse_instant(m["planned_end_utc"]) for m in pred_rows)
            required = calc.buffer_hours_for(pred, kind)
            gap_hours = (planned_start - latest_end).total_seconds() / 3600.0
            if gap_hours < required:
                bad(
                    "ERR_MILESTONE_BUFFER_VIOLATION",
                    "at least %d hours are required between %s and %s" % (required, pred, kind),
                )

    deadline = parse_instant(cycle["statutory_deadline_utc"])
    if not planned_start < planned_end or planned_end > deadline:
        bad("ERR_MILESTONE_PAST_DEADLINE", "the candidate window is not inside the statutory deadline")

    log = TouchLog()
    slack_calendar, slack_business = calc.milestone_slack(cycle, planned_end)
    row = store.new_row(
        "milestone",
        {
            "cycle_id": cycle["id"],
            "kind": kind,
            "planned_start_utc": fmt_instant(planned_start),
            "planned_end_utc": fmt_instant(planned_end),
            "actual_start_utc": None,
            "actual_end_utc": None,
            "status": "PLANNED",
            "slack_calendar_days": slack_calendar,
            "slack_business_days": slack_business,
        },
    )
    calc.recompute_cycle_slack(cycle)
    log.touch(cycle)
    return success_object(public(row), 201)


@bp.post("/disclosure/milestones/<milestone_id>/transitions")
def transition_milestone(milestone_id):
    actor = authorize(request, [ROLE_CONTROLLER])
    body = body_of(request)
    gate_action(actor, "milestone", body)
    milestone = store.must_get("milestone", milestone_id)
    action = require_action("milestone", body)

    if milestone["status"] in ("COMPLETE", "BREACHED"):
        bad("ERR_ENTITY_TERMINAL", "milestone is %s" % milestone["status"])
    cycle = store.get("cycle", milestone["cycle_id"])

    log = TouchLog()
    if action == "START":
        if milestone["status"] != "PLANNED":
            bad("ERR_INVALID_STATE", "START requires a PLANNED milestone")
        if cycle is None or cycle["status"] not in ("CLOSE_OPEN", "REVIEW_OPEN", "CERTIFICATION_OPEN"):
            bad("ERR_INVALID_STATE", "the cycle does not admit starting a milestone")
        milestone["status"] = "IN_PROGRESS"
        milestone["actual_start_utc"] = store.clock.now_iso()
    else:
        if milestone["status"] != "IN_PROGRESS":
            bad("ERR_INVALID_STATE", "COMPLETE requires an IN_PROGRESS milestone")
        milestone["status"] = "COMPLETE"
        milestone["actual_end_utc"] = store.clock.now_iso()
    log.touch(milestone)
    if cycle is not None:
        calc.recompute_cycle_slack(cycle)
        log.touch(cycle)
    return success_object(public(milestone))
