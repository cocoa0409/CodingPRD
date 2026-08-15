"""EngineeringSurvey endpoints: authoring, peer review with SoD, and the
certified-revision loop with the pin-stale project cascade."""

from flask import Blueprint, g

from db import store, new_record, touch
from errors import (err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_SOD_VIOLATION,
                    ERR_FORBIDDEN)
from middleware import require_roles, body
from response import success, list_response
from serializers import ser_engineering_survey
from services import (get_project, get_engineering_survey, children,
                      cascade_release_readiness_lost)
from util import req_enum, req_int

bp = Blueprint("engineering", __name__)

DEMOLITION_METHODS = ("IMPLOSION", "HIGH_REACH_ARM", "MECHANICAL", "SELECTIVE_DECONSTRUCTION")
STABILITY_RATINGS = ("STABLE", "CONDITIONALLY_STABLE", "UNSTABLE")
ES_READ_ROLES = ("ContractorAdmin", "SiteSupervisor", "StructuralEngineer", "PeerReviewEngineer")
ES_ACTIONS = ("SUBMIT", "CERTIFY", "REQUEST_REVISION")
ES_ACTION_ROLES = {
    "SUBMIT": ("StructuralEngineer",),
    "CERTIFY": ("PeerReviewEngineer",),
    "REQUEST_REVISION": ("PeerReviewEngineer",),
}


@bp.post("/demolition/projects/<pid>/engineering-surveys")
@require_roles("StructuralEngineer")
def create_engineering_survey(pid):
    b = body()
    method = req_enum(b, "demolition_method", DEMOLITION_METHODS)
    rating = req_enum(b, "structural_stability_rating", STABILITY_RATINGS)
    height = req_int(b, "max_structure_height_ft", minimum=1)
    distance = req_int(b, "adjacent_structure_distance_ft", minimum=0)
    project = get_project(pid)

    rec = new_record()
    rec.update({
        "project_id": project["id"],
        "revision_number": 1,
        "demolition_method": method,
        "structural_stability_rating": rating,
        "max_structure_height_ft": height,
        "adjacent_structure_distance_ft": distance,
        "author_user_id": g.user_id,
        "certified_by_user_id": None,
        "status": "DRAFT",
    })
    store.engineering_surveys[rec["id"]] = rec
    return success(ser_engineering_survey(rec), status=201)


@bp.get("/demolition/projects/<pid>/engineering-surveys")
@require_roles(*ES_READ_ROLES)
def list_engineering_surveys(pid):
    project = get_project(pid)
    return list_response(children(store.engineering_surveys, "project_id", project["id"]),
                         ser_engineering_survey)


@bp.post("/demolition/engineering-surveys/<eid>/transition")
@require_roles("StructuralEngineer", "PeerReviewEngineer")
def engineering_survey_transition(eid):
    b = body()
    action = b.get("action")
    if not isinstance(action, str) or action not in ES_ACTIONS:
        raise err(ERR_VALIDATION, "invalid action")
    survey = get_engineering_survey(eid)
    if g.role not in ES_ACTION_ROLES[action]:
        raise err(ERR_FORBIDDEN, "role not permitted for this action")
    status = survey["status"]

    if action == "SUBMIT":
        if status != "DRAFT":
            raise err(ERR_INVALID_STATE, "SUBMIT requires DRAFT")
        survey["status"] = "SUBMITTED"
    elif action == "CERTIFY":
        if status != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "CERTIFY requires SUBMITTED")
        if g.user_id == survey["author_user_id"]:
            raise err(ERR_SOD_VIOLATION, "certifier must differ from the author")
        survey["certified_by_user_id"] = g.user_id
        survey["status"] = "CERTIFIED"
    else:  # REQUEST_REVISION
        if status == "SUBMITTED":
            survey["status"] = "DRAFT"
        elif status == "CERTIFIED":
            survey["status"] = "DRAFT"
            survey["revision_number"] += 1
            survey["certified_by_user_id"] = None
            # Pin-stale cascade: a load-bearing certified revision was sent back.
            project = store.projects.get(survey["project_id"])
            if (project is not None
                    and project["pinned_engineering_survey_id"] == survey["id"]
                    and project["status"] == "RELEASED"):
                cascade_release_readiness_lost(project)
        else:
            raise err(ERR_INVALID_STATE, "REQUEST_REVISION requires SUBMITTED or CERTIFIED")

    touch(survey)
    return success(ser_engineering_survey(survey))
