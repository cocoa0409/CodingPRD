"""Public review announcement, closing and disposition approval (PRD 3.6)."""

from flask import Blueprint

from core import auth, envelope
from core.errors import fail
from core.store import db, insert, now, now_iso, public, rows, touch
from core.util import date_part
from core.validation import Body, apply_filters, load_fk, load_path, no_body
from services import graph, reviews as review_service

bp = Blueprint("public_reviews", __name__)

FILTERS = ("draft_id", "disposition_approved_by_participant_id", "status")

ANNOUNCEABLE = ("PUBLIC_REVIEW_READY", "PUBLIC_REVIEW")


@bp.post("/sdo/public-reviews")
def announce_review():
    auth.authenticate((auth.STANDARDS_STAFF,))
    body = Body(("draft_id", "start_date", "end_date", "expected_draft_version"))
    draft_id = body.id_ref("draft_id", required=True)
    start_date = body.date("start_date", required=True)
    end_date = body.date("end_date", required=True)
    expected_draft_version = body.integer("expected_draft_version", required=True,
                                          minimum=0)

    draft = load_fk("drafts", draft_id, optional=False)

    existing = graph.reviews_of_draft(draft)
    if draft["status"] == "PUBLIC_REVIEW":
        # Supersession path: only an announcement that has not yet started may be
        # replaced.
        for review in existing:
            if review["status"] not in ("SCHEDULED", "CANCELLED"):
                fail("ERR_INVALID_DRAFT_STATE",
                     "The draft already carries a live public review.")
    elif draft["status"] != "PUBLIC_REVIEW_READY":
        fail("ERR_INVALID_DRAFT_STATE",
             "A draft in %s cannot be offered for public review." % draft["status"])

    if expected_draft_version != draft["version"]:
        fail("ERR_STALE_DRAFT_VERSION",
             "expected_draft_version %d does not match the draft's version %d."
             % (expected_draft_version, draft["version"]))

    duration = review_service.duration_days(start_date, end_date)
    if start_date > end_date or duration < review_service.MIN_REVIEW_DAYS:
        fail("ERR_REVIEW_PERIOD_TOO_SHORT",
             "A public review period must span at least %d inclusive days."
             % review_service.MIN_REVIEW_DAYS)

    work_item = graph.work_item_of_draft(draft)
    if work_item is not None:
        if review_service.buffer_conflict(work_item, start_date, end_date) is not None:
            fail("ERR_REVIEW_WINDOW_BUFFER_CONFLICT",
                 "The period falls within 15 days of another review on this work item.")

    status = "OPEN" if start_date <= date_part(now()) else "SCHEDULED"
    row = insert("public_reviews", {
        "draft_id": draft["id"],
        "start_date": body.raw("start_date"),
        "end_date": body.raw("end_date"),
        "duration_days": duration,
        "status": status,
        "announced_at": now_iso(),
        "closed_at": None,
        "comment_count": 0,
        "disposed_count": 0,
        "unresolved_comment_count": 0,
        "disposition_completeness_pct": 100.0,
        "disposition_approved_by_participant_id": None,
        "disposition_approved_at": None,
        "_start_date": start_date,
        "_end_date": end_date,
    })

    for review in existing:
        if review["status"] == "SCHEDULED":
            # The cancelled announcement keeps its own comment_count on the record.
            review["status"] = "CANCELLED"
            touch(review)

    draft["status"] = "PUBLIC_REVIEW"
    touch(draft)
    return envelope.created(public(row))


@bp.get("/sdo/public-reviews")
def list_reviews():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("public_reviews"), FILTERS))


@bp.get("/sdo/public-reviews/<public_review_id>")
def get_review(public_review_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(public(load_path("public_reviews", public_review_id)))


@bp.post("/sdo/public-reviews/<public_review_id>/close")
def close_review(public_review_id):
    auth.authenticate((auth.STANDARDS_STAFF,))
    review = load_path("public_reviews", public_review_id)
    no_body()

    if review["status"] != "OPEN":
        fail("ERR_INVALID_PUBLIC_REVIEW_STATE", "Only an OPEN review may be closed.")

    if date_part(now()) <= review["_end_date"]:
        fail("ERR_REVIEW_NOT_ENDED",
             "The last day of the inclusive review period has not fully elapsed.")

    review["closed_at"] = now_iso()
    review["status"] = "CLOSED"
    review_service.recompute_counters(review)
    if review["comment_count"] == 0:
        # A review that drew no comments is 100.0 percent disposed by definition and
        # skips DISPOSITION_DRAFTED entirely; nobody approved it, so the approver
        # stays null.
        review["status"] = "DISPOSITION_APPROVED"
        review["disposition_completeness_pct"] = 100.0
        review["disposition_approved_at"] = now_iso()
        review["disposition_approved_by_participant_id"] = None
    touch(review)

    draft = db.drafts.get(review["draft_id"])
    if draft is not None:
        if draft["status"] == "PUBLIC_REVIEW":
            draft["status"] = "PUBLIC_REVIEW_CLOSED"
        touch(draft)
    return envelope.object_response(public(review))


@bp.post("/sdo/public-reviews/<public_review_id>/approve-disposition")
def approve_disposition(public_review_id):
    auth.authenticate((auth.STANDARDS_STAFF, auth.COMMITTEE_CHAIR))
    review = load_path("public_reviews", public_review_id)
    no_body()

    if review["status"] != "DISPOSITION_DRAFTED":
        fail("ERR_INVALID_PUBLIC_REVIEW_STATE",
             "Only a DISPOSITION_DRAFTED review may be approved.")

    if review["disposition_completeness_pct"] != 100.0:
        fail("ERR_DISPOSITION_INCOMPLETE",
             "The disposition record is only %.1f percent complete."
             % review["disposition_completeness_pct"])

    draft = db.drafts.get(review["draft_id"])
    work_item = graph.work_item_of_draft(draft) if draft is not None else None
    committee = graph.sponsoring_committee(work_item)
    if committee is not None and auth.caller_id() == committee.get("chair_participant_id"):
        fail("ERR_DISPOSITION_APPROVER_CONFLICT",
             "Whoever wrote the dispositions may not sign them off.")

    review["status"] = "DISPOSITION_APPROVED"
    review["disposition_approved_at"] = now_iso()
    if auth.caller_role() == auth.COMMITTEE_CHAIR:
        review["disposition_approved_by_participant_id"] = auth.caller_id()
    else:
        review["disposition_approved_by_participant_id"] = None
    touch(review)
    return envelope.object_response(public(review))
