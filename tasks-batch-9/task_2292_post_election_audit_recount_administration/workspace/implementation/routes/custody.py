"""BallotBatch and CustodyEvent endpoints."""

from flask import Blueprint

from db import db, insert, now_iso, touch
from errors import fail
from middleware import (
    ROLE_AUDIT_MANAGER,
    ROLE_CANDIDATE_REPRESENTATIVE,
    ROLE_CUSTODY_OFFICER,
    ROLE_ELECTIONS_DIRECTOR,
    SIX_ROLES,
    guard,
)
from response import object_response
from routes.common import list_endpoint, lookup, paged, single
from services.domain import (
    append_custody_event,
    audit_batches_of_round,
    batches_of_contest,
    custody_events_of_batch,
    tallies_of_ballot_batch,
)
from validate import (
    body,
    filter_value,
    opt_str,
    pagination,
    req_int,
    req_str,
    req_vote_map,
)

bp = Blueprint("custody", __name__)

CUSTODY_STATUSES = ("SEALED", "CHECKED_OUT", "RESEALED", "QUARANTINED")
CUSTODY_EVENT_TYPES = ("INTAKE", "AUTHORIZED", "CHECK_OUT", "CHECK_IN", "QUARANTINE")
CUSTODY_READ_ROLES = (
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_AUDIT_MANAGER,
    ROLE_CUSTODY_OFFICER,
    ROLE_CANDIDATE_REPRESENTATIVE,
)


def _batch_payload(data, prefix=""):
    label = req_str(data, "batch_label", 1, 32)
    storage_location_code = req_str(data, "storage_location_code", 1, None)
    ballot_count = req_int(data, "ballot_count", 1, None)
    machine_votes = req_vote_map(data, "machine_votes")
    current_seal_number = req_str(data, "current_seal_number", 1, None)
    if sum(machine_votes.values()) > ballot_count:
        fail("ERR_VALIDATION", "machine_votes may not exceed ballot_count.")
    return {
        "batch_label": label,
        "storage_location_code": storage_location_code,
        "ballot_count": ballot_count,
        "machine_votes": machine_votes,
        "current_seal_number": current_seal_number,
    }


def _new_batch(election_id, contest_id, payload):
    row = insert(
        "ballot_batches",
        {
            "election_id": election_id,
            "contest_id": contest_id,
            "batch_label": payload["batch_label"],
            "storage_location_code": payload["storage_location_code"],
            "ballot_count": payload["ballot_count"],
            "machine_votes": dict(payload["machine_votes"]),
            "current_seal_number": payload["current_seal_number"],
            "custody_status": "SEALED",
            "retrieval_authorized_at": None,
            "open_checkout_count": 0,
            "checkout_cycle_count": 0,
            "last_checked_out_at": None,
            "last_resealed_at": None,
            "quarantine_reason": None,
        },
    )
    append_custody_event(
        row, "INTAKE", None, payload["current_seal_number"], note=None
    )
    return row


@bp.post("/ballot-batches")
@guard([ROLE_CUSTODY_OFFICER])
def create_ballot_batch():
    data = body()
    election_id = req_str(data, "election_id", 1, None)
    contest_id = req_str(data, "contest_id", 1, None)
    payload = _batch_payload(data)

    election = lookup("elections", election_id)
    contest = lookup("contests", contest_id)

    if election["status"] == "CERTIFIED":
        fail("ERR_ELECTION_ALREADY_CERTIFIED")
    if contest["election_id"] != election_id:
        fail("ERR_CROSS_ELECTION_REFERENCE")
    if set(payload["machine_votes"].keys()) != set(contest["candidate_names"]):
        fail("ERR_CANDIDATE_NAME_UNKNOWN")

    existing = batches_of_contest(contest)
    if any(b["batch_label"] == payload["batch_label"] for b in existing):
        fail("ERR_DUPLICATE_BATCH_LABEL")

    batched = sum(b["ballot_count"] for b in existing)
    if batched + payload["ballot_count"] > contest["ballots_cast"]:
        fail("ERR_BALLOT_ACCOUNTING_EXCEEDED")

    row = _new_batch(election_id, contest_id, payload)
    return single(row, 201)


@bp.post("/ballot-batches/bulk")
@guard([ROLE_CUSTODY_OFFICER])
def create_ballot_batches_bulk():
    data = body()
    election_id = req_str(data, "election_id", 1, None)
    contest_id = req_str(data, "contest_id", 1, None)
    raw_batches = data.get("batches")
    if raw_batches is None:
        fail("ERR_VALIDATION", "Field 'batches' is required.")
    if not isinstance(raw_batches, list):
        fail("ERR_VALIDATION", "Field 'batches' must be an array.")
    if len(raw_batches) < 1:
        fail("ERR_VALIDATION", "Field 'batches' must contain at least one entry.")
    payloads = []
    for entry in raw_batches:
        if not isinstance(entry, dict):
            fail("ERR_VALIDATION", "Each entry of 'batches' must be an object.")
        payloads.append(_batch_payload(entry))

    election = lookup("elections", election_id)
    contest = lookup("contests", contest_id)

    if election["status"] == "CERTIFIED":
        fail("ERR_ELECTION_ALREADY_CERTIFIED")
    if contest["election_id"] != election_id:
        fail("ERR_CROSS_ELECTION_REFERENCE")
    for payload in payloads:
        if set(payload["machine_votes"].keys()) != set(contest["candidate_names"]):
            fail("ERR_CANDIDATE_NAME_UNKNOWN")

    existing = batches_of_contest(contest)
    taken = set(b["batch_label"] for b in existing)
    for payload in payloads:
        if payload["batch_label"] in taken:
            fail("ERR_DUPLICATE_BATCH_LABEL")
        taken.add(payload["batch_label"])

    batched = sum(b["ballot_count"] for b in existing)
    incoming = sum(p["ballot_count"] for p in payloads)
    if batched + incoming > contest["ballots_cast"]:
        fail("ERR_BALLOT_ACCOUNTING_EXCEEDED")

    created = [_new_batch(election_id, contest_id, p) for p in payloads]
    return object_response(
        {
            "created_count": len(created),
            "batch_labels": [b["batch_label"] for b in created],
            "batch_ids": [b["id"] for b in created],
        },
        201,
    )


@bp.get("/ballot-batches")
@guard(SIX_ROLES)
def list_ballot_batches():
    return list_endpoint(
        "ballot_batches",
        {
            "election_id": ("election_id", None),
            "contest_id": ("contest_id", None),
            "custody_status": ("custody_status", CUSTODY_STATUSES),
        },
        sort_keys=("batch_label",),
    )


@bp.get("/ballot-batches/<batch_id>")
@guard(SIX_ROLES)
def get_ballot_batch(batch_id):
    return single(lookup("ballot_batches", batch_id))


@bp.post("/ballot-batches/<batch_id>/quarantine")
@guard([ROLE_CUSTODY_OFFICER])
def quarantine_ballot_batch(batch_id):
    data = body()
    reason = req_str(data, "reason", 1, None)

    batch = lookup("ballot_batches", batch_id)
    if batch["custody_status"] == "QUARANTINED":
        fail("ERR_INVALID_BATCH_STATE")

    batch["custody_status"] = "QUARANTINED"
    batch["quarantine_reason"] = reason
    touch(batch)
    append_custody_event(
        batch,
        "QUARANTINE",
        batch["current_seal_number"],
        batch["current_seal_number"],
        note=reason,
    )

    for tally in tallies_of_ballot_batch(batch):
        if tally["status"] == "DRAFT":
            tally["status"] = "VOIDED"
            touch(tally)
    for audit_batch in db.audit_batches.values():
        if audit_batch["ballot_batch_id"] != batch["id"]:
            continue
        if audit_batch["tally_status"] in ("NOT_STARTED", "IN_PROGRESS"):
            audit_batch["tally_status"] = "VOIDED"
            touch(audit_batch)
    return single(batch)


@bp.get("/ballot-batches/<batch_id>/custody-events")
@guard(SIX_ROLES)
def list_batch_custody_events(batch_id):
    limit, offset = pagination()
    event_type = filter_value("event_type", CUSTODY_EVENT_TYPES)
    batch = lookup("ballot_batches", batch_id)
    rows = custody_events_of_batch(batch)
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    return paged(rows, limit, offset, ("sequence_no",))


@bp.get("/custody-events")
@guard(CUSTODY_READ_ROLES)
def list_custody_events():
    return list_endpoint(
        "custody_events",
        {
            "ballot_batch_id": ("ballot_batch_id", None),
            "event_type": ("event_type", CUSTODY_EVENT_TYPES),
        },
        sort_keys=("ballot_batch_id", "sequence_no"),
    )


@bp.get("/custody-events/<event_id>")
@guard(CUSTODY_READ_ROLES)
def get_custody_event(event_id):
    return single(lookup("custody_events", event_id))
