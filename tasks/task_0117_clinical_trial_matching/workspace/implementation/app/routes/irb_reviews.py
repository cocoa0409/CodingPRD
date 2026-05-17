"""IRB review submission and listing."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from ..auth import ROLE_IRB, ROLE_PI, require_roles
from ..clock import now
from ..errors import err_invalid_state, err_sod_violation
from ..helpers import (
    assert_enum,
    assert_string,
    new_uuid,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing
from ..services.lookups import get_trial, irb_reviews_for_trial
from ..services.serialize import serialize_irb_review
from ..store import store

bp = Blueprint("irb_reviews", __name__)


ALLOWED_DECISIONS = ["APPROVED", "REVISIONS_REQUESTED", "REJECTED"]


@bp.post("/trials/<trial_id>/irb-reviews")
@require_roles(ROLE_IRB)
def submit_irb_review(trial_id: str, **caller):
    body = require_json_object()
    decision = assert_enum(body.get("decision"), "decision", ALLOWED_DECISIONS, required=True)
    notes = assert_string(body.get("notes"), "notes", required=True, min_len=1, max_len=1000)
    reviewer_id = caller["_caller_id"]

    with store().lock:
        trial = get_trial(trial_id)
        if trial["status"] != "IRB_PENDING":
            raise err_invalid_state("Trial is not in IRB_PENDING")
        # SoD: reviewer must not be the trial's creator. PRD §2.5.
        if reviewer_id == trial["created_by_user_id"]:
            raise err_sod_violation()

        ts = now()
        review_id = new_uuid()
        review = {
            "id": review_id,
            "trial_id": trial_id,
            "decision": decision,
            "reviewer_id": reviewer_id,
            "decided_at": ts,
            "notes": notes,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        store().irb_reviews[review_id] = review

        # Apply state effects.
        if decision == "APPROVED":
            trial["status"] = "APPROVED"
            trial["irb_decision_note"] = notes
            trial["irb_approval_expires_at"] = ts + timedelta(days=365)
        elif decision == "REVISIONS_REQUESTED":
            trial["status"] = "DRAFT"
            trial["irb_decision_note"] = notes
        elif decision == "REJECTED":
            trial["status"] = "TERMINATED"
            trial["irb_decision_note"] = notes

        trial["updated_at"] = ts
        trial["version"] = trial["version"] + 1

    return created(serialize_irb_review(review))


@bp.get("/trials/<trial_id>/irb-reviews")
@require_roles(ROLE_PI, ROLE_IRB)
def list_irb_reviews(trial_id: str, **_caller):
    limit, offset = parse_pagination()
    with store().lock:
        get_trial(trial_id)
        rows = irb_reviews_for_trial(trial_id)
        total = len(rows)
        page = paginate(rows, limit, offset)
        items = [serialize_irb_review(r) for r in page]
    return listing(items, total, limit, offset)
