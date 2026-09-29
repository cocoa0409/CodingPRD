"""Authoring, reviewing and dispatching the answer (PRD §3.6)."""
from flask import Blueprint

import calc
import validation as V
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from serializers import draft_out
from store import (ACTIVE_DRAFT_STATUSES, DISCLOSURE_CLASSES, DRAFT_STATUSES,
                   MAX_REVISION_ROUNDS, new_row, sorted_rows, store, touch)

bp = Blueprint("drafts", __name__)

DECISIONS = ["APPROVE", "REQUEST_CHANGES"]


@bp.post("/response-drafts")
def create_draft():
    actor = V.authorize("IRAnalyst")
    b = V.body()
    inquiry_id = V.f_str(b, "inquiry_id", required=True)
    body_text = V.f_str(b, "body_text", required=True, max_len=4000)
    disclosure_class = V.f_enum(b, "disclosure_class", DISCLOSURE_CLASSES, required=True)
    cited_disclosure_id = V.f_str(b, "cited_disclosure_id", default=None)

    inquiry = V.get_inquiry(inquiry_id)
    if cited_disclosure_id is not None:
        V.get_disclosure(cited_disclosure_id)

    if inquiry["status"] not in ("ROUTED", "DRAFTING"):
        raise ApiError("ERR_INQUIRY_INVALID_STATE",
                       "a draft may only be opened against a ROUTED or DRAFTING inquiry")

    for existing in store.drafts.values():
        if existing["inquiry_id"] == inquiry["id"] and existing["status"] in ACTIVE_DRAFT_STATUSES:
            raise ApiError("ERR_ACTIVE_DRAFT_EXISTS",
                           "this inquiry already holds an active response draft")

    draft = new_row({
        "inquiry_id": inquiry["id"],
        "cited_disclosure_id": cited_disclosure_id,
        "author_user_id": actor.user_id,
        "reviewer_user_id": None,
        "body_text": body_text,
        "disclosure_class": disclosure_class,
        "status": "DRAFT",
        "revision_round": 1,
        "reviewer_note": None,
        "pinned_disclosure_version": None,
        "blocked_reason": None,
    })
    store.drafts[draft["id"]] = draft
    if inquiry["status"] == "ROUTED":
        inquiry["status"] = "DRAFTING"
    touch(inquiry)
    return created(draft_out(draft))


@bp.get("/response-drafts")
def list_drafts():
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer")
    limit, offset = V.q_pagination()
    inquiry_id = V.q_str("inquiry_id")
    cited_disclosure_id = V.q_str("cited_disclosure_id")
    author_user_id = V.q_str("author_user_id")
    status = V.q_enum("status", DRAFT_STATUSES)
    disclosure_class = V.q_enum("disclosure_class", DISCLOSURE_CLASSES)
    rows = sorted_rows(store.drafts)
    if inquiry_id is not None:
        rows = [r for r in rows if r["inquiry_id"] == inquiry_id]
    if cited_disclosure_id is not None:
        rows = [r for r in rows if r["cited_disclosure_id"] == cited_disclosure_id]
    if author_user_id is not None:
        rows = [r for r in rows if r["author_user_id"] == author_user_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if disclosure_class is not None:
        rows = [r for r in rows if r["disclosure_class"] == disclosure_class]
    page, total = paginate(rows, limit, offset)
    return ok_list([draft_out(r) for r in page], limit, offset, total)


@bp.get("/response-drafts/<draft_id>")
def read_draft(draft_id):
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer")
    return ok(draft_out(V.get_draft(draft_id)))


@bp.post("/response-drafts/<draft_id>/submit-review")
def submit_review(draft_id):
    actor = V.authorize("IRAnalyst")
    draft = V.get_draft(draft_id)

    if draft["status"] != "DRAFT":
        raise ApiError("ERR_DRAFT_INVALID_STATE", "only a DRAFT may be submitted for review")

    if draft["disclosure_class"] == "GUIDANCE_REPEAT":
        cited = store.disclosures.get(draft["cited_disclosure_id"]) \
            if draft["cited_disclosure_id"] else None
        if cited is None or cited["status"] != "PUBLISHED":
            raise ApiError("ERR_CITATION_REQUIRED",
                           "a GUIDANCE_REPEAT draft must cite a PUBLISHED disclosure")

    if actor.user_id != draft["author_user_id"]:
        raise ApiError("ERR_DRAFT_AUTHOR_MISMATCH", "only the author may submit this draft")

    draft["status"] = "IN_REVIEW"
    touch(draft)
    inquiry = store.inquiries.get(draft["inquiry_id"])
    if inquiry is not None:
        inquiry["status"] = "AWAITING_APPROVAL"
        touch(inquiry)
    return ok(draft_out(draft))


@bp.post("/response-drafts/<draft_id>/review")
def review_draft(draft_id):
    actor = V.authorize("DisclosureOfficer")
    b = V.body()
    decision = V.f_enum(b, "decision", DECISIONS, required=True)
    expected_inquiry_version = V.f_int(b, "expected_inquiry_version", required=True, minimum=0)
    reviewer_note = V.f_str(b, "reviewer_note", default=None)
    if decision == "REQUEST_CHANGES" and reviewer_note is None:
        V.bad("reviewer_note is required when requesting changes")

    draft = V.get_draft(draft_id)
    inquiry = store.inquiries.get(draft["inquiry_id"])

    # 7 -- optimistic concurrency on the parent inquiry
    if inquiry is None or expected_inquiry_version != inquiry["version"]:
        raise ApiError("ERR_STALE_INQUIRY_VERSION",
                       "expected_inquiry_version does not match the inquiry's current version")

    # 8 -- the draft's own state precondition
    if draft["status"] != "IN_REVIEW":
        raise ApiError("ERR_DRAFT_INVALID_STATE", "only an IN_REVIEW draft may be reviewed")

    # 9 -- cross-entity referential state
    cited = store.disclosures.get(draft["cited_disclosure_id"]) \
        if draft["cited_disclosure_id"] else None
    if decision == "APPROVE" and draft["cited_disclosure_id"] is not None:
        if cited is None or cited["status"] != "PUBLISHED":
            raise ApiError("ERR_CITATION_REQUIRED",
                           "the cited disclosure is no longer PUBLISHED")

    # 10 -- the review wall
    if actor.user_id == draft["author_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the author of a draft may not review it")

    company = store.companies.get(inquiry["company_id"])

    if decision == "APPROVE":
        # 11 -- disclosure-boundary gates
        if company is not None and company["disclosure_posture"] == "BLACKOUT":
            raise ApiError("ERR_DISCLOSURE_BLACKOUT",
                           "the issuer's disclosure posture is BLACKOUT")
        if draft["disclosure_class"] == "MATERIAL_NONPUBLIC":
            raise ApiError("ERR_SELECTIVE_DISCLOSURE_BLOCKED",
                           "a MATERIAL_NONPUBLIC draft can never be approved")
        draft["status"] = "APPROVED"
        draft["reviewer_user_id"] = actor.user_id
        if reviewer_note is not None:
            draft["reviewer_note"] = reviewer_note
        draft["pinned_disclosure_version"] = cited["version"] if cited is not None else None
        touch(draft)
        touch(inquiry)  # status deliberately stays AWAITING_APPROVAL
    else:
        draft["status"] = "CHANGES_REQUESTED"
        draft["reviewer_user_id"] = actor.user_id
        draft["reviewer_note"] = reviewer_note
        touch(draft)
        inquiry["status"] = "DRAFTING"
        calc.recompute_sla(inquiry)
        touch(inquiry)
    return ok(draft_out(draft))


@bp.post("/response-drafts/<draft_id>/revise")
def revise_draft(draft_id):
    actor = V.authorize("IRAnalyst")
    b = V.body()
    body_text = V.f_str(b, "body_text", default=None, max_len=4000)
    disclosure_class = V.f_enum(b, "disclosure_class", DISCLOSURE_CLASSES, default=None)
    cited_supplied = "cited_disclosure_id" in b
    cited_disclosure_id = V.f_str(b, "cited_disclosure_id", default=None)

    draft = V.get_draft(draft_id)
    if cited_disclosure_id is not None:
        V.get_disclosure(cited_disclosure_id)

    if draft["status"] not in ("CHANGES_REQUESTED", "BLOCKED"):
        raise ApiError("ERR_DRAFT_INVALID_STATE",
                       "only a CHANGES_REQUESTED or BLOCKED draft may be revised")
    if actor.user_id != draft["author_user_id"]:
        raise ApiError("ERR_DRAFT_AUTHOR_MISMATCH", "only the author may revise this draft")
    if draft["revision_round"] >= MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED",
                       "this draft has consumed all %d authoring rounds" % MAX_REVISION_ROUNDS)

    draft["status"] = "DRAFT"
    draft["revision_round"] = draft["revision_round"] + 1
    draft["blocked_reason"] = None
    draft["reviewer_note"] = None
    draft["pinned_disclosure_version"] = None
    if body_text is not None:
        draft["body_text"] = body_text
    if disclosure_class is not None:
        draft["disclosure_class"] = disclosure_class
    if cited_supplied:
        draft["cited_disclosure_id"] = cited_disclosure_id
    touch(draft)
    return ok(draft_out(draft))


@bp.post("/response-drafts/<draft_id>/send")
def send_draft(draft_id):
    actor = V.authorize("IRAnalyst")
    draft = V.get_draft(draft_id)

    if draft["status"] != "APPROVED":
        raise ApiError("ERR_DRAFT_INVALID_STATE", "only an APPROVED draft may be dispatched")
    if actor.user_id != draft["author_user_id"]:
        raise ApiError("ERR_DRAFT_AUTHOR_MISMATCH", "only the author may dispatch this draft")

    inquiry = store.inquiries.get(draft["inquiry_id"])
    company = store.companies.get(inquiry["company_id"]) if inquiry is not None else None
    if company is not None and company["disclosure_posture"] == "BLACKOUT":
        raise ApiError("ERR_DISCLOSURE_BLACKOUT", "the issuer's disclosure posture is BLACKOUT")

    if draft["cited_disclosure_id"] is not None:
        cited = store.disclosures.get(draft["cited_disclosure_id"])
        if (cited is None or cited["status"] != "PUBLISHED"
                or cited["version"] != draft["pinned_disclosure_version"]):
            raise ApiError("ERR_PINNED_DISCLOSURE_STALE",
                           "the cited disclosure has moved on since approval")

    draft["status"] = "SENT"
    touch(draft)
    if inquiry is not None:
        inquiry["status"] = "ANSWERED"
        inquiry["answered_at"] = store.now()
        touch(inquiry)
    if company is not None:
        calc.inquiry_count_write(company)
    return ok(draft_out(draft))
