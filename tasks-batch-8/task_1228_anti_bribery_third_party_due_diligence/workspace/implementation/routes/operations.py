"""GiftHospitalityEntry, ReDiligenceCycle, AuditExercise, TrainingAssignment routes."""

from datetime import date

from flask import Blueprint, request

import db as dbmod
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND,
    ERR_COUNTRY_SANCTIONED, ERR_EVENT_IN_PAST, ERR_GIFT_CAP_EXCEEDED,
    ERR_ENHANCED_REVIEW_REQUIRED, ERR_DUPLICATE_ACTIVE_CYCLE,
    ERR_AUDIT_NOTICE_TOO_SHORT, ERR_AUDIT_WINDOW_OVERLAP, ERR_FINDINGS_PENDING,
    ERR_UNAUTHORIZED_ROLE,
)
from middleware import require_roles, get_json_body, parse_pagination, ALL_ROLES
from response import success_object, success_list
from services.common import (
    new_id, stamp_new, touch, bump, req_str, req_int, req_bool, opt_bool, req_enum,
    req_number, parse_iso_date, number_out,
)
from services import core

bp = Blueprint("operations", __name__)


def serialize_gift(g):
    return {
        "id": g["id"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
        "third_party_id": g["third_party_id"],
        "entry_type": g["entry_type"],
        "recipient_is_government_official": g["recipient_is_government_official"],
        "value_cents": g["value_cents"],
        "fx_rate_to_usd": number_out(g["fx_rate_to_usd"]),
        "value_usd_cents": g["value_usd_cents"],
        "event_date": g["event_date"].isoformat(),
        "entry_status": g["entry_status"],
        "requires_enhanced_approval": g["requires_enhanced_approval"],
    }


def serialize_cycle(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "third_party_id": c["third_party_id"],
        "cycle_status": c["cycle_status"],
        "trigger_source": c["trigger_source"],
        "due_date": c["due_date"].isoformat(),
        "outcome": c["outcome"],
    }


def serialize_audit(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "third_party_id": a["third_party_id"],
        "audit_status": a["audit_status"],
        "notice_date": a["notice_date"].isoformat(),
        "fieldwork_start_date": a["fieldwork_start_date"].isoformat(),
        "fieldwork_end_date": a["fieldwork_end_date"].isoformat(),
        "findings_total": a["findings_total"],
        "findings_substantiated_critical": a["findings_substantiated_critical"],
    }


def serialize_training(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "assignee_user_id": t["assignee_user_id"],
        "course_code": t["course_code"],
        "due_date": t["due_date"].isoformat(),
        "training_status": t["training_status"],
    }


def _get_gift(entry_id):
    g = dbmod.DB["gift_entries"].get(entry_id)
    if g is None:
        raise_err(ERR_NOT_FOUND, "gift entry not found")
    return g


def _get_cycle(cycle_id):
    c = dbmod.DB["rediligence_cycles"].get(cycle_id)
    if c is None:
        raise_err(ERR_NOT_FOUND, "re-diligence cycle not found")
    return c


def _get_audit(audit_id):
    a = dbmod.DB["audit_exercises"].get(audit_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, "audit exercise not found")
    return a


# --- GiftHospitalityEntry ------------------------------------------------------------

@bp.post("/compliance/third-parties/<id>/gift-hospitality-entries")
def create_gift(id):
    user_id, _ = require_roles(["BusinessSponsor"])
    tp = core.get_tp(id)
    body = get_json_body()
    # state: DD_REVIEW / ENHANCED_REVIEW / APPROVED / SUSPENDED
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    core.ensure_transition(
        tp["onboarding_status"],
        {"DD_REVIEW", "ENHANCED_REVIEW", "APPROVED", "SUSPENDED"},
        "ThirdParty",
    )
    entry_type = req_enum(body, "entry_type", {"GIFT", "HOSPITALITY", "TRAVEL"})
    is_gov = req_bool(body, "recipient_is_government_official")
    value_cents = req_int(body, "value_cents")
    if value_cents <= 0:
        raise_err(ERR_VALIDATION, "value_cents must be > 0")
    fx = req_number(body, "fx_rate_to_usd")
    if fx <= 0:
        raise_err(ERR_VALIDATION, "fx_rate_to_usd must be > 0")
    event_date = parse_iso_date(req_str(body, "event_date"), "event_date")
    # sanctions safety (priority 6)
    profile = core.get_country_profile_for(tp)
    if is_gov and profile is not None and profile.get("sanctioned"):
        raise_err(ERR_COUNTRY_SANCTIONED, "government-official gift for a sanctioned-country third party")
    # temporal (priority 7)
    if event_date < dbmod.current_date():
        raise_err(ERR_EVENT_IN_PAST, "event_date is before the current date")
    usd = core.value_usd_cents_of(value_cents, fx)
    # fiscal cap (priority 10)
    prospective = 0
    if is_gov:
        prospective = core.rolling_gov_total(tp["id"], event_date) + usd
        if prospective > core.GIFT_HARD_CAP_CENTS:
            raise_err(ERR_GIFT_CAP_EXCEEDED, "prospective government-official rolling total exceeds the hard cap")
    requires_enhanced = bool(is_gov and prospective >= core.GIFT_ENHANCED_THRESHOLD_CENTS)
    rec = stamp_new({
        "id": new_id(),
        "third_party_id": tp["id"],
        "entry_type": entry_type,
        "recipient_is_government_official": is_gov,
        "value_cents": value_cents,
        "fx_rate_to_usd": fx,
        "value_usd_cents": usd,
        "event_date": event_date,
        "entry_status": "PENDING_APPROVAL",
        "requires_enhanced_approval": requires_enhanced,
    })
    dbmod.DB["gift_entries"][rec["id"]] = rec
    core.refresh_gift_aggregate(tp)
    return success_object(serialize_gift(rec), 201)


@bp.post("/compliance/gift-hospitality-entries/<entry_id>/approve")
def approve_gift(entry_id):
    require_roles(["ComplianceOfficer"])
    g = _get_gift(entry_id)
    tp = core.get_tp(g["third_party_id"])
    body = get_json_body()
    core.ensure_not_terminal(g["entry_status"], core.GIFT_TERMINAL, "GiftHospitalityEntry")
    core.ensure_transition(g["entry_status"], {"PENDING_APPROVAL"}, "GiftHospitalityEntry")
    evidence = opt_bool(body, "enhanced_review_evidence", False)
    # re-check rolling hard cap at approval time; enhanced evidence gate
    if g["recipient_is_government_official"]:
        prospective = core.rolling_gov_total(tp["id"], g["event_date"]) + g["value_usd_cents"]
        if g["requires_enhanced_approval"] and not evidence:
            raise_err(ERR_ENHANCED_REVIEW_REQUIRED, "enhanced review evidence is required")
        if prospective > core.GIFT_HARD_CAP_CENTS:
            raise_err(ERR_GIFT_CAP_EXCEEDED, "rolling government-official total would exceed the hard cap")
    else:
        if g["requires_enhanced_approval"] and not evidence:
            raise_err(ERR_ENHANCED_REVIEW_REQUIRED, "enhanced review evidence is required")
    g["entry_status"] = "APPROVED"
    touch(g)
    core.refresh_gift_aggregate(tp)
    return success_object(serialize_gift(g))


@bp.post("/compliance/gift-hospitality-entries/<entry_id>/reject")
def reject_gift(entry_id):
    require_roles(["ComplianceOfficer"])
    g = _get_gift(entry_id)
    core.ensure_not_terminal(g["entry_status"], core.GIFT_TERMINAL, "GiftHospitalityEntry")
    core.ensure_transition(g["entry_status"], {"PENDING_APPROVAL"}, "GiftHospitalityEntry")
    g["entry_status"] = "REJECTED"
    touch(g)
    return success_object(serialize_gift(g))


@bp.post("/compliance/gift-hospitality-entries/<entry_id>/void")
def void_gift(entry_id):
    require_roles(["ComplianceOfficer"])
    g = _get_gift(entry_id)
    tp = core.get_tp(g["third_party_id"])
    core.ensure_not_terminal(g["entry_status"], core.GIFT_TERMINAL, "GiftHospitalityEntry")
    core.ensure_transition(g["entry_status"], {"APPROVED"}, "GiftHospitalityEntry")
    g["entry_status"] = "VOIDED"
    touch(g)
    core.refresh_gift_aggregate(tp)
    return success_object(serialize_gift(g))


@bp.get("/compliance/third-parties/<id>/gift-hospitality-entries")
def list_gifts(id):
    require_roles(ALL_ROLES)
    core.get_tp(id)
    limit, offset = parse_pagination()
    status_f = request.args.get("entry_status")
    rows = core.gifts_of(id)
    if status_f is not None:
        rows = [r for r in rows if r["entry_status"] == status_f]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_gift(r) for r in page], total, limit, offset)


# --- ReDiligenceCycle -----------------------------------------------------------------

@bp.post("/compliance/third-parties/<id>/rediligence-cycles")
def create_cycle_route(id):
    require_roles(["ComplianceOfficer"])
    tp = core.get_tp(id)
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    if core.has_active_cycle(tp["id"]):
        raise_err(ERR_DUPLICATE_ACTIVE_CYCLE, "another non-completed cycle exists for the third party")
    today = dbmod.current_date()
    due = date.fromordinal(today.toordinal() + core.MANUAL_CYCLE_DAYS)
    rec = core.create_cycle(tp, "MANUAL", due)
    return success_object(serialize_cycle(rec), 201)


@bp.post("/compliance/rediligence-cycles/<cycle_id>/start")
def start_cycle(cycle_id):
    require_roles(["ComplianceOfficer"])
    c = _get_cycle(cycle_id)
    core.ensure_not_terminal(c["cycle_status"], core.CYCLE_TERMINAL, "ReDiligenceCycle")
    core.ensure_transition(c["cycle_status"], {"SCHEDULED"}, "ReDiligenceCycle")
    c["cycle_status"] = "IN_PROGRESS"
    touch(c)
    return success_object(serialize_cycle(c))


@bp.post("/compliance/rediligence-cycles/<cycle_id>/complete")
def complete_cycle(cycle_id):
    require_roles(["ComplianceOfficer"])
    c = _get_cycle(cycle_id)
    body = get_json_body()
    outcome = req_enum(body, "outcome", {"REAFFIRM", "DOWNGRADE", "TERMINATE"})
    core.ensure_not_terminal(c["cycle_status"], core.CYCLE_TERMINAL, "ReDiligenceCycle")
    core.ensure_transition(c["cycle_status"], {"IN_PROGRESS"}, "ReDiligenceCycle")
    tp = core.get_tp(c["third_party_id"])
    c["cycle_status"] = "COMPLETED"
    c["outcome"] = outcome
    touch(c)

    today = dbmod.current_date()
    if outcome == "REAFFIRM":
        interval = core.tier_interval_days(tp["risk_tier"] or "LOW")
        expires = date.fromordinal(today.toordinal() + interval)
        tp["diligence_expires_at"] = expires
        bump(tp)
        core.create_cycle(tp, "SCHEDULED", expires)
    elif outcome == "DOWNGRADE":
        current_tier = tp["risk_tier"] or "LOW"
        idx = core.TIER_LADDER.index(current_tier)
        new_tier = core.TIER_LADDER[min(idx + 1, len(core.TIER_LADDER) - 1)]
        tp["risk_tier"] = new_tier
        interval = core.tier_interval_days(new_tier)
        expires = date.fromordinal(today.toordinal() + interval)
        tp["diligence_expires_at"] = expires
        bump(tp)
        successor_due = date.fromordinal(today.toordinal() + core.MANUAL_CYCLE_DAYS)
        core.create_cycle(tp, "SCHEDULED", successor_due)
    else:  # TERMINATE
        core.terminate_third_party(tp)
    return success_object(serialize_cycle(c))


@bp.get("/compliance/third-parties/<id>/rediligence-cycles")
def list_cycles(id):
    require_roles(ALL_ROLES)
    core.get_tp(id)
    limit, offset = parse_pagination()
    status_f = request.args.get("cycle_status")
    rows = core.cycles_of(id)
    if status_f is not None:
        rows = [r for r in rows if r["cycle_status"] == status_f]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_cycle(r) for r in page], total, limit, offset)


# --- AuditExercise ----------------------------------------------------------------------

@bp.post("/compliance/third-parties/<id>/audit-exercises")
def create_audit(id):
    require_roles(["AuditLead"])
    tp = core.get_tp(id)
    body = get_json_body()
    core.ensure_not_terminal(tp["onboarding_status"], core.TP_TERMINAL, "ThirdParty")
    if tp["onboarding_status"] != "APPROVED":
        from errors import ERR_THIRD_PARTY_NOT_APPROVED
        raise_err(ERR_THIRD_PARTY_NOT_APPROVED, "third party is not APPROVED")
    start = parse_iso_date(req_str(body, "fieldwork_start_date"), "fieldwork_start_date")
    end = parse_iso_date(req_str(body, "fieldwork_end_date"), "fieldwork_end_date")
    if end <= start:
        raise_err(ERR_VALIDATION, "fieldwork_end_date must be later than fieldwork_start_date")
    today = dbmod.current_date()
    earliest = date.fromordinal(today.toordinal() + core.AUDIT_NOTICE_DAYS)
    if start < earliest:
        raise_err(ERR_AUDIT_NOTICE_TOO_SHORT, "fieldwork start is before notice_date + 10 days")
    # half-open overlap: [start, end) vs existing [s, e): conflict iff start < e AND s < end
    for a in dbmod.DB["audit_exercises"].values():
        if a["third_party_id"] == tp["id"] and a["audit_status"] in ("NOTICED", "IN_FIELDWORK"):
            if start < a["fieldwork_end_date"] and a["fieldwork_start_date"] < end:
                raise_err(ERR_AUDIT_WINDOW_OVERLAP, "fieldwork window overlaps an existing audit window")
    rec = stamp_new({
        "id": new_id(),
        "third_party_id": tp["id"],
        "audit_status": "NOTICED",
        "notice_date": today,
        "fieldwork_start_date": start,
        "fieldwork_end_date": end,
        "findings_total": None,
        "findings_substantiated_critical": None,
    })
    dbmod.DB["audit_exercises"][rec["id"]] = rec
    return success_object(serialize_audit(rec), 201)


@bp.post("/compliance/audit-exercises/<audit_id>/begin-fieldwork")
def begin_fieldwork(audit_id):
    require_roles(["AuditLead"])
    a = _get_audit(audit_id)
    core.ensure_not_terminal(a["audit_status"], core.AUDIT_TERMINAL, "AuditExercise")
    core.ensure_transition(a["audit_status"], {"NOTICED"}, "AuditExercise")
    today = dbmod.current_date()
    earliest = date.fromordinal(a["notice_date"].toordinal() + core.AUDIT_NOTICE_DAYS)
    if today < earliest:
        raise_err(ERR_AUDIT_NOTICE_TOO_SHORT, "current date is before notice_date + 10 days")
    a["audit_status"] = "IN_FIELDWORK"
    touch(a)
    return success_object(serialize_audit(a))


@bp.post("/compliance/audit-exercises/<audit_id>/issue-findings")
def issue_findings(audit_id):
    require_roles(["AuditLead"])
    a = _get_audit(audit_id)
    body = get_json_body()
    core.ensure_not_terminal(a["audit_status"], core.AUDIT_TERMINAL, "AuditExercise")
    core.ensure_transition(a["audit_status"], {"IN_FIELDWORK"}, "AuditExercise")
    total = req_int(body, "findings_total")
    if total < 0:
        raise_err(ERR_VALIDATION, "findings_total must be >= 0")
    critical = req_int(body, "findings_substantiated_critical")
    if critical < 0 or critical > total:
        raise_err(ERR_VALIDATION, "findings_substantiated_critical must be between 0 and findings_total")
    a["findings_total"] = total
    a["findings_substantiated_critical"] = critical
    a["audit_status"] = "FINDINGS_ISSUED"
    touch(a)
    if critical >= 1:
        tp = core.get_tp(a["third_party_id"])
        core.create_red_flag(
            tp["id"], "AUDIT", a["id"], "CRITICAL",
            f"Audit findings: {critical} substantiated critical",
            escalated_by_for_auto=None,
        )
    return success_object(serialize_audit(a))


@bp.post("/compliance/audit-exercises/<audit_id>/close")
def close_audit(audit_id):
    require_roles(["AuditLead"])
    a = _get_audit(audit_id)
    core.ensure_not_terminal(a["audit_status"], core.AUDIT_TERMINAL, "AuditExercise")
    core.ensure_transition(a["audit_status"], {"FINDINGS_ISSUED"}, "AuditExercise")
    for f in core.flags_of(a["third_party_id"]):
        if f["source_type"] == "AUDIT" and f["source_ref_id"] == a["id"]:
            if f["flag_status"] not in core.FLAG_TERMINAL:
                raise_err(ERR_FINDINGS_PENDING, "a spawned red flag is not yet resolved")
    a["audit_status"] = "CLOSED"
    touch(a)
    return success_object(serialize_audit(a))


@bp.get("/compliance/third-parties/<id>/audit-exercises")
def list_audits(id):
    require_roles(ALL_ROLES)
    core.get_tp(id)
    limit, offset = parse_pagination()
    status_f = request.args.get("audit_status")
    rows = [a for a in dbmod.DB["audit_exercises"].values() if a["third_party_id"] == id]
    rows.sort(key=lambda a: a["created_at"])
    if status_f is not None:
        rows = [r for r in rows if r["audit_status"] == status_f]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_audit(r) for r in page], total, limit, offset)


# --- TrainingAssignment ------------------------------------------------------------------

@bp.post("/compliance/training-assignments")
def create_training():
    require_roles(["ComplianceAdmin"])
    body = get_json_body()
    assignee = req_str(body, "assignee_user_id")
    course = req_str(body, "course_code")
    due = parse_iso_date(req_str(body, "due_date"), "due_date")
    rec = stamp_new({
        "id": new_id(),
        "assignee_user_id": assignee,
        "course_code": course,
        "due_date": due,
        "training_status": "ASSIGNED",
    })
    dbmod.DB["training_assignments"][rec["id"]] = rec
    return success_object(serialize_training(rec), 201)


@bp.post("/compliance/training-assignments/<assignment_id>/complete")
def complete_training(assignment_id):
    user_id, role = require_roles(["BusinessSponsor", "ComplianceAdmin"])
    t = dbmod.DB["training_assignments"].get(assignment_id)
    if t is None:
        raise_err(ERR_NOT_FOUND, "training assignment not found")
    core.ensure_not_terminal(t["training_status"], core.TRAINING_TERMINAL, "TrainingAssignment")
    core.ensure_transition(t["training_status"], {"ASSIGNED", "OVERDUE"}, "TrainingAssignment")
    if role == "BusinessSponsor" and t["assignee_user_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "a sponsor may only complete its own assignments")
    t["training_status"] = "COMPLETED"
    touch(t)
    return success_object(serialize_training(t))


@bp.get("/compliance/training-assignments")
def list_training():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    assignee_f = request.args.get("assignee_user_id")
    status_f = request.args.get("training_status")
    rows = list(dbmod.DB["training_assignments"].values())
    if assignee_f is not None:
        rows = [r for r in rows if r["assignee_user_id"] == assignee_f]
    if status_f is not None:
        rows = [r for r in rows if r["training_status"] == status_f]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize_training(r) for r in page], total, limit, offset)
