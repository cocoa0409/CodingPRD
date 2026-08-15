"""Issues, submit-validation, remediation plans, milestones (PRD §3.5-§3.7)."""
from flask import Blueprint, request

from calc import detect_repeat, maybe_advance_exam, recompute_exam
from db import db, new_id, next_seq, now, touch
from errors import (ApiError, ERR_ALREADY_TERMINAL,
                    ERR_CERTIFICATION_INSUFFICIENT, ERR_DUPLICATE_KEY,
                    ERR_INVALID_REFERENCE, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_ISSUE_NOT_CLOSABLE,
                    ERR_NO_ACTIVE_PLAN, ERR_STALE_VERSION)
from middleware import auth, require_role, reviewer_gate
from response import ok_obj
from serializers import ser_closure, ser_issue, ser_milestone, ser_plan
from util import (enum_filter, get_or_404, list_page, payload, req_dt,
                  req_enum, req_str)

bp = Blueprint("remediation", __name__)

RAM = "RegulatoryAffairsManager"
OWNER = "RemediationOwner"
REVIEWER = "ComplianceReviewer"
SEVERITIES = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
CLASSIFICATIONS = ["MRA", "MRIA"]
ISSUE_STATUSES = ["OPEN", "REMEDIATION_PLANNED", "IN_PROGRESS",
                  "VALIDATION_SUBMITTED", "CLOSED", "OVERDUE"]
PLAN_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "ACTIVE", "COMPLETE",
                 "REJECTED", "SUPERSEDED"]
MILESTONE_STATUSES = ["PENDING", "IN_PROGRESS", "COMPLETE", "OVERDUE"]


def _occ(payload_dict, field, current_version):
    """Optimistic concurrency check (priority 7). Field is non-optional."""
    v = payload_dict.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s is required" % field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an integer" % field)
    if v != current_version:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "%s does not match current version" % field)


def _active_plan(issue_id):
    for p in db.plans.values():
        if p["issue_id"] == issue_id and p["status"] == "ACTIVE":
            return p
    return None


def _operative_plan(issue_id):
    """The plan governing the issue's remediation: the ACTIVE plan, else the
    highest-version COMPLETE plan (the one whose milestones were executed)."""
    active = _active_plan(issue_id)
    if active is not None:
        return active
    completed = [p for p in db.plans.values()
                 if p["issue_id"] == issue_id and p["status"] == "COMPLETE"]
    if completed:
        return max(completed, key=lambda p: p["plan_version"])
    return None


def _cert_gate(uid, issue):
    """MRIA adjudication requires certification_level L3 (priority 6)."""
    if issue["classification"] == "MRIA":
        rev = db.reviewers.get(uid)
        if rev is None or rev["certification_level"] != "L3":
            raise ApiError(ERR_CERTIFICATION_INSUFFICIENT, 422,
                           "MRIA requires an L3 reviewer")


# ------------------------------------------------------------------ issues
@bp.post("/regulatory-exams/examinations/<eid>/issues")
def create_issue(eid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    exam = get_or_404(db.exams, eid)
    p = payload()
    # (7) optimistic concurrency on the examination
    _occ(p, "expected_examination_version", exam["version"])
    # (11) issue_ref unique within the examination
    ref = p.get("issue_ref")
    if isinstance(ref, str):
        for i in db.issues.values():
            if i["examination_id"] == eid and i["issue_ref"] == ref:
                raise ApiError(ERR_DUPLICATE_KEY, 409,
                               "issue_ref already exists on this examination")
    # (12) referential: informal_finding_id must belong to this examination
    fid = p.get("informal_finding_id")
    finding = None
    if fid is not None:
        if not isinstance(fid, str):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "informal_finding_id must be a string")
        finding = db.findings.get(fid)
        meeting = db.meetings.get(finding["examiner_meeting_id"]) if finding else None
        if finding is None or meeting is None or meeting["examination_id"] != eid:
            raise ApiError(ERR_INVALID_REFERENCE, 422,
                           "informal_finding_id not found in this examination")
    # (14) shape
    ref = req_str(p, "issue_ref")
    cls = req_enum(p, "classification", CLASSIFICATIONS)
    sev = req_enum(p, "severity", SEVERITIES)
    due = req_dt(p, "due_date")
    rec = {"id": new_id(), "examination_id": eid,
           "informal_finding_id": finding["id"] if finding else None,
           "issue_ref": ref, "classification": cls, "severity": sev,
           "is_repeat_finding": detect_repeat(ref, exam, now()),
           "due_date": due, "status": "OPEN", "escalated_to_board": False,
           "closed_at": None,
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.issues[rec["id"]] = rec
    if finding is not None:
        finding["promoted_issue_id"] = rec["id"]
        touch(finding)
    recompute_exam(exam)
    touch(exam)
    return ok_obj(ser_issue(rec), 201)


@bp.get("/regulatory-exams/examinations/<eid>/issues")
def list_issues_for_exam(eid):
    auth()
    get_or_404(db.exams, eid)
    status = enum_filter("status", ISSUE_STATUSES)
    cls = enum_filter("classification", CLASSIFICATIONS)
    rows = [i for i in db.issues.values()
            if i["examination_id"] == eid
            and (status is None or i["status"] == status)
            and (cls is None or i["classification"] == cls)]
    return list_page(rows, ser_issue)


@bp.get("/regulatory-exams/issues")
def list_issues_portfolio():
    auth()
    fid = request.args.get("informal_finding_id")
    rows = [i for i in db.issues.values()
            if fid is None or i["informal_finding_id"] == fid]
    return list_page(rows, ser_issue)


@bp.get("/regulatory-exams/issues/<iid>")
def get_issue(iid):
    auth()
    return ok_obj(ser_issue(get_or_404(db.issues, iid)))


@bp.post("/regulatory-exams/issues/<iid>/submit-validation")
def submit_validation(iid):
    auth_pair = auth()
    require_role(auth_pair[1], OWNER)
    issue = get_or_404(db.issues, iid)
    if issue["status"] == "CLOSED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "issue is CLOSED")
    if issue["status"] != "IN_PROGRESS":
        raise ApiError(ERR_ISSUE_NOT_CLOSABLE, 422,
                       "issue is not IN_PROGRESS")
    p = payload()
    evid = p.get("validation_evidence_id")
    # (12) referential
    if evid is not None:
        if not isinstance(evid, str):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "validation_evidence_id must be a string")
        if evid not in db.evidences:
            raise ApiError(ERR_INVALID_REFERENCE, 422,
                           "validation_evidence_id does not exist")
    # closable: evidence SUFFICIENT on this same issue
    ev = db.evidences.get(evid) if isinstance(evid, str) else None
    if ev is None or ev["issue_id"] != iid or ev["review_status"] != "SUFFICIENT":
        if evid is None:
            pass  # missing field handled at request-shape below
        else:
            raise ApiError(ERR_ISSUE_NOT_CLOSABLE, 422,
                           "evidence is not SUFFICIENT on this issue")
    # closable: every milestone of the operative plan COMPLETE
    plan = _operative_plan(iid)
    mss = [m for m in db.milestones.values()
           if plan is not None and m["remediation_plan_id"] == plan["id"]]
    if plan is None or len(mss) == 0 \
            or any(m["status"] != "COMPLETE" for m in mss):
        raise ApiError(ERR_ISSUE_NOT_CLOSABLE, 422,
                       "active plan milestones are not all COMPLETE")
    # (14) shape
    if evid is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "validation_evidence_id is required")
    narrative = req_str(p, "closure_narrative")
    round_n = 1 + sum(1 for c in db.closures.values() if c["issue_id"] == iid)
    cr = {"id": new_id(), "issue_id": iid, "request_round": round_n,
          "closure_narrative": narrative, "validation_evidence_id": evid,
          "status": "PENDING", "reviewed_by_user_id": None,
          "rejection_reason": None,
          "created_at": now(), "updated_at": now(), "version": 1,
          "_seq": next_seq()}
    db.closures[cr["id"]] = cr
    issue["status"] = "VALIDATION_SUBMITTED"
    touch(issue)
    exam = db.exams[issue["examination_id"]]
    touch(exam)
    maybe_advance_exam(exam)
    return ok_obj(ser_closure(cr), 201)


# ------------------------------------------------------------------ plans
@bp.post("/regulatory-exams/issues/<iid>/remediation-plans")
def create_plan(iid):
    auth_pair = auth()
    require_role(auth_pair[1], OWNER)
    issue = get_or_404(db.issues, iid)
    p = payload()
    # (12) referential: owner must be an existing, active BankOfficer
    owner = p.get("owner_user_id")
    if owner is not None:
        if not isinstance(owner, str):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "owner_user_id must be a string")
        officer = db.officers.get(owner)
        if officer is None:
            raise ApiError(ERR_INVALID_REFERENCE, 422,
                           "owner_user_id does not reference a BankOfficer")
        if not officer.get("active", True):
            raise ApiError(ERR_INVALID_REFERENCE, 422,
                           "owner_user_id references an inactive officer")
    # (14) shape
    owner = req_str(p, "owner_user_id")
    root = req_str(p, "root_cause_narrative")
    corr = req_str(p, "corrective_action_summary")
    pv = 1 + sum(1 for pl in db.plans.values() if pl["issue_id"] == iid)
    rec = {"id": new_id(), "issue_id": iid, "plan_version": pv,
           "owner_user_id": owner, "root_cause_narrative": root,
           "corrective_action_summary": corr, "status": "DRAFT",
           "submitted_at": None, "approved_at": None,
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.plans[rec["id"]] = rec
    touch(issue)
    return ok_obj(ser_plan(rec), 201)


@bp.get("/regulatory-exams/issues/<iid>/remediation-plans")
def list_plans_for_issue(iid):
    auth()
    get_or_404(db.issues, iid)
    status = enum_filter("status", PLAN_STATUSES)
    rows = [p for p in db.plans.values()
            if p["issue_id"] == iid and (status is None or p["status"] == status)]
    return list_page(rows, ser_plan)


@bp.get("/regulatory-exams/remediation-plans")
def list_plans_portfolio():
    auth()
    owner = request.args.get("owner_user_id")
    rows = [p for p in db.plans.values()
            if owner is None or p["owner_user_id"] == owner]
    return list_page(rows, ser_plan)


@bp.get("/regulatory-exams/remediation-plans/<pid>")
def get_plan(pid):
    auth()
    return ok_obj(ser_plan(get_or_404(db.plans, pid)))


def _plan_for_action(pid):
    plan = get_or_404(db.plans, pid)
    if plan["status"] in ("COMPLETE", "SUPERSEDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "plan is in a terminal state")
    return plan


@bp.post("/regulatory-exams/remediation-plans/<pid>/submit")
def submit_plan(pid):
    auth_pair = auth()
    require_role(auth_pair[1], OWNER)
    plan = _plan_for_action(pid)
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "plan is not DRAFT")
    if not any(m["remediation_plan_id"] == pid for m in db.milestones.values()):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "at least one milestone must exist")
    issue = db.issues[plan["issue_id"]]
    if issue["status"] not in ("OPEN", "REMEDIATION_PLANNED", "IN_PROGRESS",
                               "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "issue state does not permit plan submission")
    plan["status"] = "SUBMITTED"
    plan["submitted_at"] = now()
    touch(plan)
    return ok_obj(ser_plan(plan))


@bp.post("/regulatory-exams/remediation-plans/<pid>/approve")
def approve_plan(pid):
    uid, role = auth()
    require_role(role, REVIEWER)
    reviewer_gate(uid)
    plan = _plan_for_action(pid)
    if plan["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "plan is not SUBMITTED")
    issue = db.issues[plan["issue_id"]]
    # state: no other plan for the issue may currently be ACTIVE
    for other in db.plans.values():
        if other["issue_id"] == plan["issue_id"] and other["id"] != pid \
                and other["status"] == "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "another plan for this issue is ACTIVE")
    # (6) certification gate
    _cert_gate(uid, issue)
    plan["status"] = "APPROVED"
    plan["approved_at"] = now()
    touch(plan)
    if issue["status"] == "OPEN":
        issue["status"] = "REMEDIATION_PLANNED"
    touch(issue)
    return ok_obj(ser_plan(plan))


@bp.post("/regulatory-exams/remediation-plans/<pid>/reject")
def reject_plan(pid):
    uid, role = auth()
    require_role(role, REVIEWER)
    reviewer_gate(uid)
    plan = _plan_for_action(pid)
    if plan["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "plan is not SUBMITTED")
    req_str(payload(), "rejection_reason")
    plan["status"] = "REJECTED"
    touch(plan)
    return ok_obj(ser_plan(plan))


@bp.post("/regulatory-exams/remediation-plans/<pid>/revise")
def revise_plan(pid):
    auth_pair = auth()
    require_role(auth_pair[1], OWNER)
    plan = _plan_for_action(pid)
    if plan["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, 409, "plan is not REJECTED")
    plan["status"] = "DRAFT"
    touch(plan)
    return ok_obj(ser_plan(plan))


@bp.post("/regulatory-exams/remediation-plans/<pid>/activate")
def activate_plan(pid):
    auth_pair = auth()
    require_role(auth_pair[1], OWNER)
    plan = _plan_for_action(pid)
    if plan["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "plan is not APPROVED")
    issue = db.issues[plan["issue_id"]]
    if issue["status"] not in ("REMEDIATION_PLANNED", "IN_PROGRESS", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "issue state does not permit activation")
    # Displacement: any other ACTIVE plan on this issue becomes SUPERSEDED and
    # its still-PENDING milestones freeze as OVERDUE-equivalents.
    for other in db.plans.values():
        if other["issue_id"] == plan["issue_id"] and other["id"] != pid \
                and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)
            for m in db.milestones.values():
                if m["remediation_plan_id"] == other["id"] \
                        and m["status"] == "PENDING":
                    m["status"] = "OVERDUE"
                    touch(m)
    plan["status"] = "ACTIVE"
    touch(plan)
    exam = db.exams[issue["examination_id"]]
    recompute_exam(exam)
    return ok_obj(ser_plan(plan))


# -------------------------------------------------------------- milestones
@bp.post("/regulatory-exams/remediation-plans/<pid>/milestones")
def create_milestone(pid):
    auth_pair = auth()
    require_role(auth_pair[1], OWNER)
    plan = get_or_404(db.plans, pid)
    p = payload()
    # (7) optimistic concurrency on the plan
    _occ(p, "expected_plan_version", plan["version"])
    # (11) sequence_index unique within the plan
    si = p.get("sequence_index")
    if isinstance(si, int) and not isinstance(si, bool):
        for m in db.milestones.values():
            if m["remediation_plan_id"] == pid and m["sequence_index"] == si:
                raise ApiError(ERR_DUPLICATE_KEY, 409,
                               "sequence_index already used on this plan")
    # (14) shape
    name = req_str(p, "milestone_name")
    due = req_dt(p, "due_date")
    if si is not None:
        if not isinstance(si, int) or isinstance(si, bool) or si < 1:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "sequence_index must be an integer >= 1")
        assigned = si
    else:
        existing = [m["sequence_index"] for m in db.milestones.values()
                    if m["remediation_plan_id"] == pid]
        assigned = max(existing) + 1 if existing else 1
    rec = {"id": new_id(), "remediation_plan_id": pid, "milestone_name": name,
           "sequence_index": assigned, "due_date": due, "status": "PENDING",
           "completed_at": None,
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.milestones[rec["id"]] = rec
    touch(plan)
    return ok_obj(ser_milestone(rec), 201)


@bp.get("/regulatory-exams/remediation-plans/<pid>/milestones")
def list_milestones(pid):
    auth()
    get_or_404(db.plans, pid)
    status = enum_filter("status", MILESTONE_STATUSES)
    rows = [m for m in db.milestones.values()
            if m["remediation_plan_id"] == pid
            and (status is None or m["status"] == status)]
    return list_page(rows, ser_milestone)


@bp.get("/regulatory-exams/remediation-milestones/<mid>")
def get_milestone(mid):
    auth()
    return ok_obj(ser_milestone(get_or_404(db.milestones, mid)))


@bp.post("/regulatory-exams/remediation-milestones/<mid>/start")
def start_milestone(mid):
    auth_pair = auth()
    require_role(auth_pair[1], OWNER)
    ms = get_or_404(db.milestones, mid)
    if ms["status"] in ("COMPLETE", "OVERDUE"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "milestone is in a terminal state")
    plan = db.plans[ms["remediation_plan_id"]]
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_NO_ACTIVE_PLAN, 422, "parent plan is not ACTIVE")
    if ms["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "milestone is not PENDING")
    for m in db.milestones.values():
        if m["remediation_plan_id"] == plan["id"] \
                and m["sequence_index"] < ms["sequence_index"] \
                and m["status"] not in ("IN_PROGRESS", "COMPLETE"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "an earlier milestone is not yet started")
    ms["status"] = "IN_PROGRESS"
    touch(ms)
    touch(plan)
    issue = db.issues[plan["issue_id"]]
    if issue["status"] in ("REMEDIATION_PLANNED", "OVERDUE"):
        issue["status"] = "IN_PROGRESS"  # escalated_to_board preserved
    touch(issue)
    return ok_obj(ser_milestone(ms))


@bp.post("/regulatory-exams/remediation-milestones/<mid>/complete")
def complete_milestone(mid):
    auth_pair = auth()
    require_role(auth_pair[1], OWNER)
    ms = get_or_404(db.milestones, mid)
    if ms["status"] in ("COMPLETE", "OVERDUE"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "milestone is in a terminal state")
    plan = db.plans[ms["remediation_plan_id"]]
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_NO_ACTIVE_PLAN, 422, "parent plan is not ACTIVE")
    if ms["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "milestone is not IN_PROGRESS")
    ms["status"] = "COMPLETE"
    ms["completed_at"] = now()
    touch(ms)
    touch(plan)
    siblings = [m for m in db.milestones.values()
                if m["remediation_plan_id"] == plan["id"]]
    if siblings and all(m["status"] == "COMPLETE" for m in siblings):
        plan["status"] = "COMPLETE"  # ACTIVE -> COMPLETE auto-transition
    return ok_obj(ser_milestone(ms))
