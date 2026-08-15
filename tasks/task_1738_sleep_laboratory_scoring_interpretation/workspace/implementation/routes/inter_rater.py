"""Inter-rater reliability cases and the remediation recall cascade (PRD 3.8)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_CASE_TASKS_INVALID,
    ERR_CASE_ALREADY_EXISTS,
    ERR_CASE_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public, query_filters
from services.calculations import adjudication_metrics, recompute_scorer_reliability
from services.core import new_record, touch
from util import CLOCK
from validate import get_body, req_str, req_int, require_path_resource, require_body_ref

bp = Blueprint("inter_rater", __name__)


@bp.post("/inter-rater-cases")
def create_case():
    authorized(["LabDirector"])
    body = get_body()
    # Priority 3: body FK existence in declaration order.
    study = require_body_ref("sleep_studies", body.get("study_id"))
    primary = require_body_ref("scoring_tasks", body.get("primary_task_id"))
    rescore = require_body_ref("scoring_tasks", body.get("rescore_task_id"))
    # Priority 4: shape.
    study_id = req_str(body, "study_id")
    primary_task_id = req_str(body, "primary_task_id")
    rescore_task_id = req_str(body, "rescore_task_id")
    # Priority 9: both ACCEPTED, correct kinds, same study, different scorers.
    if not (
        primary["status"] == "ACCEPTED"
        and rescore["status"] == "ACCEPTED"
        and primary["assignment_kind"] == "PRIMARY"
        and rescore["assignment_kind"] == "RELIABILITY_RESCORE"
        and primary["study_id"] == study_id
        and rescore["study_id"] == study_id
        and primary["scorer_id"] != rescore["scorer_id"]
    ):
        raise_error(ERR_CASE_TASKS_INVALID,
                    "case tasks must be ACCEPTED, of kinds PRIMARY and RELIABILITY_RESCORE, "
                    "on the same study, by different scorers")
    # Priority 11: one case per rescore task.
    for existing in db["inter_rater_cases"].values():
        if existing["rescore_task_id"] == rescore_task_id:
            raise_error(ERR_CASE_ALREADY_EXISTS,
                        "an InterRaterCase already references this rescore_task_id")
    rec = new_record("inter_rater_cases", {
        "study_id": study_id,
        "primary_task_id": primary_task_id,
        "rescore_task_id": rescore_task_id,
        "epochs_concordant": None,
        "ahi_primary": None,
        "ahi_rescore": None,
        "ahi_delta": None,
        "percent_agreement": None,
        "concordant": None,
        "adjudicated_at": None,
        "status": "OPEN",
    })
    return success_object(public(rec), status=201)


@bp.get("/inter-rater-cases")
def list_cases():
    return list_response("inter_rater_cases",
                         query_filters("study_id", "primary_task_id", "rescore_task_id"))


@bp.get("/inter-rater-cases/<interRaterCaseId>")
def get_case(interRaterCaseId):
    return get_one("inter_rater_cases", interRaterCaseId)


def _remediation_recall_cascade(scorer):
    """Every open task of the scorer is recalled; each recalled PRIMARY pushes
    its study back from SCORING_IN_PROGRESS to SCORING_QUEUED."""
    for task in db["scoring_tasks"].values():
        if (task["scorer_id"] == scorer["id"]
                and task["status"] in ("ASSIGNED", "IN_PROGRESS", "RETURNED_FOR_REVISION")):
            task["status"] = "RECALLED"
            touch(task)
            if task["assignment_kind"] == "PRIMARY":
                study = db["sleep_studies"].get(task["study_id"])
                if study is not None and study["status"] == "SCORING_IN_PROGRESS":
                    study["status"] = "SCORING_QUEUED"
                    touch(study)


@bp.post("/inter-rater-cases/<interRaterCaseId>/adjudicate")
def adjudicate_case(interRaterCaseId):
    authorized(["LabDirector"])
    case = require_path_resource("inter_rater_cases", interRaterCaseId)
    body = get_body()
    epochs_concordant = req_int(body, "epochs_concordant")
    if case["status"] != "OPEN":
        raise_error(ERR_CASE_INVALID_STATE,
                    f"adjudicate requires OPEN, found {case['status']}")
    primary = db["scoring_tasks"].get(case["primary_task_id"])
    rescore = db["scoring_tasks"].get(case["rescore_task_id"])
    if epochs_concordant < 0 or epochs_concordant > rescore["epochs_total"]:
        raise_error(ERR_INVALID_REQUEST,
                    "epochs_concordant must be within 0..rescore_task.epochs_total")
    study = db["sleep_studies"].get(case["study_id"])
    idx_p, idx_r, delta, pct, concordant = adjudication_metrics(
        study["study_type"], primary, rescore, epochs_concordant)
    case["epochs_concordant"] = epochs_concordant
    case["ahi_primary"] = idx_p
    case["ahi_rescore"] = idx_r
    case["ahi_delta"] = delta
    case["percent_agreement"] = pct
    case["concordant"] = concordant
    case["adjudicated_at"] = CLOCK.now_iso()
    case["status"] = "ADJUDICATED"
    touch(case)
    # Rescorer reliability cascade.
    scorer = db["scorers"].get(rescore["scorer_id"])
    if scorer is not None:
        if concordant:
            scorer["consecutive_nonconcordant"] = 0
        else:
            scorer["consecutive_nonconcordant"] = scorer.get("consecutive_nonconcordant", 0) + 1
        recompute_scorer_reliability(scorer)
        touch(scorer)
        if scorer["reliability_status"] == "REMEDIATION":
            _remediation_recall_cascade(scorer)
    return success_object(public(case))
