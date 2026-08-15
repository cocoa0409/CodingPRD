"""FlushSequence endpoints: create, list, get, start, execute-step, complete, abort."""
from flask import Blueprint, request

import db
from db import new_base, touch
from errors import (
    ApiError,
    ERR_DECHLORINATION_LIMIT_EXCEEDED,
    ERR_FLUSH_SEQUENCE_NOT_FOUND,
    ERR_HYDRANT_NOT_FOUND,
    ERR_HYDRANT_NOT_IN_SERVICE,
    ERR_PROGRAM_MISMATCH,
    ERR_PROGRAM_NOT_FOUND,
    ERR_SEQUENCE_NOT_IN_PROGRESS,
    ERR_SEQUENCE_NOT_PLANNED,
    ERR_SEQUENCE_ZONE_COOLDOWN,
    ERR_STEP_OUT_OF_SEQUENCE,
    ERR_STEPS_INCOMPLETE,
    ERR_ZONE_NOT_FOUND,
    invalid_request,
    not_found,
)
from middleware import auth, auth_any, require_role
from response import success_list, success_object
from serializers import sequence_view
from services import (
    DISCHARGE_LIMIT_MG_L,
    compute_dechlorination_tablets,
    compute_flush_volume,
    resolve_linked_complaints,
    revert_linked_complaints,
    zone_cooldown_violation,
)
from validation import F, paginate, validate_body, validate_empty_body

bp = Blueprint("flush_sequences", __name__)


def get_sequence_or_404(sequence_id):
    s = db.store.flush_sequences.get(sequence_id)
    if s is None:
        raise not_found(ERR_FLUSH_SEQUENCE_NOT_FOUND, "FlushSequence")
    return s


@bp.post("/flush-sequences")
def create_sequence():
    user_id, role = auth()
    body = validate_body([
        F("program_id", "str"),
        F("zone_id", "str"),
        F("hydrant_id", "str"),
        F("window_start", "datetime"),
        F("window_end", "datetime"),
        F("steps", "steps"),
    ])
    if body["window_end"] <= body["window_start"]:
        raise invalid_request("window_end must be strictly after window_start")
    require_role(role, {"FieldOperator"})
    # Body FK existence
    program = db.store.programs.get(body["program_id"])
    if program is None:
        raise not_found(ERR_PROGRAM_NOT_FOUND, "FlushingProgram")
    zone = db.store.zones.get(body["zone_id"])
    if zone is None:
        raise not_found(ERR_ZONE_NOT_FOUND, "PressureZone")
    hydrant = db.store.hydrants.get(body["hydrant_id"])
    if hydrant is None:
        raise not_found(ERR_HYDRANT_NOT_FOUND, "Hydrant")
    # Business constraint: the sequence's program must equal the hydrant's program
    if body["program_id"] != hydrant["program_id"]:
        raise ApiError(
            ERR_PROGRAM_MISMATCH,
            "FlushSequence.program_id differs from its hydrant's program_id",
            422,
        )
    # Temporal: zone cooldown between non-terminal sequences
    if zone_cooldown_violation(zone, body["window_start"], body["window_end"]):
        raise ApiError(
            ERR_SEQUENCE_ZONE_COOLDOWN,
            "Gap to another PLANNED/IN_PROGRESS sequence in this zone is below cooldown_minutes",
            409,
        )
    sequence = new_base()
    sequence.update({
        "program_id": body["program_id"],
        "zone_id": body["zone_id"],
        "hydrant_id": body["hydrant_id"],
        "origin": "SCHEDULED_PROGRAM",
        "status": "PLANNED",
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "steps": body["steps"],
        "source_chlorine_residual_mg_L": None,
        "total_flushed_gallons": None,
        "dechlorination_tablets_required": None,
        "final_discharge_residual_mg_L": None,
    })
    db.store.flush_sequences[sequence["id"]] = sequence
    return success_object(sequence_view(sequence), code=201)


@bp.get("/flush-sequences")
def list_sequences():
    auth_any()
    items = list(db.store.flush_sequences.values())
    for field in ("program_id", "zone_id", "hydrant_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [s for s in items if s[field] == value]
    page, meta = paginate(items)
    return success_list([sequence_view(s) for s in page], meta)


@bp.get("/flush-sequences/<sequence_id>")
def get_sequence(sequence_id):
    auth_any()
    return success_object(sequence_view(get_sequence_or_404(sequence_id)))


@bp.post("/flush-sequences/<sequence_id>/start")
def start_sequence(sequence_id):
    user_id, role = auth()
    body = validate_body([F("source_chlorine_residual_mg_L", "number")])
    require_role(role, {"FieldOperator"})
    sequence = get_sequence_or_404(sequence_id)
    if sequence["status"] != "PLANNED":
        raise ApiError(ERR_SEQUENCE_NOT_PLANNED, "Sequence must be PLANNED to start", 409)
    hydrant = db.store.hydrants[sequence["hydrant_id"]]
    if hydrant["status"] != "IN_SERVICE":
        raise ApiError(ERR_HYDRANT_NOT_IN_SERVICE, "Hydrant must be IN_SERVICE", 409)
    sequence["source_chlorine_residual_mg_L"] = body["source_chlorine_residual_mg_L"]
    sequence["status"] = "IN_PROGRESS"
    touch(sequence)
    return success_object(sequence_view(sequence))


@bp.post("/flush-sequences/<sequence_id>/execute-step")
def execute_step(sequence_id):
    user_id, role = auth()
    body = validate_body([
        F("step_index", "int"),
        F("flow_gpm", "number"),
        F("duration_minutes", "number"),
    ])
    require_role(role, {"FieldOperator"})
    sequence = get_sequence_or_404(sequence_id)
    if sequence["status"] != "IN_PROGRESS":
        raise ApiError(ERR_SEQUENCE_NOT_IN_PROGRESS, "Sequence must be IN_PROGRESS", 409)
    target = None
    for step in sequence["steps"]:
        if step["step_index"] == body["step_index"]:
            target = step
        elif step["step_index"] < body["step_index"] and step["status"] != "EXECUTED":
            # every step with a smaller step_index must already be EXECUTED
            raise ApiError(
                ERR_STEP_OUT_OF_SEQUENCE,
                "An earlier step has not been EXECUTED",
                409,
            )
    if target is None or target["status"] != "PENDING":
        raise ApiError(
            ERR_STEP_OUT_OF_SEQUENCE,
            "Step must exist and be PENDING",
            409,
        )
    target["status"] = "EXECUTED"
    target["executed_at"] = db.now()
    target["executed_by_user_id"] = user_id
    target["flow_gpm"] = body["flow_gpm"]
    target["duration_minutes"] = body["duration_minutes"]
    touch(sequence)
    return success_object(sequence_view(sequence))


@bp.post("/flush-sequences/<sequence_id>/complete")
def complete_sequence(sequence_id):
    user_id, role = auth()
    body = validate_body([F("final_discharge_residual_mg_L", "number")])
    require_role(role, {"FieldOperator"})
    sequence = get_sequence_or_404(sequence_id)
    if sequence["status"] != "IN_PROGRESS":
        raise ApiError(ERR_SEQUENCE_NOT_IN_PROGRESS, "Sequence must be IN_PROGRESS", 409)
    # SAFETY (higher priority) precedes the structural steps check
    final_residual = float(body["final_discharge_residual_mg_L"])
    if final_residual > DISCHARGE_LIMIT_MG_L:
        raise ApiError(
            ERR_DECHLORINATION_LIMIT_EXCEEDED,
            "final_discharge_residual_mg_L must be at most 0.1",
            422,
        )
    if any(step["status"] != "EXECUTED" for step in sequence["steps"]):
        raise ApiError(ERR_STEPS_INCOMPLETE, "Every step must be EXECUTED", 409)
    sequence["final_discharge_residual_mg_L"] = body["final_discharge_residual_mg_L"]
    sequence["total_flushed_gallons"] = compute_flush_volume(sequence["steps"])
    sequence["dechlorination_tablets_required"] = compute_dechlorination_tablets(
        sequence["total_flushed_gallons"], sequence["source_chlorine_residual_mg_L"]
    )
    sequence["status"] = "COMPLETED"
    touch(sequence)
    # CASCADE: LINKED complaints pointing at this sequence -> RESOLVED
    resolve_linked_complaints(sequence)
    hydrant = db.store.hydrants[sequence["hydrant_id"]]
    hydrant["targeted_flush_pending"] = False
    touch(hydrant)
    return success_object(sequence_view(sequence))


@bp.post("/flush-sequences/<sequence_id>/abort")
def abort_sequence(sequence_id):
    user_id, role = auth()
    validate_empty_body()
    require_role(role, {"FieldOperator"})
    sequence = get_sequence_or_404(sequence_id)
    if sequence["status"] != "IN_PROGRESS":
        raise ApiError(ERR_SEQUENCE_NOT_IN_PROGRESS, "Sequence must be IN_PROGRESS", 409)
    sequence["status"] = "ABORTED"
    touch(sequence)
    # COMPENSATION: linked complaints revert to OPEN with the link cleared
    revert_linked_complaints(sequence)
    hydrant = db.store.hydrants[sequence["hydrant_id"]]
    hydrant["targeted_flush_pending"] = False
    touch(hydrant)
    return success_object(sequence_view(sequence))
