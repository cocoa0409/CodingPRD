"""Assembly batches and traveler steps (PRD 3.6)."""

from flask import Blueprint, request

from db import store, new_record, mutate, pub
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ROOM_NOT_ACTIVE,
    ERR_ROOM_NOT_IN_CONTROL,
    ERR_ROOM_NOT_CERTIFIED,
    ERR_GOWNING_NOT_QUALIFIED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_BATCH_VERSION,
    ERR_BATCH_NOT_COMPLETE,
    ERR_BATCH_NOT_ON_HOLD,
    ERR_BATCH_NOT_STARTABLE,
    ERR_BATCH_TRAVELERS_UNSETTLED,
    ERR_TRAVELER_STEP_ORDER,
    ERR_TRAVELER_NOT_IN_PROGRESS,
    ERR_TRAVELER_PERFORMER_MISMATCH,
    ERR_TRAVELER_NOT_VOIDABLE,
)
from middleware import require_role, body, QA, PO
from response import ok, paginate
from services.core import (
    req_string,
    req_int,
    touch_room,
    qualified_unexpired_qualification,
)

bp = Blueprint("batches", __name__)
READERS = [QA, PO]


def load_batch(batch_id):
    batch = store.batches.get(batch_id)
    if batch is None:
        raise ApiError(ERR_NOT_FOUND, 404, "batch %s not found" % batch_id)
    return batch


def load_traveler(traveler_id):
    traveler = store.travelers.get(traveler_id)
    if traveler is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "traveler %s not found" % traveler_id)
    return traveler


def maybe_complete_batch(batch):
    """IN_PROGRESS -> COMPLETE when every traveler is COMPLETE/VOID and at
    least one is COMPLETE."""
    if batch["status"] != "IN_PROGRESS":
        return
    siblings = [t for t in store.travelers.values()
                if t["batch_id"] == batch["id"]]
    if not siblings:
        return
    settled = all(t["status"] in ("COMPLETE", "VOID") for t in siblings)
    any_complete = any(t["status"] == "COMPLETE" for t in siblings)
    if settled and any_complete:
        batch["status"] = "COMPLETE"
        mutate(batch)


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/batches")
def create_batch():
    require_role([PO])
    payload = body()
    cleanroom_id = payload.get("cleanroom_id")
    if not isinstance(cleanroom_id, str) \
            or store.rooms.get(cleanroom_id) is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "cleanroom %s not found" % cleanroom_id)
    touch_room(store.rooms[cleanroom_id])
    batch = new_record({
        "cleanroom_id": cleanroom_id,
        "batch_number": req_string(payload, "batch_number"),
        "product_code": req_string(payload, "product_code"),
        "status": "OPEN",
        "hold_reason": None,
    })
    store.batches[batch["id"]] = batch
    return ok(pub(batch), 201)


@bp.get("/cleanroom/batches")
def list_batches():
    require_role(READERS)
    records = list(store.batches.values())
    cleanroom_id = request.args.get("cleanroom_id")
    status = request.args.get("status")
    if cleanroom_id is not None:
        records = [b for b in records if b["cleanroom_id"] == cleanroom_id]
    if status is not None:
        records = [b for b in records if b["status"] == status]
    return paginate(records, request.args)


@bp.get("/cleanroom/batches/<batchId>")
def get_batch(batchId):
    require_role(READERS)
    return ok(pub(load_batch(batchId)))


@bp.post("/cleanroom/batches/<batchId>/release")
def release_batch(batchId):
    uid = require_role([QA])
    payload = body()
    batch = load_batch(batchId)

    # priority 4: OCC expected_batch_version
    expected = payload.get("expected_batch_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int) \
                or expected != batch["version"]:
            raise ApiError(ERR_STALE_BATCH_VERSION, 412,
                           "expected_batch_version does not match the "
                           "batch's current version")

    # priority 5: state
    if batch["status"] != "COMPLETE":
        raise ApiError(ERR_BATCH_NOT_COMPLETE, 409, "batch is not COMPLETE")

    room = touch_room(store.rooms[batch["cleanroom_id"]])
    # priority 6: posture gate
    if room["environment_posture"] != "IN_CONTROL":
        raise ApiError(ERR_ROOM_NOT_IN_CONTROL, 409,
                       "room environment_posture is not IN_CONTROL")
    # priority 7: certification gate
    if room["certification_status"] != "CERTIFIED":
        raise ApiError(ERR_ROOM_NOT_CERTIFIED, 409,
                       "room certification_status is not CERTIFIED")
    # priority 8: segregation vs every traveler step performer
    siblings = [t for t in store.travelers.values()
                if t["batch_id"] == batch["id"]]
    for t in siblings:
        performer = t.get("performed_by_user_id")
        if performer is not None and performer == uid:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                           "releaser must differ from every traveler step "
                           "performer")

    # priority 9: structural validity
    if expected is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_batch_version is required")

    # priority 12: aggregate guard (defensive; COMPLETE implies settled)
    if any(t["status"] in ("PENDING", "IN_PROGRESS") for t in siblings):
        raise ApiError(ERR_BATCH_TRAVELERS_UNSETTLED, 409,
                       "batch has travelers in PENDING or IN_PROGRESS")

    batch["status"] = "RELEASED"
    mutate(batch)
    return ok(pub(batch))


@bp.post("/cleanroom/batches/<batchId>/reject")
def reject_batch(batchId):
    require_role([QA])
    batch = load_batch(batchId)
    if batch["status"] != "COMPLETE":
        raise ApiError(ERR_BATCH_NOT_COMPLETE, 409, "batch is not COMPLETE")
    batch["status"] = "REJECTED"
    mutate(batch)
    return ok(pub(batch))


@bp.post("/cleanroom/batches/<batchId>/resume")
def resume_batch(batchId):
    require_role([QA])
    batch = load_batch(batchId)
    if batch["status"] != "ON_HOLD":
        raise ApiError(ERR_BATCH_NOT_ON_HOLD, 409, "batch is not ON_HOLD")
    room = touch_room(store.rooms[batch["cleanroom_id"]])
    if room["environment_posture"] != "IN_CONTROL":
        raise ApiError(ERR_ROOM_NOT_IN_CONTROL, 409,
                       "room environment_posture is not IN_CONTROL")
    batch["status"] = "IN_PROGRESS"
    batch["hold_reason"] = None
    mutate(batch)
    return ok(pub(batch))


# ---------------------------------------------------------------------------
# Travelers
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/batches/<batchId>/travelers")
def create_traveler(batchId):
    require_role([PO])
    batch = load_batch(batchId)
    payload = body()
    traveler = new_record({
        "batch_id": batch["id"],
        "step_sequence": req_int(payload, "step_sequence"),
        "step_description": req_string(payload, "step_description"),
        "performed_by_user_id": None,
        "status": "PENDING",
    })
    store.travelers[traveler["id"]] = traveler
    return ok(pub(traveler), 201)


@bp.get("/cleanroom/batches/<batchId>/travelers")
def list_travelers(batchId):
    require_role(READERS)
    batch = load_batch(batchId)
    records = [t for t in store.travelers.values()
               if t["batch_id"] == batch["id"]]
    return paginate(records, request.args)


@bp.get("/cleanroom/travelers/<travelerId>")
def get_traveler(travelerId):
    require_role(READERS)
    return ok(pub(load_traveler(travelerId)))


@bp.post("/cleanroom/travelers/<travelerId>/start")
def start_traveler(travelerId):
    uid = require_role([PO])
    traveler = load_traveler(travelerId)

    # priority 5: traveler transition state, then batch startability
    if traveler["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "traveler is not PENDING")
    batch = store.batches[traveler["batch_id"]]
    if batch["status"] not in ("OPEN", "IN_PROGRESS"):
        raise ApiError(ERR_BATCH_NOT_STARTABLE, 409,
                       "batch is not OPEN or IN_PROGRESS")

    room = touch_room(store.rooms[batch["cleanroom_id"]])
    if room["status"] != "ACTIVE":
        raise ApiError(ERR_ROOM_NOT_ACTIVE, 409, "room is not ACTIVE")
    # priority 6: posture gate
    if room["environment_posture"] != "IN_CONTROL":
        raise ApiError(ERR_ROOM_NOT_IN_CONTROL, 409,
                       "room environment_posture is not IN_CONTROL")
    # priority 11: operator gowning qualification (per-room, unexpired)
    if qualified_unexpired_qualification(uid, room["id"]) is None:
        raise ApiError(ERR_GOWNING_NOT_QUALIFIED, 409,
                       "operator holds no QUALIFIED, unexpired gowning "
                       "qualification for this room")
    # priority 12: ascending step order
    siblings = [t for t in store.travelers.values()
                if t["batch_id"] == batch["id"] and t["id"] != traveler["id"]]
    if any(t["step_sequence"] < traveler["step_sequence"]
           and t["status"] in ("PENDING", "IN_PROGRESS")
           for t in siblings):
        raise ApiError(ERR_TRAVELER_STEP_ORDER, 409,
                       "a lower step_sequence sibling is not yet COMPLETE "
                       "or VOID")

    traveler["performed_by_user_id"] = uid
    traveler["status"] = "IN_PROGRESS"
    mutate(traveler)
    if batch["status"] == "OPEN":
        batch["status"] = "IN_PROGRESS"
        mutate(batch)
    return ok(pub(traveler))


@bp.post("/cleanroom/travelers/<travelerId>/complete")
def complete_traveler(travelerId):
    uid = require_role([PO])
    traveler = load_traveler(travelerId)
    if traveler["status"] != "IN_PROGRESS":
        raise ApiError(ERR_TRAVELER_NOT_IN_PROGRESS, 409,
                       "traveler is not IN_PROGRESS")
    if uid != traveler["performed_by_user_id"]:
        raise ApiError(ERR_TRAVELER_PERFORMER_MISMATCH, 409,
                       "completer must be the operator who started the step")
    traveler["status"] = "COMPLETE"
    mutate(traveler)
    batch = store.batches[traveler["batch_id"]]
    maybe_complete_batch(batch)
    return ok(pub(traveler))


@bp.post("/cleanroom/travelers/<travelerId>/void")
def void_traveler(travelerId):
    require_role([QA])
    traveler = load_traveler(travelerId)
    if traveler["status"] != "PENDING":
        raise ApiError(ERR_TRAVELER_NOT_VOIDABLE, 409,
                       "traveler is not PENDING")
    traveler["status"] = "VOID"
    mutate(traveler)
    batch = store.batches[traveler["batch_id"]]
    maybe_complete_batch(batch)
    return ok(pub(traveler))
