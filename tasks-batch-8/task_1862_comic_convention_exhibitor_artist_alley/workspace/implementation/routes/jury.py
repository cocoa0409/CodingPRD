"""JuryScore routes."""

from flask import Blueprint, request

import db
from errors import fail
from helpers import (get_json_body, require_str, require_int, paginate,
                     sort_by_created, get_or_404)
from middleware import require_roles
from response import success_object, success_list
from services import calc

bp = Blueprint("jury", __name__)


def score_view(s):
    return {k: s[k] for k in (
        "id", "application_id", "juror_user_id", "originality", "craft",
        "category_fit", "professionalism", "weighted_total", "created_at")}


@bp.route("/jury-scores", methods=["POST"])
def create_jury_score():
    user_id, _ = require_roles("JuryMember")
    body = get_json_body()
    application_id = require_str(body, "application_id")
    originality = require_int(body, "originality", minimum=0, maximum=100)
    craft = require_int(body, "craft", minimum=0, maximum=100)
    category_fit = require_int(body, "category_fit", minimum=0, maximum=100)
    professionalism = require_int(body, "professionalism", minimum=0, maximum=100)

    a = db.applications.get(application_id)
    if a is None:
        fail("ERR_NOT_FOUND", "application_id does not exist")
    conv = db.conventions[a["convention_id"]]
    # phase gate (temporal) then state gate
    if conv["phase"] != "JURY_REVIEW":
        fail("ERR_PHASE_PRECONDITION", "Scoring requires phase JURY_REVIEW")
    if a["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        fail("ERR_INVALID_TRANSITION",
             "Application must be SUBMITTED or UNDER_REVIEW")
    if user_id in a["conflicted_juror_user_ids"]:
        fail("ERR_JURY_CONFLICT_OF_INTEREST",
             "Juror is barred from scoring this application")
    for js in db.jury_scores.values():
        if js["application_id"] == application_id and js["juror_user_id"] == user_id:
            fail("ERR_DUPLICATE_JURY_SCORE",
                 "This juror has already scored the application")

    s = {
        "id": db.new_id(),
        "application_id": application_id,
        "juror_user_id": user_id,
        "originality": originality,
        "craft": craft,
        "category_fit": category_fit,
        "professionalism": professionalism,
        "weighted_total": calc.jury_weighted_total(originality, craft, category_fit, professionalism),
        "created_at": db.now_iso(),
    }
    db.jury_scores[s["id"]] = s

    # first score moves SUBMITTED -> UNDER_REVIEW
    if a["status"] == "SUBMITTED":
        a["status"] = "UNDER_REVIEW"
    a["jury_composite_score"] = calc.jury_composite(application_id)
    db.touch(a)
    return success_object(score_view(s), 201)


@bp.route("/jury-scores", methods=["GET"])
def list_jury_scores():
    require_roles("ShowDirector", "JuryMember")
    items = list(db.jury_scores.values())
    for f in ("application_id", "juror_user_id"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s[f] == v]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([score_view(s) for s in page], limit, offset, total)


@bp.route("/jury-scores/<juryScoreId>", methods=["GET"])
def get_jury_score(juryScoreId):
    require_roles("ShowDirector", "JuryMember")
    s = get_or_404(db.jury_scores, juryScoreId)
    return success_object(score_view(s), 200)
