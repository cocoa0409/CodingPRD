"""Device transfers: the two-party ownership handshake."""
from datetime import timedelta

from flask import Blueprint, request

import auth
import clock
import db
import serializers as ser
import services
from config import (
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_HOMEOWNER,
    TRANSFER_ACCEPT_WINDOW_HOURS,
    TRANSFER_STATUSES,
)
from errors import ApiError
from response import created, enum_filter, listing, ok, page_params, str_filter
from util import get_body, opt_string, req_int, req_string

bp = Blueprint("transfers", __name__)

IN_FLIGHT_CLAIM_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED")


def _transfer(tid):
    row = db.transfers.get(tid)
    if row is None:
        raise ApiError("ERR_TRANSFER_NOT_FOUND", "No device transfer exists with id %s." % tid)
    return row


# ---------------------------------------------------------------- reads
@bp.get("/device-transfers/<tid>")
def get_transfer(tid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN, ROLE_ANALYST)
    row = _transfer(tid)
    auth.own_transfer(actor, row)
    return ok(ser.transfer(row))


@bp.get("/device-transfers")
def list_transfers():
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN, ROLE_ANALYST)
    limit, offset = page_params()
    device_id = str_filter("device_id")
    from_id = str_filter("from_homeowner_id")
    to_id = str_filter("to_homeowner_id")
    status = enum_filter("status", TRANSFER_STATUSES)
    rows = list(db.transfers.values())
    if actor.is_homeowner:
        rows = [
            t
            for t in rows
            if actor.user_id in (t["from_homeowner_id"], t["to_homeowner_id"])
        ]
    if device_id is not None:
        rows = [t for t in rows if t["device_id"] == device_id]
    if from_id is not None:
        rows = [t for t in rows if t["from_homeowner_id"] == from_id]
    if to_id is not None:
        rows = [t for t in rows if t["to_homeowner_id"] == to_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    rows = db.sort_rows(rows, lambda t: t["created_at"])
    return listing(rows, ser.transfer, limit, offset)


# ---------------------------------------------------------------- writes
@bp.post("/device-transfers")
def initiate():
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ADMIN)
    body = get_body(request)
    device_id = req_string(body, "device_id")
    to_homeowner_id = req_string(body, "to_homeowner_id")
    expected = req_int(body, "expected_device_version", minimum=0)
    note = opt_string(body, "transfer_note", 1, 280)

    device_row = db.devices.get(device_id)
    if device_row is None:
        raise ApiError("ERR_DEVICE_NOT_FOUND", "No device exists with id %s." % device_id)
    buyer = db.homeowners.get(to_homeowner_id)
    if buyer is None:
        raise ApiError(
            "ERR_HOMEOWNER_NOT_FOUND", "No homeowner exists with id %s." % to_homeowner_id
        )

    auth.own_device(actor, device_row)
    prop = db.properties[device_row["property_id"]]
    seller_id = prop["homeowner_id"]
    auth.alive_id(seller_id)
    auth.alive(buyer)

    if expected != device_row["version"]:
        raise ApiError(
            "ERR_STALE_DEVICE_VERSION",
            "expected_device_version does not match the device's current version.",
        )

    open_events = [
        e
        for e in db.events_for_device(device_id)
        if e["event_state"] in ("DETECTED", "ALERTED", "ESCALATED")
    ]
    if open_events or device_row["valve_state"] != "OPEN":
        raise ApiError(
            "ERR_UNRESOLVED_EVENTS_BLOCK_TRANSFER",
            "The device must be quiet with an OPEN valve before a transfer.",
        )
    live_claims = [
        c
        for c in db.claims.values()
        if c["device_id"] == device_id and c["status"] in IN_FLIGHT_CLAIM_STATUSES
    ]
    if live_claims:
        raise ApiError(
            "ERR_UNRESOLVED_EVENTS_BLOCK_TRANSFER",
            "A reimbursement claim on this device is still in flight.",
        )
    if to_homeowner_id == seller_id:
        raise ApiError(
            "ERR_TRANSFER_TARGET_INVALID", "The buyer must differ from the current owner."
        )
    if device_row["lifecycle_state"] not in ("ARMED", "LEARNING"):
        raise ApiError(
            "ERR_DEVICE_NOT_TRANSFERABLE",
            "A device in %s cannot change hands." % device_row["lifecycle_state"],
        )

    now = clock.now()
    for existing in db.transfers_for_device(device_id):
        if existing["status"] == "INITIATED":
            existing["status"] = "CANCELLED"
            existing["cancel_reason"] = "SUPERSEDED"
            db.touch(existing)

    row = {
        "device_id": device_id,
        "from_homeowner_id": seller_id,
        "to_homeowner_id": to_homeowner_id,
        "status": "INITIATED",
        "initiated_at": now,
        "expires_at": now + timedelta(hours=TRANSFER_ACCEPT_WINDOW_HOURS),
        "accepted_at": None,
        "accepted_by_user_id": None,
        "cancel_reason": None,
        "transfer_note": note,
    }
    db.insert(db.transfers, row)

    device_row["lifecycle_state"] = "TRANSFER_PENDING"
    db.touch(device_row)
    if prop["property_state"] == "ACTIVE":
        prop["property_state"] = "TRANSFER_PENDING"
        db.touch(prop)
    return created(ser.transfer(row))


@bp.post("/device-transfers/<tid>/accept")
def accept(tid):
    actor = auth.guard(ROLE_HOMEOWNER)
    transfer_row = _transfer(tid)
    get_body(request)
    buyer = db.homeowners.get(transfer_row["to_homeowner_id"])
    if buyer is not None:
        auth.alive(buyer)

    if transfer_row["status"] != "INITIATED":
        raise ApiError("ERR_TRANSFER_NOT_PENDING", "This transfer is no longer pending.")
    device_row = db.devices[transfer_row["device_id"]]
    open_events = [
        e
        for e in db.events_for_device(device_row["id"])
        if e["event_state"] in ("ALERTED", "ESCALATED")
    ]
    if open_events or device_row["valve_state"] != "OPEN":
        raise ApiError(
            "ERR_UNRESOLVED_EVENTS_BLOCK_TRANSFER",
            "The device must be quiet with an OPEN valve before acceptance.",
        )
    if clock.now() > transfer_row["expires_at"]:
        raise ApiError(
            "ERR_TRANSFER_WINDOW_EXPIRED", "The acceptance window for this transfer has closed."
        )
    if actor.user_id != transfer_row["to_homeowner_id"]:
        raise ApiError(
            "ERR_TRANSFER_TARGET_INVALID", "Only the named buyer may accept this transfer."
        )
    services.accept_transfer(transfer_row)
    return ok(ser.transfer(transfer_row))
