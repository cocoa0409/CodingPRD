"""Weld endpoints: log (identity + qualification + continuity + half-open
window overlap) and repair loop."""

from flask import Blueprint

import domain
from envelope import ok_object
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_WELDER_DOUBLE_BOOKED,
    ERR_WELDER_NOT_QUALIFIED,
    ERR_WELD_REPAIR_LIMIT,
)
from store import new_record, store, touch, public
from validate import (
    authenticate,
    get_body,
    req_date,
    req_datetime,
    req_enum,
    req_str,
    require_role,
)
from . import list_response

bp = Blueprint("welds", __name__)

WELDER = {"WELDER"}
READERS = {"FABRICATOR_ADMIN", "DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"}


def view(w):
    return public(w)


def get_weld_or_404(wid):
    w = store.welds.get(wid)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Weld not found.")
    return w


@bp.post("/welds")
def create_weld():
    uid, role = authenticate()
    require_role(role, WELDER)
    body = get_body()
    # Rung 2: WELDER ownership — the payload welder_id must be the caller
    welder_id_raw = body.get("welder_id")
    if welder_id_raw is not None and welder_id_raw != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "A welder may only log their own welds.")
    # Rung 3: body FK existence
    piece_id = body.get("piece_id")
    if piece_id is not None and piece_id not in store.pieces:
        raise ApiError(ERR_NOT_FOUND, 404, "Piece not found.")
    if welder_id_raw is not None and welder_id_raw not in store.welders:
        raise ApiError(ERR_NOT_FOUND, 404, "Welder not found.")
    # Rung 4: shape
    piece_id = req_str(body, "piece_id")
    welder_id = req_str(body, "welder_id")
    process = req_enum(body, "process", ("SMAW", "FCAW", "GMAW"))
    weld_date = req_date(body, "weld_date")
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    if window_end <= window_start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "window_end must be strictly after window_start.")
    current_date = store.clock.date()
    if weld_date > current_date:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "weld_date must not be later than the current date."
        )
    piece = store.pieces[piece_id]
    welder = store.welders[welder_id]
    # Rung 6: shop welding happens while the piece is IN_SHOP
    if piece["status"] != "IN_SHOP":
        raise ApiError(ERR_INVALID_STATE, 409, "Welds may only be logged on an IN_SHOP piece.")
    # Rung 7: qualification + continuity against the logical clock
    if not domain.welder_qualified(welder, process, current_date):
        raise ApiError(
            ERR_WELDER_NOT_QUALIFIED,
            409,
            "Welder is suspended, process-mismatched, expired, or continuity-lapsed.",
        )
    # Rung 9: half-open window overlap across every prior weld of the welder
    if domain.welder_window_conflict(welder_id, window_start, window_end):
        raise ApiError(ERR_WELDER_DOUBLE_BOOKED, 409, "Weld window overlaps an existing weld.")
    w = new_record()
    w.update(
        {
            "piece_id": piece_id,
            "welder_id": welder_id,
            "process": process,
            "weld_date": weld_date.isoformat(),
            "window_start": body["window_start"],
            "window_end": body["window_end"],
            "repair_count": 0,
            "status": "WELDED",
            "_window_start_dt": window_start,
            "_window_end_dt": window_end,
        }
    )
    store.welds[w["id"]] = w
    return ok_object(view(w), 201)


@bp.get("/welds")
def list_welds():
    uid, role = authenticate()
    require_role(role, READERS)
    return list_response(
        store.welds.values(),
        view,
        [("piece_id", "piece_id"), ("welder_id", "welder_id"), ("status", "status")],
    )


@bp.get("/welds/<wid>")
def get_weld(wid):
    uid, role = authenticate()
    require_role(role, READERS)
    return ok_object(view(get_weld_or_404(wid)))


@bp.post("/welds/<wid>/repair")
def repair_weld(wid):
    uid, role = authenticate()
    require_role(role, WELDER)
    w = store.welds.get(wid)
    # Rung 2: ownership (checked whenever the weld resolves; else rung 3 404s)
    if w is not None and w["welder_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "A welder may only repair their own welds.")
    if w is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Weld not found.")
    # Rung 6
    if w["status"] not in ("VISUAL_REJECTED", "NDT_REJECTED"):
        raise ApiError(
            ERR_INVALID_STATE, 409, "Only a VISUAL_REJECTED or NDT_REJECTED weld can be repaired."
        )
    # Rung 9: repairs at counts zero and one proceed; two is the limit
    if w["repair_count"] >= 2:
        raise ApiError(ERR_WELD_REPAIR_LIMIT, 409, "Weld repair limit (2) reached.")
    w["status"] = "WELDED"
    w["repair_count"] += 1
    touch(w)
    return ok_object(view(w))
