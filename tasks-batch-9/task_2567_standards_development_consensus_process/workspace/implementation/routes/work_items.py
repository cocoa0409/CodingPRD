"""Work items: proposal, scope approval, draft creation, publication and the
periodic review cycle (PRD 3.2, 3.9)."""

from flask import Blueprint

from core import auth, envelope
from core.enums import PERIODIC_ACTION, SCOPE_DECISION, WORK_ITEM_TYPE
from core.errors import bad_request, fail
from core.store import insert, now, now_iso, public, rows, touch
from core.util import date_part, iso_date, round4
from core.validation import Body, apply_filters, load_fk, load_path, no_body
from services import ballots, gate, graph, ip, schedule

bp = Blueprint("work_items", __name__)

FILTERS = ("proposer_participant_id", "sponsoring_committee_id", "progress_status",
           "ip_status", "consensus_gate")

SUPERSEDABLE_DRAFT_STATES = ("DRAFTING", "COMMENT_RESOLUTION", "PUBLIC_REVIEW_CLOSED")
NEGATIVE_CHECK_STATES = ("COMMENT_RESOLUTION", "PUBLIC_REVIEW_CLOSED")


@bp.post("/sdo/work-items")
def create_work_item():
    auth.authenticate((auth.PROPOSER, auth.COMMITTEE_MEMBER, auth.COMMITTEE_CHAIR))
    body = Body(("title", "scope_text", "work_item_type", "proposer_participant_id",
                 "target_completion_date"))
    title = body.string("title", required=True, min_len=1, max_len=200)
    scope_text = body.string("scope_text", required=True, min_len=1, max_len=1200)
    work_item_type = body.enum("work_item_type", WORK_ITEM_TYPE, required=True)
    proposer_id = body.id_ref("proposer_participant_id", required=True)
    target_date = body.date("target_completion_date", required=True)

    load_fk("participants", proposer_id, optional=False)
    auth.require_actor_identity(proposer_id)

    row = insert("work_items", {
        "title": title,
        "scope_text": scope_text,
        "work_item_type": work_item_type,
        "proposer_participant_id": proposer_id,
        "target_completion_date": iso_date(target_date),
        "sponsoring_committee_id": None,
        "designation": None,
        "progress_status": "PROPOSED",
        "ip_status": "IP_PENDING",
        "consensus_gate": "OPEN",
        "scope_approved_at": None,
        "edition": None,
        "published_at": None,
        "periodic_review_due_date": None,
        "last_periodic_action_at": None,
        "errata_count": 0,
        "interpretation_count": 0,
        "unresolved_negative_count": 0,
        "_target_completion_date": target_date,
        "_periodic_review_due_date": None,
        "_published_at": None,
    })
    return envelope.created(public(row))


@bp.get("/sdo/work-items")
def list_work_items():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("work_items"), FILTERS))


@bp.get("/sdo/work-items/<work_item_id>")
def get_work_item(work_item_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(public(load_path("work_items", work_item_id)))


@bp.post("/sdo/work-items/<work_item_id>/approve-scope")
def approve_scope(work_item_id):
    auth.authenticate((auth.STANDARDS_STAFF,))
    work_item = load_path("work_items", work_item_id)
    body = Body(("decision", "sponsoring_committee_id", "designation", "rationale"))
    decision = body.enum("decision", SCOPE_DECISION, required=True)
    committee_id = body.id_ref("sponsoring_committee_id",
                               required=(decision == "APPROVE"))
    designation = body.string("designation", required=(decision == "APPROVE"),
                              min_len=1, max_len=32)
    body.string("rationale", required=(decision == "REJECT"), min_len=1, max_len=2000)

    committee = load_fk("committees", committee_id) if committee_id else None

    if work_item["progress_status"] != "PROPOSED":
        fail("ERR_INVALID_WORK_ITEM_STATE",
             "Scope decisions are only available on a PROPOSED work item.")

    if decision == "APPROVE":
        if committee["status"] != "ACTIVE":
            fail("ERR_COMMITTEE_NOT_ACTIVE",
                 "The nominated sponsoring committee is not ACTIVE.")
        work_item["sponsoring_committee_id"] = committee["id"]
        work_item["designation"] = designation
        work_item["scope_approved_at"] = now_iso()
        work_item["edition"] = 1
        # SCOPE_APPROVED is traversed inside this same request.
        work_item["progress_status"] = "IN_DEVELOPMENT"
    else:
        work_item["progress_status"] = "SCOPE_REJECTED"

    touch(work_item)
    gate.recompute(work_item)
    return envelope.object_response(public(work_item))


@bp.post("/sdo/work-items/<work_item_id>/drafts")
def create_draft(work_item_id):
    auth.authenticate((auth.COMMITTEE_CHAIR, auth.STANDARDS_STAFF))
    work_item = load_path("work_items", work_item_id)
    body = Body(("total_clause_count", "changed_clause_count", "prior_draft_id",
                 "summary"))
    total_clause_count = body.integer("total_clause_count", required=True, minimum=1)
    changed_clause_count = body.integer("changed_clause_count", minimum=0, default=0)
    prior_draft_id = body.id_ref("prior_draft_id", nullable=True, default=None)
    summary = body.string("summary", min_len=1, max_len=2000, nullable=True, default=None)
    if changed_clause_count > total_clause_count:
        bad_request("changed_clause_count may not exceed total_clause_count.")

    prior = load_fk("drafts", prior_draft_id)

    if prior is not None:
        if prior["status"] not in SUPERSEDABLE_DRAFT_STATES:
            fail("ERR_INVALID_DRAFT_STATE",
                 "A draft in %s cannot be superseded." % prior["status"])

    if work_item["progress_status"] != "IN_DEVELOPMENT":
        fail("ERR_INVALID_WORK_ITEM_STATE",
             "Draft revisions require the work item to be IN_DEVELOPMENT.")

    if prior is not None and prior["status"] in NEGATIVE_CHECK_STATES:
        for vote in graph.votes_of_draft(prior):
            if vote["adjudication_status"] == "PENDING":
                fail("ERR_NEGATIVES_NOT_CONSIDERED",
                     "The predecessor draft still carries an unresolved negative.")

    if total_clause_count == 0:
        ratio = 0.0
    else:
        ratio = round4(float(changed_clause_count) / float(total_clause_count))

    row = insert("drafts", {
        "work_item_id": work_item["id"],
        "prior_draft_id": prior["id"] if prior is not None else None,
        "revision_number": (prior["revision_number"] + 1) if prior is not None else 1,
        "total_clause_count": total_clause_count,
        "changed_clause_count": changed_clause_count,
        "substantive_change_ratio": ratio,
        "summary": summary,
        "status": "DRAFTING",
        "unresolved_negative_count": 0,
        "carryover_unresolved_negative_count":
            prior["carryover_unresolved_negative_count"] if prior is not None else 0,
        "recirculation_required": False,
        "ballot_round_count": 0,
    })

    if prior is not None:
        prior["status"] = "ABANDONED"
        prior["recirculation_required"] = False
        touch(prior)

    touch(work_item)
    return envelope.created(public(row))


@bp.post("/sdo/work-items/<work_item_id>/publish")
def publish_work_item(work_item_id):
    auth.authenticate((auth.STANDARDS_STAFF,))
    work_item = load_path("work_items", work_item_id)
    no_body()

    if work_item["progress_status"] != "CONSENSUS_APPROVED":
        fail("ERR_INVALID_WORK_ITEM_STATE",
             "Only a CONSENSUS_APPROVED work item may be published.")

    committee = graph.sponsoring_committee(work_item)
    if committee is None or committee["status"] != "ACTIVE":
        fail("ERR_COMMITTEE_NOT_ACTIVE", "The sponsoring committee is not ACTIVE.")

    for vote in graph.votes_of_work_item(work_item):
        if vote["adjudication_status"] == "PENDING":
            fail("ERR_NEGATIVES_NOT_CONSIDERED",
                 "An unresolved negative is still pending adjudication.")

    fresh_gate, _negatives = gate.evaluate(work_item)
    if fresh_gate != "OPEN":
        fail("ERR_CONSENSUS_GATE_BLOCKED", "The procedural gate is BLOCKED.")

    if ip.evaluate(work_item) != "IP_CLEARED":
        fail("ERR_IP_NOT_CLEARED", "Patent clearance has not been reached.")

    approved_draft = None
    for draft in graph.drafts_of(work_item):
        if draft["status"] == "APPROVED":
            approved_draft = draft
    if approved_draft is None or not ballots.latest_review_approved(approved_draft):
        fail("ERR_PUBLIC_REVIEW_NOT_APPROVED",
             "The approved draft's latest public review is not DISPOSITION_APPROVED.")

    work_item["progress_status"] = "PUBLISHED"
    work_item["published_at"] = now_iso()
    work_item["_published_at"] = now()
    due = schedule.due_date_from(date_part(now()))
    work_item["_periodic_review_due_date"] = due
    work_item["periodic_review_due_date"] = iso_date(due)
    touch(work_item)
    ip.recompute(work_item)
    gate.recompute(work_item)
    return envelope.object_response(public(work_item))


@bp.post("/sdo/work-items/<work_item_id>/periodic-review")
def periodic_review(work_item_id):
    auth.authenticate((auth.STANDARDS_STAFF,))
    work_item = load_path("work_items", work_item_id)
    body = Body(("action", "rationale"))
    action = body.enum("action", PERIODIC_ACTION, required=True)
    body.string("rationale", min_len=1, max_len=2000, nullable=True, default=None)

    status = work_item["progress_status"]
    if action == "OPEN_REVIEW":
        if status not in ("PUBLISHED", "REAFFIRMED"):
            fail("ERR_INVALID_WORK_ITEM_STATE",
                 "A periodic review opens only from PUBLISHED or REAFFIRMED.")
    elif action == "REAFFIRM":
        if status != "UNDER_PERIODIC_REVIEW":
            fail("ERR_INVALID_WORK_ITEM_STATE",
                 "Reaffirmation requires the work item to be UNDER_PERIODIC_REVIEW.")
    else:
        if status not in ("UNDER_PERIODIC_REVIEW", "SUSPENDED"):
            fail("ERR_INVALID_WORK_ITEM_STATE",
                 "Withdrawal is available from UNDER_PERIODIC_REVIEW or SUSPENDED.")

    fresh_gate, _negatives = gate.evaluate(work_item)
    if fresh_gate != "OPEN":
        fail("ERR_CONSENSUS_GATE_BLOCKED", "The procedural gate is BLOCKED.")

    due = work_item.get("_periodic_review_due_date")

    if action == "REAFFIRM":
        latest_draft = graph.latest_draft_of(work_item)
        satisfied = False
        if latest_draft is not None:
            for ballot in graph.ballots_of_draft(latest_draft):
                if (ballot["effective_ballot_kind"] == "REAFFIRMATION"
                        and ballot["status"] == "EVALUATED"
                        and ballot["consensus_result"] == "APPROVED"):
                    satisfied = True
                    break
        if not satisfied:
            fail("ERR_REAFFIRMATION_BALLOT_REQUIRED",
                 "An approved reaffirmation ballot on the latest draft is required.")

    today = date_part(now())
    if due is not None and today < schedule.window_opens_on(due):
        fail("ERR_PERIODIC_REVIEW_NOT_DUE",
             "The periodic review window has not opened yet.")

    if action == "REAFFIRM" and due is not None and today > schedule.grace_ends_on(due):
        fail("ERR_REAFFIRMATION_WINDOW_EXPIRED",
             "The reaffirmation grace period has expired.")

    work_item["last_periodic_action_at"] = now_iso()
    if action == "OPEN_REVIEW":
        work_item["progress_status"] = "UNDER_PERIODIC_REVIEW"
    elif action == "REAFFIRM":
        work_item["progress_status"] = "REAFFIRMED"
        next_due = schedule.due_date_from(today)
        work_item["_periodic_review_due_date"] = next_due
        work_item["periodic_review_due_date"] = iso_date(next_due)
    else:
        work_item["progress_status"] = "WITHDRAWN"
        work_item["_periodic_review_due_date"] = None
        work_item["periodic_review_due_date"] = None
    touch(work_item)
    gate.recompute(work_item)
    return envelope.object_response(public(work_item))
