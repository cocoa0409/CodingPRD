"""ClarificationDrawing endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_STALE_VERSION,
    ERR_RFI_INVALID_STATE,
)
from middleware import get_user_context, require_role, get_body
from response import success_object, success_list
from services.helpers import (
    base_entity, touch, paginate, get_rfi, get_drawing,
    req_str, req_int,
)

bp = Blueprint("clarification_drawings", __name__)

ALL_ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")


@bp.post("/ca/clarification-drawings")
def create_clarification_drawing():
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    body = get_body(required=True)
    rfi_id = req_str(body, "rfi_id")
    drawing_ref = req_str(body, "drawing_ref")
    expected_rfi_version = req_int(body, "expected_rfi_version")

    rfi = get_rfi(rfi_id)

    # OCC (stage 5) precedes the target-entity state gate (stage 8).
    if expected_rfi_version != rfi["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_rfi_version does not equal the RFI's current version",
            412,
        )
    if rfi["status"] not in ("CLARIFICATION_PENDING", "ANSWERED"):
        raise ApiError(
            ERR_RFI_INVALID_STATE,
            "drawing creation requires RFI CLARIFICATION_PENDING or ANSWERED",
            409,
        )

    issued_at = db.now_iso()
    prior = [d for d in db.clarification_drawings.values() if d["rfi_id"] == rfi_id]
    revision_number = max((d["revision_number"] for d in prior), default=0) + 1

    # Supersede the previously ISSUED drawing of the same RFI.
    for d in prior:
        if d["status"] == "ISSUED":
            d["status"] = "SUPERSEDED"
            touch(d)

    drawing = base_entity()
    drawing.update({
        "rfi_id": rfi_id,
        "drawing_ref": drawing_ref,
        "revision_number": revision_number,
        "issued_at": issued_at,
        "status": "ISSUED",
    })
    db.clarification_drawings[drawing["id"]] = drawing

    # A CLARIFICATION_PENDING RFI transitions to ANSWERED on first drawing.
    if rfi["status"] == "CLARIFICATION_PENDING":
        from routes.rfis import answer_rfi_with_clock
        answer_rfi_with_clock(rfi, issued_at)
    # The parent RFI's version increments on every drawing.
    touch(rfi)
    return success_object(drawing, 201)


@bp.get("/ca/clarification-drawings")
def list_clarification_drawings():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.clarification_drawings.values())
    rfi_id = request.args.get("rfi_id")
    if rfi_id is not None:
        items = [d for d in items if d["rfi_id"] == rfi_id]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/ca/clarification-drawings/<did>")
def get_one_clarification_drawing(did):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success_object(get_drawing(did))
