"""AttributeScore submission (PRD §3.5): ownership-bound, auto-SUBMITTED
on the sixth distinct attribute."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_FORBIDDEN_ROLE, ERR_INVALID_SESSION_STATE,
    ERR_SCORE_OUT_OF_RANGE, ERR_SCORE_ALREADY_SUBMITTED,
    ERR_PANELIST_NOT_QUALIFIED,
)
from flask import Blueprint, g, request
from response import respond, respond_list
from services import ser_score, scores_of_assignment, ATTRIBUTES
from util import body, paginate, req_field, req_str, sort_created, touch

bp = Blueprint("scores", __name__)


def get_score(score_id):
    s = db.store["scores"].get(score_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, f"AttributeScore {score_id} not found")
    return s


@bp.route("/attribute-scores", methods=["POST"])
@require_roles("Panelist")
def create_score():
    b = body()
    assignment_id = req_str(b, "assignment_id")
    attribute = req_field(b, "attribute")
    if attribute not in ATTRIBUTES:
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST,
                  f"attribute must be one of {sorted(ATTRIBUTES)}")
    if "score" not in b or b["score"] is None:
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, "Missing required field: score")
    score_value = b["score"]
    assignment = db.store["assignments"].get(assignment_id)
    if assignment is None:
        raise_err(ERR_NOT_FOUND, f"PanelAssignment {assignment_id} not found")
    # Ownership: a panelist scores only their own assignment (PRD §2.1).
    if assignment["panelist_id"] != g.user_id:
        raise_err(ERR_FORBIDDEN_ROLE,
                  "a panelist may only score their own assignment")
    session = db.store["sessions"][assignment["session_id"]]
    if session["status"] != "OPEN":
        raise_err(ERR_INVALID_SESSION_STATE,
                  "scores may be submitted only while the session is OPEN")
    if (not isinstance(score_value, int) or isinstance(score_value, bool)
            or score_value < 1 or score_value > 15):
        raise_err(ERR_SCORE_OUT_OF_RANGE,
                  "score must be an integer within 1..15")
    existing = scores_of_assignment(assignment_id)
    for sc in existing:
        if sc["attribute"] == attribute:
            raise_err(ERR_SCORE_ALREADY_SUBMITTED,
                      "a score for this (assignment_id, attribute) already "
                      "exists")
    panelist = db.store["panelists"][assignment["panelist_id"]]
    if attribute not in panelist["qualified_attributes"]:
        raise_err(ERR_PANELIST_NOT_QUALIFIED,
                  "attribute is not in the panelist's qualified_attributes")
    score = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "assignment_id": assignment_id,
        "attribute": attribute,
        "score": score_value,
        "created_at": clock.now(),
    }
    db.store["scores"][score["id"]] = score
    # The 6th distinct attribute flips the assignment to SUBMITTED and
    # resets the panelist's consecutive_no_shows (PRD §3.5).
    if len(existing) + 1 == len(ATTRIBUTES):
        if assignment["status"] == "ASSIGNED":
            assignment["status"] = "SUBMITTED"
            touch(assignment)
        if panelist["consecutive_no_shows"] != 0:
            panelist["consecutive_no_shows"] = 0
            touch(panelist)
    return respond(ser_score(score), 201)


@bp.route("/attribute-scores", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_scores():
    items = sort_created(db.store["scores"].values())
    assignment_id = request.args.get("assignment_id")
    if assignment_id is not None:
        items = [s for s in items if s["assignment_id"] == assignment_id]
    page, pagination = paginate(items)
    return respond_list([ser_score(s) for s in page], pagination)


@bp.route("/attribute-scores/<score_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_score(score_id):
    return respond(ser_score(get_score(score_id)), 200)
