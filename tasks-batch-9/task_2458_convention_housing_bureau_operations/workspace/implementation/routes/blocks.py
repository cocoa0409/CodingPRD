"""Hotel block assembly, terms negotiation, contracting and lifecycle (PRD §3.2, §3.4, §3.9)."""

from flask import Blueprint

import calc
import serializers as ser
import validators as V
from auth import authenticate
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import (
    ALL_ROLES,
    STORE,
    base_record,
    clock_at_or_after_date,
    clock_before_date,
    touch,
)

bp = Blueprint("blocks", __name__, url_prefix="/housing")

BLOCK_STATUSES = (
    "DRAFT",
    "TERMS_SUBMITTED",
    "CHANGES_REQUESTED",
    "CONTRACTED",
    "OPEN",
    "CUTOFF_PASSED",
    "CLOSED",
)


@bp.post("/hotel-blocks")
def create_block():
    authenticate(["BureauCoordinator"])
    body = V.json_body()

    event_id = V.field_str(body, "event_id")
    hotel_id = V.field_str(body, "hotel_id")
    contracted_rooms_per_night = V.field_int(body, "contracted_rooms_per_night", minimum=1)
    negotiated_nightly_rate_cents = V.field_int(body, "negotiated_nightly_rate_cents", minimum=1)
    commission_pct = V.field_number(body, "commission_pct", exclusive_minimum=0, maximum=0.25)
    rebate_per_room_night_cents = V.field_int(body, "rebate_per_room_night_cents", minimum=0)
    cutoff_date = V.field_date(body, "cutoff_date")
    reduction_rights_pct = V.field_number(body, "reduction_rights_pct", minimum=0, maximum=0.50)

    event = V.get_event(event_id)
    V.get_hotel(hotel_id)

    record = base_record()
    record.update(
        {
            "event_id": event_id,
            "hotel_id": hotel_id,
            "status": "DRAFT",
            "revision_round": 0,
            "negotiated_nightly_rate_cents": negotiated_nightly_rate_cents,
            "commission_pct": commission_pct,
            "rebate_per_room_night_cents": rebate_per_room_night_cents,
            "cutoff_date": cutoff_date,
            "reduction_rights_pct": reduction_rights_pct,
            "contracted_rooms_per_night": contracted_rooms_per_night,
            "original_contracted_rooms_per_night": None,
            "unassigned_rooms_per_night": 0,
            "released_rooms_per_night": 0,
            "attrition_liability_cents": 0,
            "confirmation_number": None,
        }
    )
    STORE.hotel_blocks[record["id"]] = record
    calc.recompute_event(event)
    return created(ser.block_out(record))


@bp.get("/hotel-blocks/<block_id>")
def read_block(block_id):
    authenticate(ALL_ROLES)
    block = V.get_block(block_id)
    return ok(ser.block_out(block))


@bp.get("/hotel-blocks")
def list_blocks():
    authenticate(
        ["BureauCoordinator", "BureauController", "EventOrganizer", "HotelManager", "Attendee"]
    )
    event_id = V.str_arg("event_id")
    hotel_id = V.str_arg("hotel_id")
    status = V.enum_arg("status", BLOCK_STATUSES)
    limit, offset = V.pagination_args()

    items = list(STORE.hotel_blocks.values())
    if event_id is not None:
        items = [b for b in items if b["event_id"] == event_id]
    if hotel_id is not None:
        items = [b for b in items if b["hotel_id"] == hotel_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sorted(items, key=lambda b: (b["created_at"], b["_seq"]))
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.block_out(b) for b in page], pagination)


@bp.post("/hotel-blocks/<block_id>/terms")
def submit_terms(block_id):
    authenticate(["BureauCoordinator"])
    body = V.json_body()

    negotiated_nightly_rate_cents = V.field_int(body, "negotiated_nightly_rate_cents", minimum=1)
    commission_pct = V.field_number(body, "commission_pct", exclusive_minimum=0, maximum=0.25)
    rebate_per_room_night_cents = V.field_int(body, "rebate_per_room_night_cents", minimum=0)
    cutoff_date = V.field_date(body, "cutoff_date")
    reduction_rights_pct = V.field_number(body, "reduction_rights_pct", minimum=0, maximum=0.50)
    expected_version = V.field_int(body, "expected_hotel_block_version", minimum=0)

    block = V.get_block(block_id)

    # step 8 — own-state transition legality
    if block["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        fail("ERR_INVALID_BLOCK_STATE", "terms may only be submitted from DRAFT or CHANGES_REQUESTED")
    # step 10 — optimistic concurrency
    if expected_version != block["version"]:
        fail("ERR_STALE_BLOCK_VERSION", "expected_hotel_block_version does not match the block version")
    # step 27 — negotiation rounds
    if block["revision_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", "the negotiation cycle is capped at 3 submissions")

    block["negotiated_nightly_rate_cents"] = negotiated_nightly_rate_cents
    block["commission_pct"] = commission_pct
    block["rebate_per_room_night_cents"] = rebate_per_room_night_cents
    block["cutoff_date"] = cutoff_date
    block["reduction_rights_pct"] = reduction_rights_pct
    block["revision_round"] += 1
    block["status"] = "TERMS_SUBMITTED"
    touch(block)
    calc.recompute_event_of_block(block)
    return ok(ser.block_out(block))


@bp.post("/hotel-blocks/<block_id>/request-changes")
def request_changes(block_id):
    principal = authenticate(["HotelManager"])
    V.json_body()
    block = V.get_block(block_id)

    # step 6 — ownership
    if block["hotel_id"] != principal.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "the acting hotel does not own this block")
    # step 8 — own-state
    if block["status"] != "TERMS_SUBMITTED":
        fail("ERR_INVALID_BLOCK_STATE", "changes may only be requested from TERMS_SUBMITTED")

    block["status"] = "CHANGES_REQUESTED"
    touch(block)
    calc.recompute_event_of_block(block)
    return ok(ser.block_out(block))


@bp.post("/hotel-blocks/<block_id>/contract")
def contract_block(block_id):
    principal = authenticate(["HotelManager"])
    body = V.json_body()
    confirmation_number = V.field_str(body, "confirmation_number", required=False, min_len=0)

    block = V.get_block(block_id)

    # step 6 — ownership
    if block["hotel_id"] != principal.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "the acting hotel does not own this block")
    # step 8 — own-state
    if block["status"] != "TERMS_SUBMITTED":
        fail("ERR_INVALID_BLOCK_STATE", "a block may only be contracted from TERMS_SUBMITTED")
    # step 9 — cross-entity state gate
    hotel = STORE.hotels.get(block["hotel_id"])
    if hotel is None or hotel["standing"] != "ACTIVE":
        fail("ERR_HOTEL_SUSPENDED", "the property standing is not ACTIVE")
    # step 26 — standardization
    event = calc.event_of_block(block)
    if (
        block["commission_pct"] < event["standard_commission_pct"]
        or block["rebate_per_room_night_cents"] < event["standard_rebate_per_room_night_cents"]
        or block["cutoff_date"] != event["cutoff_date"]
    ):
        fail("ERR_TERMS_NOT_STANDARDIZED", "block terms violate the event standardization floor")

    block["status"] = "CONTRACTED"
    block["original_contracted_rooms_per_night"] = block["contracted_rooms_per_night"]
    block["unassigned_rooms_per_night"] = block["contracted_rooms_per_night"]
    if confirmation_number is not None:
        block["confirmation_number"] = confirmation_number
    touch(block)
    calc.recompute_event(event)
    return ok(ser.block_out(block))


@bp.post("/hotel-blocks/<block_id>/open")
def open_block(block_id):
    authenticate(["BureauCoordinator"])
    V.json_body()
    block = V.get_block(block_id)

    # step 8 — own-state
    if block["status"] != "CONTRACTED":
        fail("ERR_INVALID_BLOCK_STATE", "a block may only be opened from CONTRACTED")
    # step 9 — cross-entity state gate
    approved = [
        sb for sb in calc.sub_blocks_of_block(block["id"]) if sb["approval_status"] == "APPROVED"
    ]
    if not approved:
        fail("ERR_NO_APPROVED_SUB_BLOCK", "the block has no APPROVED sub-block")
    # step 11 — clock gate
    if not clock_before_date(block["cutoff_date"]):
        fail("ERR_CUTOFF_PASSED", "the block cutoff date has been reached")

    block["status"] = "OPEN"
    touch(block)
    calc.recompute_event_of_block(block)
    return ok(ser.block_out(block))


@bp.post("/hotel-blocks/<block_id>/cutoff")
def cutoff_block(block_id):
    authenticate(["BureauCoordinator"])
    V.json_body()
    block = V.get_block(block_id)

    if block["status"] != "OPEN":
        fail("ERR_INVALID_BLOCK_STATE", "the cutoff sweep may only run from OPEN")
    if not clock_at_or_after_date(block["cutoff_date"]):
        fail("ERR_CUTOFF_NOT_REACHED", "the block cutoff date has not been reached")

    block["status"] = "CUTOFF_PASSED"

    sub_blocks = [
        sb for sb in calc.sub_blocks_of_block(block["id"]) if sb["approval_status"] == "APPROVED"
    ]
    sub_blocks.sort(key=lambda sb: sb["carve_seq"])
    for sub_block in sub_blocks:
        calc.sync_sub_block_quiet(sub_block)
        committed = sub_block["committed_rooms"]
        released = sub_block["allotted_rooms"] - committed
        mutated = False
        if released != 0:
            sub_block["released_rooms"] += released
            sub_block["allotted_rooms"] = committed
            block["released_rooms_per_night"] += released
            mutated = True
        if sub_block["allotted_rooms"] == 0:
            sub_block["approval_status"] = "RELEASED"
            mutated = True
        calc.sync_sub_block_quiet(sub_block)
        if mutated:
            touch(sub_block)

    if block["unassigned_rooms_per_night"]:
        block["released_rooms_per_night"] += block["unassigned_rooms_per_night"]
        block["unassigned_rooms_per_night"] = 0

    touch(block)
    calc.recompute_event_of_block(block)
    return ok(ser.block_out(block))


@bp.post("/hotel-blocks/<block_id>/close")
def close_block(block_id):
    authenticate(["BureauCoordinator"])
    V.json_body()
    block = V.get_block(block_id)

    if block["status"] != "CUTOFF_PASSED":
        fail("ERR_INVALID_BLOCK_STATE", "a block may only be closed from CUTOFF_PASSED")
    event = calc.event_of_block(block)
    if not clock_at_or_after_date(event["event_end_date"]):
        fail("ERR_EVENT_NOT_ENDED", "the event end date has not been reached")

    block["status"] = "CLOSED"
    block["attrition_liability_cents"] = calc.attrition_penalty_exposure(block)
    touch(block)
    calc.recompute_event(event)
    return ok(ser.block_out(block))


@bp.get("/hotel-blocks/<block_id>/pickup-pace")
def pickup_pace(block_id):
    authenticate(["BureauCoordinator", "BureauController", "EventOrganizer", "HotelManager"])
    block = V.get_block(block_id)
    return ok(calc.block_pickup_pace(block))
