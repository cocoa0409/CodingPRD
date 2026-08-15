"""Federal program reviews and corrective actions."""

from flask import Blueprint, request

from core import (db, enum_or_422, err, get_body, get_or_404, mint, paginate,
                  parse_date, pub, req_int, require_roles, success, touch,
                  _MISSING)

bp = Blueprint("reviews", __name__)

SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
BASE_WEIGHT = {"LOW": 10, "MEDIUM": 25, "HIGH": 50}
ESCALATION_SCORE_THRESHOLD = 100

ADVANCE_PATH = {"OPENED": "FINDINGS_ISSUED",
                "FINDINGS_ISSUED": "CORRECTIVE_ACTION",
                "CORRECTIVE_ACTION": "UNDER_VERIFICATION",
                "UNDER_VERIFICATION": "CLOSED"}


def _actions_of(review_id):
    return [a for a in db.corrective_actions.values()
            if a["review_id"] == review_id]


def _is_repeat_finding(action):
    """True iff the same finding_code exists on any CLOSED review."""
    for other in db.corrective_actions.values():
        if other["finding_code"] != action["finding_code"]:
            continue
        review = db.program_reviews.get(other["review_id"])
        if review is not None and review["status"] == "CLOSED":
            return True
    return False


def _weight_of(action):
    w = BASE_WEIGHT[action["severity"]]
    return w * 2 if _is_repeat_finding(action) else w


def _open_count(review):
    return sum(1 for a in _actions_of(review["id"])
               if a["status"] in ("OPEN", "SUBMITTED"))


def _penalty(review):
    return sum(_weight_of(a) for a in _actions_of(review["id"]))


def _serialize_review(review):
    out = pub(review)
    score = _penalty(review)
    out["penalty_score"] = score
    out["escalated"] = score >= ESCALATION_SCORE_THRESHOLD
    out["open_action_count"] = _open_count(review)
    return out


def _serialize_action(action):
    out = pub(action)
    out["is_repeat_finding"] = _is_repeat_finding(action)
    out["weight"] = _weight_of(action)
    return out


@bp.post("/program-reviews")
@require_roles("FederalReviewer")
def create_review():
    data = get_body()
    start = req_int(data, "scope_year_start")
    end = req_int(data, "scope_year_end")
    for r in db.program_reviews.values():
        if r["status"] == "CLOSED":
            continue
        if r["scope_year_start"] <= end and start <= r["scope_year_end"]:
            err("ERR_REVIEW_SCOPE_OVERLAP", 409,
                "Scope overlaps a non-CLOSED program review")
    if end < start:
        err("ERR_VALIDATION_FAILED", 422,
            "scope_year_end must be >= scope_year_start")
    review = mint({"scope_year_start": start,
                   "scope_year_end": end,
                   "opened_at": None,  # set below to creation time
                   "penalty_score": 0,
                   "escalated": False,
                   "open_action_count": 0,
                   "status": "OPENED"})
    review["opened_at"] = review["created_at"]
    db.program_reviews[review["id"]] = review
    return success(_serialize_review(review), 201)


@bp.get("/program-reviews")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def list_reviews():
    items = list(db.program_reviews.values())
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    window, page = paginate(items)
    return success([_serialize_review(e) for e in window], 200, page)


@bp.get("/program-reviews/<rid>")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def get_review(rid):
    return success(_serialize_review(get_or_404(db.program_reviews, rid)), 200)


@bp.post("/program-reviews/<rid>/advance")
@require_roles("FederalReviewer")
def advance_review(rid):
    review = get_or_404(db.program_reviews, rid)
    current = review["status"]
    if current not in ADVANCE_PATH:
        err("ERR_INVALID_STATE", 409,
            "Review in status %s cannot advance" % current)
    if current == "FINDINGS_ISSUED":
        if not _actions_of(rid):
            err("ERR_UNRESOLVED_ACTIONS", 422,
                "At least one corrective action is required")
    elif current in ("CORRECTIVE_ACTION", "UNDER_VERIFICATION"):
        if _open_count(review) != 0:
            err("ERR_UNRESOLVED_ACTIONS", 422,
                "open_action_count must be 0 to advance")
    review["status"] = ADVANCE_PATH[current]
    touch(review)
    return success(_serialize_review(review), 200)


@bp.post("/program-reviews/<rid>/return-for-correction")
@require_roles("FederalReviewer")
def return_for_correction(rid):
    data = get_body()
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        err("ERR_INVALID_REQUEST", 400, "Field note must be a string")
    review = get_or_404(db.program_reviews, rid)
    if review["status"] != "UNDER_VERIFICATION":
        err("ERR_INVALID_STATE", 409,
            "Only an UNDER_VERIFICATION review may be returned for correction")
    if note is not None:
        review["return_note"] = note
    review["status"] = "CORRECTIVE_ACTION"
    touch(review)
    return success(_serialize_review(review), 200)


@bp.post("/program-reviews/<rid>/corrective-actions")
@require_roles("FederalReviewer")
def create_action(rid):
    data = get_body()
    for field in ("finding_code", "severity", "description", "due_date"):
        v = data.get(field)
        if v is None or not isinstance(v, str):
            err("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % field)
    due = parse_date(data["due_date"])
    review = get_or_404(db.program_reviews, rid)
    if review["status"] not in ("FINDINGS_ISSUED", "CORRECTIVE_ACTION"):
        err("ERR_INVALID_STATE", 409,
            "Actions may be added only in FINDINGS_ISSUED or "
            "CORRECTIVE_ACTION")
    enum_or_422(data["severity"], SEVERITIES, "severity")
    opened_date = parse_date(review["opened_at"][:10])
    if due < opened_date:
        err("ERR_VALIDATION_FAILED", 422,
            "due_date must be >= the review opened date")
    action = mint({"review_id": rid,
                   "finding_code": data["finding_code"],
                   "severity": data["severity"],
                   "description": data["description"],
                   "due_date": data["due_date"],
                   "is_repeat_finding": False,
                   "weight": 0,
                   "resolution_summary": None,
                   "rejection_count": 0,
                   "verification_note": None,
                   "status": "OPEN"})
    db.corrective_actions[action["id"]] = action
    touch(review)  # open_action_count / penalty_score change
    return success(_serialize_action(action), 201)


@bp.get("/program-reviews/<rid>/corrective-actions")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def list_actions(rid):
    get_or_404(db.program_reviews, rid)
    items = _actions_of(rid)
    window, page = paginate(items)
    return success([_serialize_action(e) for e in window], 200, page)


@bp.post("/corrective-actions/<aid>/submit")
@require_roles("CleryCoordinator")
def submit_action(aid):
    data = get_body()
    summary = data.get("resolution_summary", _MISSING)
    if summary is _MISSING or not isinstance(summary, str):
        err("ERR_INVALID_REQUEST", 400,
            "Field resolution_summary must be a string")
    action = get_or_404(db.corrective_actions, aid)
    if action["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Only an OPEN action may be submitted")
    review = db.program_reviews.get(action["review_id"])
    if review is None or review["status"] != "CORRECTIVE_ACTION":
        err("ERR_INVALID_STATE", 409,
            "Parent review must be in CORRECTIVE_ACTION")
    action["resolution_summary"] = summary
    action["status"] = "SUBMITTED"
    touch(action)
    return success(_serialize_action(action), 200)


@bp.post("/corrective-actions/<aid>/verify")
@require_roles("FederalReviewer")
def verify_action(aid):
    action = get_or_404(db.corrective_actions, aid)
    if action["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409,
            "Only a SUBMITTED action may be verified")
    action["status"] = "VERIFIED"
    touch(action)
    review = db.program_reviews.get(action["review_id"])
    if review is not None:
        if _open_count(review) == 0 and review["status"] == "CORRECTIVE_ACTION":
            review["status"] = "UNDER_VERIFICATION"
        touch(review)
    return success(_serialize_action(action), 200)


@bp.post("/corrective-actions/<aid>/reject")
@require_roles("FederalReviewer")
def reject_action(aid):
    data = get_body()
    note = data.get("verification_note", _MISSING)
    if note is _MISSING or not isinstance(note, str):
        err("ERR_INVALID_REQUEST", 400,
            "Field verification_note must be a string")
    action = get_or_404(db.corrective_actions, aid)
    if action["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409,
            "Only a SUBMITTED action may be rejected")
    action["status"] = "OPEN"
    action["rejection_count"] += 1
    action["verification_note"] = note
    touch(action)
    review = db.program_reviews.get(action["review_id"])
    if review is not None:
        touch(review)
    return success(_serialize_action(action), 200)
