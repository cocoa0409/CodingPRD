"""AttorneyReview routes: request (ASSEMBLED->IN_REVIEW, pricing, window
occupancy) and attorney-driven transitions (IN_REVIEW / APPROVED /
CHANGES_REQUESTED) with branch side effects."""

from flask import Blueprint, request

import errors
import validators
from common import base_entity, get_or_404, list_collection, parse_datetime, serialize, touch
from db import store
from middleware import get_json_body, get_user_id, parse_pagination, roles
from response import array_response, object_response
from services.pricing import order_for_project, recompute_net, review_surcharge_cents

bp = Blueprint("attorney_reviews", __name__)


def _window_conflicts(attorney_id, start, end, exclude_id=None):
    """Half-open [start, end) overlap against same attorney's non-CANCELLED
    reviews. Back-to-back (one ends as next begins) is allowed."""
    for r in store.attorney_reviews.values():
        if r["id"] == exclude_id:
            continue
        if r["attorney_id"] != attorney_id:
            continue
        if r["status"] == "CANCELLED":
            continue
        other_start = parse_datetime(r["window_start"], "window_start")
        other_end = parse_datetime(r["window_end"], "window_end")
        # Half-open overlap: start < other_end and other_start < end.
        if start < other_end and other_start < end:
            return True
    return False


@bp.route("/legal/attorney-reviews", methods=["POST"])
@roles("Customer")
def create_review():
    body = get_json_body()
    project_id = validators.require_string(body, "document_project_id")
    attorney_id = validators.require_string(body, "attorney_id")
    window_start_raw = validators.require_string(body, "window_start")
    window_end_raw = validators.require_string(body, "window_end")

    # Existence (404), left-to-right.
    project = store.document_projects.get(project_id)
    if project is None:
        raise errors.not_found("document_project_id does not exist")
    attorney = store.attorneys.get(attorney_id)
    if attorney is None:
        raise errors.not_found("attorney_id does not exist")

    # Well-formedness of window datetimes (400).
    start = parse_datetime(window_start_raw, "window_start")
    end = parse_datetime(window_end_raw, "window_end")

    # State validity (409): project must be ASSEMBLED.
    if project["status"] != "ASSEMBLED":
        raise errors.invalid_state("Attorney review requires project status ASSEMBLED")

    # PRD §3.5 order: add-on election, then subscription-active gate.
    if project["attorney_review_addon"] is not True:
        raise errors.ApiError(errors.ERR_REVIEW_ADDON_NOT_ELECTED, 409,
                              "Attorney-review add-on was not elected")

    subscription = store.subscriptions.get(project["subscription_id"])
    if subscription is None or subscription["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_SUBSCRIPTION_NOT_ACTIVE, 403,
                              "Owning subscription is not ACTIVE")

    # Scheduling overlap (409).
    if _window_conflicts(attorney_id, start, end):
        raise errors.ApiError(errors.ERR_ATTORNEY_WINDOW_CONFLICT, 409,
                              "Attorney window overlaps an existing review")

    plan = store.subscription_plans.get(subscription["plan_id"])
    surcharge = review_surcharge_cents(plan)

    ent = base_entity()
    ent.update({
        "document_project_id": project_id,
        "attorney_id": attorney_id,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "status": "ASSIGNED",  # REQUESTED -> ASSIGNED auto on creation
        "surcharge_cents": surcharge,
    })
    store.attorney_reviews[ent["id"]] = ent

    # Project ASSEMBLED -> IN_REVIEW.
    project["status"] = "IN_REVIEW"
    touch(project)

    # Charge surcharge (review_pricing / money_conservation).
    order = order_for_project(project_id)
    if order is not None:
        order["amount_charged_cents"] += surcharge
        recompute_net(order)
        touch(order)

    return object_response(serialize(ent), 201)


@bp.route("/legal/attorney-reviews/<rid>", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def get_review(rid):
    ent = get_or_404(store.attorney_reviews, rid)
    return object_response(serialize(ent), 200)


@bp.route("/legal/attorney-reviews", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def list_reviews():
    limit, offset = parse_pagination()
    project_id = request.args.get("document_project_id")
    attorney_id = request.args.get("attorney_id")

    def predicate(e):
        if project_id is not None and e["document_project_id"] != project_id:
            return False
        if attorney_id is not None and e["attorney_id"] != attorney_id:
            return False
        return True

    page, total = list_collection(store.attorney_reviews, predicate, limit, offset)
    return array_response(page, limit, offset, total, 200)


@bp.route("/legal/attorney-reviews/<rid>/transition", methods=["POST"])
@roles("Attorney")
def transition_review(rid):
    review = get_or_404(store.attorney_reviews, rid)
    body = get_json_body()
    to_status = validators.require_enum(
        body, "to_status", {"IN_REVIEW", "APPROVED", "CHANGES_REQUESTED"}
    )

    # Ownership: acting Attorney must be review.attorney_id (403).
    acting = get_user_id()
    if acting != review["attorney_id"]:
        raise errors.ApiError(errors.ERR_NOT_REVIEW_OWNER, 403,
                              "Acting attorney is not the assigned reviewer")

    current = review["status"]
    project = store.document_projects.get(review["document_project_id"])

    if to_status == "IN_REVIEW":
        if current != "ASSIGNED":
            raise errors.invalid_state("IN_REVIEW requires ASSIGNED")
        review["status"] = "IN_REVIEW"
        touch(review)

    elif to_status == "APPROVED":
        if current != "IN_REVIEW":
            raise errors.invalid_state("APPROVED requires IN_REVIEW")
        review["status"] = "APPROVED"
        touch(review)
        # Branch A: project IN_REVIEW -> ASSEMBLED (window released; no money change).
        if project is not None and project["status"] == "IN_REVIEW":
            project["status"] = "ASSEMBLED"
            touch(project)

    elif to_status == "CHANGES_REQUESTED":
        if current != "IN_REVIEW":
            raise errors.invalid_state("CHANGES_REQUESTED requires IN_REVIEW")
        review["status"] = "CHANGES_REQUESTED"
        touch(review)
        # Branch B: project IN_REVIEW -> CHANGES_REQUESTED.
        if project is not None and project["status"] == "IN_REVIEW":
            project["status"] = "CHANGES_REQUESTED"
            touch(project)
            # Hop C: newest FINAL revision of the project flips to SUPERSEDED.
            finals = [
                rev for rev in store.document_revisions.values()
                if rev["document_project_id"] == project["id"] and rev["status"] == "FINAL"
            ]
            if finals:
                finals.sort(key=lambda rev: rev["_seq"])
                newest = finals[-1]
                newest["status"] = "SUPERSEDED"
                touch(newest)

    return object_response(serialize(review), 200)
