"""Inspection endpoints: schedule / submit / void, with the dependent
piece/weld transitions and the lock rules on void."""

from flask import Blueprint

from envelope import ok_object
from errors import (
    ApiError,
    ERR_CROSS_JOB_REFERENCE,
    ERR_INSPECTION_LOCKED,
    ERR_INSPECTION_TARGET_INVALID,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_WELDS_INCOMPLETE,
)
from store import new_record, store, touch, public
from validate import authenticate, get_body, req_enum, req_str, require_role
from . import list_response

bp = Blueprint("inspections", __name__)

QC = {"QC_INSPECTOR"}
READERS = {"FABRICATOR_ADMIN", "DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"}
KINDS = ("FINAL_PIECE", "WELD_VISUAL", "WELD_NDT", "AISC_AUDIT")
WELD_KINDS = ("WELD_VISUAL", "WELD_NDT")


def view(i):
    return public(i)


def get_inspection_or_404(iid):
    i = store.inspections.get(iid)
    if i is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Inspection not found.")
    return i


def target_weld(i):
    return store.welds.get(i["weld_id"]) if i["weld_id"] else None


def target_piece(i):
    return store.pieces.get(i["piece_id"]) if i["piece_id"] else None


@bp.post("/inspections")
def create_inspection():
    uid, role = authenticate()
    require_role(role, QC)
    body = get_body()
    # Rung 3: body FK existence for every supplied reference
    job_id = body.get("job_id")
    if job_id is not None and job_id not in store.jobs:
        raise ApiError(ERR_NOT_FOUND, 404, "Job not found.")
    piece_id = body.get("piece_id")
    if piece_id is not None and piece_id not in store.pieces:
        raise ApiError(ERR_NOT_FOUND, 404, "Piece not found.")
    weld_id = body.get("weld_id")
    if weld_id is not None and weld_id not in store.welds:
        raise ApiError(ERR_NOT_FOUND, 404, "Weld not found.")
    # Rung 4: shape
    job_id = req_str(body, "job_id")
    kind = req_enum(body, "kind", KINDS)
    piece = store.pieces.get(piece_id) if piece_id is not None else None
    weld = store.welds.get(weld_id) if weld_id is not None else None
    # Rung 6: scheduling a FINAL_PIECE inspection advances an IN_SHOP piece
    if kind == "FINAL_PIECE" and piece is not None and piece["status"] != "IN_SHOP":
        raise ApiError(
            ERR_INVALID_STATE, 409, "FINAL_PIECE inspection requires the piece to be IN_SHOP."
        )
    # Rung 8a: cross-job consistency of supplied references
    if piece is not None and piece["job_id"] != job_id:
        raise ApiError(ERR_CROSS_JOB_REFERENCE, 409, "piece_id belongs to a different job.")
    if weld is not None:
        weld_piece = store.pieces.get(weld["piece_id"])
        if weld_piece is None or weld_piece["job_id"] != job_id:
            raise ApiError(ERR_CROSS_JOB_REFERENCE, 409, "weld_id belongs to a different job.")
    # Rung 8b: target shape must match the kind
    if kind == "FINAL_PIECE":
        shape_ok = piece_id is not None and weld_id is None
    elif kind in WELD_KINDS:
        shape_ok = weld_id is not None and piece_id is None
    else:  # AISC_AUDIT targets the job alone
        shape_ok = piece_id is None and weld_id is None
    if not shape_ok:
        raise ApiError(
            ERR_INSPECTION_TARGET_INVALID, 409, "piece_id/weld_id presence does not match kind."
        )
    # Rung 9: every weld of the piece must stand NDT_PASSED before final inspection
    if kind == "FINAL_PIECE":
        piece_welds = [w for w in store.welds.values() if w["piece_id"] == piece_id]
        if any(w["status"] != "NDT_PASSED" for w in piece_welds):
            raise ApiError(
                ERR_WELDS_INCOMPLETE, 409, "Every weld of the piece must be NDT_PASSED."
            )
    i = new_record()
    i.update(
        {
            "job_id": job_id,
            "kind": kind,
            "piece_id": piece_id,
            "weld_id": weld_id,
            "status": "SCHEDULED",
            "inspector_user_id": None,
        }
    )
    store.inspections[i["id"]] = i
    if kind == "FINAL_PIECE":
        piece["status"] = "AWAITING_INSPECTION"
        touch(piece)
    return ok_object(view(i), 201)


@bp.get("/inspections")
def list_inspections():
    uid, role = authenticate()
    require_role(role, READERS)
    return list_response(
        store.inspections.values(),
        view,
        [
            ("job_id", "job_id"),
            ("piece_id", "piece_id"),
            ("weld_id", "weld_id"),
            ("kind", "kind"),
            ("status", "status"),
        ],
    )


@bp.get("/inspections/<iid>")
def get_inspection(iid):
    uid, role = authenticate()
    require_role(role, READERS)
    return ok_object(view(get_inspection_or_404(iid)))


@bp.post("/inspections/<iid>/submit")
def submit_inspection(iid):
    uid, role = authenticate()
    require_role(role, QC)
    i = get_inspection_or_404(iid)
    body = get_body()
    outcome = req_enum(body, "outcome", ("PASSED", "FAILED"))
    if i["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Inspection must be SCHEDULED to submit.")
    # Rung 7: no one inspects their own weld
    if i["kind"] in WELD_KINDS:
        weld = target_weld(i)
        if weld is not None and uid == weld["welder_id"]:
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES, 409, "The inspector may not inspect their own weld."
            )
    i["inspector_user_id"] = uid
    i["status"] = outcome
    touch(i)
    # Dependent transitions per kind (applied when the dependent record stands
    # in the expected from-state)
    if i["kind"] == "FINAL_PIECE":
        piece = target_piece(i)
        if piece is not None and piece["status"] == "AWAITING_INSPECTION":
            # PASSED: AWAITING_INSPECTION -> INSPECTED -> READY_TO_SHIP within
            # the same request; FAILED: -> REWORK
            piece["status"] = "READY_TO_SHIP" if outcome == "PASSED" else "REWORK"
            touch(piece)
    elif i["kind"] == "WELD_VISUAL":
        weld = target_weld(i)
        if weld is not None and weld["status"] == "WELDED":
            weld["status"] = "VISUAL_PASSED" if outcome == "PASSED" else "VISUAL_REJECTED"
            touch(weld)
    elif i["kind"] == "WELD_NDT":
        weld = target_weld(i)
        if weld is not None and weld["status"] == "VISUAL_PASSED":
            weld["status"] = "NDT_PASSED" if outcome == "PASSED" else "NDT_REJECTED"
            touch(weld)
    # AISC_AUDIT moves no dependent record
    return ok_object(view(i))


@bp.post("/inspections/<iid>/void")
def void_inspection(iid):
    uid, role = authenticate()
    require_role(role, QC)
    i = get_inspection_or_404(iid)
    if i["status"] not in ("PASSED", "FAILED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PASSED or FAILED inspection can be voided.")
    was_passed = i["status"] == "PASSED"
    piece = target_piece(i)
    weld = target_weld(i)
    if was_passed:
        # Rung 8: locked once downstream progress consumed the result
        if i["kind"] == "FINAL_PIECE":
            if piece is None or piece["status"] != "READY_TO_SHIP" or piece["load_id"] is not None:
                raise ApiError(
                    ERR_INSPECTION_LOCKED,
                    409,
                    "Piece has shipped or sits on a load; inspection is locked.",
                )
        elif i["kind"] == "WELD_VISUAL":
            if weld is None or weld["status"] != "VISUAL_PASSED":
                raise ApiError(
                    ERR_INSPECTION_LOCKED,
                    409,
                    "A later weld stage has consumed the visual result; inspection is locked.",
                )
        elif i["kind"] == "WELD_NDT":
            if weld is None or weld["status"] != "NDT_PASSED":
                raise ApiError(ERR_INSPECTION_LOCKED, 409, "Weld is no longer NDT_PASSED.")
        # AISC_AUDIT: always voidable, no dependent state
    i["status"] = "VOIDED"
    touch(i)
    # Reversion applies only when voiding a PASSED inspection; voiding a FAILED
    # inspection reverts nothing (rework/rejection states stand).
    if was_passed:
        if i["kind"] == "FINAL_PIECE" and piece is not None and piece["status"] == "READY_TO_SHIP":
            piece["status"] = "AWAITING_INSPECTION"
            touch(piece)
        elif i["kind"] == "WELD_VISUAL" and weld is not None and weld["status"] == "VISUAL_PASSED":
            weld["status"] = "WELDED"
            touch(weld)
        elif i["kind"] == "WELD_NDT" and weld is not None and weld["status"] == "NDT_PASSED":
            weld["status"] = "VISUAL_PASSED"
            touch(weld)
    return ok_object(view(i))
