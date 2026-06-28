"""KilnBatch routes (PRD §3.4, §3.5; SCAFFOLD §1.5, §1.2, §2.9 OCC).

RBAC:
  POST /kiln-batches                     StudioStaff, StudioManager
  GET  /kiln-batches/{id}                StudioStaff, StudioManager
  GET  /kiln-batches                     StudioStaff, StudioManager
  GET  /kiln-batches/{id}/pieces         StudioStaff, StudioManager
  POST /kiln-batches/{id}/load           StudioStaff, StudioManager
  POST /kiln-batches/{id}/start-firing   StudioStaff, StudioManager
  POST /kiln-batches/{id}/complete-firing StudioStaff, StudioManager
  POST /kiln-batches/{id}/cancel         StudioManager
"""

from datetime import timedelta

from flask import Blueprint, request

from clock import clock
from db import db, new_id, stamp_common, touch
from errors import (ApiError, invalid_state, ERR_FIRING_TEMP_MISMATCH,
                    ERR_KILN_AT_CAPACITY, ERR_STALE_BATCH_VERSION, ERR_VISIT_NOT_OPEN)
from middleware import get_caller, require_roles
from response import success, list_success, parse_pagination, paginate
from services import serializers
from services.lookup import get_batch, get_piece
from services.transitions import complete_firing
from services.validation import (require_body, require_str, require_int,
                                 optional_int, optional_enum)

bp = Blueprint("kiln_batches", __name__)

STAFF_MANAGER = {"StudioStaff", "StudioManager"}
FIRING_TEMPS = {"CONE_06", "CONE_6"}


@bp.route("/kiln-batches", methods=["POST"])
def create_batch():
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    payload = require_body(request.get_json(silent=True))
    kiln_name = require_str(payload, "kiln_name")
    firing_temp = optional_enum(payload, "firing_temp", FIRING_TEMPS, "CONE_06")
    capacity_slots = require_int(payload, "capacity_slots", minimum=1)
    turnaround_hours = optional_int(payload, "turnaround_hours", default=48, minimum=0)

    record = {
        "id": new_id(),
        "kiln_name": kiln_name,
        "firing_temp": firing_temp,
        "capacity_slots": capacity_slots,
        "occupied_slots": 0,
        "turnaround_hours": turnaround_hours,
        "started_at": None,
        "firing_completes_at": None,
        "status": "LOADING",
    }
    stamp_common(record)
    # version begins at 1 (stamp_common); SCAFFOLD: "occupied_slots=0, version=1".
    db.kiln_batches[record["id"]] = record
    return success(serializers.kiln_batch(record), status=201)


@bp.route("/kiln-batches/<batch_id>", methods=["GET"])
def fetch_batch(batch_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    batch = get_batch(batch_id)
    return success(serializers.kiln_batch(batch))


@bp.route("/kiln-batches", methods=["GET"])
def list_batches():
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    limit, offset = parse_pagination(request.args)
    records = list(db.kiln_batches.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    firing_temp = request.args.get("firing_temp")
    if firing_temp is not None:
        records = [r for r in records if r["firing_temp"] == firing_temp]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.kiln_batch(r) for r in window], limit, offset, total)


@bp.route("/kiln-batches/<batch_id>/pieces", methods=["GET"])
def list_batch_pieces(batch_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    batch = get_batch(batch_id)
    limit, offset = parse_pagination(request.args)
    records = [p for p in db.bisque_pieces.values() if p["kiln_batch_id"] == batch_id]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.bisque_piece(r) for r in window], limit, offset, total)


@bp.route("/kiln-batches/<batch_id>/load", methods=["POST"])
def load_piece(batch_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    # Existence: batch then body-referenced piece, left-to-right (PRD §2.8).
    batch = get_batch(batch_id)
    payload = require_body(request.get_json(silent=True))
    bisque_piece_id = require_str(payload, "bisque_piece_id")
    expected_version = require_int(payload, "expected_kiln_batch_version", minimum=0)
    piece = get_piece(bisque_piece_id)

    # State check first: non-PAINTED piece or non-LOADING batch -> ERR_INVALID_STATE
    # (PRD §3.4 ordering).
    if piece["status"] != "PAINTED" or batch["status"] != "LOADING":
        raise invalid_state("Piece must be PAINTED and batch must be LOADING")

    # Firing-temp mismatch (PRD §3.4 ordering: after state).
    if batch["firing_temp"] != piece["firing_temp"]:
        raise ApiError(ERR_FIRING_TEMP_MISMATCH, 409,
                       "Piece firing_temp does not match batch firing_temp")

    # Capacity overflow guard (PRD §3.4: ERR_KILN_AT_CAPACITY).
    if batch["occupied_slots"] >= batch["capacity_slots"]:
        raise ApiError(ERR_KILN_AT_CAPACITY, 409, "Kiln batch is at capacity")

    # OCC stale-version check, before any slot is consumed (PRD §2.9, §3.4).
    if expected_version != batch["version"]:
        raise ApiError(ERR_STALE_BATCH_VERSION, 412,
                       "expected_kiln_batch_version does not match batch version")

    # The piece's owning studio visit must still be OPEN (SCAFFOLD precondition).
    visit = db.studio_visits.get(piece["studio_visit_id"])
    if visit is None or visit["status"] != "OPEN":
        raise ApiError(ERR_VISIT_NOT_OPEN, 409, "Owning visit is not OPEN")

    # Commit.
    piece["kiln_batch_id"] = batch["id"]
    piece["status"] = "LOADED"
    touch(piece)
    batch["occupied_slots"] += 1
    touch(batch)  # increments version by 1
    return success(serializers.bisque_piece(piece))


@bp.route("/kiln-batches/<batch_id>/start-firing", methods=["POST"])
def start_firing(batch_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    batch = get_batch(batch_id)

    if batch["status"] != "LOADING":
        raise invalid_state("Batch is not LOADING")
    # Cannot fire an empty kiln (PRD §3.5).
    if batch["occupied_slots"] < 1:
        raise invalid_state("Batch has no loaded pieces")

    now = clock.now()
    batch["started_at"] = clock.now_iso()
    completes = now + timedelta(hours=batch["turnaround_hours"])
    from clock import format_iso
    batch["firing_completes_at"] = format_iso(completes)

    # Cascade: every LOADED piece on this batch -> FIRING.
    for piece in db.bisque_pieces.values():
        if piece["kiln_batch_id"] == batch_id and piece["status"] == "LOADED":
            piece["status"] = "FIRING"
            touch(piece)

    batch["status"] = "FIRING"
    touch(batch)
    return success(serializers.kiln_batch(batch))


@bp.route("/kiln-batches/<batch_id>/complete-firing", methods=["POST"])
def complete_firing_endpoint(batch_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    batch = get_batch(batch_id)
    if batch["status"] != "FIRING":
        raise invalid_state("Batch is not FIRING")
    complete_firing(batch)
    return success(serializers.kiln_batch(batch))


@bp.route("/kiln-batches/<batch_id>/cancel", methods=["POST"])
def cancel_batch(batch_id):
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    batch = get_batch(batch_id)
    if batch["status"] != "LOADING":
        raise invalid_state("Batch is not LOADING")

    # Cascade: every LOADED piece -> PAINTED with kiln_batch_id=null.
    for piece in db.bisque_pieces.values():
        if piece["kiln_batch_id"] == batch_id and piece["status"] == "LOADED":
            piece["kiln_batch_id"] = None
            piece["status"] = "PAINTED"
            touch(piece)

    batch["occupied_slots"] = 0
    batch["status"] = "CANCELLED"
    touch(batch)
    return success(serializers.kiln_batch(batch))
