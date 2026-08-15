"""AbandonmentReview routes (PRD §3.6): proposal with OCC, segregation-of-duties
decision pair, and the executing depth-3 abandonment cascade."""

from flask import Blueprint

import db as dbmod
import serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_CLIENT_SUSPENDED,
    ERR_REVIEW_ALREADY_OPEN,
    ERR_FAMILY_NOT_IN_PRUNING_REVIEW,
)
from middleware import require_roles, get_json_body, ALL_ROLES
from response import success_object, success_list_all
from services.common import (
    new_id, stamp_new, bump, get_application, get_review,
    family_of_application, client_of_application,
    check_allowed_fields, req_str, ensure_transition,
)
from services import calc
from services.cascade import application_terminal_cascade

bp = Blueprint("reviews", __name__)

REVIEW_OPEN = {"PROPOSED", "UNDER_REVIEW", "APPROVED"}


@bp.post("/applications/<application_id>/abandonment-reviews")
def create_review(application_id):
    require_roles(["DocketingManager"])
    app = get_application(application_id)
    body = get_json_body()
    # OCC (priority 5) precedes body-shape validation (priority 6).
    expected = body.get("expected_application_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != app["version"]:
            raise_err(ERR_STALE_VERSION, "expected_application_version is stale")
    check_allowed_fields(body, {"rationale", "expected_application_version"})
    rationale = req_str(body, "rationale")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_application_version is required and must be an integer")
    # Business order: open-review check (18) before the suspended-client gate (24).
    if any(
        rv["application_id"] == app["id"] and rv["status"] in REVIEW_OPEN
        for rv in dbmod.DB["reviews"].values()
    ):
        raise_err(ERR_REVIEW_ALREADY_OPEN, "An open AbandonmentReview already exists for this application")
    client = client_of_application(app)
    if client["status"] == "SUSPENDED":
        raise_err(ERR_CLIENT_SUSPENDED, "Client is SUSPENDED")
    rec = stamp_new({
        "id": new_id(),
        "application_id": app["id"],
        "rationale": rationale,
        "estimated_savings_usd_cents": calc.pruning_savings_estimate(app["id"]),
        "submitted_by_user_id": None,
        "status": "PROPOSED",
    })
    dbmod.DB["reviews"][rec["id"]] = rec
    bump(app)  # proposal opens review state: Application.version += 1
    return success_object(serialize.review(rec), 201)


@bp.get("/applications/<application_id>/abandonment-reviews")
def list_application_reviews(application_id):
    require_roles(ALL_ROLES)
    app = get_application(application_id)
    items = [r for r in dbmod.DB["reviews"].values() if r["application_id"] == app["id"]]
    items.sort(key=lambda r: r["created_at"])
    return success_list_all([serialize.review(r) for r in items])


@bp.get("/abandonment-reviews/<review_id>")
def get_review_route(review_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.review(get_review(review_id)))


@bp.post("/abandonment-reviews/<review_id>/submit")
def submit_review(review_id):
    user_id, _ = require_roles(["DocketingManager"])
    rec = get_review(review_id)
    ensure_transition(rec, {"PROPOSED"}, "reviews", "AbandonmentReview")
    rec["status"] = "UNDER_REVIEW"
    rec["submitted_by_user_id"] = user_id
    bump(rec)
    return success_object(serialize.review(rec))


@bp.post("/abandonment-reviews/<review_id>/approve")
def approve_review(review_id):
    user_id, _ = require_roles(["DocketingManager"])
    rec = get_review(review_id)
    ensure_transition(rec, {"UNDER_REVIEW"}, "reviews", "AbandonmentReview")
    if user_id == rec["submitted_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Approver must differ from the submitter")
    rec["status"] = "APPROVED"
    bump(rec)
    return success_object(serialize.review(rec))


@bp.post("/abandonment-reviews/<review_id>/reject")
def reject_review(review_id):
    user_id, _ = require_roles(["DocketingManager"])
    rec = get_review(review_id)
    ensure_transition(rec, {"UNDER_REVIEW"}, "reviews", "AbandonmentReview")
    if user_id == rec["submitted_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Rejector must differ from the submitter")
    rec["status"] = "REJECTED"
    bump(rec)
    return success_object(serialize.review(rec))


@bp.post("/abandonment-reviews/<review_id>/execute")
def execute_review(review_id):
    require_roles(["DocketingManager"])
    rec = get_review(review_id)
    ensure_transition(rec, {"APPROVED"}, "reviews", "AbandonmentReview")
    app = dbmod.DB["applications"][rec["application_id"]]
    family = family_of_application(app)
    if family["status"] != "PRUNING_REVIEW":
        raise_err(ERR_FAMILY_NOT_IN_PRUNING_REVIEW, "Family is not in PRUNING_REVIEW")
    # Hop 1: application abandonment; hops 2-3 fire inside the cascade.
    if app["status"] in ("PENDING", "GRANTED"):
        application_terminal_cascade(app, "ABANDONED")
    rec["status"] = "EXECUTED"
    bump(rec)
    return success_object(serialize.review(rec))
