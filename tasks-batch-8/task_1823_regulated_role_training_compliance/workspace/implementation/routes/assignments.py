"""Assignments, extensions, completion records, and escalation notices."""
from datetime import timedelta

from flask import Blueprint, request, g

from db import new_entity, now, store, touch
from errors import ApiError, bad_request, not_found
from middleware import require_any_authenticated, require_roles
from response import (get_body, list_response, pub, req_decimal, req_enum,
                      req_int, req_str, success)
from services import (EVIDENCE_TIERS, NON_TERMINAL, cancel_assignment,
                      deadline_stage, recompute_posture, recompute_verified_count)
from util import DAY

bp = Blueprint("assignments", __name__)

PROGRESS_STATUSES = ("ASSIGNED", "IN_PROGRESS", "SUBMITTED", "VERIFIED_COMPLETED",
                     "FAILED", "CANCELLED", "EXPIRED")
DEADLINE_STATUSES = ("ON_TRACK", "DUE_SOON", "OVERDUE", "ESCALATED", "FROZEN")


def get_assignment(aid):
    a = store.assignments.get(aid)
    if a is None:
        raise not_found("assignment not found")
    return a


def get_completion(cid):
    c = store.completions.get(cid)
    if c is None:
        raise not_found("completion not found")
    return c


def get_notice(nid):
    n = store.notices.get(nid)
    if n is None:
        raise not_found("escalation notice not found")
    return n


def manager_gate(assignment):
    """P3 for Manager-acted resources: self-service forbidden, direct reports only.

    Self check precedes the direct-manager check so a manager acting on their own
    record is reported as ERR_SELF_ACTION_FORBIDDEN (segregation of duties)."""
    caller = g.user_id
    emp = store.employees.get(assignment["employee_id"])
    if caller == assignment["employee_id"]:
        raise ApiError("ERR_SELF_ACTION_FORBIDDEN",
                       "a manager may not act on their own record")
    if emp is None or emp["manager_id"] != caller:
        raise ApiError("ERR_OWNERSHIP_MISMATCH",
                       "caller is not the direct manager of this employee")
    return emp


def recompute_deadline_after_relief(assignment, employee):
    """Extension grant/revoke recompute: new stage, no notices; posture may unblock."""
    stage = deadline_stage(assignment, employee)
    if stage != assignment["deadline_status"]:
        assignment["deadline_status"] = stage
    recompute_posture(employee)


# ------------------------------------------------------------------ assignment

@bp.get("/assignments")
def list_assignments():
    require_any_authenticated()
    items = list(store.assignments.values())
    f_emp = request.args.get("employee_id")
    f_req = request.args.get("role_requirement_id")
    f_curr = request.args.get("curriculum_id")
    f_src = request.args.get("source_role_change_id")
    f_prog = request.args.get("progress_status")
    f_dl = request.args.get("deadline_status")
    if f_emp is not None:
        items = [a for a in items if a["employee_id"] == f_emp]
    if f_req is not None:
        items = [a for a in items if a["role_requirement_id"] == f_req]
    if f_curr is not None:
        items = [a for a in items if a["curriculum_id"] == f_curr]
    if f_src is not None:
        items = [a for a in items if a["source_role_change_id"] == f_src]
    if f_prog is not None:
        items = [a for a in items if a["progress_status"] == f_prog]
    if f_dl is not None:
        items = [a for a in items if a["deadline_status"] == f_dl]
    items.sort(key=lambda a: a["created_at"])
    return list_response(items)


@bp.get("/assignments/<aid>")
def read_assignment(aid):
    require_any_authenticated()
    return success(pub(get_assignment(aid)))


@bp.post("/assignments/<aid>/start")
def start_assignment(aid):
    uid, _ = require_roles("Employee")
    a = get_assignment(aid)
    # P3 ownership: employees act only on their own assignments.
    if a["employee_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "caller does not own this assignment")
    # P7 state gates, in scaffold precondition order.
    if a["progress_status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", "assignment is not in ASSIGNED")
    emp = store.employees.get(a["employee_id"])
    if emp is not None and emp["status"] == "TERMINATED":
        raise ApiError("ERR_EMPLOYEE_TERMINATED", "employee is TERMINATED")
    a["progress_status"] = "IN_PROGRESS"
    touch(a)
    return success(pub(a))


@bp.post("/assignments/<aid>/extensions")
def grant_extension(aid):
    uid, _ = require_roles("Manager")
    a = get_assignment(aid)
    emp = manager_gate(a)  # P3
    body = get_body()  # P4 schema
    extend_by = req_int(body, "extend_by_days")
    reason = req_str(body, "reason")
    expected = req_int(body, "expected_assignment_version")
    # P6 OCC
    if expected != a["version"]:
        raise ApiError("ERR_STALE_VERSION", "assignment version is stale")
    # P7 state
    if a["progress_status"] not in ("ASSIGNED", "IN_PROGRESS"):
        raise ApiError("ERR_ASSIGNMENT_NOT_EXTENDABLE",
                       "only ASSIGNED or IN_PROGRESS assignments can be extended")
    # P9 limits: single active extension, then 1..30 days.
    if a["active_extension_days"] > 0:
        raise ApiError("ERR_EXTENSION_LIMIT_ACTIVE", "an active extension already exists")
    if extend_by < 1 or extend_by > 30:
        raise ApiError("ERR_EXTENSION_DAYS_INVALID", "extend_by_days must be within 1..30")
    a["active_extension_days"] = extend_by
    a["due_at"] = a["base_due_at"] + timedelta(days=extend_by)
    a["_extension_reason"] = reason
    touch(a)
    recompute_deadline_after_relief(a, emp)
    return success(pub(a))


@bp.post("/assignments/<aid>/extensions/revoke")
def revoke_extension(aid):
    uid, _ = require_roles("Manager")
    a = get_assignment(aid)
    emp = manager_gate(a)  # P3
    body = get_body()  # P4
    expected = req_int(body, "expected_assignment_version")
    # P6 OCC
    if expected != a["version"]:
        raise ApiError("ERR_STALE_VERSION", "assignment version is stale")
    # Revoke requires an active extension.
    if a["active_extension_days"] <= 0:
        raise ApiError("ERR_NO_ACTIVE_EXTENSION", "no active extension to revoke")
    a["due_at"] = a["due_at"] - timedelta(days=a["active_extension_days"])
    a["active_extension_days"] = 0
    a["_extension_reason"] = None
    touch(a)
    recompute_deadline_after_relief(a, emp)
    return success(pub(a))


@bp.post("/assignments/<aid>/cancel")
def cancel(aid):
    require_roles("ComplianceAdmin")
    a = get_assignment(aid)
    if a["progress_status"] not in NON_TERMINAL:
        raise ApiError("ERR_INVALID_STATE", "only a non-terminal assignment can be cancelled")
    cancel_assignment(a)
    emp = store.employees.get(a["employee_id"])
    if emp is not None:
        recompute_posture(emp)
    return success(pub(a))


# ----------------------------------------------------------------- completions

@bp.post("/assignments/<aid>/completions")
def submit_completion(aid):
    uid, _ = require_roles("Employee")
    a = get_assignment(aid)
    # P3 ownership
    if a["employee_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "caller does not own this assignment")
    # P4 schema
    body = get_body()
    score = req_decimal(body, "score_pct", 0, 100, 2)
    evidence_type = req_enum(body, "evidence_type", tuple(EVIDENCE_TIERS.keys()))
    evidence_uri = None
    if "evidence_uri" in body and body["evidence_uri"] is not None:
        evidence_uri = body["evidence_uri"]
        if not isinstance(evidence_uri, str):
            raise bad_request("evidence_uri must be a string")
    # P7 state gates: submittable, then not frozen.
    if a["progress_status"] not in ("ASSIGNED", "IN_PROGRESS"):
        raise ApiError("ERR_ASSIGNMENT_NOT_SUBMITTABLE",
                       "progress_status is not ASSIGNED or IN_PROGRESS")
    if a["deadline_status"] == "FROZEN":
        raise ApiError("ERR_ASSIGNMENT_FROZEN", "assignment is FROZEN (employee on leave)")
    # P11 safety gates, in scaffold order: score, evidence tier, evidence uri.
    curr = store.curricula[a["curriculum_id"]]
    if score < curr["passing_score_pct"]:
        raise ApiError("ERR_SCORE_BELOW_PASSING", "score is below the passing threshold")
    if EVIDENCE_TIERS[evidence_type] < EVIDENCE_TIERS[curr["evidence_requirement"]]:
        raise ApiError("ERR_EVIDENCE_TYPE_INSUFFICIENT",
                       "evidence tier below the curriculum requirement")
    if evidence_type != "NONE" and not evidence_uri:
        raise ApiError("ERR_EVIDENCE_URI_MISSING",
                       "evidence_uri is required when evidence_type is not NONE")
    t = now()
    attempt_no = sum(1 for c in store.completions.values()
                     if c["assignment_id"] == aid) + 1
    c = new_entity()
    c.update({
        "assignment_id": aid,
        "attempt_no": attempt_no,
        "score_pct": score,
        "evidence_type": evidence_type,
        "evidence_uri": evidence_uri,
        "submitted_at": t,
        # Both booleans are computed at the submission moment and immutable thereafter.
        "is_late": t > a["due_at"],
        "passed": score >= curr["passing_score_pct"],
        "review_status": "PENDING_REVIEW",
        "reviewed_by": None,
        "review_note": None,
    })
    store.completions[c["id"]] = c
    a["progress_status"] = "SUBMITTED"
    touch(a)
    return success(pub(c), "object", 201)


@bp.get("/assignments/<aid>/completions")
def list_completions(aid):
    require_any_authenticated()
    get_assignment(aid)
    items = [c for c in store.completions.values() if c["assignment_id"] == aid]
    items.sort(key=lambda c: c["attempt_no"])  # domain ordering: attempt_no ASC
    return list_response(items)


@bp.post("/completions/<cid>/accept")
def accept_completion(cid):
    uid, _ = require_roles("ComplianceAdmin")
    body = get_body()
    note = body.get("review_note")
    if note is not None and not isinstance(note, str):
        raise bad_request("review_note must be a string")
    c = get_completion(cid)
    if c["review_status"] != "PENDING_REVIEW":
        raise ApiError("ERR_COMPLETION_NOT_REVIEWABLE", "completion is not PENDING_REVIEW")
    a = store.assignments[c["assignment_id"]]
    curr = store.curricula[a["curriculum_id"]]
    t = now()
    c["review_status"] = "ACCEPTED"
    c["reviewed_by"] = uid
    if note is not None:
        c["review_note"] = note
    touch(c)
    a["progress_status"] = "VERIFIED_COMPLETED"
    a["completed_at"] = t
    req = store.requirements.get(a["role_requirement_id"])
    if req is not None and req["recurrence"] == "VALIDITY_CYCLE":
        # validity_months read at accept time; calendar months, day clamped to month end.
        from util import add_months
        a["expires_at"] = add_months(t, curr["validity_months"])
    else:
        a["expires_at"] = None
    touch(a)
    emp = store.employees.get(a["employee_id"])
    if emp is not None:
        recompute_verified_count(emp)
        recompute_posture(emp)  # a later verified completion cures a FAILED-hard block
    return success(pub(c))


@bp.post("/completions/<cid>/reject")
def reject_completion(cid):
    uid, _ = require_roles("ComplianceAdmin")
    body = get_body()
    note = req_str(body, "review_note")
    c = get_completion(cid)
    if c["review_status"] != "PENDING_REVIEW":
        raise ApiError("ERR_COMPLETION_NOT_REVIEWABLE", "completion is not PENDING_REVIEW")
    a = store.assignments[c["assignment_id"]]
    curr = store.curricula[a["curriculum_id"]]
    c["review_status"] = "REJECTED"
    c["reviewed_by"] = uid
    c["review_note"] = note
    touch(c)
    a["attempts_used"] += 1
    if a["attempts_used"] >= curr["max_attempts"]:
        a["progress_status"] = "FAILED"  # attempt ceiling reached: fails outright
    else:
        a["progress_status"] = "IN_PROGRESS"  # revision loop
    touch(a)
    emp = store.employees.get(a["employee_id"])
    if emp is not None:
        recompute_posture(emp)  # HARD failure blocks; PENDING attestations -> BLOCKED
    return success(pub(c))


@bp.post("/completions/<cid>/void")
def void_completion(cid):
    uid, _ = require_roles("ComplianceAdmin")
    body = get_body()
    reason = req_str(body, "reason")
    c = get_completion(cid)
    if c["review_status"] != "ACCEPTED":
        raise ApiError("ERR_COMPLETION_NOT_VOIDABLE", "only an ACCEPTED completion can be voided")
    a = store.assignments[c["assignment_id"]]
    c["review_status"] = "VOIDED"
    c["reviewed_by"] = uid
    c["review_note"] = reason
    touch(c)
    if a["progress_status"] == "VERIFIED_COMPLETED":
        a["progress_status"] = "IN_PROGRESS"
        a["completed_at"] = None
        a["expires_at"] = None
        touch(a)
    emp = store.employees.get(a["employee_id"])
    if emp is not None:
        recompute_verified_count(emp)
        recompute_posture(emp)
    return success(pub(c))


# ----------------------------------------------------------------- escalations

@bp.get("/assignments/<aid>/escalations")
def list_assignment_escalations(aid):
    require_any_authenticated()
    get_assignment(aid)
    items = [n for n in store.notices.values() if n["assignment_id"] == aid]
    items.sort(key=lambda n: (n["triggered_at"], n["level"]))  # domain ordering
    return list_response(items)


@bp.get("/employees/<eid>/escalations")
def list_employee_escalations(eid):
    require_any_authenticated()
    if eid not in store.employees:
        raise not_found("employee not found")
    items = [n for n in store.notices.values() if n["recipient_employee_id"] == eid]
    items.sort(key=lambda n: n["created_at"])
    return list_response(items)


@bp.post("/escalations/<nid>/acknowledge")
def acknowledge_notice(nid):
    uid, role = require_roles("Manager", "ComplianceAdmin")
    n = get_notice(nid)
    # Addressee checks (before the OPEN state check; ownership is priority 3).
    if n["recipient_employee_id"] is None:
        # Level-3 notice addressed to the compliance office: admin only.
        if role != "ComplianceAdmin":
            raise ApiError("ERR_FORBIDDEN_ROLE",
                           "level-3 notices are acknowledged by ComplianceAdmin only")
    else:
        if role != "Manager" or uid != n["recipient_employee_id"]:
            raise ApiError("ERR_OWNERSHIP_MISMATCH",
                           "only the addressed manager may acknowledge this notice")
    if n["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "notice is not OPEN")
    n["status"] = "ACKNOWLEDGED"
    touch(n)
    return success(pub(n))
