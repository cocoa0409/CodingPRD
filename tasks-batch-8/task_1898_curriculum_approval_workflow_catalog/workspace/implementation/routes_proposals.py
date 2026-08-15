"""Proposals: create/list/get/edit, submit, withdraw, decisions, activate."""

from flask import Blueprint, request

import calc
import db
from db import STORE, new_id, new_record, next_seq, now_iso, pub, touch
from errors import ApiError
from helpers import (
    body_fk, check_fields, get_json_body, is_number_held, list_response,
    parse_dt, path_param, validate_requisites,
)
from middleware import require_auth
from response import ok

bp = Blueprint("proposals", __name__)

PROPOSER = {"FacultyProposer"}
DECISION_ROLES = {"DepartmentChair", "CurriculumCommittee", "FacultySenate", "Registrar"}

REVIEW_STAGES = ("DEPT_REVIEW", "COMMITTEE_REVIEW", "SENATE_REVIEW", "REGISTRAR_REVIEW")
STAGE_ROLE = {
    "DEPT_REVIEW": "DepartmentChair",
    "COMMITTEE_REVIEW": "CurriculumCommittee",
    "SENATE_REVIEW": "FacultySenate",
    "REGISTRAR_REVIEW": "Registrar",
}
NEXT_STAGE = {
    "DEPT_REVIEW": "COMMITTEE_REVIEW",
    "COMMITTEE_REVIEW": "SENATE_REVIEW",
    "SENATE_REVIEW": "REGISTRAR_REVIEW",
}

PROPOSAL_TYPES = ("NEW_COURSE", "COURSE_CHANGE", "DEACTIVATION")
DECISION_ACTIONS = ("APPROVE", "RETURN", "REJECT", "NOTIFY", "REASSIGN_TERM")


def _append_decision(proposal, action, from_status, to_status, role, uid, rationale=None, term_id=None):
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
        "proposal_id": proposal["id"],
        "action": action,
        "from_status": from_status,
        "to_status": to_status,
        "actor_role": role,
        "actor_id": uid,
        "rationale": rationale,
        "recorded_term_id": term_id,
    }
    STORE["decision_records"].append(rec)


def _remove_proposed_links(proposal):
    for l in STORE["requisite_links"].values():
        if l["proposal_id"] == proposal["id"] and l["status"] == "PROPOSED":
            l["status"] = "REMOVED"
            touch(l)


def _proposal_type_rules(ptype, body, partial=False):
    """Type-consistency shape rules shared by create and edit."""
    target = body.get("target_course_id")
    cohorts = body.get("declared_remaining_cohorts")
    if ptype == "NEW_COURSE" and target is not None:
        raise ApiError("ERR_VALIDATION", 400, "target_course_id must be null for NEW_COURSE")
    if ptype != "DEACTIVATION" and cohorts is not None:
        raise ApiError("ERR_VALIDATION", 400, "declared_remaining_cohorts applies only to DEACTIVATION")
    if cohorts is not None and cohorts < 0:
        raise ApiError("ERR_VALIDATION", 400, "declared_remaining_cohorts must be at least zero")


# --- Create / read / edit ------------------------------------------------------

@bp.post("/curriculum/proposals")
def create_proposal():
    uid, _ = require_auth(PROPOSER)
    body = get_json_body()
    check_fields(body, {
        "proposal_type": ("str", True),
        "proposer_department_id": ("str", True),
        "requested_effective_term_id": ("str", True),
        "target_course_id": ("str", False),
        "proposed_subject_code": ("str", False),
        "proposed_course_number": ("str", False),
        "proposed_title": ("str", False),
        "proposed_credit_hours": ("num", False),
        "contact_hours_per_week": ("num", False),
        "out_of_class_hours_per_week": ("num", False),
        "learning_outcomes": ("str_list", False),
        "justification": ("str", False),
        "proposed_requisites": ("list", False),
        "declared_remaining_cohorts": ("int", False),
    })
    ptype = body["proposal_type"]
    if ptype not in PROPOSAL_TYPES:
        raise ApiError("ERR_VALIDATION", 400, "invalid proposal_type")
    body_fk("departments", body["proposer_department_id"], "proposer_department_id")
    body_fk("terms", body["requested_effective_term_id"], "requested_effective_term_id")
    if body.get("target_course_id") is not None:
        body_fk("courses", body["target_course_id"], "target_course_id")
    _proposal_type_rules(ptype, body)
    requisites = []
    if body.get("proposed_requisites") is not None:
        requisites = validate_requisites(body["proposed_requisites"])
    rec = new_record()
    rec.update({
        "proposal_type": ptype,
        "proposer_id": uid,
        "proposer_department_id": body["proposer_department_id"],
        "target_course_id": body.get("target_course_id"),
        "proposed_subject_code": body.get("proposed_subject_code"),
        "proposed_course_number": body.get("proposed_course_number"),
        "proposed_title": body.get("proposed_title"),
        "proposed_credit_hours": body.get("proposed_credit_hours"),
        "contact_hours_per_week": body.get("contact_hours_per_week"),
        "out_of_class_hours_per_week": body.get("out_of_class_hours_per_week"),
        "learning_outcomes": body.get("learning_outcomes"),
        "justification": body.get("justification"),
        "proposed_requisites": requisites,
        "declared_remaining_cohorts": body.get("declared_remaining_cohorts"),
        "requested_effective_term_id": body["requested_effective_term_id"],
        "effective_term_id": None,
        "substantive_change_score": None,
        "accreditor_notification_required": None,
        "notification_sent_at": None,
        "status": "DRAFT",
    })
    STORE["proposals"][rec["id"]] = rec
    return ok(pub(rec), 201)


_PROPOSAL_FILTERS = (
    "target_course_id", "requested_effective_term_id", "effective_term_id",
    "proposer_department_id", "proposer_id", "status",
)


@bp.get("/curriculum/proposals")
def list_proposals():
    require_auth()
    records = list(STORE["proposals"].values())
    for f in _PROPOSAL_FILTERS:
        v = request.args.get(f)
        if v is not None:
            records = [p for p in records if ("" if p[f] is None else str(p[f])) == v]
    return list_response(records, pub)


@bp.get("/curriculum/proposals/<pid>")
def get_proposal(pid):
    require_auth()
    return ok(pub(path_param("proposals", pid)), 200)


@bp.put("/curriculum/proposals/<pid>")
def edit_proposal(pid):
    uid, _ = require_auth(PROPOSER)
    rec = path_param("proposals", pid)
    body = get_json_body()
    check_fields(body, {
        "expected_proposal_version": ("int", True),
        "proposed_subject_code": ("str", False),
        "proposed_course_number": ("str", False),
        "proposed_title": ("str", False),
        "proposed_credit_hours": ("num", False),
        "contact_hours_per_week": ("num", False),
        "out_of_class_hours_per_week": ("num", False),
        "learning_outcomes": ("str_list", False),
        "justification": ("str", False),
        "proposed_requisites": ("list", False),
        "declared_remaining_cohorts": ("int", False),
        "requested_effective_term_id": ("str", False),
        "proposer_department_id": ("str", False),
    })
    if body.get("requested_effective_term_id") is not None:
        body_fk("terms", body["requested_effective_term_id"], "requested_effective_term_id")
    if body.get("proposer_department_id") is not None:
        body_fk("departments", body["proposer_department_id"], "proposer_department_id")
    requisites = None
    if body.get("proposed_requisites") is not None:
        requisites = validate_requisites(body["proposed_requisites"])
    merged = dict(rec)
    merged.update({k: v for k, v in body.items() if v is not None and k != "expected_proposal_version"})
    _proposal_type_rules(rec["proposal_type"], merged)
    # ownership (5) then state (6) then OCC
    if uid != rec["proposer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "only the proposal author may edit it")
    if rec["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE", 409, "proposal is not editable in its current state")
    if body["expected_proposal_version"] != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "proposal version does not match expected_proposal_version")
    for f in ("proposed_subject_code", "proposed_course_number", "proposed_title",
              "proposed_credit_hours", "contact_hours_per_week", "out_of_class_hours_per_week",
              "learning_outcomes", "justification", "declared_remaining_cohorts",
              "requested_effective_term_id", "proposer_department_id"):
        if f in body and body[f] is not None:
            rec[f] = body[f]
    if requisites is not None:
        rec["proposed_requisites"] = requisites
    touch(rec)
    return ok(pub(rec), 200)


# --- Submit --------------------------------------------------------------------

def _submit_completeness(p):
    """Type-specific submit completeness is body validation (priority 4)."""
    t = p["proposal_type"]
    if t == "NEW_COURSE":
        required = ("proposed_subject_code", "proposed_course_number", "proposed_title",
                    "proposed_credit_hours", "contact_hours_per_week", "out_of_class_hours_per_week",
                    "learning_outcomes")
        if any(p[f] is None for f in required):
            raise ApiError("ERR_VALIDATION", 400, "NEW_COURSE submission payload is incomplete")
    elif t == "COURSE_CHANGE":
        required = ("proposed_subject_code", "proposed_course_number", "proposed_title",
                    "proposed_credit_hours", "contact_hours_per_week", "out_of_class_hours_per_week",
                    "learning_outcomes")
        if p["target_course_id"] is None or any(p[f] is None for f in required):
            raise ApiError("ERR_VALIDATION", 400, "COURSE_CHANGE submission payload is incomplete")
    else:  # DEACTIVATION
        if p["target_course_id"] is None or p["declared_remaining_cohorts"] is None:
            raise ApiError("ERR_VALIDATION", 400, "DEACTIVATION submission payload is incomplete")


@bp.post("/curriculum/proposals/<pid>/submit")
def submit_proposal(pid):
    uid, _ = require_auth(PROPOSER)
    p = path_param("proposals", pid)
    check_fields(get_json_body(), {})
    _submit_completeness(p)  # priority 4
    if uid != p["proposer_id"]:  # priority 5
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "only the proposal author may submit it")
    if p["status"] not in ("DRAFT", "RETURNED"):  # priority 6
        raise ApiError("ERR_INVALID_STATE", 409, "proposal cannot be submitted from its current state")
    if p["proposal_type"] in ("COURSE_CHANGE", "DEACTIVATION"):
        target = STORE["courses"].get(p["target_course_id"])
        if target is None or target["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "target course is not ACTIVE")
    # priority 10: submission window
    term = STORE["terms"].get(p["requested_effective_term_id"])
    if term is None or term["status"] != "OPEN_FOR_PROPOSALS" or not (db.clock_now() < parse_dt(term["proposal_freeze_at"])):
        raise ApiError("ERR_PROPOSAL_WINDOW_CLOSED", 409, "the requested term's proposal window is closed")
    # priority 14: every requisite references an ACTIVE course
    for entry in p["proposed_requisites"]:
        rc = STORE["courses"].get(entry["requisite_course_id"])
        if rc is None or rc["status"] != "ACTIVE":
            raise ApiError("ERR_REQUISITE_TARGET_INACTIVE", 422, "requisite course is not ACTIVE")
    # priority 16: self-requisite
    if p["target_course_id"] is not None:
        for entry in p["proposed_requisites"]:
            if entry["requisite_course_id"] == p["target_course_id"]:
                raise ApiError("ERR_SELF_REQUISITE", 422, "a course cannot be its own requisite")
    # priority 17: course-number hold (NEW_COURSE)
    if p["proposal_type"] == "NEW_COURSE" and is_number_held(
        p["proposed_subject_code"], p["proposed_course_number"], exclude_proposal_id=p["id"]
    ):
        raise ApiError("ERR_COURSE_NUMBER_HELD", 409, "course number is already held")
    # priority 22: present-but-empty learning outcomes
    if p["proposal_type"] in ("NEW_COURSE", "COURSE_CHANGE") and p["learning_outcomes"] is not None and len(p["learning_outcomes"]) == 0:
        raise ApiError("ERR_LEARNING_OUTCOMES_REQUIRED", 422, "learning_outcomes must be non-empty")
    # priority 23: credit-hour workload check
    if p["proposal_type"] in ("NEW_COURSE", "COURSE_CHANGE") and not calc.credit_workload_passes(
        p["contact_hours_per_week"], p["out_of_class_hours_per_week"], p["proposed_credit_hours"]
    ):
        raise ApiError("ERR_CREDIT_HOUR_MISMATCH", 422, "proposed credit hours deviate from computed workload credits")
    # side effects
    from_status = p["status"]
    for entry in p["proposed_requisites"]:
        link = new_record()
        link.update({
            "course_id": p["target_course_id"],  # null while a NEW_COURSE proposal is pre-EFFECTIVE
            "requisite_course_id": entry["requisite_course_id"],
            "requisite_type": entry["requisite_type"],
            "proposal_id": p["id"],
            "status": "PROPOSED",
        })
        STORE["requisite_links"][link["id"]] = link
    score = calc.substantive_change_score(p, "PROVISIONAL")
    p["substantive_change_score"] = score
    p["accreditor_notification_required"] = calc.notification_required(score)
    p["status"] = "DEPT_REVIEW"
    _append_decision(p, "SUBMIT", from_status, "DEPT_REVIEW", "FacultyProposer", uid)
    touch(p)
    return ok(pub(p), 200)


# --- Withdraw ------------------------------------------------------------------

@bp.post("/curriculum/proposals/<pid>/withdraw")
def withdraw_proposal(pid):
    uid, _ = require_auth(PROPOSER)
    p = path_param("proposals", pid)
    check_fields(get_json_body(), {})
    if uid != p["proposer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "only the proposal author may withdraw it")
    if p["status"] not in ("DRAFT", "RETURNED") + REVIEW_STAGES + ("APPROVED",):
        raise ApiError("ERR_INVALID_STATE", 409, "proposal cannot be withdrawn from its current state")
    from_status = p["status"]
    if from_status in REVIEW_STAGES:
        _remove_proposed_links(p)
    # APPROVED withdrawal's scheduled-count decrement is implicit in the
    # computed Term.scheduled_proposal_count (status leaves APPROVED).
    p["status"] = "WITHDRAWN"
    _append_decision(p, "WITHDRAW", from_status, "WITHDRAWN", "FacultyProposer", uid)
    touch(p)
    return ok(pub(p), 200)


# --- Decisions -----------------------------------------------------------------

@bp.post("/curriculum/proposals/<pid>/decisions")
def post_decision(pid):
    uid, role = require_auth(DECISION_ROLES)
    p = path_param("proposals", pid)
    body = get_json_body()
    check_fields(body, {
        "action": ("str", True),
        "rationale": ("str", False),
        "effective_term_id": ("str", False),
    })
    action = body["action"]
    if action not in DECISION_ACTIONS:
        raise ApiError("ERR_VALIDATION", 400, "invalid decision action")
    # contextual body rules still at priority 4 (PRD 2.8)
    new_term = None
    if action == "APPROVE" and role == "Registrar":
        if body.get("effective_term_id") is None:
            raise ApiError("ERR_VALIDATION", 400, "effective_term_id is required for registrar approval")
        new_term = body_fk("terms", body["effective_term_id"], "effective_term_id")
    if action == "REASSIGN_TERM":
        if body.get("effective_term_id") is None:
            raise ApiError("ERR_VALIDATION", 400, "effective_term_id is required for REASSIGN_TERM")
        new_term = body_fk("terms", body["effective_term_id"], "effective_term_id")
        if p["effective_term_id"] is not None and body["effective_term_id"] == p["effective_term_id"]:
            raise ApiError("ERR_VALIDATION", 400, "effective_term_id must differ from the current term")
    rationale = body.get("rationale")

    # priority 5: DEPT_REVIEW ownership (chair of the sponsoring department)
    if role == "DepartmentChair" and p["status"] == "DEPT_REVIEW" and action in ("APPROVE", "RETURN", "REJECT"):
        if uid != p["proposer_department_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "acting chair does not head the sponsoring department")

    # priority 6: the requested transition must exist from the current state
    if action in ("APPROVE", "RETURN", "REJECT"):
        if p["status"] not in REVIEW_STAGES:
            raise ApiError("ERR_INVALID_STATE", 409, f"{action} is not available from state {p['status']}")
    elif action == "NOTIFY":
        if p["status"] != "REGISTRAR_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "NOTIFY is only available in REGISTRAR_REVIEW")
        if not p["accreditor_notification_required"] or p["notification_sent_at"] is not None:
            raise ApiError("ERR_INVALID_STATE", 409, "no accreditor notification is pending")
    else:  # REASSIGN_TERM
        if p["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", 409, "REASSIGN_TERM is only available while APPROVED")

    # priority 7: stage-role class match
    if action == "REASSIGN_TERM":
        if role != "Registrar":
            raise ApiError("ERR_FORBIDDEN", 403, "only the Registrar may reassign the effective term")
    elif role != STAGE_ROLE[p["status"]]:
        raise ApiError("ERR_FORBIDDEN", 403, "role does not match the proposal's current review stage")

    # priority 8: segregation of duties
    if action in ("APPROVE", "RETURN", "REJECT") and uid == p["proposer_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 403, "the proposer may not decide their own proposal")

    from_status = p["status"]

    if action == "APPROVE" and from_status == "REGISTRAR_REVIEW":
        # priority 9: accreditor notification must be recorded first
        if p["accreditor_notification_required"] and p["notification_sent_at"] is None:
            raise ApiError("ERR_ACCREDITOR_NOTIFICATION_PENDING", 409, "accreditor notification has not been recorded")
        # priority 13: teach-out commitment for deactivations with cohorts
        if p["proposal_type"] == "DEACTIVATION" and (p["declared_remaining_cohorts"] or 0) > 0:
            committed = any(
                plan for plan in STORE["teach_out_plans"].values()
                if plan["proposal_id"] == p["id"] and plan["status"] in ("COMMITTED", "IN_PROGRESS", "COMPLETE")
            )
            if not committed:
                raise ApiError("ERR_TEACH_OUT_NOT_COMMITTED", 409, "no committed teach-out plan exists")
        p["effective_term_id"] = new_term["id"]
        p["status"] = "APPROVED"
        _append_decision(p, "APPROVE", from_status, "APPROVED", role, uid, rationale, term_id=new_term["id"])
    elif action == "APPROVE":
        to_status = NEXT_STAGE[from_status]
        if to_status == "REGISTRAR_REVIEW":
            score = calc.substantive_change_score(p, "FINAL")
            p["substantive_change_score"] = score
            p["accreditor_notification_required"] = calc.notification_required(score)
        p["status"] = to_status
        _append_decision(p, "APPROVE", from_status, to_status, role, uid, rationale)
    elif action in ("RETURN", "REJECT"):
        _remove_proposed_links(p)
        to_status = "RETURNED" if action == "RETURN" else "REJECTED"
        p["status"] = to_status
        _append_decision(p, action, from_status, to_status, role, uid, rationale)
    elif action == "NOTIFY":
        p["notification_sent_at"] = db.logical_iso()
        _append_decision(p, "NOTIFY", from_status, from_status, role, uid, rationale)
    else:  # REASSIGN_TERM
        p["effective_term_id"] = new_term["id"]
        _append_decision(p, "REASSIGN_TERM", from_status, from_status, role, uid, rationale, term_id=new_term["id"])

    touch(p)
    return ok(pub(p), 200)


@bp.get("/curriculum/proposals/<pid>/decisions")
def list_decisions(pid):
    require_auth()
    p = path_param("proposals", pid)
    records = [d for d in STORE["decision_records"] if d["proposal_id"] == p["id"]]
    return list_response(records, pub)


@bp.get("/curriculum/proposals/<pid>/requisites")
def list_proposal_requisites(pid):
    require_auth()
    p = path_param("proposals", pid)
    records = [l for l in STORE["requisite_links"].values() if l["proposal_id"] == p["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [l for l in records if l["status"] == status]
    return list_response(records, pub)


# --- Activate ------------------------------------------------------------------

def _find_draft_edition(academic_year):
    for ed in STORE["catalog_editions"].values():
        if ed["academic_year"] == academic_year and ed["status"] == "DRAFT":
            return ed
    return None


def _stage_catalog_entry(course, proposal, effective_term):
    edition = _find_draft_edition(effective_term["academic_year"])
    if edition is None:
        return
    entry = new_record()
    entry.update({
        "edition_id": edition["id"],
        "course_id": course["id"],
        "proposal_id": proposal["id"],
        "subject_code": course["subject_code"],
        "course_number": course["course_number"],
        "title": course["title"],
        "credit_hours": course["credit_hours"],
        "status": "STAGED",
    })
    STORE["catalog_entries"][entry["id"]] = entry


@bp.post("/curriculum/proposals/<pid>/activate")
def activate_proposal(pid):
    uid, role = require_auth({"Registrar"})
    p = path_param("proposals", pid)
    check_fields(get_json_body(), {})
    if p["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "only an APPROVED proposal can be activated")
    effective_term = STORE["terms"].get(p["effective_term_id"])
    if effective_term is None or effective_term["status"] not in ("PROPOSAL_FROZEN", "CATALOG_FROZEN"):
        raise ApiError("ERR_TERM_NOT_LOCKED", 409, "the effective term is not locked")

    # Pre-generate the materialized course id so NEW_COURSE links can be checked.
    new_course_id = new_id() if p["proposal_type"] == "NEW_COURSE" else None

    def link_x(link):
        return link["course_id"] if link["course_id"] is not None else new_course_id

    # priority 15: cycle pre-check over the whole batch (atomic abort)
    pending = sorted(
        (l for l in STORE["requisite_links"].values() if l["proposal_id"] == p["id"] and l["status"] == "PROPOSED"),
        key=lambda l: l["_seq"],
    )
    simulated = []
    for link in pending:
        if link["requisite_type"] != "PREREQUISITE":
            continue  # COREQUISITE edges never participate
        x, r = link_x(link), link["requisite_course_id"]
        if calc.would_close_cycle(x, r, simulated):
            raise ApiError("ERR_REQUISITE_CYCLE", 422, "activation would close a prerequisite cycle")
        simulated.append((x, r))

    # priority 17: re-check the course-number hold at activation time
    if p["proposal_type"] == "NEW_COURSE" and is_number_held(
        p["proposed_subject_code"], p["proposed_course_number"], exclude_proposal_id=p["id"]
    ):
        raise ApiError("ERR_COURSE_NUMBER_HELD", 409, "course number is already held")

    # --- apply effects ---
    target_course = None
    if p["proposal_type"] == "NEW_COURSE":
        course = new_record()
        course["id"] = new_course_id
        course.update({
            "subject_code": p["proposed_subject_code"],
            "course_number": p["proposed_course_number"],
            "title": p["proposed_title"],
            "credit_hours": p["proposed_credit_hours"],
            "contact_hours_per_week": p["contact_hours_per_week"],
            "out_of_class_hours_per_week": p["out_of_class_hours_per_week"],
            "learning_outcomes": list(p["learning_outcomes"]),
            "owning_department_id": p["proposer_department_id"],
            "introduced_in_term_id": p["effective_term_id"],
            "last_published_edition_id": None,
            "status": "ACTIVE",
        })
        STORE["courses"][course["id"]] = course
        target_course = course
    else:
        target_course = STORE["courses"].get(p["target_course_id"])

    if p["proposal_type"] == "COURSE_CHANGE":
        target_course["title"] = p["proposed_title"]
        target_course["credit_hours"] = p["proposed_credit_hours"]
        target_course["contact_hours_per_week"] = p["contact_hours_per_week"]
        target_course["out_of_class_hours_per_week"] = p["out_of_class_hours_per_week"]
        target_course["learning_outcomes"] = list(p["learning_outcomes"])
        touch(target_course)

    # flip PROPOSED links to ACTIVE in creation order
    for link in pending:
        if link["course_id"] is None:
            link["course_id"] = new_course_id
        link["status"] = "ACTIVE"
        touch(link)
        carrier = STORE["courses"].get(link["course_id"])
        if carrier is not None:
            touch(carrier)  # prerequisite_summary recomputed at read time

    if p["proposal_type"] == "DEACTIVATION":
        target_course["status"] = "DEACTIVATING"
        touch(target_course)
        for plan in STORE["teach_out_plans"].values():
            if plan["proposal_id"] == p["id"] and plan["status"] == "COMMITTED":
                plan["status"] = "IN_PROGRESS"
                touch(plan)
        # links naming the deactivated course as requisite -> REMOVED
        for link in sorted(STORE["requisite_links"].values(), key=lambda l: l["_seq"]):
            if link["requisite_course_id"] == target_course["id"] and link["status"] == "ACTIVE":
                link["status"] = "REMOVED"
                touch(link)
                dependent = STORE["courses"].get(link["course_id"])
                if dependent is not None:
                    touch(dependent)  # summary recompute + version bump
        # links the deactivated course itself carries -> REMOVED
        for link in sorted(STORE["requisite_links"].values(), key=lambda l: l["_seq"]):
            if link["course_id"] == target_course["id"] and link["status"] == "ACTIVE":
                link["status"] = "REMOVED"
                touch(link)
        # STAGED catalog entries for the course -> EXCLUDED
        for entry in STORE["catalog_entries"].values():
            if entry["course_id"] == target_course["id"] and entry["status"] == "STAGED":
                entry["status"] = "EXCLUDED"
                touch(entry)
    else:
        _stage_catalog_entry(target_course, p, effective_term)

    p["status"] = "EFFECTIVE"
    _append_decision(p, "ACTIVATE", "APPROVED", "EFFECTIVE", role, uid)
    touch(p)
    return ok(pub(p), 200)
