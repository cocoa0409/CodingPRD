"""DateCodeRecommendation proposal, acceptance, rejection (PRD §3.7)."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STUDY_STATE,
    ERR_STALE_STUDY_VERSION, ERR_ARM_STUDY_MISMATCH, ERR_RECO_NOT_PROPOSED,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import (
    ser_recommendation, date_code_for, supersede_recommendation,
    arms_of_study,
)
from util import body, paginate, req_str, sort_created, touch

bp = Blueprint("recommendations", __name__)


def get_rec(rec_id):
    r = db.store["recommendations"].get(rec_id)
    if r is None:
        raise_err(ERR_NOT_FOUND,
                  f"DateCodeRecommendation {rec_id} not found")
    return r


@bp.route("/date-code-recommendations", methods=["POST"])
@require_roles("SensoryScientist")
def create_recommendation():
    b = body()
    study_id = req_str(b, "study_id")
    arm_id = req_str(b, "arm_id")
    if "expected_study_version" not in b or b["expected_study_version"] is None:
        raise_err(ERR_INVALID_REQUEST,
                  "Missing required field: expected_study_version")
    expected = b["expected_study_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST,
                  "expected_study_version must be an integer")
    study = db.store["studies"].get(study_id)
    if study is None:
        raise_err(ERR_NOT_FOUND, f"Study {study_id} not found")
    arm = db.store["arms"].get(arm_id)
    if arm is None:
        raise_err(ERR_NOT_FOUND, f"StudyArm {arm_id} not found")
    # OCC guard (PRD §2.6 rung 4): after existence, before state.
    if expected != study["version"]:
        raise_err(ERR_STALE_STUDY_VERSION,
                  f"expected_study_version {expected} does not match "
                  f"current version {study['version']}")
    if study["status"] not in ("ANALYSIS", "REPORTING"):
        raise_err(ERR_INVALID_STUDY_STATE,
                  "recommendations require the study to be ANALYSIS or "
                  "REPORTING")
    if arm["study_id"] != study_id:
        raise_err(ERR_ARM_STUDY_MISMATCH,
                  "arm_id does not belong to the study")
    basis, computed_days = date_code_for(arm, study)
    # A new PROPOSED supersedes the arm's existing PROPOSED (PRD §3.7).
    for rec in db.store["recommendations"].values():
        if rec["arm_id"] == arm_id and rec["status"] == "PROPOSED":
            supersede_recommendation(rec)
    now = clock.now()
    rec = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "study_id": study_id,
        "arm_id": arm_id,
        "basis": basis,
        "computed_days": computed_days,
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["recommendations"][rec["id"]] = rec
    touch(study)  # creation increments Study.version by 1 (§2.7)
    return respond(ser_recommendation(rec), 201)


@bp.route("/date-code-recommendations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_recommendations():
    items = sort_created(db.store["recommendations"].values())
    for field in ("study_id", "arm_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [r for r in items if r[field] == v]
    page, pagination = paginate(items)
    return respond_list([ser_recommendation(r) for r in page], pagination)


@bp.route("/date-code-recommendations/<rec_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_recommendation(rec_id):
    return respond(ser_recommendation(get_rec(rec_id)), 200)


@bp.route("/date-code-recommendations/<rec_id>/accept", methods=["POST"])
@require_roles("SensoryScientist")
def accept_recommendation(rec_id):
    rec = get_rec(rec_id)
    if rec["status"] != "PROPOSED":
        raise_err(ERR_RECO_NOT_PROPOSED,
                  "accept requires the recommendation to be PROPOSED")
    study = db.store["studies"][rec["study_id"]]
    if study["status"] not in ("ANALYSIS", "REPORTING"):
        raise_err(ERR_INVALID_STUDY_STATE,
                  "accept requires the study to be ANALYSIS or REPORTING")
    rec["status"] = "ACCEPTED"
    touch(rec)
    # Auto-advance ANALYSIS -> REPORTING once every arm holds an ACCEPTED
    # recommendation (PRD §3.7).
    if study["status"] == "ANALYSIS":
        arms = arms_of_study(study["id"])
        accepted_arms = {r["arm_id"] for r in
                         db.store["recommendations"].values()
                         if r["study_id"] == study["id"]
                         and r["status"] == "ACCEPTED"}
        if arms and all(a["id"] in accepted_arms for a in arms):
            study["status"] = "REPORTING"
            touch(study)
    return respond(ser_recommendation(rec), 200)


@bp.route("/date-code-recommendations/<rec_id>/reject", methods=["POST"])
@require_roles("SensoryScientist")
def reject_recommendation(rec_id):
    rec = get_rec(rec_id)
    if rec["status"] != "PROPOSED":
        raise_err(ERR_RECO_NOT_PROPOSED,
                  "reject requires the recommendation to be PROPOSED")
    rec["status"] = "REJECTED"
    touch(rec)
    return respond(ser_recommendation(rec), 200)
