"""Mailing batches and ballot packets."""
from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import BATCH_TYPES, UNDELIVERABLE_REASON_CODES
from errors import ApiError
from services import accountability, cascade, election_flow, logbook, postage, posture

bp = Blueprint("mailing", __name__)

READ_ROLES = ("ElectionsAdmin", "ElectionsClerk", "CanvassSupervisor")


def _queued_packets(batch):
    return db.ordered(
        [
            p for p in db.ballot_packets.values()
            if p["mailing_batch_id"] == batch["id"] and p["status"] == "QUEUED"
        ]
    )


@bp.post("/mailing-batches")
def create_batch():
    mw.require_roles("ElectionsClerk")
    payload = mw.body()
    election_id = mw.require_string(payload, "election_id")
    batch_type = mw.require_enum(payload, "batch_type", BATCH_TYPES)
    scheduled_send_date = mw.require_date(payload, "scheduled_send_date")

    election_rec = lookups.election(election_id)
    posture.require_not_certified(election_rec)

    required_send_by_date = (
        election_rec["uocava_send_deadline_date"]
        if batch_type == "UOCAVA"
        else election_rec["domestic_send_deadline_date"]
    )
    rec = db.make_record(
        db.mailing_batches,
        {
            "election_id": election_rec["id"],
            "batch_type": batch_type,
            "scheduled_send_date": scheduled_send_date,
            "status": "DRAFT",
            "required_send_by_date": required_send_by_date,
            "packet_count": 0,
            "estimated_postage_cents": 0,
            "actual_postage_cents": None,
            "sealed_at": None,
            "dispatched_at": None,
            "cancellation_reason_code": None,
        },
    )
    return response.record_response(rec, 201)


@bp.get("/mailing-batches/<batch_id>")
def get_batch(batch_id):
    mw.require_roles(*READ_ROLES)
    rec = lookups.mailing_batch(batch_id)
    accountability.recompute_batch(rec)
    return response.record_response(rec)


@bp.get("/mailing-batches")
def list_batches():
    mw.require_roles(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = list(db.mailing_batches.values())
    for rec in rows:
        accountability.recompute_batch(rec)
    rows = mw.apply_filters(rows, ["election_id", "status", "batch_type"])
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/mailing-batches/<batch_id>/packets")
def add_packet(batch_id):
    mw.require_roles("ElectionsClerk")
    payload = mw.body()
    ballot_request_id = mw.require_string(payload, "ballot_request_id")
    packet_weight_grams = mw.require_int(payload, "packet_weight_grams", minimum=1)

    batch = lookups.mailing_batch(batch_id)
    request_rec = lookups.ballot_request(ballot_request_id)
    election_rec = db.elections.get(batch["election_id"])
    posture.require_not_certified(election_rec)

    accountability.recompute_batch(batch)
    if batch["status"] != "DRAFT":
        raise ApiError("ERR_BATCH_STATE_INVALID")
    if request_rec["status"] != "APPROVED":
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    if request_rec["election_id"] != batch["election_id"]:
        raise ApiError("ERR_REQUEST_ELECTION_MISMATCH")

    voter_rec = db.voters.get(request_rec["voter_id"])
    uocava_status = voter_rec["uocava_status"] if voter_rec else "NONE"
    if batch["batch_type"] == "UOCAVA" and uocava_status not in ("MILITARY", "OVERSEAS"):
        raise ApiError("ERR_UOCAVA_BATCH_MISMATCH")
    if batch["batch_type"] == "DOMESTIC_INITIAL" and uocava_status != "NONE":
        raise ApiError("ERR_UOCAVA_BATCH_MISMATCH")

    batch_sequence = batch["packet_count"] + 1
    packet = db.make_record(
        db.ballot_packets,
        {
            "mailing_batch_id": batch["id"],
            "ballot_request_id": request_rec["id"],
            "packet_weight_grams": packet_weight_grams,
            "packet_postage_cents": postage.packet_postage_cents(
                packet_weight_grams, uocava_status, request_rec["forwarding_class"]
            ),
            "packet_serial": "%s-%04d" % (batch["scheduled_send_date"], batch_sequence),
            "batch_sequence": batch_sequence,
            "status": "QUEUED",
            "mailed_at": None,
            "undeliverable_reason_code": None,
        },
    )
    accountability.recompute_batch(batch)
    return response.record_response(packet, 201)


@bp.post("/mailing-batches/<batch_id>/seal")
def seal_batch(batch_id):
    mw.require_roles("ElectionsClerk")
    mw.body()
    batch = lookups.mailing_batch(batch_id)
    election_rec = db.elections.get(batch["election_id"])
    posture.require(election_rec, ("PRE_MAIL", "MAILING"))

    accountability.recompute_batch(batch)
    if batch["status"] != "DRAFT":
        raise ApiError("ERR_BATCH_STATE_INVALID")
    if batch["packet_count"] < 1:
        raise ApiError("ERR_BATCH_STATE_INVALID")

    estimated = postage.batch_total_cents(_queued_packets(batch))
    if election_rec["postage_committed_cents"] + estimated > election_rec["postage_budget_cents"]:
        raise ApiError("ERR_POSTAGE_BUDGET_EXCEEDED")

    batch["estimated_postage_cents"] = estimated
    batch["status"] = "SEALED"
    batch["sealed_at"] = db.now()
    db.touch(batch)

    election_rec["postage_committed_cents"] += estimated
    db.touch(election_rec)
    return response.record_response(batch)


@bp.post("/mailing-batches/<batch_id>/dispatch")
def dispatch_batch(batch_id):
    actor = mw.require_roles("ElectionsClerk")
    mw.body()
    batch = lookups.mailing_batch(batch_id)
    election_rec = db.elections.get(batch["election_id"])
    posture.require_not_certified(election_rec)

    accountability.recompute_batch(batch)
    if batch["status"] != "SEALED":
        raise ApiError("ERR_BATCH_STATE_INVALID")

    required = db.parse_date(batch["required_send_by_date"])
    if required is not None and db.now().date() > required:
        raise ApiError(
            "ERR_UOCAVA_SEND_DEADLINE_PASSED"
            if batch["batch_type"] == "UOCAVA"
            else "ERR_DOMESTIC_SEND_DEADLINE_PASSED"
        )

    queued = _queued_packets(batch)
    actual = postage.batch_total_cents(queued)
    if election_rec["postage_actual_cents"] + actual > election_rec["postage_budget_cents"]:
        raise ApiError("ERR_POSTAGE_BUDGET_EXCEEDED")

    batch["actual_postage_cents"] = actual
    batch["status"] = "DISPATCHED"
    batch["dispatched_at"] = db.now()
    db.touch(batch)
    election_rec["postage_actual_cents"] += actual
    db.touch(election_rec)

    for packet in queued:
        packet["status"] = "MAILED"
        packet["mailed_at"] = db.now()
        db.touch(packet)
        request_rec = db.ballot_requests.get(packet["ballot_request_id"])
        if request_rec is not None and request_rec["status"] == "APPROVED":
            request_rec["status"] = "MAILED"
            db.touch(request_rec)

    accountability.recompute_batch(batch)
    accountability.recompute(election_rec)
    election_flow.auto_advance(election_rec, "PRE_MAIL", "MAILING")
    logbook.append(
        election_rec,
        "BATCH_DISPATCHED",
        actor.role,
        actor.user_id,
        "MailingBatch",
        batch["id"],
        "Mailing batch dispatched.",
    )
    return response.record_response(batch)


@bp.post("/mailing-batches/<batch_id>/cancel")
def cancel_batch(batch_id):
    actor = mw.require_roles("ElectionsClerk")
    payload = mw.body()
    cancellation_reason_code = mw.require_string(payload, "cancellation_reason_code")
    batch = lookups.mailing_batch(batch_id)
    election_rec = db.elections.get(batch["election_id"])
    posture.require_not_certified(election_rec)

    if batch["status"] not in ("DRAFT", "SEALED"):
        raise ApiError("ERR_BATCH_STATE_INVALID")

    was_sealed = batch["status"] == "SEALED"
    frozen_estimate = batch["estimated_postage_cents"]
    batch["status"] = "CANCELLED"
    batch["cancellation_reason_code"] = cancellation_reason_code
    db.touch(batch)

    for packet in _queued_packets(batch):
        packet["status"] = "SPOILED"
        db.touch(packet)

    if was_sealed:
        # Compensating action: release exactly the frozen figure that was committed.
        election_rec["postage_committed_cents"] -= frozen_estimate
        db.touch(election_rec)

    accountability.recompute_batch(batch)
    accountability.recompute(election_rec)
    logbook.append(
        election_rec,
        "BATCH_CANCELLED",
        actor.role,
        actor.user_id,
        "MailingBatch",
        batch["id"],
        "Mailing batch cancelled.",
    )
    return response.record_response(batch)


@bp.get("/ballot-packets/<packet_id>")
def get_packet(packet_id):
    mw.require_roles(*READ_ROLES)
    return response.record_response(lookups.ballot_packet(packet_id))


@bp.get("/ballot-packets")
def list_packets():
    mw.require_roles(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(
        list(db.ballot_packets.values()),
        ["mailing_batch_id", "ballot_request_id", "status"],
    )
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/ballot-packets/<packet_id>/undeliverable")
def mark_undeliverable(packet_id):
    actor = mw.require_roles("ElectionsClerk")
    payload = mw.body()
    reason_code = mw.require_enum(
        payload, "undeliverable_reason_code", UNDELIVERABLE_REASON_CODES
    )
    packet = lookups.ballot_packet(packet_id)
    election_rec = lookups.election_of_packet(packet)
    posture.require_not_certified(election_rec)

    if packet["status"] != "MAILED":
        raise ApiError("ERR_PACKET_STATE_INVALID")

    packet["status"] = "UNDELIVERABLE"
    packet["undeliverable_reason_code"] = reason_code
    db.touch(packet)
    accountability.recompute_batch(db.mailing_batches.get(packet["mailing_batch_id"]))
    accountability.recompute(election_rec)
    logbook.append(
        election_rec,
        "PACKET_UNDELIVERABLE",
        actor.role,
        actor.user_id,
        "BallotPacket",
        packet["id"],
        "Ballot packet returned undeliverable (%s)." % reason_code,
    )
    cascade.undeliverable_event(
        lookups.voter_of_packet(packet), election_rec, "PACKET_UNDELIVERABLE", actor
    )
    return response.record_response(packet)
