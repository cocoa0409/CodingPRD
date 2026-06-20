"""DischargeBarrier: open + resolve, with open_barrier_count reconciliation."""

from flask import Blueprint, request

import errors
from errors import err
from db import store, iso
from middleware import authenticate, authorize, get_json_body, parse_pagination
from response import success, list_success
from services import common
from services.listing import paginate

bp = Blueprint("discharge_barriers", __name__)

BARRIER_TYPES = {"PLACEMENT_SNF", "TRANSPORT", "PHARMACY", "FAMILY", "EQUIPMENT"}
BARRIER_STATUSES = {"OPEN", "RESOLVED"}


def _get_barrier_or_404(barrier_id):
    b = store.discharge_barriers.get(barrier_id)
    if b is None:
        raise err(errors.ERR_NOT_FOUND, "Discharge barrier not found")
    return b


@bp.route("/discharge-barriers", methods=["POST"])
def create_barrier():
    _, role = authenticate()
    authorize(role, {"CaseManager", "BedControlCoordinator"})
    body = get_json_body()

    encounter_id = body.get("encounter_id")
    if not isinstance(encounter_id, str) or not encounter_id:
        raise err(errors.ERR_INVALID_REQUEST, "encounter_id is required")
    if encounter_id not in store.encounters:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "encounter_id does not resolve")

    barrier_type = body.get("barrier_type")
    if barrier_type not in BARRIER_TYPES:
        raise err(errors.ERR_INVALID_REQUEST,
                  "barrier_type must be one of PLACEMENT_SNF, TRANSPORT, PHARMACY, FAMILY, EQUIPMENT")

    note = body.get("note", "")
    if note is None:
        note = ""
    if not isinstance(note, str):
        raise err(errors.ERR_INVALID_REQUEST, "note must be a string")

    now = store.clock_now()
    barrier = {
        "encounter_id": encounter_id,
        "barrier_type": barrier_type,
        "note": note,
        "status": "OPEN",
        "opened_at": iso(now),
        "resolved_at": None,
    }
    common.stamp_new(barrier)
    store.discharge_barriers[barrier["id"]] = barrier
    # reconcile encounter count
    enc = store.encounters.get(encounter_id)
    if enc is not None:
        common.recompute_encounter(enc)
    return success(common.serialize_barrier(barrier), status=201)


@bp.route("/discharge-barriers/<barrier_id>", methods=["GET"])
def get_barrier(barrier_id):
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "CaseManager", "BedControlCoordinator"})
    b = _get_barrier_or_404(barrier_id)
    return success(common.serialize_barrier(b))


@bp.route("/discharge-barriers", methods=["GET"])
def list_barriers():
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "CaseManager", "BedControlCoordinator"})
    limit, offset = parse_pagination()
    enc_filter = request.args.get("encounter_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in BARRIER_STATUSES:
        raise err(errors.ERR_INVALID_REQUEST, "invalid status filter")
    barriers = list(store.discharge_barriers.values())
    if enc_filter is not None:
        barriers = [b for b in barriers if b["encounter_id"] == enc_filter]
    if status_filter is not None:
        barriers = [b for b in barriers if b["status"] == status_filter]
    page, total = paginate(barriers, limit, offset)
    return list_success([common.serialize_barrier(b) for b in page], limit, offset, total)


@bp.route("/discharge-barriers/<barrier_id>/resolve", methods=["POST"])
def resolve_barrier(barrier_id):
    _, role = authenticate()
    authorize(role, {"CaseManager", "FlowAdmin"})
    b = _get_barrier_or_404(barrier_id)
    if b["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Barrier is not OPEN")
    now = store.clock_now()
    b["status"] = "RESOLVED"
    b["resolved_at"] = iso(now)
    common.touch(b)
    enc = store.encounters.get(b["encounter_id"])
    if enc is not None:
        common.recompute_encounter(enc)
    return success(common.serialize_barrier(b))
