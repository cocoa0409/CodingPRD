"""Script clearance reviews, items and waivers (PRD 3.7)."""
from flask import Blueprint

from db import base_row, db, touch
from errors import ApiError
from middleware import LEGAL_COUNSEL, SHOWRUNNER, STUDIO_EXECUTIVE, fetch, require
from response import created, ok
from routes.common import list_out, match, out
from services import calc, domain
from validation import body_json, filter_value, raw, v_enum, v_str

bp = Blueprint("clearance", __name__)

READ_ROLES = (LEGAL_COUNSEL, SHOWRUNNER, STUDIO_EXECUTIVE)
DRAFT_STATUSES = ("DELIVERED", "NOTES_ISSUED", "ACCEPTED")


def _review_context(review):
    assignment = db.assignments[review["assignment_id"]]
    episode = db.episodes[assignment["episode_id"]]
    season = db.seasons[episode["season_id"]]
    return assignment, episode, season


@bp.post("/script-assignments/<assignment_id>/clearance-reviews")
def open_review(assignment_id):
    require(LEGAL_COUNSEL)
    assignment = fetch(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    episode = domain.episode_of_assignment(assignment)
    season = domain.season_of_episode(episode)
    body = body_json()
    milestone_ref = raw(body, "reviewed_draft_milestone_id")
    milestone = None
    if milestone_ref is not None:
        milestone = fetch(db.milestones, milestone_ref, "ERR_MILESTONE_NOT_FOUND")
    if milestone is None:
        raise ApiError("ERR_INVALID_REQUEST")
    # 19. review linkage
    if (milestone["assignment_id"] != assignment["id"]
            or milestone["status"] not in DRAFT_STATUSES):
        raise ApiError("ERR_MILESTONE_NOT_IN_ASSIGNMENT")
    row = base_row()
    row["assignment_id"] = assignment["id"]
    row["reviewed_draft_milestone_id"] = milestone["id"]
    row["item_count"] = 0
    row["decided_item_count"] = 0
    row["risk_score"] = 0
    row["posture"] = "PENDING"
    row["legal_waiver_granted"] = False
    row["waiver_memo"] = None
    db.reviews[row["id"]] = row
    if episode["clearance_posture"] != "PENDING":
        episode["clearance_posture"] = "PENDING"
        touch(episode)
        domain.recompute_coverage(season)
    return created(out(row))


@bp.post("/clearance-reviews/<review_id>/items")
def add_item(review_id):
    require(LEGAL_COUNSEL)
    review = fetch(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")
    assignment, episode, season = _review_context(review)
    body = body_json()
    row = base_row()
    row["item_type"] = v_enum(body, "item_type", calc.CLEARANCE_ITEM_TYPES)
    row["descriptor"] = v_str(body, "descriptor", 1, 200)
    row["scene_reference"] = v_str(body, "scene_reference", 1, 80)
    if review["posture"] == "CONDITIONAL_WAIVED":
        raise ApiError("ERR_REVIEW_WAIVED")
    row["review_id"] = review["id"]
    row["decision"] = "SUBMITTED"
    row["risk_weight"] = 0
    row["conditional_note"] = None
    db.items[row["id"]] = row
    posture = domain.recompute_review(review)
    touch(review)
    domain.mirror_clearance(review, posture)
    domain.recompute_coverage(season)
    return created(out(row))


@bp.post("/clearance-items/<item_id>/decide")
def decide_item(item_id):
    require(LEGAL_COUNSEL)
    item = fetch(db.items, item_id, "ERR_ITEM_NOT_FOUND")
    review = db.reviews[item["review_id"]]
    assignment, episode, season = _review_context(review)
    agreement = domain.agreement_of(season)
    body = body_json()
    decision = v_enum(body, "decision", ("CLEARED", "CONDITIONAL", "BLOCKED"))
    note = v_str(body, "conditional_note", 1, 500, required=False)
    if item["decision"] != "SUBMITTED":
        raise ApiError("ERR_ITEM_ALREADY_DECIDED")
    if review["posture"] == "CONDITIONAL_WAIVED":
        raise ApiError("ERR_REVIEW_WAIVED")
    if decision == "CONDITIONAL" and not note:
        raise ApiError("ERR_CONDITIONAL_NOTE_REQUIRED")
    item["decision"] = decision
    item["risk_weight"] = (agreement["clearance_item_weights"][item["item_type"]]
                           * calc.DECISION_MULTIPLIER[decision])
    item["conditional_note"] = note if decision == "CONDITIONAL" else None
    touch(item)
    posture = domain.recompute_review(review)
    touch(review)
    domain.mirror_clearance(review, posture)
    domain.recompute_coverage(season)
    return ok(out(item))


@bp.post("/clearance-reviews/<review_id>/waiver")
def grant_waiver(review_id):
    require(LEGAL_COUNSEL)
    review = fetch(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")
    assignment, episode, season = _review_context(review)
    body = body_json()
    memo = v_str(body, "waiver_memo", 1, 1000)
    if review["posture"] != "CONDITIONAL":
        raise ApiError("ERR_WAIVER_NOT_APPLICABLE")
    review["posture"] = "CONDITIONAL_WAIVED"
    review["legal_waiver_granted"] = True
    review["waiver_memo"] = memo
    touch(review)
    domain.mirror_clearance(review, "CONDITIONAL_WAIVED")
    domain.recompute_coverage(season)
    return ok(out(review))


@bp.get("/clearance-reviews/<review_id>")
def get_review(review_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")))


@bp.get("/clearance-reviews")
def list_reviews():
    require(*READ_ROLES)
    rows = list(db.reviews.values())
    rows = match(rows, "assignment_id", filter_value("assignment_id"))
    rows = match(rows, "reviewed_draft_milestone_id",
                 filter_value("reviewed_draft_milestone_id"))
    rows = match(rows, "posture", filter_value("posture"))
    return list_out(rows)


@bp.get("/clearance-items/<item_id>")
def get_item(item_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.items, item_id, "ERR_ITEM_NOT_FOUND")))


@bp.get("/clearance-items")
def list_items():
    require(*READ_ROLES)
    rows = list(db.items.values())
    rows = match(rows, "review_id", filter_value("review_id"))
    rows = match(rows, "item_type", filter_value("item_type"))
    rows = match(rows, "decision", filter_value("decision"))
    return list_out(rows)
