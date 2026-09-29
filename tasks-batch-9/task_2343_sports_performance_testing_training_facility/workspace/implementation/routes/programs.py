"""Periodized program design: programs and their block chain (PRD 3.3)."""

from flask import Blueprint

import response
import serializers
from db import create, now_iso, ordered, store, touch
from errors import ApiError
from middleware import (body_json, guard, pagination, query_enum, query_str,
                        resolve_acting_staff, slice_page, v_date, v_enum,
                        v_id, v_int, v_number, v_string)
from routes.common import (get_athlete, get_program_block, get_training_program,
                           require_state)
from services import calc, domain

bp = Blueprint("programs", __name__)

SPORTS = ("BASKETBALL", "SOCCER", "BASEBALL", "VOLLEYBALL", "TRACK")
PROGRAM_STATUSES = ("DRAFT", "ACTIVE", "ARCHIVED")
PHASES = ("GENERAL_PREP", "SPECIFIC_PREP", "COMPETITION", "TAPER", "TRANSITION")

SEQ_ERROR = "ERR_PROGRAM_BLOCK_SEQUENCE_INVALID"


# ---------------------------------------------------------------- programs ----
@bp.post("/training-programs")
def create_program():
    ctx = guard("PerformanceDirector", "Coach")
    resolve_acting_staff(ctx)
    body = body_json()
    athlete = get_athlete(body.get("athlete_id"))

    sport = v_enum(body, "sport", SPORTS)
    position = v_string(body, "position", min_len=1, max_len=40)
    start = v_date(body, "competition_start_date")
    end = v_date(body, "competition_end_date")
    if sport != athlete["sport"]:
        raise ApiError("ERR_INVALID_REQUEST", "sport must equal the athlete's current sport")
    if position != athlete["position"]:
        raise ApiError("ERR_INVALID_REQUEST", "position must equal the athlete's current position")
    if end <= start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "competition_end_date must be strictly later than competition_start_date",
        )

    record = create(
        store.training_programs,
        {
            "athlete_id": athlete["id"],
            "sport": sport,
            "position": position,
            "competition_start_date": start.isoformat(),
            "competition_end_date": end.isoformat(),
            "status": "DRAFT",
            "planned_load_units": 0,
            "pinned_block_versions": None,
            "activated_at": None,
        },
    )
    return response.created(serializers.training_program(record))


@bp.get("/training-programs/<training_program_id>")
def read_program(training_program_id):
    ctx = guard("PerformanceDirector", "Coach", "Athlete", "Guardian")
    program = get_training_program(training_program_id)
    resolve_acting_staff(ctx)
    return response.ok(serializers.training_program(program))


@bp.get("/training-programs")
def list_programs():
    ctx = guard("PerformanceDirector", "Coach")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    athlete_id = query_str("athlete_id")
    status = query_enum("status", PROGRAM_STATUSES)

    rows = ordered(store.training_programs)
    if athlete_id:
        rows = [r for r in rows if r["athlete_id"] == athlete_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = slice_page(rows, limit, offset)
    return response.ok_list([serializers.training_program(r) for r in page], limit, offset, total)


# ------------------------------------------------------------------ blocks ----
@bp.post("/training-programs/<training_program_id>/blocks")
def append_block(training_program_id):
    ctx = guard("PerformanceDirector", "Coach")
    program = get_training_program(training_program_id)
    resolve_acting_staff(ctx)
    body = body_json()

    predecessor = None
    if body.get("predecessor_block_id") is not None:
        predecessor = get_program_block(body.get("predecessor_block_id"))

    expected = v_int(body, "expected_training_program_version")
    phase = v_enum(body, "phase", PHASES)
    start_week = v_int(body, "start_week", minimum=1)
    end_week = v_int(body, "end_week", minimum=1)
    intensity = v_int(body, "target_intensity_pct", minimum=40, maximum=105)
    volume = v_number(body, "weekly_volume_units", exclusive_minimum=0)
    if end_week < start_week:
        raise ApiError("ERR_INVALID_REQUEST", "end_week may not be earlier than start_week")

    if expected != program["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_training_program_version does not match the program's current version",
        )

    require_state(program, "status", ("DRAFT",), ("ARCHIVED",), "TrainingProgram")

    blocks = serializers.program_blocks_of(program["id"])
    if predecessor is None:
        if blocks:
            raise ApiError(SEQ_ERROR, "Only the first block of a program may omit predecessor_block_id")
        if start_week != 1:
            raise ApiError(SEQ_ERROR, "The root block must start at week 1")
    else:
        if not blocks:
            raise ApiError(SEQ_ERROR, "The first block of a program must have a null predecessor_block_id")
        if predecessor["training_program_id"] != program["id"]:
            raise ApiError(SEQ_ERROR, "predecessor_block_id must name a block of the same program")
        if any(b["predecessor_block_id"] == predecessor["id"] for b in blocks):
            raise ApiError(SEQ_ERROR, "That predecessor block already has a successor")
        if start_week != predecessor["end_week"] + 1:
            raise ApiError(
                SEQ_ERROR,
                "start_week must be exactly one greater than the predecessor's end_week",
            )

    record = create(
        store.program_blocks,
        {
            "training_program_id": program["id"],
            "predecessor_block_id": predecessor["id"] if predecessor else None,
            "phase": phase,
            "start_week": start_week,
            "end_week": end_week,
            "target_intensity_pct": intensity,
            "weekly_volume_units": volume,
            "status": "PLANNED",
            "sequence_index": len(blocks),
        },
    )
    touch(program)
    return response.created(serializers.program_block(record))


@bp.get("/program-blocks/<program_block_id>")
def read_block(program_block_id):
    ctx = guard("PerformanceDirector", "Coach", "Athlete", "Guardian")
    block = get_program_block(program_block_id)
    resolve_acting_staff(ctx)
    return response.ok(serializers.program_block(block))


@bp.get("/program-blocks")
def list_blocks():
    ctx = guard("PerformanceDirector", "Coach")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    program_id = query_str("training_program_id")
    predecessor_id = query_str("predecessor_block_id")
    phase = query_enum("phase", PHASES)

    rows = ordered(store.program_blocks)
    if program_id:
        rows = [r for r in rows if r["training_program_id"] == program_id]
    if predecessor_id:
        rows = [r for r in rows if r["predecessor_block_id"] == predecessor_id]
    if phase:
        rows = [r for r in rows if r["phase"] == phase]
    page, total = slice_page(rows, limit, offset)
    return response.ok_list([serializers.program_block(r) for r in page], limit, offset, total)


# -------------------------------------------------------------- activation ----
def _validate_chain(blocks):
    if len(blocks) < 2:
        raise ApiError(SEQ_ERROR, "A program needs at least two blocks to be activated")
    roots = [b for b in blocks if b["predecessor_block_id"] is None]
    if len(roots) != 1:
        raise ApiError(SEQ_ERROR, "Exactly one block may have a null predecessor_block_id")
    by_id = {b["id"]: b for b in blocks}
    successors = {}
    for block in blocks:
        pred = block["predecessor_block_id"]
        if pred is None:
            continue
        if pred not in by_id:
            raise ApiError(SEQ_ERROR, "A block names a predecessor outside this program")
        if pred in successors:
            raise ApiError(SEQ_ERROR, "The block chain branches: a predecessor has two successors")
        successors[pred] = block

    walked = []
    current = roots[0]
    seen = set()
    while current is not None:
        if current["id"] in seen:
            raise ApiError(SEQ_ERROR, "The block chain contains a cycle")
        seen.add(current["id"])
        walked.append(current)
        current = successors.get(current["id"])
    if len(walked) != len(blocks):
        raise ApiError(SEQ_ERROR, "The blocks do not form a single unbroken chain")

    for block in walked[1:]:
        predecessor = by_id[block["predecessor_block_id"]]
        if block["start_week"] != predecessor["end_week"] + 1:
            raise ApiError(
                SEQ_ERROR,
                "start_week must be exactly one greater than the predecessor's end_week",
            )
    if not any(b["phase"] == "COMPETITION" for b in blocks):
        raise ApiError(SEQ_ERROR, "A program needs at least one COMPETITION block")
    return walked


@bp.post("/training-programs/<training_program_id>/activate")
def activate_program(training_program_id):
    guard("PerformanceDirector")
    program = get_training_program(training_program_id)
    body_json()

    require_state(program, "status", ("DRAFT",), ("ARCHIVED",), "TrainingProgram")
    athlete = store.athletes.get(program["athlete_id"])
    if athlete is not None and athlete["membership_status"] == "SUSPENDED":
        raise ApiError(
            "ERR_ATHLETE_SUSPENDED", "A suspended athlete may not have a program activated"
        )

    blocks = serializers.program_blocks_of(program["id"])
    _validate_chain(blocks)

    if athlete is not None and athlete["training_clearance"] == "MEDICAL_HOLD":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A program cannot be activated for an athlete on medical hold",
        )

    ordered_blocks = sorted(blocks, key=lambda b: (b["sequence_index"], b["created_at"], b["_seq"]))
    snapshot = []
    for block in ordered_blocks:
        block["status"] = "PINNED"
        touch(block)
        snapshot.append({"program_block_id": block["id"], "pinned_version": block["version"]})

    program["status"] = "ACTIVE"
    program["pinned_block_versions"] = snapshot
    program["planned_load_units"] = calc.program_planned_load(ordered_blocks)
    program["activated_at"] = now_iso()
    touch(program)

    for other in ordered(store.training_programs):
        if other["id"] == program["id"]:
            continue
        if other["athlete_id"] != program["athlete_id"]:
            continue
        if other["status"] == "ACTIVE":
            other["status"] = "ARCHIVED"
            touch(other)

    return response.ok(serializers.training_program(program))
