"""Re-abstraction audits, discrepancy ledgers and quality scores."""

from flask import Blueprint

import calcs
import db
import services
import spec
import validate
from db import all_of, clock_now, fmt_date, fmt_instant, mark, parse_date
from errors import ApiError, invalid
from middleware import ANY_ROLE, actor, endpoint
from routes.common import PREFIX, need, ok, page

bp = Blueprint("audits", __name__)


@bp.post(PREFIX + "/qa-audits")
@endpoint(["QaReviewer", "RegistryManager"])
def create_audit():
    body = validate.body()
    abstraction_id = validate.f_str(body, "abstraction_id")
    auditor_id = validate.f_str(body, "auditor_id")
    audit_type = validate.f_enum(body, "audit_type", spec.AUDIT_TYPES)
    window_start = validate.f_date(body, "window_start")
    window_end = validate.f_date(body, "window_end")
    if window_end < window_start:
        raise invalid("window_end must not precede window_start.")

    abstraction = need("abstraction", abstraction_id,
                       "ERR_ABSTRACTION_NOT_FOUND")
    auditor = need("abstractor", auditor_id, "ERR_ABSTRACTOR_NOT_FOUND")

    if abstraction["abstraction_state"] not in ("SUBMITTED_FOR_QA", "APPROVED"):
        raise ApiError("ERR_ABSTRACTION_NOT_AUDITABLE")
    if auditor["employment_status"] != "ACTIVE":
        raise ApiError("ERR_ABSTRACTOR_NOT_ACTIVE")
    if auditor_id == abstraction["abstractor_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    overlapping = 0
    for existing in all_of("audit"):
        if existing["auditor_id"] != auditor_id:
            continue
        if existing["audit_state"] == "VOIDED":
            continue
        other_start = parse_date(existing["window_start"])
        other_end = parse_date(existing["window_end"])
        if window_start <= other_end and other_start <= window_end:
            overlapping += 1
    if overlapping >= spec.AUDITOR_WINDOW_CAPACITY:
        raise ApiError("ERR_AUDITOR_WINDOW_CAPACITY_EXCEEDED")

    case = db.get("case", abstraction["case_id"])
    if case is not None and auditor["program_id"] != case["program_id"]:
        raise ApiError("ERR_ABSTRACTOR_PROGRAM_MISMATCH")

    audit = db.new_entity("audit", {
        "abstraction_id": abstraction_id,
        "auditor_id": auditor_id,
        "audit_type": audit_type,
        "window_start": fmt_date(window_start),
        "window_end": fmt_date(window_end),
        "audited_field_count": 0,
        "minor_discrepancy_count": 0,
        "major_discrepancy_count": 0,
        "critical_discrepancy_count": 0,
        "weighted_error_score": 0,
        "verdict": None,
        "audit_state": "OPEN",
        "scored_at": None,
        "cascade_applied": False,
        "_pre_cascade_completed_on": None,
    })
    return ok(audit, 201)


@bp.get(PREFIX + "/qa-audits")
@endpoint(ANY_ROLE)
def list_audits():
    abstraction_id = validate.q_str("abstraction_id")
    auditor_id = validate.q_str("auditor_id")
    audit_state = validate.q_enum("audit_state", spec.AUDIT_STATES)
    verdict = validate.q_enum("verdict", spec.AUDIT_VERDICTS)
    items = all_of("audit")
    if abstraction_id is not None:
        items = [a for a in items if a["abstraction_id"] == abstraction_id]
    if auditor_id is not None:
        items = [a for a in items if a["auditor_id"] == auditor_id]
    if audit_state is not None:
        items = [a for a in items if a["audit_state"] == audit_state]
    if verdict is not None:
        items = [a for a in items if a["verdict"] == verdict]
    return page(items)


@bp.get(PREFIX + "/qa-audits/<audit_id>")
@endpoint(ANY_ROLE)
def read_audit(audit_id):
    audit = need("audit", audit_id, "ERR_AUDIT_NOT_FOUND")
    return ok(audit)


@bp.post(PREFIX + "/qa-audits/<audit_id>/score")
@endpoint(["QaReviewer"])
def score_audit(audit_id):
    body = validate.body()
    audited_field_count = validate.f_int(body, "audited_field_count", minimum=1)
    minor = validate.f_int(body, "minor_discrepancy_count", minimum=0)
    major = validate.f_int(body, "major_discrepancy_count", minimum=0)
    critical = validate.f_int(body, "critical_discrepancy_count", minimum=0)

    audit = need("audit", audit_id, "ERR_AUDIT_NOT_FOUND")
    if audit["audit_state"] == "VOIDED":
        raise ApiError("ERR_AUDIT_ALREADY_VOIDED")
    if audit["audit_state"] != "OPEN":
        raise ApiError("ERR_AUDIT_ALREADY_SCORED")
    if actor() != audit["auditor_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_ABSTRACTOR")

    weighted = calcs.weighted_error_score(minor, major, critical)
    verdict = calcs.audit_verdict(weighted, critical)

    mark(audit)
    audit["audited_field_count"] = audited_field_count
    audit["minor_discrepancy_count"] = minor
    audit["major_discrepancy_count"] = major
    audit["critical_discrepancy_count"] = critical
    audit["weighted_error_score"] = weighted
    audit["verdict"] = verdict
    audit["scored_at"] = fmt_instant(clock_now())
    audit["audit_state"] = "CLOSED_PASS" if verdict == "PASS" else "CLOSED_FAIL"

    abstraction = db.get("abstraction", audit["abstraction_id"])
    author = db.get("abstractor", abstraction["abstractor_id"]) \
        if abstraction is not None else None

    if author is not None:
        mark(author)
        author["lifetime_discrepancy_points"] = (
            author["lifetime_discrepancy_points"] + weighted)
        if verdict == "PASS":
            author["audit_fail_streak"] = 0
        else:
            author["audit_fail_streak"] = author["audit_fail_streak"] + 1
        services.refresh_abstractor_quality(author)

    if (verdict == "CRITICAL_FAIL" and abstraction is not None
            and abstraction["abstraction_state"] == "APPROVED"):
        audit["cascade_applied"] = True
        mark(abstraction)
        abstraction["abstraction_state"] = "REWORK_REQUIRED"
        case = db.get("case", abstraction["case_id"])
        if case is not None and case["case_state"] == "COMPLETED":
            audit["_pre_cascade_completed_on"] = case.get("completed_on")
            mark(case)
            case["case_state"] = "REWORK_PENDING"
            case["completed_on"] = None
            services.refresh_case_timeliness(case)
            services.refresh_case_follow_up(case)
            if author is not None:
                mark(author)
                author["assigned_open_case_count"] = (
                    author["assigned_open_case_count"] + 1)
            program = db.get("program", case["program_id"])
            if program is not None:
                services.refresh_program_follow_up(program)
                services.refresh_program_aggregates(program)

    if author is not None and author["audit_fail_streak"] >= spec.AUDIT_FAIL_STREAK_SUSPEND:
        mark(author)
        author["employment_status"] = "SUSPENDED_FROM_ABSTRACTING"
        services.release_worklist(author)

    return ok(audit)


@bp.post(PREFIX + "/qa-audits/<audit_id>/void")
@endpoint(["RegistryManager"])
def void_audit(audit_id):
    body = validate.body()
    validate.f_str(body, "void_reason")

    audit = need("audit", audit_id, "ERR_AUDIT_NOT_FOUND")
    if audit["audit_state"] == "VOIDED":
        raise ApiError("ERR_AUDIT_ALREADY_VOIDED")

    previous_state = audit["audit_state"]
    weighted = audit["weighted_error_score"]
    cascade_applied = audit.get("cascade_applied")

    mark(audit)
    audit["audit_state"] = "VOIDED"

    abstraction = db.get("abstraction", audit["abstraction_id"])
    author = db.get("abstractor", abstraction["abstractor_id"]) \
        if abstraction is not None else None

    if previous_state in spec.CLOSED_AUDIT_STATES and author is not None:
        mark(author)
        author["lifetime_discrepancy_points"] = max(
            0, author["lifetime_discrepancy_points"] - weighted)
        if previous_state == "CLOSED_FAIL":
            author["audit_fail_streak"] = services.recompute_fail_streak(author)
        services.refresh_abstractor_quality(author)
        services.refresh_abstractor_productivity(author)

    if (previous_state == "CLOSED_FAIL" and cascade_applied
            and abstraction is not None
            and abstraction["abstraction_state"] == "REWORK_REQUIRED"):
        superseding = [a for a in all_of("abstraction")
                       if a.get("supersedes_abstraction_id") == abstraction["id"]]
        if not superseding:
            mark(abstraction)
            abstraction["abstraction_state"] = "APPROVED"
            case = db.get("case", abstraction["case_id"])
            if case is not None and case["case_state"] == "REWORK_PENDING":
                mark(case)
                case["case_state"] = "COMPLETED"
                case["completed_on"] = audit.get("_pre_cascade_completed_on")
                services.refresh_case_timeliness(case)
                services.refresh_case_follow_up(case)
                if author is not None:
                    mark(author)
                    author["assigned_open_case_count"] = max(
                        0, author["assigned_open_case_count"] - 1)
                    services.refresh_abstractor_productivity(author)
                program = db.get("program", case["program_id"])
                if program is not None:
                    services.refresh_program_follow_up(program)
                    services.refresh_program_aggregates(program)

    return ok(audit)
