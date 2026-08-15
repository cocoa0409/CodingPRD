"""ResearchPlan + EthicsReview routes."""

from flask import Blueprint, request
import db
import validators as V
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination, paginate
from serializers import research_plan_out, ethics_review_out
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL, ERR_FORBIDDEN, ERR_PROJECT_LOCKED,
    ERR_SOD_VIOLATION, ERR_RATIONALE_REQUIRED, ERR_REFERENTIAL_INTEGRITY,
)

bp = Blueprint("research_plans", __name__)

_VALID_RISK = {"LOW", "MODERATE", "HIGH"}
_VALID_PLAN_STATUS = {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED",
                      "REJECTED", "REVISION_REQUIRED"}
_VALID_DECISION = {"APPROVE", "REJECT", "REQUEST_REVISION"}


def _touch(r):
    r["updated_at"] = db.now_display_iso()
    r["version"] += 1


def _get_plan_or_404(rid):
    r = db.research_plans.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, f"Research plan not found: {rid}")
    return r


def _touch_project(p):
    p["updated_at"] = db.now_display_iso()
    p["version"] += 1


@bp.route("/science-fair/research-plans", methods=["POST"])
def create_plan():
    body = V.get_json_body()
    V.require_fields(body, ["project_id", "plan_text", "risk_level"])
    pid = V.req_str(body, "project_id")
    plan_text = V.req_str(body, "plan_text")
    risk = V.req_enum(body, "risk_level", _VALID_RISK)

    user_id, role = require_roles("Mentor")

    project = db.projects.get(pid)
    if project is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY, f"Project not found: {pid}")
    if project["mentor_id"] != user_id:
        raise_err(ERR_FORBIDDEN,
                  "Mentor may only create plans for own projects")

    now = db.now_display_iso()
    r = {
        "id": db.new_id(),
        "project_id": pid,
        "plan_text": plan_text,
        "risk_level": risk,
        "status": "DRAFT",
        "review_cycle_count": 0,
        "approved_plan_version": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.research_plans[r["id"]] = r
    return success_object(research_plan_out(r), 201)


@bp.route("/science-fair/research-plans", methods=["GET"])
def list_plans():
    require_roles("FairDirector", "EthicsReviewer", "Mentor")
    limit, offset = parse_pagination()
    items = list(db.research_plans.values())
    pid = request.args.get("project_id")
    if pid:
        items = [r for r in items if r["project_id"] == pid]
    st = request.args.get("status")
    if st:
        items = [r for r in items if r["status"] == st]
    data, total = paginate(items, research_plan_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/research-plans/<rid>", methods=["GET"])
def get_plan(rid):
    require_roles("FairDirector", "EthicsReviewer", "Mentor")
    r = _get_plan_or_404(rid)
    return success_object(research_plan_out(r))


@bp.route("/science-fair/research-plans/<rid>", methods=["PUT"])
def update_plan(rid):
    body = V.get_json_body()
    plan_text = V.opt_str(body, "plan_text")
    risk = V.opt_enum(body, "risk_level", _VALID_RISK)

    user_id, role = require_roles("Mentor")
    r = _get_plan_or_404(rid)

    project = db.projects.get(r["project_id"])
    if project is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY, "Parent project missing")
    if project["mentor_id"] != user_id:
        raise_err(ERR_FORBIDDEN,
                  "Mentor may only edit plans for own projects")

    plan_text_changed = plan_text is not None and plan_text != r["plan_text"]

    if r["status"] == "REVISION_REQUIRED" and plan_text_changed:
        # Revision loop: back to DRAFT, clear approved_plan_version
        r["plan_text"] = plan_text
        if risk is not None:
            r["risk_level"] = risk
        r["status"] = "DRAFT"
        r["approved_plan_version"] = None
        _touch(r)
        return success_object(research_plan_out(r))

    # Ordinary edit: allowed unless plan is in a terminal state
    if r["status"] in ("APPROVED", "REJECTED"):
        raise_err(ERR_ALREADY_TERMINAL,
                  f"Research plan is {r['status']} (terminal)")

    if plan_text is not None:
        r["plan_text"] = plan_text
    if risk is not None:
        r["risk_level"] = risk
    _touch(r)
    return success_object(research_plan_out(r))


@bp.route("/science-fair/research-plans/<rid>/submit", methods=["POST"])
def submit_plan(rid):
    V.get_json_body()
    user_id, role = require_roles("Mentor")
    r = _get_plan_or_404(rid)

    project = db.projects.get(r["project_id"])
    if project is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY, "Parent project missing")
    if project["mentor_id"] != user_id:
        raise_err(ERR_FORBIDDEN,
                  "Mentor may only submit plans for own projects")

    if r["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot submit plan from status {r['status']}")
    if project["registration_status"] not in ("DRAFT", "SUBMITTED"):
        raise_err(ERR_PROJECT_LOCKED,
                  "ResearchPlan mutation attempted while parent project is "
                  "in a locked registration state")

    r["status"] = "SUBMITTED"
    _touch(r)
    return success_object(research_plan_out(r))


@bp.route("/science-fair/research-plans/<rid>/begin-review", methods=["POST"])
def begin_review(rid):
    V.get_json_body()
    require_roles("EthicsReviewer")
    r = _get_plan_or_404(rid)

    if r["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot begin review from status {r['status']}")
    r["status"] = "UNDER_REVIEW"
    r["review_cycle_count"] += 1
    _touch(r)
    return success_object(research_plan_out(r))


@bp.route("/science-fair/research-plans/<rid>/decisions", methods=["POST"])
def record_decision(rid):
    body = V.get_json_body()
    V.require_fields(body, ["reviewer_mentor_id", "decision"])
    reviewer_mentor_id = V.req_str(body, "reviewer_mentor_id")
    decision = V.req_enum(body, "decision", _VALID_DECISION)
    rationale = V.opt_str(body, "rationale")

    require_roles("EthicsReviewer")
    r = _get_plan_or_404(rid)

    project = db.projects.get(r["project_id"])
    if project is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY, "Parent project missing")

    # Plan must be UNDER_REVIEW (state check)
    if r["status"] != "UNDER_REVIEW":
        if r["status"] in ("APPROVED", "REJECTED"):
            raise_err(ERR_ALREADY_TERMINAL,
                      f"Research plan is {r['status']} (terminal)")
        raise_err(ERR_INVALID_STATE,
                  f"Cannot record decision from status {r['status']}")

    # Priority 5 — segregation of duties
    if reviewer_mentor_id == project["mentor_id"]:
        raise_err(ERR_SOD_VIOLATION,
                  "Ethics reviewer must not be the project's mentor")

    # Rationale required for non-APPROVE decisions
    if decision != "APPROVE" and (rationale is None or rationale == ""):
        raise_err(ERR_RATIONALE_REQUIRED,
                  "rationale is required for REJECT / REQUEST_REVISION")

    # Reviewer mentor must exist (referential)
    if db.mentors.get(reviewer_mentor_id) is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  f"Reviewer mentor not found: {reviewer_mentor_id}")

    # Create EthicsReview
    now = db.now_display_iso()
    review = {
        "id": db.new_id(),
        "research_plan_id": rid,
        "reviewer_mentor_id": reviewer_mentor_id,
        "decision": decision,
        "rationale": rationale,
        "decided_at": db.now_display_iso(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.ethics_reviews[review["id"]] = review

    # Drive plan + project transitions
    if decision == "APPROVE":
        r["status"] = "APPROVED"
        _touch(r)
        # Version-pinning: pin the plan's version at APPROVED time (after
        # the transition's own increment) so the snapshot matches until a
        # later version advance makes it stale.
        r["approved_plan_version"] = r["version"]
        project["ethics_status"] = "APPROVED"
        _touch_project(project)
    elif decision == "REJECT":
        r["status"] = "REJECTED"
        _touch(r)
        project["ethics_status"] = "REJECTED"
        project["registration_status"] = "WITHDRAWN"
        _touch_project(project)
    else:  # REQUEST_REVISION
        r["status"] = "REVISION_REQUIRED"
        _touch(r)

    return success_object(ethics_review_out(review), 201)


# ---- EthicsReview readback ----

@bp.route("/science-fair/ethics-reviews", methods=["GET"])
def list_ethics_reviews():
    require_roles("FairDirector", "EthicsReviewer")
    limit, offset = parse_pagination()
    items = list(db.ethics_reviews.values())
    rpid = request.args.get("research_plan_id")
    if rpid:
        items = [r for r in items if r["research_plan_id"] == rpid]
    rmid = request.args.get("reviewer_mentor_id")
    if rmid:
        items = [r for r in items if r["reviewer_mentor_id"] == rmid]
    data, total = paginate(items, ethics_review_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/ethics-reviews/<rid>", methods=["GET"])
def get_ethics_review(rid):
    require_roles("FairDirector", "EthicsReviewer")
    r = db.ethics_reviews.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, f"Ethics review not found: {rid}")
    return success_object(ethics_review_out(r))
