"""FileTransferBatch endpoints.  Demobilization hand-back with SoD on accept."""
from flask import Blueprint, request

import derive
import store
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing
from store import clock_now, touch

bp = Blueprint("batches", __name__)


@bp.post("/file-transfer-batches")
def create_batch():
    begin()
    soft = validate.soft_body()
    raw_event = validate.raw_ref(soft, "event_id")
    event = validate.event(raw_event) if raw_event is not None else None
    payload = validate.body()
    if event is None:
        validate.req_string(payload, "event_id")
    target_unit = validate.req_string(payload, "target_unit")

    rec = store.base_record()
    rec.update({
        "event_id": event["id"],
        "target_unit": target_unit,
        "status": "OPEN",
        "submitted_at_utc": None,
        "rejection_reason": None,
        "_submitted_by_user_id": None,
    })
    store.batches[rec["id"]] = rec
    return created(derive.batch_out(rec))


@bp.get("/file-transfer-batches")
def list_batches():
    begin()
    rows = list(store.batches.values())
    for param, field in (("event_id", "event_id"), ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, derive.batch_out)


@bp.get("/file-transfer-batches/<batch_id>")
def read_batch(batch_id):
    begin()
    return ok(derive.batch_out(validate.batch(batch_id)))


def _members(batch_id):
    return [c for c in store.claims.values() if c.get("transfer_batch_id") == batch_id]


@bp.post("/file-transfer-batches/<batch_id>/claims")
def add_claim(batch_id):
    begin()
    # Existence: claim (5) precedes batch (14).
    soft = validate.soft_body()
    raw_claim = validate.raw_ref(soft, "claim_id")
    claim = validate.claim(raw_claim) if raw_claim is not None else None
    rec = validate.batch(batch_id)
    payload = validate.body()
    if claim is None:
        validate.req_string(payload, "claim_id")

    if rec["status"] != "OPEN":
        fail("ERR_BATCH_NOT_OPEN")
    if claim["handling_status"] != "CLOSED":
        fail("ERR_CLAIM_NOT_TRANSFERABLE")
    # Position 30.
    if claim["event_id"] != rec["event_id"]:
        fail("ERR_EVENT_SCOPE_MISMATCH")

    claim["transfer_batch_id"] = rec["id"]
    touch(claim)
    return ok(derive.batch_out(rec))


@bp.post("/file-transfer-batches/<batch_id>/submit")
def submit_batch(batch_id):
    user_id, _role = begin()
    rec = validate.batch(batch_id)
    if rec["status"] != "OPEN":
        fail("ERR_BATCH_NOT_OPEN")
    event = store.events.get(rec["event_id"])
    if event is None or event["status"] != "DEMOBILIZING":
        fail("ERR_EVENT_NOT_DEMOBILIZING")
    # Position 37 - the empty-batch gate (422) precedes the blocking gate (409).
    members = _members(rec["id"])
    if len(members) < 1:
        fail("ERR_BATCH_EMPTY")
    if derive.batch_blocking_claim_count(rec["id"]) != 0:
        fail("ERR_BATCH_HAS_BLOCKING_CLAIMS")
    for claim in members:
        if claim["handling_status"] != "CLOSED":
            fail("ERR_CLAIM_NOT_TRANSFERABLE")

    rec["status"] = "SUBMITTED"
    rec["submitted_at_utc"] = clock_now()
    rec["_submitted_by_user_id"] = user_id
    touch(rec)
    for claim in members:
        claim["handling_status"] = "TRANSFERRED"
        touch(claim)
    touch(event)
    return ok(derive.batch_out(rec))


@bp.post("/file-transfer-batches/<batch_id>/accept")
def accept_batch(batch_id):
    user_id, _role = begin()
    rec = validate.batch(batch_id)
    if rec["status"] != "SUBMITTED":
        fail("ERR_BATCH_NOT_SUBMITTED")
    # Position 22 - the accepting user may not be the submitter.
    if rec.get("_submitted_by_user_id") is not None \
            and rec["_submitted_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
    rec["status"] = "ACCEPTED"
    touch(rec)
    return ok(derive.batch_out(rec))


@bp.post("/file-transfer-batches/<batch_id>/reject")
def reject_batch(batch_id):
    begin()
    rec = validate.batch(batch_id)
    payload = validate.soft_body()
    reason = payload.get("rejection_reason")
    if not isinstance(reason, str) or not reason:
        fail("ERR_REJECTION_REASON_REQUIRED")
    if rec["status"] != "SUBMITTED":
        fail("ERR_BATCH_NOT_SUBMITTED")

    rec["status"] = "REJECTED"
    rec["rejection_reason"] = reason
    touch(rec)
    for claim in _members(rec["id"]):
        if claim["handling_status"] == "TRANSFERRED":
            claim["handling_status"] = "CLOSED"
            touch(claim)
    event = store.events.get(rec["event_id"])
    if event is not None:
        touch(event)
    return ok(derive.batch_out(rec))


@bp.post("/file-transfer-batches/<batch_id>/reopen-batch")
def reopen_batch(batch_id):
    begin()
    rec = validate.batch(batch_id)
    if rec["status"] != "REJECTED":
        fail("ERR_BATCH_NOT_REJECTED")
    rec["status"] = "OPEN"
    rec["rejection_reason"] = None
    touch(rec)
    return ok(derive.batch_out(rec))
