"""Chain of custody transfers."""

from flask import Blueprint

import calc
import domain
import serializers as ser
import validate as v
from auth import ALL_ROLES, authorize
from envelope import created, listed, ok, paginate
from errors import ApiError
from store import db, mark, new_entity, now, sort_rows

bp = Blueprint("custody", __name__)

PURPOSES = ("LAB_ANALYSIS", "COURT_PRESENTATION", "INVESTIGATIVE_REVIEW")
OPEN_STATUSES = domain.OPEN_TRANSFER_STATUSES


def _effective_end(transfer):
    return transfer["returned_at"] or transfer["due_back_at"]


def _escort_load(to_custodian_id, released_at, due_back_at):
    """calculations.escort_concurrency_load — closed intervals, touching counts."""
    load = 0
    for transfer in db.transfers.values():
        if transfer["to_custodian_id"] != to_custodian_id:
            continue
        if transfer["status"] not in OPEN_STATUSES:
            continue
        if transfer["released_at"] <= due_back_at and released_at <= _effective_end(transfer):
            load += 1
    return load


def _window_conflict(item_id, released_at, due_back_at):
    """calculations.item_custody_window_conflict — half-open, adjacency allowed."""
    for transfer in db.transfers.values():
        if transfer["evidence_item_id"] != item_id:
            continue
        if transfer["status"] not in OPEN_STATUSES:
            continue
        if released_at < _effective_end(transfer) and transfer["released_at"] < due_back_at:
            return True
    return False


@bp.post("/custody-transfers")
def request_transfer():
    principal = authorize(["Investigator", "LabAnalyst", "EvidenceTechnician"])
    data = v.body()
    item_id = v.req_str(data, "evidence_item_id")
    custodian_id = v.req_str(data, "to_custodian_id")
    purpose = v.req_enum(data, "purpose", PURPOSES)
    released_at = v.req_dt(data, "released_at")
    due_back_at = v.req_dt(data, "due_back_at")

    item = domain.find(db.items, item_id, "ERR_EVIDENCE_ITEM_NOT_FOUND")
    to_custodian = domain.find(db.custodians, custodian_id, "ERR_CUSTODIAN_NOT_FOUND")

    room = domain.room_of_item(item)
    domain.gate_locked_down(room)
    domain.gate_restricted(room)

    domain.gate_active(principal.custodian, to_custodian)
    domain.gate_certified(principal.custodian, to_custodian)

    if _escort_load(to_custodian["id"], released_at, due_back_at) >= calc.MAX_CONCURRENT_ESCORTS:
        raise ApiError("ERR_ESCORT_CAPACITY_EXCEEDED")

    if due_back_at <= released_at:
        raise ApiError("ERR_INVALID_TRANSFER_WINDOW")
    if due_back_at - released_at > calc.DAY * calc.MAX_WINDOW_DAYS_BY_PURPOSE[purpose]:
        raise ApiError("ERR_TRANSFER_WINDOW_TOO_LONG")

    if _window_conflict(item["id"], released_at, due_back_at):
        raise ApiError("ERR_CUSTODY_WINDOW_CONFLICT")

    transfer = new_entity(
        "CustodyTransfer",
        {
            "evidence_item_id": item["id"],
            "to_custodian_id": to_custodian["id"],
            "purpose": purpose,
            "released_at": released_at,
            "due_back_at": due_back_at,
            "from_custodian_id": None,
            "status": "REQUESTED",
            "released_signature": None,
            "witness_signature": None,
            "receipt_signature": None,
            "returned_at": None,
            "denial_reason": None,
        },
    )
    db.transfers[transfer["id"]] = transfer
    domain.refresh_custodian(to_custodian)
    domain.refresh_item_transfer_count(item)
    return created(ser.transfer(transfer))


@bp.get("/custody-transfers/<transfer_id>")
def get_transfer(transfer_id):
    authorize(ALL_ROLES)
    transfer = domain.find(db.transfers, transfer_id, "ERR_CUSTODY_TRANSFER_NOT_FOUND")
    return ok(ser.transfer(transfer))


@bp.get("/custody-transfers")
def list_transfers():
    authorize(ALL_ROLES)
    rows = v.filter_rows(
        sort_rows(db.transfers.values()),
        {
            "evidence_item_id": ("evidence_item_id", "str"),
            "from_custodian_id": ("from_custodian_id", "str"),
            "to_custodian_id": ("to_custodian_id", "str"),
            "status": ("status", "str"),
        },
    )
    page, limit, offset, total = paginate(rows)
    return listed([ser.transfer(r) for r in page], limit, offset, total)


@bp.post("/custody-transfers/<transfer_id>/release")
def release_transfer(transfer_id):
    principal = authorize(["EvidenceTechnician"])
    transfer = domain.find(db.transfers, transfer_id, "ERR_CUSTODY_TRANSFER_NOT_FOUND")
    data = v.body()
    released_signature = v.req_str(data, "released_signature", min_len=1)
    witness_signature = v.opt_str(data, "witness_signature")

    item = db.items.get(transfer["evidence_item_id"])
    location = domain.location_of_item(item)
    room = domain.room_of_item(item)
    to_custodian = db.custodians.get(transfer["to_custodian_id"])

    domain.gate_locked_down(room)
    domain.gate_restricted(room)

    if transfer["status"] != "REQUESTED":
        raise ApiError("ERR_TRANSFER_STATE_INVALID")
    if item["custody_state"] != "STORED":
        raise ApiError("ERR_ITEM_CUSTODY_STATE_INVALID")
    if location is not None and location["status"] != "OPEN":
        raise ApiError("ERR_LOCATION_SEALED")

    domain.gate_active(principal.custodian, to_custodian)
    domain.gate_certified(principal.custodian, to_custodian)

    if location is not None and location["requires_dual_signature"]:
        if witness_signature is None or witness_signature == "":
            raise ApiError("ERR_WITNESS_SIGNATURE_REQUIRED")

    transfer["status"] = "RELEASED"
    transfer["from_custodian_id"] = principal.user_id
    transfer["released_signature"] = released_signature
    transfer["witness_signature"] = witness_signature
    mark(transfer)

    item["custody_state"] = "CHECKED_OUT"
    item["current_holder_id"] = transfer["to_custodian_id"]
    mark(item)

    domain.refresh_location(location)
    domain.append_chain_event(
        item,
        "RELEASE",
        principal.role,
        principal.custodian_id,
        released_signature,
        "Item released to custodian %s for %s." % (transfer["to_custodian_id"], transfer["purpose"]),
    )
    domain.refresh_custodian(to_custodian)
    domain.refresh_item_transfer_count(item)
    domain.refresh_room(room)
    return ok(ser.transfer(transfer))


@bp.post("/custody-transfers/<transfer_id>/return")
def return_transfer(transfer_id):
    principal = authorize(["EvidenceTechnician"])
    transfer = domain.find(db.transfers, transfer_id, "ERR_CUSTODY_TRANSFER_NOT_FOUND")
    data = v.body()
    receipt_signature = v.req_str(data, "receipt_signature", min_len=1)

    item = db.items.get(transfer["evidence_item_id"])
    location = domain.location_of_item(item)
    room = domain.room_of_item(item)
    to_custodian = db.custodians.get(transfer["to_custodian_id"])

    domain.gate_locked_down(room)

    if transfer["status"] not in ("RELEASED", "OVERDUE"):
        raise ApiError("ERR_TRANSFER_STATE_INVALID")
    if item["custody_state"] != "CHECKED_OUT":
        raise ApiError("ERR_ITEM_CUSTODY_STATE_INVALID")
    if location is not None and location["status"] != "OPEN":
        raise ApiError("ERR_LOCATION_SEALED")

    domain.gate_active(principal.custodian, to_custodian)

    transfer["status"] = "RETURNED"
    transfer["returned_at"] = now()
    transfer["receipt_signature"] = receipt_signature
    mark(transfer)

    item["custody_state"] = "STORED"
    item["current_holder_id"] = None
    mark(item)

    domain.refresh_location(location)
    domain.append_chain_event(
        item,
        "RECEIPT",
        principal.role,
        principal.custodian_id,
        receipt_signature,
        "Item received back into the property room.",
    )
    domain.refresh_custodian(to_custodian)
    domain.refresh_item_transfer_count(item)
    domain.refresh_room(room)
    return ok(ser.transfer(transfer))


@bp.post("/custody-transfers/<transfer_id>/report-lost")
def report_lost(transfer_id):
    principal = authorize(["PropertyRoomManager"])
    transfer = domain.find(db.transfers, transfer_id, "ERR_CUSTODY_TRANSFER_NOT_FOUND")
    data = v.body()
    reason = v.req_str(data, "reason", min_len=1)

    item = db.items.get(transfer["evidence_item_id"])
    room = domain.room_of_item(item)
    to_custodian = db.custodians.get(transfer["to_custodian_id"])

    domain.gate_locked_down(room)

    if transfer["status"] not in ("RELEASED", "OVERDUE"):
        raise ApiError("ERR_TRANSFER_STATE_INVALID")
    if item["custody_state"] != "CHECKED_OUT":
        raise ApiError("ERR_ITEM_CUSTODY_STATE_INVALID")

    transfer["status"] = "LOST"
    transfer["denial_reason"] = reason
    mark(transfer)

    item["current_holder_id"] = None
    mark(item)
    domain.raise_missing_discrepancy(item, None, principal.role, principal.custodian_id)

    domain.refresh_custodian(to_custodian)
    domain.refresh_item_transfer_count(item)
    domain.refresh_room(room)
    return ok(ser.transfer(transfer))
