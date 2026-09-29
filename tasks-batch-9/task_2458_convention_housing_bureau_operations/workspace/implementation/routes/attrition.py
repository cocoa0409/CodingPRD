"""Reduction rights: filing, approval and the exercise cascade (PRD §3.7)."""

from flask import Blueprint

import calc
import serializers as ser
import validators as V
from auth import authenticate
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import STORE, base_record, clock_before_date, touch

bp = Blueprint("attrition", __name__, url_prefix="/housing")

REDUCTION_READ_ROLES = ["BureauCoordinator", "BureauController", "EventOrganizer", "HotelManager"]


@bp.post("/attrition-reductions")
def file_reduction():
    principal = authenticate(["BureauCoordinator"])
    body = V.json_body()

    hotel_block_id = V.field_str(body, "hotel_block_id")
    requested_reduction_rooms = V.field_int(body, "requested_reduction_rooms", minimum=1)
    effective_date = V.field_date(body, "effective_date")
    justification_code = V.field_str(body, "justification_code")

    block = V.get_block(hotel_block_id)
    event = calc.event_of_block(block)

    # step 12 — the reduction window closes AT the attrition deadline midnight.
    if event is not None and not clock_before_date(event["attrition_deadline_date"]):
        fail("ERR_REDUCTION_WINDOW_CLOSED", "the attrition reduction window has closed")

    # step 20 — remaining rights headroom
    headroom = calc.reduction_rights_headroom(block)
    if requested_reduction_rooms > headroom:
        fail(
            "ERR_REDUCTION_RIGHTS_EXCEEDED",
            "only %d rooms of reduction rights remain" % max(0, headroom),
        )

    record = base_record()
    record.update(
        {
            "hotel_block_id": block["id"],
            "requested_reduction_rooms": requested_reduction_rooms,
            "effective_date": effective_date,
            "justification_code": justification_code,
            "status": "SUBMITTED",
            "requested_by_user_id": principal.user_id,
            "approved_by_user_id": None,
            "rooms_absorbed_from_unassigned": 0,
            "rooms_absorbed_from_sub_blocks": 0,
            "penalty_avoided_cents": None,
        }
    )
    STORE.reductions[record["id"]] = record
    return created(ser.reduction_out(record))


@bp.get("/attrition-reductions/<reduction_id>")
def read_reduction(reduction_id):
    authenticate(REDUCTION_READ_ROLES)
    reduction = V.get_reduction(reduction_id)
    return ok(ser.reduction_out(reduction))


@bp.get("/hotel-blocks/<block_id>/attrition-reductions")
def list_block_reductions(block_id):
    authenticate(REDUCTION_READ_ROLES)
    limit, offset = V.pagination_args()
    block = V.get_block(block_id)

    items = calc.reductions_of_block(block["id"])
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.reduction_out(r) for r in page], pagination)


@bp.post("/attrition-reductions/<reduction_id>/approve")
def approve_reduction(reduction_id):
    principal = authenticate(["BureauController"])
    V.json_body()
    reduction = V.get_reduction(reduction_id)

    # step 7 — segregation of duties
    if principal.user_id == reduction["requested_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the requester may not approve their own reduction")
    # step 8 — own-state
    if reduction["status"] != "SUBMITTED":
        fail("ERR_INVALID_REDUCTION_STATE", "only a SUBMITTED reduction may be approved")
    # step 9 — the parent block must be OPEN or CUTOFF_PASSED
    block = STORE.hotel_blocks.get(reduction["hotel_block_id"])
    if block is None or block["status"] not in ("OPEN", "CUTOFF_PASSED"):
        fail("ERR_INVALID_BLOCK_STATE", "the parent block must be OPEN or CUTOFF_PASSED")

    reduction["status"] = "APPROVED"
    reduction["approved_by_user_id"] = principal.user_id
    touch(reduction)
    return ok(ser.reduction_out(reduction))


@bp.post("/attrition-reductions/<reduction_id>/reject")
def reject_reduction(reduction_id):
    principal = authenticate(["BureauController"])
    V.json_body()
    reduction = V.get_reduction(reduction_id)

    if principal.user_id == reduction["requested_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the requester may not reject their own reduction")
    if reduction["status"] != "SUBMITTED":
        fail("ERR_INVALID_REDUCTION_STATE", "only a SUBMITTED reduction may be rejected")

    reduction["status"] = "REJECTED"
    touch(reduction)
    return ok(ser.reduction_out(reduction))


@bp.post("/attrition-reductions/<reduction_id>/exercise")
def exercise_reduction(reduction_id):
    authenticate(["BureauCoordinator"])
    V.json_body()
    reduction = V.get_reduction(reduction_id)

    # step 8 — own-state before the cross-entity block gate
    if reduction["status"] != "APPROVED":
        fail("ERR_INVALID_REDUCTION_STATE", "only an APPROVED reduction may be exercised")
    block = STORE.hotel_blocks.get(reduction["hotel_block_id"])
    if block is None or block["status"] not in ("OPEN", "CUTOFF_PASSED"):
        fail("ERR_INVALID_BLOCK_STATE", "the parent block must be OPEN or CUTOFF_PASSED")

    rooms = reduction["requested_reduction_rooms"]

    # LINK 1 — the contract shrinks (contracted_room_nights is derived).
    block["contracted_rooms_per_night"] -= rooms
    touch(block)

    # LINK 2 — the waterfall: unassigned inventory absorbs first.
    outstanding = rooms
    from_unassigned = min(outstanding, block["unassigned_rooms_per_night"])
    block["unassigned_rooms_per_night"] -= from_unassigned
    outstanding -= from_unassigned

    eligible = [
        sb for sb in calc.sub_blocks_of_block(block["id"]) if sb["approval_status"] == "APPROVED"
    ]
    eligible.sort(key=lambda sb: (calc.SEGMENT_RANK.get(sb["segment"], 99), sb["carve_seq"]))
    touched_sub_blocks = []
    for sub_block in eligible:
        if outstanding <= 0:
            break
        give = min(outstanding, sub_block["allotted_rooms"])
        if give <= 0:
            continue
        sub_block["allotted_rooms"] -= give
        outstanding -= give
        touched_sub_blocks.append(sub_block)

    from_sub_blocks = rooms - from_unassigned

    # LINKS 3 and 4 — unwind over-commitment, then re-derive.
    for sub_block in touched_sub_blocks:
        calc.waitlist_overcommitment(sub_block)
        calc.sync_sub_block_quiet(sub_block)
        touch(sub_block)
    event = calc.event_of_block(block)
    calc.recompute_event(event)

    # Only after the cascade settles are the penalty figures written.  Both
    # variants read the SAME post-cascade actual room nights.
    actual = calc.block_actual_room_nights(block)
    post_reduction = calc.attrition_penalty_exposure(block, actual_room_nights=actual)
    pre_reduction = calc.attrition_penalty_exposure(
        block,
        contracted_rooms=block["contracted_rooms_per_night"] + rooms,
        actual_room_nights=actual,
    )
    block["attrition_liability_cents"] = post_reduction

    reduction["status"] = "EXERCISED"
    reduction["rooms_absorbed_from_unassigned"] = from_unassigned
    reduction["rooms_absorbed_from_sub_blocks"] = from_sub_blocks
    reduction["penalty_avoided_cents"] = pre_reduction - post_reduction
    touch(reduction)
    return ok(ser.reduction_out(reduction))
