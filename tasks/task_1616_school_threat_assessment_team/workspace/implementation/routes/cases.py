"""Threat case endpoints: intake, triage, screening, removal, close, reopen,
plus the case-scoped sub-resource list endpoints, documents, and audit trail."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CASE_NOT_CLOSABLE,
    ERR_CASE_NOT_IN_INTAKE,
    ERR_CASE_NOT_REMOVABLE,
    ERR_CASE_NOT_REOPENABLE,
    ERR_CASE_NOT_TRIAGED,
    ERR_CASE_PURGED,
    ERR_ESCALATION_UNRESOLVED,
    ERR_OPEN_CHECKINS_EXIST,
    ERR_OPEN_REFERRALS_EXIST,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    get_json_body,
    optional_bool,
    paginate,
    parse_pagination,
    require_enum,
    require_string,
    require_string_allow_empty,
    sort_by_created_at,
)

bp = Blueprint("cases", __name__)

REPORTER_CHANNELS = {"TIP_LINE", "STAFF_REFERRAL"}
TRIAGE_PRIORITIES = {"ROUTINE", "URGENT", "EMERGENT"}
REMOVAL_TYPES = {"EMERGENCY_REMOVAL", "DISCIPLINARY_EXCLUSION"}
DOC_TYPES = {"INTAKE_NOTE", "INTERVIEW_SUMMARY", "PLAN_DOCUMENT", "LEGAL_HOLD", "OTHER"}

ALL_ROLES = ("IntakeCoordinator", "ThreatAssessor", "TeamLead", "DistrictAdministrator")


# ---------------------------------------------------------------------------
# Case intake / reads
# ---------------------------------------------------------------------------

@bp.route("/threat-cases", methods=["POST"])
@require_roles("IntakeCoordinator")
def create_case(_user_id: str, _role: str):
    body = get_json_body()
    school_id = require_string(body, "school_id")
    subject_alias = require_string(body, "subject_alias")
    reporter_channel = require_enum(body, "reporter_channel", REPORTER_CHANNELS)
    summary = require_string(body, "summary")

    # Body-referenced FK existence (priority 3.6).
    domain.require_school(school_id)

    case = {
        "school_id": school_id,
        "subject_alias": subject_alias,
        "reporter_channel": reporter_channel,
        "summary": summary,
        "status": "INTAKE",
        "triage_priority": None,
        "screening_score": None,
        "screening_outcome": None,
        "risk_level": None,
        "monitoring_cadence_days": None,
        "consecutive_missed_count": 0,
        "escalation_flag": False,
        "removal_type": None,
        "closed_at": None,
        "retention_purge_after": None,
        "purged_at": None,
    }
    db.stamp_new(case)
    db.threat_cases[case["id"]] = case
    domain.audit(case["id"], "CASE_CREATED",
                 f"Threat case created via {reporter_channel}", _user_id, _role)
    return success_object(db.public(case), 201)


@bp.route("/threat-cases", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_cases(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.threat_cases.values()))
    items = apply_filters(items, ["school_id", "status", "risk_level"])
    page, total = paginate(items, limit, offset)
    return success_list([db.public(c) for c in page], limit, offset, total)


@bp.route("/threat-cases/<case_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_case(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    return success_object(db.public(case))


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------

@bp.route("/threat-cases/<case_id>/triage", methods=["POST"])
@require_roles("IntakeCoordinator")
def triage_case(case_id: str, _user_id: str, _role: str):
    body = get_json_body()
    triage_priority = require_enum(body, "triage_priority", TRIAGE_PRIORITIES)
    require_string_allow_empty(body, "triage_notes")

    case = domain.get_case_or_404(case_id)
    if case["status"] != "INTAKE":
        raise_err(ERR_CASE_NOT_IN_INTAKE, "Triage requires status INTAKE")

    case["status"] = "TRIAGED"
    case["triage_priority"] = triage_priority
    db.touch(case)
    domain.audit(case["id"], "CASE_TRIAGED",
                 f"Case triaged with priority {triage_priority}", _user_id, _role)

    if triage_priority == "EMERGENT":
        domain.auto_create_le_referral(case, _user_id, _role, "EMERGENT triage")

    return success_object(db.public(case))


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

@bp.route("/threat-cases/<case_id>/screening", methods=["POST"])
@require_roles("ThreatAssessor")
def screen_case(case_id: str, _user_id: str, _role: str):
    body = get_json_body()
    # Schema tier: every supplied screening factor must be a boolean.
    score, outcome = domain.compute_screening(body)

    case = domain.get_case_or_404(case_id)
    if case["status"] != "TRIAGED":
        raise_err(ERR_CASE_NOT_TRIAGED, "Screening requires status TRIAGED")

    case["screening_score"] = score
    case["screening_outcome"] = outcome
    if outcome == "SUBSTANTIVE":
        case["status"] = "UNDER_ASSESSMENT"
    else:
        case["status"] = "CLOSED_NO_THREAT"
        case["closed_at"] = db.now_logical_iso()
        school = domain.get_school_for_case(case)
        retention_days = school["retention_days"] if school else 365
        case["retention_purge_after"] = domain.retention_purge_date(db.clock(), retention_days)
    db.touch(case)
    domain.audit(case["id"], "CASE_SCREENED",
                 f"Screening recorded: score {score}, outcome {outcome}", _user_id, _role)
    return success_object(db.public(case))


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------

@bp.route("/threat-cases/<case_id>/remove", methods=["POST"])
@require_roles("TeamLead")
def remove_case(case_id: str, _user_id: str, _role: str):
    body = get_json_body()
    removal_type = require_enum(body, "removal_type", REMOVAL_TYPES)
    require_string_allow_empty(body, "removal_reason")

    case = domain.get_case_or_404(case_id)
    if case["status"] not in ("UNDER_ASSESSMENT", "PLAN_ACTIVE"):
        raise_err(ERR_CASE_NOT_REMOVABLE,
                  "Removal requires status UNDER_ASSESSMENT or PLAN_ACTIVE")

    case["status"] = "REMOVED"
    case["removal_type"] = removal_type
    db.touch(case)
    domain.audit(case["id"], "CASE_REMOVED",
                 f"Subject removed from campus ({removal_type})", _user_id, _role)
    # Deliberately no cascade: open check-ins and referrals survive removal.
    return success_object(db.public(case))


# ---------------------------------------------------------------------------
# Closure
# ---------------------------------------------------------------------------

@bp.route("/threat-cases/<case_id>/close", methods=["POST"])
@require_roles("TeamLead")
def close_case(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    if case["status"] != "PLAN_ACTIVE":
        raise_err(ERR_CASE_NOT_CLOSABLE, "Close requires status PLAN_ACTIVE")

    # Blockers, evaluated in the PRD-pinned order.
    if any(c["status"] == "MISSED" for c in domain.case_children(db.check_ins, case["id"])):
        raise_err(ERR_OPEN_CHECKINS_EXIST, "Close blocked: MISSED check-ins exist")
    if any(r["status"] == "SENT" for r in domain.case_children(db.referrals, case["id"])):
        raise_err(ERR_OPEN_REFERRALS_EXIST, "Close blocked: SENT referrals exist")
    if case["escalation_flag"]:
        raise_err(ERR_ESCALATION_UNRESOLVED, "Close blocked: escalation flag is set")

    case["status"] = "CLOSED_MANAGED"
    case["closed_at"] = db.now_logical_iso()
    school = domain.get_school_for_case(case)
    retention_days = school["retention_days"] if school else 365
    case["retention_purge_after"] = domain.retention_purge_date(db.clock(), retention_days)
    db.touch(case)

    # Cascade: every ACTIVE and DRAFT management plan -> CLOSED.
    for plan in domain.case_children(db.management_plans, case["id"]):
        if plan["status"] in ("ACTIVE", "DRAFT"):
            plan["status"] = "CLOSED"
            db.touch(plan)
    # Cascade: every SCHEDULED check-in -> CANCELLED (the only producer).
    for chk in domain.case_children(db.check_ins, case["id"]):
        if chk["status"] == "SCHEDULED":
            chk["status"] = "CANCELLED"
            db.touch(chk)

    domain.audit(case["id"], "CASE_CLOSED", "Case closed as managed", _user_id, _role)
    return success_object(db.public(case))


# ---------------------------------------------------------------------------
# Reopen
# ---------------------------------------------------------------------------

@bp.route("/threat-cases/<case_id>/reopen", methods=["POST"])
@require_roles("IntakeCoordinator")
def reopen_case(case_id: str, _user_id: str, _role: str):
    case = domain.get_case_or_404(case_id)
    if case["status"] not in ("CLOSED_NO_THREAT", "CLOSED_MANAGED"):
        raise_err(ERR_CASE_NOT_REOPENABLE,
                  "Reopen requires status CLOSED_NO_THREAT or CLOSED_MANAGED")

    case["status"] = "TRIAGED"
    case["closed_at"] = None
    case["retention_purge_after"] = None
    case["consecutive_missed_count"] = 0
    case["escalation_flag"] = False
    # triage_priority preserved.
    db.touch(case)
    domain.audit(case["id"], "CASE_REOPENED", "Case reopened on a new report",
                 _user_id, _role)
    return success_object(db.public(case))


# ---------------------------------------------------------------------------
# Case sub-resource lists (FK reverse reachability)
# ---------------------------------------------------------------------------

def _list_children(case_id: str, store: dict, filter_names: list[str]):
    domain.get_case_or_404(case_id)
    limit, offset = parse_pagination()
    items = sort_by_created_at([e for e in store.values() if e.get("case_id") == case_id])
    items = apply_filters(items, filter_names)
    page, total = paginate(items, limit, offset)
    return success_list([db.public(e) for e in page], limit, offset, total)


@bp.route("/threat-cases/<case_id>/interviews", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_case_interviews(case_id: str, _user_id: str, _role: str):
    return _list_children(case_id, db.interviews, ["status"])


@bp.route("/threat-cases/<case_id>/risk-assessments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_case_assessments(case_id: str, _user_id: str, _role: str):
    return _list_children(case_id, db.risk_assessments, ["status"])


@bp.route("/threat-cases/<case_id>/management-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_case_plans(case_id: str, _user_id: str, _role: str):
    return _list_children(case_id, db.management_plans, ["status"])


@bp.route("/threat-cases/<case_id>/referrals", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_case_referrals(case_id: str, _user_id: str, _role: str):
    return _list_children(case_id, db.referrals, ["referral_type", "status"])


@bp.route("/threat-cases/<case_id>/monitoring-check-ins", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_case_checkins(case_id: str, _user_id: str, _role: str):
    return _list_children(case_id, db.check_ins, ["status"])


@bp.route("/threat-cases/<case_id>/re-entry-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_case_reentry_plans(case_id: str, _user_id: str, _role: str):
    return _list_children(case_id, db.reentry_plans, ["status"])


# ---------------------------------------------------------------------------
# Case documents (append-only)
# ---------------------------------------------------------------------------

@bp.route("/threat-cases/<case_id>/documents", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_case_documents(case_id: str, _user_id: str, _role: str):
    domain.get_case_or_404(case_id)
    limit, offset = parse_pagination()
    items = sort_by_created_at([d for d in db.documents.values() if d.get("case_id") == case_id])
    # Sealed documents are withheld from IntakeCoordinator and ThreatAssessor.
    if _role in ("IntakeCoordinator", "ThreatAssessor"):
        items = [d for d in items if not d.get("sealed")]
    items = apply_filters(items, ["doc_type"])
    page, total = paginate(items, limit, offset)
    return success_list([db.public(d) for d in page], limit, offset, total)


@bp.route("/threat-cases/<case_id>/documents", methods=["POST"])
@require_roles("IntakeCoordinator", "ThreatAssessor", "TeamLead")
def create_case_document(case_id: str, _user_id: str, _role: str):
    body = get_json_body()
    doc_type = require_enum(body, "doc_type", DOC_TYPES)
    doc_body = require_string(body, "body")
    sealed = optional_bool(body, "sealed", False)

    case = domain.get_case_or_404(case_id)
    if case["status"] == "PURGED":
        raise_err(ERR_CASE_PURGED, "Cannot append documents to a PURGED case")

    document = {
        "case_id": case["id"],
        "doc_type": doc_type,
        "body": doc_body,
        "sealed": sealed,
        "author_user_id": _user_id,
        "purged": False,
    }
    db.stamp_new_light(document)
    db.documents[document["id"]] = document
    return success_object(db.public(document), 201)


# ---------------------------------------------------------------------------
# Audit trail (confidential: TeamLead and DistrictAdministrator only)
# ---------------------------------------------------------------------------

@bp.route("/threat-cases/<case_id>/audit-events", methods=["GET"])
@require_roles("TeamLead", "DistrictAdministrator")
def list_case_audit_events(case_id: str, _user_id: str, _role: str):
    return _list_children(case_id, db.audit_events, ["action"])
