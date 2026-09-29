"""Interpretation requests and errata against a published standard (PRD 3.9)."""

from flask import Blueprint

from core import auth, envelope
from core.enums import MAINTENANCE_ACTION, MAINTENANCE_ITEM_KIND
from core.errors import fail
from core.store import db, insert, now_iso, public, rows, touch
from core.validation import Body, apply_filters, load_fk, load_path
from services import graph

bp = Blueprint("maintenance", __name__)

FILTERS = ("work_item_id", "requester_participant_id", "item_kind", "status")

ERRATUM_STATES = ("PUBLISHED", "REAFFIRMED", "UNDER_PERIODIC_REVIEW")
ACTION_KIND = {
    "ISSUE_INTERPRETATION": "INTERPRETATION_REQUEST",
    "ISSUE_ERRATUM": "ERRATUM_REPORT",
}
ACTION_STATUS = {
    "ISSUE_INTERPRETATION": "INTERPRETATION_ISSUED",
    "ISSUE_ERRATUM": "ERRATUM_ISSUED",
    "DECLINE": "DECLINED",
}


def _refresh_counters(work_item):
    items = graph.maintenance_of(work_item)
    work_item["errata_count"] = len(
        [i for i in items if i["status"] == "ERRATUM_ISSUED"])
    work_item["interpretation_count"] = len(
        [i for i in items if i["status"] == "INTERPRETATION_ISSUED"])


@bp.post("/sdo/maintenance-items")
def submit_item():
    auth.authenticate((auth.PUBLIC_COMMENTER, auth.COMMITTEE_MEMBER,
                       auth.COMMITTEE_CHAIR, auth.PROPOSER))
    body = Body(("work_item_id", "requester_participant_id", "item_kind",
                 "question_text", "clause_reference"))
    work_item_id = body.id_ref("work_item_id", required=True)
    requester_id = body.id_ref("requester_participant_id", required=True)
    item_kind = body.enum("item_kind", MAINTENANCE_ITEM_KIND, required=True)
    question_text = body.string("question_text", required=True, min_len=1, max_len=2000)
    clause_reference = body.string("clause_reference", min_len=1, max_len=40,
                                   nullable=True, default=None)

    work_item = load_fk("work_items", work_item_id, optional=False)
    load_fk("participants", requester_id, optional=False)
    auth.require_actor_identity(requester_id)

    row = insert("maintenance_items", {
        "work_item_id": work_item["id"],
        "requester_participant_id": requester_id,
        "item_kind": item_kind,
        "question_text": question_text,
        "clause_reference": clause_reference,
        "status": "RECEIVED",
        "response_text": None,
        "erratum_clause_reference": None,
        "received_at": now_iso(),
        "resolved_at": None,
    })
    return envelope.created(public(row))


@bp.get("/sdo/maintenance-items")
def list_items():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("maintenance_items"), FILTERS))


@bp.get("/sdo/maintenance-items/<maintenance_item_id>")
def get_item(maintenance_item_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(
        public(load_path("maintenance_items", maintenance_item_id)))


@bp.post("/sdo/maintenance-items/<maintenance_item_id>/resolve")
def resolve_item(maintenance_item_id):
    auth.authenticate((auth.COMMITTEE_CHAIR, auth.STANDARDS_STAFF))
    item = load_path("maintenance_items", maintenance_item_id)
    body = Body(("action", "response_text", "erratum_clause_reference"))
    action = body.enum("action", MAINTENANCE_ACTION, required=True)
    response_text = body.string("response_text", required=True, min_len=1, max_len=2000)
    erratum_clause = body.string("erratum_clause_reference",
                                 required=(action == "ISSUE_ERRATUM"),
                                 min_len=1, max_len=40, nullable=True, default=None)

    work_item = db.work_items.get(item["work_item_id"])
    committee = graph.sponsoring_committee(work_item)
    if auth.caller_role() == auth.COMMITTEE_CHAIR:
        auth.require_committee_chair(committee)

    if work_item is not None and work_item["progress_status"] == "WITHDRAWN":
        fail("ERR_INVALID_WORK_ITEM_STATE",
             "A withdrawn standard's maintenance requests can no longer be resolved.")

    if item["status"] != "RECEIVED":
        fail("ERR_INVALID_MAINTENANCE_STATE", "A resolved item cannot be re-resolved.")

    if action == "ISSUE_ERRATUM":
        if work_item is None or work_item["progress_status"] not in ERRATUM_STATES:
            fail("ERR_STANDARD_NOT_PUBLISHED",
                 "An erratum cannot be issued against text that was never published.")

    expected_kind = ACTION_KIND.get(action)
    if expected_kind is not None and item["item_kind"] != expected_kind:
        fail("ERR_MAINTENANCE_ACTION_MISMATCH",
             "%s is not available for a %s." % (action, item["item_kind"]))

    item["status"] = ACTION_STATUS[action]
    item["response_text"] = response_text
    item["resolved_at"] = now_iso()
    if action == "ISSUE_ERRATUM":
        item["erratum_clause_reference"] = erratum_clause
    touch(item)

    # DECLINE touches nothing else; neither counter changes and edition and
    # published_at are never affected by either issuing branch.
    if action != "DECLINE" and work_item is not None:
        _refresh_counters(work_item)
        touch(work_item)
    return envelope.object_response(public(item))
