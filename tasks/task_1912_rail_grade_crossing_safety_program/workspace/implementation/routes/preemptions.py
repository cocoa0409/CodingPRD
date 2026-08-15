"""Signal preemption interconnection endpoints (PRD §3.8)."""
import uuid

from flask import Blueprint

from db import now_iso, store
from errors import (
    ApiError,
    ERR_ACTIVE_INTERCONNECTION_EXISTS,
    ERR_CROSSING_NOT_ACTIVE,
    ERR_CROSSING_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_INTERCONNECTION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PREEMPTION_REQUIRES_GATES,
    ERR_PREEMPTION_TIMING_INADEQUATE,
)
from helpers import (
    body_or_empty,
    get_or_404,
    paginate,
    query_filter,
    reject_unknown,
    req_int_range,
    req_str,
)
from middleware import auth
from response import ok, ok_list
from services import calcs

bp = Blueprint("preemption_interconnections", __name__)

ALL_ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")

IC_STATUSES = ("DRAFT", "TIMING_VERIFIED", "COMMISSIONED", "DECOMMISSIONED")
GATE_DEVICE_CLASSES = ("GATES", "FOUR_QUADRANT_GATES")

CREATE_FIELDS = (
    "crossing_id",
    "traffic_signal_ref",
    "track_approach_distance_ft",
    "design_train_speed_mph",
    "clear_storage_distance_ft",
    "advance_preemption_seconds",
    "track_clearance_green_seconds",
)


def serialize_interconnection(ic):
    return {
        "id": ic["id"],
        "crossing_id": ic["crossing_id"],
        "traffic_signal_ref": ic["traffic_signal_ref"],
        "track_approach_distance_ft": ic["track_approach_distance_ft"],
        "design_train_speed_mph": ic["design_train_speed_mph"],
        "clear_storage_distance_ft": ic["clear_storage_distance_ft"],
        "advance_preemption_seconds": ic["advance_preemption_seconds"],
        "track_clearance_green_seconds": ic["track_clearance_green_seconds"],
        "approach_seconds": ic["approach_seconds"],
        "required_clearance_green_seconds": ic["required_clearance_green_seconds"],
        "required_advance_preemption_seconds": ic["required_advance_preemption_seconds"],
        "timing_check_pass": ic["timing_check_pass"],
        "status": ic["status"],
        "created_at": ic["created_at"],
        "updated_at": ic["updated_at"],
        "version": ic["version"],
    }


@bp.post("/preemption-interconnections")
def create_interconnection():
    auth(["ProgramAdministrator"])
    body = body_or_empty()

    # Priority 3: body FK crossing_id.
    crossing_id = body.get("crossing_id")
    if isinstance(crossing_id, str) and crossing_id and crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")

    # Priority 4: the crossing must be ACTIVE.
    crossing = store.crossings.get(crossing_id) if isinstance(crossing_id, str) else None
    if crossing is not None and crossing["status"] != "ACTIVE":
        raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                       f"Crossing {crossing_id} is not ACTIVE (current: {crossing['status']})")

    # Priority 7: request shape, then one-open-interconnection.
    reject_unknown(body, CREATE_FIELDS)
    crossing_id = req_str(body, "crossing_id")
    if crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")
    traffic_signal_ref = req_str(body, "traffic_signal_ref")
    track_approach_distance_ft = req_int_range(body, "track_approach_distance_ft", 1, None)
    design_train_speed_mph = req_int_range(body, "design_train_speed_mph", 1, None)
    clear_storage_distance_ft = req_int_range(body, "clear_storage_distance_ft", 0, None)
    advance_preemption_seconds = req_int_range(body, "advance_preemption_seconds", 0, None)
    track_clearance_green_seconds = req_int_range(body, "track_clearance_green_seconds", 0, None)

    if any(
        ic["crossing_id"] == crossing_id and ic["status"] != "DECOMMISSIONED"
        for ic in store.interconnections.values()
    ):
        raise ApiError(ERR_ACTIVE_INTERCONNECTION_EXISTS, 409,
                       "A non-DECOMMISSIONED interconnection already exists for this crossing")

    timing = calcs.preemption_timing(
        track_approach_distance_ft,
        design_train_speed_mph,
        clear_storage_distance_ft,
        advance_preemption_seconds,
        track_clearance_green_seconds,
    )
    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "crossing_id": crossing_id,
        "traffic_signal_ref": traffic_signal_ref,
        "track_approach_distance_ft": track_approach_distance_ft,
        "design_train_speed_mph": design_train_speed_mph,
        "clear_storage_distance_ft": clear_storage_distance_ft,
        "advance_preemption_seconds": advance_preemption_seconds,
        "track_clearance_green_seconds": track_clearance_green_seconds,
        "approach_seconds": timing["approach_seconds"],
        "required_clearance_green_seconds": timing["required_clearance_green_seconds"],
        "required_advance_preemption_seconds": timing["required_advance_preemption_seconds"],
        "timing_check_pass": timing["timing_check_pass"],
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.interconnections[rec["id"]] = rec
    return ok(serialize_interconnection(rec), 201)


@bp.get("/preemption-interconnections")
def list_interconnections():
    auth(ALL_ROLES)
    crossing_f = query_filter("crossing_id")
    status_f = query_filter("status")
    items = []
    for ic in store.interconnections.values():
        if crossing_f is not None and ic["crossing_id"] != crossing_f:
            continue
        if status_f is not None and ic["status"] != status_f:
            continue
        items.append(ic)
    items = sorted(items, key=lambda ic: ic["created_at"])
    page, meta = paginate([serialize_interconnection(ic) for ic in items])
    return ok_list(page, meta)


@bp.get("/preemption-interconnections/<interconnection_id>")
def get_interconnection(interconnection_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.interconnections, interconnection_id, ERR_INTERCONNECTION_NOT_FOUND,
                     f"Preemption interconnection {interconnection_id} does not exist")
    return ok(serialize_interconnection(rec))


@bp.post("/preemption-interconnections/<interconnection_id>/transition")
def transition_interconnection(interconnection_id):
    user_id, role = auth(["ProgramAdministrator", "RailSafetyOfficer"])
    body = body_or_empty()
    to_status = body.get("to_status")

    # Fixed per-target role admission (priority 2; PRD §3.8 actors).
    if to_status in ("TIMING_VERIFIED", "COMMISSIONED") and role != "RailSafetyOfficer":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       "Only a RailSafetyOfficer may verify or commission an interconnection")
    if to_status == "DECOMMISSIONED" and role != "ProgramAdministrator":
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       "Only a ProgramAdministrator may decommission an interconnection")

    rec = get_or_404(store.interconnections, interconnection_id, ERR_INTERCONNECTION_NOT_FOUND,
                     f"Preemption interconnection {interconnection_id} does not exist")
    reject_unknown(body, ("to_status",))
    if not isinstance(to_status, str) or to_status not in IC_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"to_status must be one of: {', '.join(IC_STATUSES)}")

    if to_status == "TIMING_VERIFIED":
        if rec["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot verify timing from {rec['status']}")
        if not rec["timing_check_pass"]:
            raise ApiError(ERR_PREEMPTION_TIMING_INADEQUATE, 422,
                           "The design fails the preemption timing check")
        rec["status"] = "TIMING_VERIFIED"
    elif to_status == "COMMISSIONED":
        if rec["status"] != "TIMING_VERIFIED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot commission from {rec['status']}")
        crossing = store.crossings.get(rec["crossing_id"])
        if crossing is None or crossing["status"] != "ACTIVE":
            raise ApiError(ERR_CROSSING_NOT_ACTIVE, 409,
                           "The crossing is not ACTIVE")
        if crossing["warning_device_class"] not in GATE_DEVICE_CLASSES:
            raise ApiError(ERR_PREEMPTION_REQUIRES_GATES, 409,
                           "Commissioning requires GATES or FOUR_QUADRANT_GATES")
        rec["status"] = "COMMISSIONED"
    elif to_status == "DECOMMISSIONED":
        if rec["status"] not in ("DRAFT", "TIMING_VERIFIED", "COMMISSIONED"):
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot decommission from {rec['status']}")
        rec["status"] = "DECOMMISSIONED"
    else:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Cannot move to {to_status} from {rec['status']}")

    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return ok(serialize_interconnection(rec))
