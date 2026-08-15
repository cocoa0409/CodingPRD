"""Project routes: register, list, get, patch (OCC), submit, withdraw."""

from flask import Blueprint, request
import db
import validators as V
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination, paginate
from serializers import project_out
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL, ERR_FORBIDDEN, ERR_STALE_VERSION,
    ERR_REFERENTIAL_INTEGRITY, ERR_RESEARCH_PLAN_REQUIRED,
    ERR_ALREADY_ASSIGNED,
)

bp = Blueprint("projects", __name__)

_ALL_ROLES = ("FairDirector", "Mentor", "EthicsReviewer", "Judge",
              "OperationsLead", "SafetyInspector")

_REG_STATUSES = {"DRAFT", "SUBMITTED", "CONFIRMED", "WITHDRAWN"}
_JUDGING_STATUSES = {"UNASSIGNED", "ASSIGNED", "JUDGED"}
_ADV_RESULTS = {"PENDING", "ADVANCED", "WAITLISTED", "NOT_ADVANCED"}


def _touch(p):
    p["updated_at"] = db.now_display_iso()
    p["version"] += 1


def _get_project_or_404(pid):
    p = db.projects.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, f"Project not found: {pid}")
    return p


@bp.route("/science-fair/projects", methods=["POST"])
def create_project():
    body = V.get_json_body()
    # Priority 0 shape
    V.require_fields(body, ["fair_edition_id", "category_id", "title",
                            "team_size", "involves_human_subjects",
                            "involves_animal_subjects"])
    feid = V.req_str(body, "fair_edition_id")
    cat_id = V.req_str(body, "category_id")
    title = V.req_str(body, "title")
    team_size = V.req_int(body, "team_size")
    if team_size < 1 or team_size > 3:
        raise_err(ERR_INVALID_REQUEST, "team_size must be between 1 and 3")
    hs = V.req_bool(body, "involves_human_subjects")
    ans = V.req_bool(body, "involves_animal_subjects")

    user_id, role = require_roles("Mentor")

    # Referential integrity (priority 8): edition, category, mentor
    edition = db.fair_editions.get(feid)
    if edition is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  f"Fair edition not found: {feid}")
    category = db.categories.get(cat_id)
    if category is None or category["fair_edition_id"] != feid:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  f"Category {cat_id} does not exist in edition {feid}")
    mentor = db.mentors.get(user_id)
    if mentor is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  f"Mentor not found: {user_id}")

    # State: edition must be REGISTRATION_OPEN (priority 4)
    if edition["status"] != "REGISTRATION_OPEN":
        raise_err(ERR_INVALID_STATE,
                  "Project registration requires edition status "
                  "REGISTRATION_OPEN")
    # Target category must still be OPEN
    if category["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE,
                  "Target category is LOCKED; registration closed")

    now = db.now_display_iso()
    p = {
        "id": db.new_id(),
        "fair_edition_id": feid,
        "category_id": cat_id,
        "mentor_id": user_id,
        "title": title,
        "team_size": team_size,
        "involves_human_subjects": hs,
        "involves_animal_subjects": ans,
        "registration_status": "DRAFT",
        "ethics_status": None,
        "inspection_status": "NOT_SCHEDULED",
        "judging_status": "UNASSIGNED",
        "provisional_aggregate": None,
        "final_aggregate": None,
        "advancement_result": "PENDING",
        "advancement_rank": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.projects[p["id"]] = p
    return success_object(project_out(p), 201)


@bp.route("/science-fair/projects", methods=["GET"])
def list_projects():
    require_roles(*_ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.projects.values())

    feid = request.args.get("fair_edition_id")
    if feid:
        items = [p for p in items if p["fair_edition_id"] == feid]
    cat = request.args.get("category_id")
    if cat:
        items = [p for p in items if p["category_id"] == cat]
    mid = request.args.get("mentor_id")
    if mid:
        items = [p for p in items if p["mentor_id"] == mid]
    rs = request.args.get("registration_status")
    if rs:
        items = [p for p in items if p["registration_status"] == rs]
    js = request.args.get("judging_status")
    if js:
        items = [p for p in items if p["judging_status"] == js]
    ar = request.args.get("advancement_result")
    if ar:
        items = [p for p in items if p["advancement_result"] == ar]

    data, total = paginate(items, project_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/projects/<pid>", methods=["GET"])
def get_project(pid):
    require_roles(*_ALL_ROLES)
    p = _get_project_or_404(pid)
    return success_object(project_out(p))


@bp.route("/science-fair/projects/<pid>", methods=["PATCH"])
def patch_project(pid):
    body = V.get_json_body()
    V.require_fields(body, ["expected_project_version"])
    expected = V.req_int(body, "expected_project_version")
    title = V.opt_str(body, "title")
    team_size = V.opt_int(body, "team_size")
    if team_size is not None and (team_size < 1 or team_size > 3):
        raise_err(ERR_INVALID_REQUEST, "team_size must be between 1 and 3")
    cat_id = V.opt_str(body, "category_id")

    user_id, role = require_roles("Mentor", "FairDirector")

    p = _get_project_or_404(pid)

    # Terminal guard first (WITHDRAWN is terminal for registration_status)
    if p["registration_status"] == "WITHDRAWN":
        raise_err(ERR_ALREADY_TERMINAL,
                  "Project is WITHDRAWN (terminal)")

    # Ownership: Mentor may only touch own projects
    if role == "Mentor" and p["mentor_id"] != user_id:
        raise_err(ERR_FORBIDDEN,
                  "Mentor may only update own projects")

    # State gate: registration_status must be DRAFT or SUBMITTED, and edition
    # registration must still be open (PRD 3.2: while a project is in DRAFT or
    # SUBMITTED and the edition's registration is still open).
    edition = db.fair_editions.get(p["fair_edition_id"])
    if edition is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY, "Parent edition missing")
    if p["registration_status"] not in ("DRAFT", "SUBMITTED"):
        raise_err(ERR_INVALID_STATE,
                  "Project update allowed only while registration_status is "
                  "DRAFT or SUBMITTED")
    if edition["status"] != "REGISTRATION_OPEN":
        raise_err(ERR_INVALID_STATE,
                  "Project update requires edition status REGISTRATION_OPEN")

    # OCC on project version
    if expected != p["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_project_version does not match current project "
                  "version")

    # Referential integrity for category reassignment
    if cat_id is not None:
        cat = db.categories.get(cat_id)
        if cat is None or cat["fair_edition_id"] != p["fair_edition_id"]:
            raise_err(ERR_REFERENTIAL_INTEGRITY,
                      f"Category {cat_id} does not exist in edition "
                      f"{p['fair_edition_id']}")

    if title is not None:
        p["title"] = title
    if team_size is not None:
        p["team_size"] = team_size
    if cat_id is not None:
        p["category_id"] = cat_id
    _touch(p)
    return success_object(project_out(p))


@bp.route("/science-fair/projects/<pid>/submit", methods=["POST"])
def submit_project(pid):
    V.get_json_body()
    user_id, role = require_roles("Mentor")
    p = _get_project_or_404(pid)

    if p["registration_status"] == "WITHDRAWN":
        raise_err(ERR_ALREADY_TERMINAL, "Project is WITHDRAWN (terminal)")

    # Ownership
    if p["mentor_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Mentor may only submit own projects")

    # State
    if p["registration_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot submit from registration_status "
                  f"{p['registration_status']}")

    edition = db.fair_editions.get(p["fair_edition_id"])
    if edition is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY, "Parent edition missing")
    if edition["status"] != "REGISTRATION_OPEN":
        raise_err(ERR_INVALID_STATE,
                  "Project submit requires edition status REGISTRATION_OPEN")

    # team_size must be 1..3 (business rule; shape already enforced on create)
    if p["team_size"] < 1 or p["team_size"] > 3:
        raise_err(ERR_INVALID_REQUEST, "team_size must be between 1 and 3")

    requires_ethics = (p["involves_human_subjects"]
                       or p["involves_animal_subjects"])
    if requires_ethics:
        ok = any(
            rp["project_id"] == pid
            and rp["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED")
            for rp in db.research_plans.values()
        )
        if not ok:
            raise_err(ERR_RESEARCH_PLAN_REQUIRED,
                      "Project declares human/animal subjects but has no "
                      "ResearchPlan in SUBMITTED/UNDER_REVIEW/APPROVED")

    p["registration_status"] = "SUBMITTED"
    p["ethics_status"] = "PENDING" if requires_ethics else "NOT_REQUIRED"
    _touch(p)
    return success_object(project_out(p))


@bp.route("/science-fair/projects/<pid>/withdraw", methods=["POST"])
def withdraw_project(pid):
    V.get_json_body()
    user_id, role = require_roles("Mentor")
    p = _get_project_or_404(pid)

    if p["registration_status"] == "WITHDRAWN":
        raise_err(ERR_ALREADY_TERMINAL, "Project is WITHDRAWN (terminal)")

    if p["mentor_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Mentor may only withdraw own projects")

    if p["registration_status"] == "SUBMITTED":
        if p["judging_status"] != "UNASSIGNED":
            raise_err(ERR_ALREADY_ASSIGNED,
                      "Withdraw attempted while project has non-terminal "
                      "JudgingAssignments")
        # Compensation: in-flight research plans back to DRAFT
        for rp in db.research_plans.values():
            if (rp["project_id"] == pid
                    and rp["status"] in ("SUBMITTED", "UNDER_REVIEW",
                                         "REVISION_REQUIRED")):
                rp["status"] = "DRAFT"
                rp["updated_at"] = db.now_display_iso()
                rp["version"] += 1
    elif p["registration_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot withdraw from registration_status "
                  f"{p['registration_status']}")

    p["registration_status"] = "WITHDRAWN"
    _touch(p)
    return success_object(project_out(p))
