"""Piece endpoints: create / start (with the four-gate ladder) / erect."""

from flask import Blueprint

import domain
from envelope import ok_object
from errors import (
    ApiError,
    ERR_CROSS_JOB_REFERENCE,
    ERR_DRAWING_NOT_APPROVED,
    ERR_INVALID_STATE,
    ERR_MATERIAL_NOT_RECEIVED,
    ERR_NOT_FOUND,
    ERR_PIECE_MARK_NOT_UNIQUE,
    ERR_PIECE_STALE_REVISION,
    ERR_SEQUENCE_NOT_RELEASED,
)
from store import new_record, store, touch, public
from validate import authenticate, get_body, req_pos_int, req_str, require_role
from . import list_response

bp = Blueprint("pieces", __name__)

FOREMAN = {"FOREMAN"}
READERS = {"FABRICATOR_ADMIN", "DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"}


def view(p):
    return public(p)


def get_piece_or_404(pid):
    p = store.pieces.get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Piece not found.")
    return p


@bp.post("/pieces")
def create_piece():
    uid, role = authenticate()
    require_role(role, FOREMAN)
    body = get_body()
    # Rung 3: body FK existence (in declared field order)
    job_id = body.get("job_id")
    if job_id is not None and job_id not in store.jobs:
        raise ApiError(ERR_NOT_FOUND, 404, "Job not found.")
    drawing_id = body.get("drawing_id")
    if drawing_id is not None and drawing_id not in store.drawings:
        raise ApiError(ERR_NOT_FOUND, 404, "Shop drawing not found.")
    sequence_id = body.get("sequence_id")
    if sequence_id is not None and sequence_id not in store.sequences:
        raise ApiError(ERR_NOT_FOUND, 404, "Erection sequence not found.")
    # Rung 4: shape
    job_id = req_str(body, "job_id")
    piece_mark = req_str(body, "piece_mark")
    weight_lbs = req_pos_int(body, "weight_lbs")
    drawing_id = req_str(body, "drawing_id")
    sequence_id = req_str(body, "sequence_id")
    drawing = store.drawings[drawing_id]
    sequence = store.sequences[sequence_id]
    # Rung 8: both pins must belong to the piece's job
    if drawing["job_id"] != job_id or sequence["job_id"] != job_id:
        raise ApiError(
            ERR_CROSS_JOB_REFERENCE,
            409,
            "drawing_id and sequence_id must belong to the piece's job.",
        )
    # Rung 9: piece_mark unique per job
    if any(
        p for p in store.pieces.values() if p["job_id"] == job_id and p["piece_mark"] == piece_mark
    ):
        raise ApiError(ERR_PIECE_MARK_NOT_UNIQUE, 409, "piece_mark already exists within the job.")
    p = new_record()
    p.update(
        {
            "job_id": job_id,
            "piece_mark": piece_mark,
            "weight_lbs": weight_lbs,
            "drawing_id": drawing_id,
            "sequence_id": sequence_id,
            "load_id": None,
            "stale_revision": False,
            "status": "DETAILED",
        }
    )
    store.pieces[p["id"]] = p
    # Side effect: job total_weight_lbs recomputed (aggregate derived live; the
    # job is touched per PRD 2.4)
    touch(store.jobs[job_id])
    return ok_object(view(p), 201)


@bp.get("/pieces")
def list_pieces():
    uid, role = authenticate()
    require_role(role, READERS)
    return list_response(
        store.pieces.values(),
        view,
        [
            ("job_id", "job_id"),
            ("drawing_id", "drawing_id"),
            ("sequence_id", "sequence_id"),
            ("load_id", "load_id"),
            ("status", "status"),
        ],
    )


@bp.get("/pieces/<pid>")
def get_piece(pid):
    uid, role = authenticate()
    require_role(role, READERS)
    return ok_object(view(get_piece_or_404(pid)))


@bp.post("/pieces/<pid>/start")
def start_piece(pid):
    uid, role = authenticate()
    require_role(role, FOREMAN)
    p = get_piece_or_404(pid)
    # Rung 6: DETAILED -> IN_SHOP and REWORK -> IN_SHOP share one gate
    if p["status"] not in ("DETAILED", "REWORK"):
        raise ApiError(ERR_INVALID_STATE, 409, "Piece must be DETAILED or REWORK to start.")
    # Rung 8, in the fixed order: stale -> drawing -> sequence -> material
    if p["stale_revision"]:
        raise ApiError(
            ERR_PIECE_STALE_REVISION,
            409,
            "Piece is pinned to a SUPERSEDED drawing revision.",
        )
    drawing = store.drawings.get(p["drawing_id"])
    if drawing is None or drawing["status"] != "APPROVED":
        raise ApiError(ERR_DRAWING_NOT_APPROVED, 409, "Pinned drawing must be APPROVED.")
    sequence = store.sequences.get(p["sequence_id"])
    if sequence is None or sequence["status"] != "RELEASED":
        raise ApiError(ERR_SEQUENCE_NOT_RELEASED, 409, "Piece sequence must be RELEASED.")
    if not any(
        m for m in store.mill_orders.values() if m["job_id"] == p["job_id"] and m["status"] == "RECEIVED"
    ):
        raise ApiError(
            ERR_MATERIAL_NOT_RECEIVED, 409, "At least one mill order of the job must be RECEIVED."
        )
    p["status"] = "IN_SHOP"
    touch(p)
    return ok_object(view(p))


@bp.post("/pieces/<pid>/erect")
def erect_piece(pid):
    uid, role = authenticate()
    require_role(role, FOREMAN)
    p = get_piece_or_404(pid)
    if p["status"] != "SHIPPED":
        raise ApiError(ERR_INVALID_STATE, 409, "Piece must be SHIPPED to erect.")
    p["status"] = "ERECTED"
    touch(p)
    domain.erect_cascade(p)
    return ok_object(view(p))
