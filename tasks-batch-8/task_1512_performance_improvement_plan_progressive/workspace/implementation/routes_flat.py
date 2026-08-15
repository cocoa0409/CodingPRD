"""Flat query endpoints: reverse-reachability reads for every child entity
(PRD §2.6 / §4). Single-resource GET plus filtered-list GET per collection."""

from flask import Blueprint, request

from core import (
    db, auth, require_role, ok_object, list_response, public, ALL_ROLES,
    E_NOT_FOUND, err,
)

bp = Blueprint("flat_routes", __name__)

LEGAL_READERS = ["HRSystemAdmin", "HRBusinessPartner", "HRDirector", "LegalCounsel"]
NON_EMPLOYEE_READERS = ["HRSystemAdmin", "HRBusinessPartner", "HRDirector",
                        "LegalCounsel", "Manager"]


def _filters(*names):
    return {n: request.args.get(n) for n in names}


def _flat_get(store, roles, rec_id, label):
    uid, role = auth()
    require_role(role, roles)
    rec = store.get(rec_id)
    if rec is None:
        err(E_NOT_FOUND, "%s not found" % label)
    return ok_object(public(rec))


def _flat_list(store, roles, filter_names):
    uid, role = auth()
    require_role(role, roles)
    return list_response(store.values(), _filters(*filter_names))


# --- Employees ---
@bp.get("/hr-org-units/employees/<empId>")
def flat_get_employee(empId):
    return _flat_get(db.employees, ALL_ROLES, empId, "employee")


@bp.get("/hr-org-units/employees")
def flat_list_employees():
    return _flat_list(db.employees, ALL_ROLES,
                      ("hr_org_unit_id", "manager_id", "active_pip_id",
                       "employment_status", "job_family", "job_level"))


# --- Rating cycles ---
@bp.get("/hr-org-units/rating-cycles/<cycleId>")
def flat_get_cycle(cycleId):
    return _flat_get(db.cycles, ALL_ROLES, cycleId, "rating cycle")


@bp.get("/hr-org-units/rating-cycles")
def flat_list_cycles():
    return _flat_list(db.cycles, ALL_ROLES, ("hr_org_unit_id", "status"))


# --- Coaching log entries ---
@bp.get("/hr-org-units/coaching-log-entries/<entryId>")
def flat_get_coaching(entryId):
    return _flat_get(db.coaching_entries, NON_EMPLOYEE_READERS, entryId,
                     "coaching log entry")


@bp.get("/hr-org-units/coaching-log-entries")
def flat_list_coaching():
    return _flat_list(db.coaching_entries, NON_EMPLOYEE_READERS,
                      ("employee_id", "author_manager_id", "concern_id",
                       "category", "severity"))


# --- Performance concerns ---
@bp.get("/hr-org-units/performance-concerns/<concernId>")
def flat_get_concern(concernId):
    return _flat_get(db.concerns, NON_EMPLOYEE_READERS, concernId,
                     "performance concern")


@bp.get("/hr-org-units/performance-concerns")
def flat_list_concerns():
    return _flat_list(db.concerns, NON_EMPLOYEE_READERS,
                      ("employee_id", "raised_by_manager_id",
                       "decided_by_hrbp_id", "status", "category"))


# --- PIP templates ---
@bp.get("/hr-org-units/pip-templates/<templateId>")
def flat_get_template(templateId):
    return _flat_get(db.templates, ALL_ROLES, templateId, "PIP template")


@bp.get("/hr-org-units/pip-templates")
def flat_list_templates():
    return _flat_list(db.templates, ALL_ROLES,
                      ("hr_org_unit_id", "template_status", "category"))


# --- PIPs ---
@bp.get("/hr-org-units/pips/<pipId>")
def flat_get_pip(pipId):
    return _flat_get(db.pips, ALL_ROLES, pipId, "PIP")


@bp.get("/hr-org-units/pips")
def flat_list_pips():
    return _flat_list(db.pips, ALL_ROLES,
                      ("employee_id", "concern_id", "template_id",
                       "issuing_hrbp_id", "status"))


# --- PIP goals ---
@bp.get("/hr-org-units/pip-goals/<goalId>")
def flat_get_goal(goalId):
    return _flat_get(db.goals, ALL_ROLES, goalId, "PIP goal")


@bp.get("/hr-org-units/pip-goals")
def flat_list_goals():
    return _flat_list(db.goals, ALL_ROLES, ("pip_id", "goal_status"))


# --- Check-ins ---
@bp.get("/hr-org-units/check-ins/<checkInId>")
def flat_get_checkin(checkInId):
    return _flat_get(db.checkins, ALL_ROLES, checkInId, "check-in")


@bp.get("/hr-org-units/check-ins")
def flat_list_checkins():
    return _flat_list(db.checkins, ALL_ROLES, ("pip_id", "status"))


# --- Evidence items ---
@bp.get("/hr-org-units/evidence-items/<evidenceId>")
def flat_get_evidence(evidenceId):
    return _flat_get(db.evidence, NON_EMPLOYEE_READERS, evidenceId,
                     "evidence item")


@bp.get("/hr-org-units/evidence-items")
def flat_list_evidence():
    return _flat_list(db.evidence, NON_EMPLOYEE_READERS,
                      ("check_in_id", "pip_goal_id", "submitted_by_id",
                       "admissibility_decided_by_id", "admissibility", "source"))


# --- Legal reviews ---
@bp.get("/hr-org-units/legal-reviews/<reviewId>")
def flat_get_legal(reviewId):
    return _flat_get(db.legal_reviews, LEGAL_READERS, reviewId, "legal review")


@bp.get("/hr-org-units/legal-reviews")
def flat_list_legal():
    return _flat_list(db.legal_reviews, LEGAL_READERS,
                      ("pip_id", "requested_by_hrbp_id", "assigned_counsel_id",
                       "decided_by_director_id", "status", "recommendation"))


# --- Outcome decisions ---
@bp.get("/hr-org-units/outcome-decisions/<decisionId>")
def flat_get_decision(decisionId):
    return _flat_get(db.decisions, ALL_ROLES, decisionId, "outcome decision")


@bp.get("/hr-org-units/outcome-decisions")
def flat_list_decisions():
    return _flat_list(db.decisions, ALL_ROLES,
                      ("pip_id", "proposed_by_hrbp_id", "decided_by_director_id",
                       "status", "proposed_outcome"))


# --- Rebuttals ---
@bp.get("/hr-org-units/rebuttals/<rebuttalId>")
def flat_get_rebuttal(rebuttalId):
    return _flat_get(db.rebuttals, ALL_ROLES, rebuttalId, "rebuttal")


@bp.get("/hr-org-units/rebuttals")
def flat_list_rebuttals():
    return _flat_list(db.rebuttals, ALL_ROLES,
                      ("pip_id", "outcome_decision_id", "submitted_by_employee_id",
                       "reviewed_by_hrbp_id", "status"))


# --- Consistency reviews ---
@bp.get("/hr-org-units/consistency-review-items/<reviewId>")
def flat_get_consistency(reviewId):
    return _flat_get(db.consistency, LEGAL_READERS, reviewId,
                     "consistency review")


@bp.get("/hr-org-units/consistency-review-items")
def flat_list_consistency():
    return _flat_list(db.consistency, LEGAL_READERS,
                      ("hr_org_unit_id", "target_pip_id", "opened_by_hrbp_id",
                       "adjudicated_by_director_id", "status"))


# --- Rating-cycle outcome links ---
@bp.get("/hr-org-units/rating-cycle-outcome-links/<linkId>")
def flat_get_link(linkId):
    return _flat_get(db.links, ALL_ROLES, linkId, "rating-cycle outcome link")


@bp.get("/hr-org-units/rating-cycle-outcome-links")
def flat_list_links():
    return _flat_list(db.links, ALL_ROLES,
                      ("pip_id", "rating_cycle_id", "employee_id"))
