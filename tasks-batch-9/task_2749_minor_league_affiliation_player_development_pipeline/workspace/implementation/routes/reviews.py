"""League facility / player-standard inspection endpoints (PRD Section 3.1)."""
from flask import Blueprint

import auth
import calc
import common
import config
import derive
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("reviews", __name__)

TRANSITIONS = {
    "SUBMIT_REMEDIATION": ("OPEN", "REOPENED"),
    "CLOSE": ("REMEDIATION_SUBMITTED",),
    "REOPEN": ("CLOSED",),
    "WAIVE": ("OPEN", "REOPENED"),
}


@bp.post("/affiliates/<affiliate_id>/facility-reviews")
def file_review(affiliate_id):
    user_id, role = auth.require(config.ROLE_COMPLIANCE)
    auth.check_scope(role, user_id, affiliate_id)
    common.need("affiliates", affiliate_id)
    body = validate.json_body()
    category = validate.enum_field(body, "category", config.REVIEW_CATEGORIES)
    review_date = validate.date_field(body, "review_date")
    score = validate.int_field(body, "score", lo=0, hi=100)

    level = calc.deficiency_level_for(score)
    record = store.base_record()
    if level == "NONE":
        status = "CLOSED"
        due = None
    else:
        status = "OPEN"
        due = store.iso_date(store.add_days(store.parse_date(review_date),
                                           config.REMEDIATION_DAYS[level]))
    record.update({
        "affiliate_id": affiliate_id,
        "category": category,
        "review_date": review_date,
        "score": score,
        "deficiency_level": level,
        "status": status,
        "remediation_due_date": due,
        "remediation_note": None,
        "remediation_submitted_at": None,
        "reopen_count": 0,
        "waiver_granted_by_user_id": None,
        "is_overdue": False,
    })
    store.reviews[record["id"]] = record
    common.commit()
    return envelope.object_response(serialize.review(record), 201)


@bp.get("/affiliates/<affiliate_id>/facility-reviews")
def list_reviews(affiliate_id):
    auth.require(config.ROLE_FARM, config.ROLE_COMPLIANCE, config.ROLE_OPERATOR)
    common.need("affiliates", affiliate_id)
    rows = derive.reviews_of(affiliate_id)
    rows = common.apply_filters(rows, (("category", "category"), ("status", "status")))
    return envelope.paginate(rows, serialize.review)


@bp.post("/facility-reviews/<review_id>/disposition")
def dispose_review(review_id):
    user_id, role = auth.require(config.ROLE_OPERATOR, config.ROLE_COMPLIANCE)
    raw = auth.raw_body()
    review = common.find("reviews", review_id)
    if review is not None:
        auth.check_scope(role, user_id, review["affiliate_id"])
    auth.check_action_role(raw.get("action"), role, config.REVIEW_ACTION_ROLES)
    if review is None:
        raise ApiError("ERR_FACILITY_REVIEW_NOT_FOUND")

    body = validate.json_body()
    action = auth.require_action(body, config.REVIEW_ACTION_ROLES)
    remediation_note = validate.str_field(body, "remediation_note", required=False,
                                          default=None, allow_blank=True)
    validate.str_field(body, "note", required=False, default=None, allow_blank=True)

    if review["status"] not in TRANSITIONS[action]:
        raise ApiError("ERR_INVALID_REVIEW_STATE",
                       "An inspection in status %s does not accept %s."
                       % (review["status"], action))

    if action == "SUBMIT_REMEDIATION":
        due = store.parse_date(review.get("remediation_due_date"))
        if due is None or store.clock_date() > due:
            raise ApiError("ERR_REMEDIATION_WINDOW_CLOSED")

    if action == "REOPEN":
        if review["reopen_count"] >= config.MAX_REVIEW_REOPENS:
            raise ApiError("ERR_CYCLE_LIMIT_REACHED")

    if action == "WAIVE":
        if review["deficiency_level"] != "MINOR":
            raise ApiError("ERR_WAIVER_NOT_PERMITTED",
                           "Only a MINOR finding may be waived.")

    store.touch(review)
    if action == "SUBMIT_REMEDIATION":
        review["status"] = "REMEDIATION_SUBMITTED"
        review["remediation_note"] = remediation_note
        review["remediation_submitted_at"] = store.now_iso()
    elif action == "CLOSE":
        review["status"] = "CLOSED"
    elif action == "REOPEN":
        review["status"] = "REOPENED"
        review["reopen_count"] = review["reopen_count"] + 1
        review["remediation_due_date"] = store.iso_date(
            store.add_days(store.clock_date(), config.REMEDIATION_REOPEN_DAYS))
    elif action == "WAIVE":
        review["status"] = "WAIVED"
        review["waiver_granted_by_user_id"] = user_id

    common.commit()
    return envelope.object_response(serialize.review(review))
