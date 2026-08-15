"""MonitoringVisit and MonitoringFinding endpoints."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as V
from routes.grants import get_grant_or_404
from services import serializers, workflows

bp = Blueprint("monitoring", __name__)

ALL_ROLES = middleware.ROLES
SEA = {"SEAMonitor"}
CAP_FILERS = {"ComplianceAnalyst", "FederalProgramsDirector"}
SCOPES = {"PROGRAMMATIC", "FISCAL", "COMPREHENSIVE"}
SEVERITIES = {"OBSERVATION", "FINDING", "SYSTEMIC"}
CAP_NARRATIVE_MIN = 50


def get_visit_or_404(visit_id):
    v = db.visits.get(visit_id)
    if v is None:
        errors.fail(errors.ERR_NOT_FOUND, "Monitoring visit %s does not exist." % visit_id)
    return v


def get_finding_or_404(finding_id):
    f = db.findings.get(finding_id)
    if f is None:
        errors.fail(errors.ERR_NOT_FOUND, "Monitoring finding %s does not exist." % finding_id)
    return f


def _check_visit_overlap(grant_id, start, end, exclude_id=None):
    """Closed day-interval overlap: sharing even one boundary day conflicts."""
    for v in db.visits.values():
        if v["grant_id"] != grant_id or v["id"] == exclude_id:
            continue
        o_start = V.parse_date(v["visit_start_date"], "visit_start_date")
        o_end = V.parse_date(v["visit_end_date"], "visit_end_date")
        if start <= o_end and o_start <= end:
            errors.fail(
                errors.ERR_MONITORING_VISIT_OVERLAP,
                "The visit's closed day-interval overlaps another visit of the same grant.",
            )


@bp.post("/monitoring-visits")
def create_visit():
    uid, role = middleware.current_user()
    middleware.require_role(role, SEA)
    data = V.json_body()
    grant_ref = data.get("grant_id")
    if grant_ref is not None and isinstance(grant_ref, str):
        get_grant_or_404(grant_ref)
    V.check_unknown(data, {"grant_id", "visit_start_date", "visit_end_date", "scope"})
    grant_id = V.req_str(data, "grant_id")
    grant = get_grant_or_404(grant_id)
    start_raw = V.req_str(data, "visit_start_date")
    end_raw = V.req_str(data, "visit_end_date")
    start = V.parse_date(start_raw, "visit_start_date")
    end = V.parse_date(end_raw, "visit_end_date")
    if end < start:
        errors.fail(
            errors.ERR_INVALID_DATE_RANGE,
            "visit_end_date must not be before visit_start_date.",
        )
    scope = V.req_enum(data, "scope", SCOPES)
    # Tier 10: overlap runs at scheduling time.
    _check_visit_overlap(grant["id"], start, end)
    visit = db.init_common({
        "grant_id": grant["id"],
        "visit_start_date": start_raw,
        "visit_end_date": end_raw,
        "scope": scope,
        "lead_monitor_id": uid,
        "status": "SCHEDULED",
        "report_issued_at": None,
    })
    db.visits[visit["id"]] = visit
    return response.success_object(serializers.visit_view(visit), 201)


@bp.get("/monitoring-visits")
def list_visits():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    filters = [
        ("grant_id", V.query_filter("grant_id")),
        ("status", V.query_filter("status")),
    ]
    page, limit, offset, total = V.sorted_page(list(db.visits.values()), filters)
    return response.success_list(
        [serializers.visit_view(v) for v in page], limit, offset, total
    )


@bp.get("/monitoring-visits/<visit_id>")
def get_visit(visit_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    return response.success_object(serializers.visit_view(get_visit_or_404(visit_id)))


@bp.post("/monitoring-visits/<visit_id>/start")
def start_visit(visit_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, SEA)
    visit = get_visit_or_404(visit_id)
    data = V.json_body()
    V.check_unknown(data, set())
    if visit["status"] != "SCHEDULED":
        errors.fail(errors.ERR_VISIT_INVALID_STATE, "Only a SCHEDULED visit may be started.")
    start = V.parse_date(visit["visit_start_date"], "visit_start_date")
    end = V.parse_date(visit["visit_end_date"], "visit_end_date")
    today = db.clock_date()
    if not (start <= today <= end):
        errors.fail(
            errors.ERR_VISIT_WINDOW_MISSED,
            "The current clock date is outside the visit window.",
        )
    # The overlap check runs again when a visit begins.
    _check_visit_overlap(visit["grant_id"], start, end, exclude_id=visit["id"])
    visit["status"] = "IN_PROGRESS"
    db.touch(visit)
    return response.success_object(serializers.visit_view(visit))


@bp.post("/monitoring-visits/<visit_id>/issue-report")
def issue_report(visit_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, SEA)
    visit = get_visit_or_404(visit_id)
    data = V.json_body()
    V.check_unknown(data, set())
    if visit["status"] != "IN_PROGRESS":
        errors.fail(
            errors.ERR_VISIT_INVALID_STATE,
            "Only an IN_PROGRESS visit may issue its report.",
        )
    visit["status"] = "REPORT_ISSUED"
    visit["report_issued_at"] = db.now_ts()
    db.touch(visit)
    # Empty-set closure: a zero-finding visit closes immediately.
    if not workflows.visit_findings(visit["id"]):
        visit["status"] = "CLOSED"
        db.touch(visit)
        grant = db.grants[visit["grant_id"]]
        workflows.recompute_clearance(grant)
        db.touch(grant)
    return response.success_object(serializers.visit_view(visit))


@bp.post("/monitoring-findings")
def create_finding():
    _uid, role = middleware.current_user()
    middleware.require_role(role, SEA)
    data = V.json_body()
    visit_ref = data.get("visit_id")
    if visit_ref is not None and isinstance(visit_ref, str):
        get_visit_or_404(visit_ref)
    V.check_unknown(data, {"visit_id", "citation", "severity", "description", "cap_due_date"})
    visit_id = V.req_str(data, "visit_id")
    visit = get_visit_or_404(visit_id)
    citation = V.req_str(data, "citation")
    severity = V.req_enum(data, "severity", SEVERITIES)
    V.req_str(data, "description")
    cap_due_raw = V.req_str(data, "cap_due_date")
    cap_due = V.parse_date(cap_due_raw, "cap_due_date")
    # Tier 5: findings are recorded only while the visit is IN_PROGRESS.
    if visit["status"] != "IN_PROGRESS":
        errors.fail(
            errors.ERR_VISIT_NOT_ACCEPTING_FINDINGS,
            "Findings may only be recorded while the visit is IN_PROGRESS.",
        )
    # Tier 10: cap due date strictly after the visit's end.
    visit_end = V.parse_date(visit["visit_end_date"], "visit_end_date")
    if cap_due <= visit_end:
        errors.fail(
            errors.ERR_INVALID_DATE_RANGE,
            "cap_due_date must be strictly after the visit's visit_end_date.",
        )
    finding = db.init_common({
        "visit_id": visit["id"],
        "citation": citation,
        "severity": severity,
        "description": data["description"],
        "cap_due_date": cap_due_raw,
        "status": "OPEN",
        "cap_narrative": None,
        "cap_attempt_count": 0,
        "cap_submitted_by_user_id": None,
        "decided_by_user_id": None,
        "return_note": None,
    })
    db.findings[finding["id"]] = finding
    grant = db.grants[visit["grant_id"]]
    workflows.recompute_clearance(grant)
    db.touch(grant)
    return response.success_object(serializers.finding_view(finding), 201)


@bp.get("/monitoring-findings")
def list_findings():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    filters = [
        ("visit_id", V.query_filter("visit_id")),
        ("status", V.query_filter("status")),
        ("severity", V.query_filter("severity")),
    ]
    page, limit, offset, total = V.sorted_page(list(db.findings.values()), filters)
    return response.success_list(
        [serializers.finding_view(f) for f in page], limit, offset, total
    )


@bp.get("/monitoring-findings/<finding_id>")
def get_finding(finding_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    return response.success_object(serializers.finding_view(get_finding_or_404(finding_id)))


@bp.post("/monitoring-findings/<finding_id>/submit-cap")
def submit_cap(finding_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, CAP_FILERS)
    finding = get_finding_or_404(finding_id)
    data = V.json_body()
    V.check_unknown(data, {"cap_narrative"})
    narrative = V.req_str(data, "cap_narrative")
    if len(narrative) < CAP_NARRATIVE_MIN:
        errors.fail(
            errors.ERR_NARRATIVE_TOO_SHORT,
            "cap_narrative must be at least 50 characters.",
        )
    # Tier 5: OPEN, ESCALATED, or CAP_RETURNED (the revision cycle).
    if finding["status"] not in ("OPEN", "ESCALATED", "CAP_RETURNED"):
        errors.fail(
            errors.ERR_FINDING_INVALID_STATE,
            "A CAP may only be submitted from OPEN, ESCALATED, or CAP_RETURNED.",
        )
    finding["status"] = "CAP_SUBMITTED"
    finding["cap_narrative"] = narrative
    finding["cap_submitted_by_user_id"] = uid
    finding["cap_attempt_count"] += 1
    db.touch(finding)
    return response.success_object(serializers.finding_view(finding))


@bp.post("/monitoring-findings/<finding_id>/accept-cap")
def accept_cap(finding_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, SEA)
    finding = get_finding_or_404(finding_id)
    data = V.json_body()
    V.check_unknown(data, set())
    if finding["status"] != "CAP_SUBMITTED":
        errors.fail(
            errors.ERR_FINDING_INVALID_STATE,
            "accept-cap requires status CAP_SUBMITTED.",
        )
    if uid == finding["cap_submitted_by_user_id"]:
        errors.fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "The CAP decider must differ from its submitter.",
        )
    finding["status"] = "VERIFIED"
    finding["decided_by_user_id"] = uid
    db.touch(finding)
    workflows.finding_terminal_bubble_up(finding)
    return response.success_object(serializers.finding_view(finding))


@bp.post("/monitoring-findings/<finding_id>/return-cap")
def return_cap(finding_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, SEA)
    finding = get_finding_or_404(finding_id)
    data = V.json_body()
    V.check_unknown(data, {"return_note"})
    return_note = V.opt_str(data, "return_note")
    if not return_note:
        errors.fail(errors.ERR_INVALID_REQUEST, "return_note is required when a CAP is returned.")
    if finding["status"] != "CAP_SUBMITTED":
        errors.fail(
            errors.ERR_FINDING_INVALID_STATE,
            "return-cap requires status CAP_SUBMITTED.",
        )
    if uid == finding["cap_submitted_by_user_id"]:
        errors.fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "The CAP decider must differ from its submitter.",
        )
    finding["status"] = "CAP_RETURNED"
    finding["return_note"] = return_note
    finding["decided_by_user_id"] = uid
    db.touch(finding)
    return response.success_object(serializers.finding_view(finding))


@bp.post("/monitoring-findings/<finding_id>/close-no-action")
def close_no_action(finding_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, SEA)
    finding = get_finding_or_404(finding_id)
    data = V.json_body()
    V.check_unknown(data, set())
    # The shortcut is available only to an OPEN finding of OBSERVATION severity.
    if finding["status"] != "OPEN" or finding["severity"] != "OBSERVATION":
        errors.fail(
            errors.ERR_FINDING_INVALID_STATE,
            "close-no-action requires an OPEN finding of OBSERVATION severity.",
        )
    finding["status"] = "CLOSED_NO_ACTION"
    finding["decided_by_user_id"] = uid
    db.touch(finding)
    workflows.finding_terminal_bubble_up(finding)
    return response.success_object(serializers.finding_view(finding))
