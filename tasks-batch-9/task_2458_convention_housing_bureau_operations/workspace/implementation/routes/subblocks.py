"""Segregated sub-block carves, controller approval and release (PRD §3.3)."""

from flask import Blueprint

import calc
import serializers as ser
import validators as V
from auth import authenticate
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import STORE, base_record, touch

bp = Blueprint("subblocks", __name__, url_prefix="/housing")

SEGMENTS = ("GENERAL", "VIP", "STAFF", "EXHIBITOR")
APPROVAL_STATUSES = ("PENDING_APPROVAL", "APPROVED", "REJECTED", "RELEASED")
READ_ROLES = [
    "BureauCoordinator",
    "BureauController",
    "EventOrganizer",
    "HotelManager",
    "Attendee",
]


@bp.post("/hotel-blocks/<block_id>/sub-blocks")
def carve_sub_block(block_id):
    principal = authenticate(["BureauCoordinator", "EventOrganizer"])
    body = V.json_body()

    segment = V.field_enum(body, "segment", SEGMENTS)
    allotted_rooms = V.field_int(body, "allotted_rooms", minimum=1)
    eligibility_code = V.field_str(body, "eligibility_code", required=False)
    parent_sub_block_id = V.field_str(body, "parent_sub_block_id", required=False)
    expected_version = V.field_int(body, "expected_hotel_block_version", minimum=0)

    # §3.3 — the code is coupled to the segment.
    if segment == "GENERAL" and eligibility_code is not None:
        fail("ERR_INVALID_REQUEST", "eligibility_code must be omitted for a GENERAL segment")
    if segment != "GENERAL" and eligibility_code is None:
        fail("ERR_INVALID_REQUEST", "eligibility_code is required for segment %s" % segment)

    # step 4 — the path identifier resolves before anything in the body.
    block = V.get_block(block_id)
    parent = V.get_sub_block(parent_sub_block_id) if parent_sub_block_id is not None else None

    # step 6 — ownership: an organizer may only carve on its own event.
    if principal.role == "EventOrganizer" and block["event_id"] != principal.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "the acting organizer does not own this event")
    # step 10 — optimistic concurrency
    if expected_version != block["version"]:
        fail("ERR_STALE_BLOCK_VERSION", "expected_hotel_block_version does not match the block version")
    # step 14 — event posture
    event = calc.event_of_block(block)
    if event is not None and calc.derived_event(event)["housing_posture"] == "CLOSED":
        fail("ERR_EVENT_NOT_ACCEPTING_HOUSING", "the event housing posture is CLOSED")
    # step 19 — carve inventory
    if parent is None:
        if allotted_rooms > block["unassigned_rooms_per_night"]:
            fail(
                "ERR_BLOCK_UNASSIGNED_ROOMS_EXCEEDED",
                "the block has only %d unassigned rooms per night"
                % block["unassigned_rooms_per_night"],
            )
    else:
        _, parent_available, _ = calc.derived_sub_block(parent)
        if allotted_rooms > parent_available:
            fail(
                "ERR_BLOCK_UNASSIGNED_ROOMS_EXCEEDED",
                "the parent sub-block has only %d available rooms" % parent_available,
            )

    record = base_record()
    record.update(
        {
            "hotel_block_id": block["id"],
            "parent_sub_block_id": parent["id"] if parent is not None else None,
            "segment": segment,
            "allotted_rooms": allotted_rooms,
            "eligibility_code": eligibility_code,
            # A GENERAL carve is self-approving; every other segment waits.
            "approval_status": "APPROVED" if segment == "GENERAL" else "PENDING_APPROVAL",
            "carve_seq": STORE.next_carve_seq(),
            "requested_by_user_id": principal.user_id,
            "approved_by_user_id": None,
            "committed_rooms": 0,
            "available_rooms": allotted_rooms,
            "released_rooms": 0,
            "inventory_status": "FULL" if allotted_rooms == 0 else "OPEN",
        }
    )
    STORE.sub_blocks[record["id"]] = record

    if parent is None:
        block["unassigned_rooms_per_night"] -= allotted_rooms
    else:
        parent["allotted_rooms"] -= allotted_rooms
        calc.sync_sub_block_quiet(parent)
        touch(parent)
    touch(block)
    calc.sync_sub_block_quiet(record)
    calc.recompute_event(event)
    return created(ser.sub_block_out(record))


@bp.get("/sub-blocks/<sub_block_id>")
def read_sub_block(sub_block_id):
    authenticate(READ_ROLES)
    sub_block = V.get_sub_block(sub_block_id)
    return ok(ser.sub_block_out(sub_block))


@bp.get("/sub-blocks")
def list_sub_blocks():
    authenticate(READ_ROLES)
    hotel_block_id = V.str_arg("hotel_block_id")
    parent_sub_block_id = V.str_arg("parent_sub_block_id")
    segment = V.enum_arg("segment", SEGMENTS)
    approval_status = V.enum_arg("approval_status", APPROVAL_STATUSES)
    limit, offset = V.pagination_args()

    items = list(STORE.sub_blocks.values())
    if hotel_block_id is not None:
        items = [sb for sb in items if sb["hotel_block_id"] == hotel_block_id]
    if parent_sub_block_id is not None:
        items = [sb for sb in items if sb["parent_sub_block_id"] == parent_sub_block_id]
    if segment is not None:
        items = [sb for sb in items if sb["segment"] == segment]
    if approval_status is not None:
        items = [sb for sb in items if sb["approval_status"] == approval_status]
    items = sorted(items, key=lambda sb: (sb["created_at"], sb["_seq"]))
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.sub_block_out(sb) for sb in page], pagination)


@bp.post("/sub-blocks/<sub_block_id>/approve")
def approve_sub_block(sub_block_id):
    principal = authenticate(["BureauController"])
    V.json_body()
    sub_block = V.get_sub_block(sub_block_id)

    # step 7 — segregation of duties
    if principal.user_id == sub_block["requested_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the requester may not approve their own carve")
    # step 8 — own-state
    if sub_block["approval_status"] != "PENDING_APPROVAL":
        fail("ERR_INVALID_SUB_BLOCK_STATE", "only a PENDING_APPROVAL sub-block may be approved")
    # step 9 — the parent block must be CONTRACTED or OPEN
    block = calc.block_of_sub_block(sub_block)
    if block is None or block["status"] not in ("CONTRACTED", "OPEN"):
        fail("ERR_INVALID_BLOCK_STATE", "the parent block must be CONTRACTED or OPEN")

    sub_block["approval_status"] = "APPROVED"
    sub_block["approved_by_user_id"] = principal.user_id
    calc.sync_sub_block_quiet(sub_block)
    touch(sub_block)
    calc.recompute_event_of_block(block)
    return ok(ser.sub_block_out(sub_block))


@bp.post("/sub-blocks/<sub_block_id>/reject")
def reject_sub_block(sub_block_id):
    principal = authenticate(["BureauController"])
    V.json_body()
    sub_block = V.get_sub_block(sub_block_id)

    if principal.user_id == sub_block["requested_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the requester may not reject their own carve")
    if sub_block["approval_status"] != "PENDING_APPROVAL":
        fail("ERR_INVALID_SUB_BLOCK_STATE", "only a PENDING_APPROVAL sub-block may be rejected")

    block = calc.block_of_sub_block(sub_block)
    rooms = sub_block["allotted_rooms"]
    # The rooms go back the way they came.
    if sub_block["parent_sub_block_id"] is None:
        block["unassigned_rooms_per_night"] += rooms
    else:
        parent = STORE.sub_blocks.get(sub_block["parent_sub_block_id"])
        if parent is not None:
            parent["allotted_rooms"] += rooms
            calc.sync_sub_block_quiet(parent)
            touch(parent)
    sub_block["allotted_rooms"] = 0
    sub_block["approval_status"] = "REJECTED"
    calc.sync_sub_block_quiet(sub_block)
    touch(sub_block)
    touch(block)
    calc.recompute_event_of_block(block)
    return ok(ser.sub_block_out(sub_block))


@bp.post("/sub-blocks/<sub_block_id>/release")
def release_sub_block(sub_block_id):
    authenticate(["BureauCoordinator"])
    body = V.json_body()
    rooms = V.field_int(body, "rooms", minimum=0)
    sub_block = V.get_sub_block(sub_block_id)

    # step 8 — own-state
    if sub_block["approval_status"] != "APPROVED":
        fail("ERR_INVALID_SUB_BLOCK_STATE", "only an APPROVED sub-block may be released")
    # step 21 — release headroom
    committed, _available, _status = calc.derived_sub_block(sub_block)
    if rooms > sub_block["allotted_rooms"] - committed:
        fail(
            "ERR_SUB_BLOCK_HAS_COMMITTED_ROOMS",
            "only %d unsold rooms may be released" % (sub_block["allotted_rooms"] - committed),
        )
    full_release = rooms == sub_block["allotted_rooms"]
    if full_release and committed != 0:
        fail("ERR_SUB_BLOCK_HAS_COMMITTED_ROOMS", "a full release requires zero committed rooms")

    block = calc.block_of_sub_block(sub_block)
    sub_block["released_rooms"] += rooms
    if full_release:
        sub_block["allotted_rooms"] = 0
        sub_block["approval_status"] = "RELEASED"
    else:
        sub_block["allotted_rooms"] -= rooms
    block["released_rooms_per_night"] += rooms

    calc.sync_sub_block_quiet(sub_block)
    touch(sub_block)
    touch(block)
    calc.recompute_event_of_block(block)
    return ok(ser.sub_block_out(sub_block))
