"""Architectural sample panels: lay-up, the review loop and approval pinning."""

from decimal import Decimal

import calc
import response
import services as svc
from auth import ALL_ROLES, actor, endpoint
from errors import ApiError
from routes import apply_filters
from store import add_days, clock, clock_str, db, fmt_clock, new_row, touch
from validation import body, v_id, v_num, v_str

from flask import Blueprint

bp = Blueprint("sample_panels", __name__)

D = Decimal


@bp.get("/sample-panels/<pid>")
@endpoint(ALL_ROLES)
def get_panel(pid):
    return response.entity(svc.panel_or_404(pid))


@bp.get("/sample-panels")
@endpoint(ALL_ROLES)
def list_panels():
    rows = apply_filters(
        db.sample_panels.values(),
        {
            "order_id": "order_id",
            "formulation_id": "formulation_id",
            "dye_lot_id": "dye_lot_id",
            "status": "status",
        },
    )
    return response.collection(rows)


# --------------------------------------------------------------------------
# POST /orders/{id}/sample-panels
# --------------------------------------------------------------------------
@bp.post("/orders/<oid>/sample-panels")
@endpoint(["BlendTechnician"])
def lay_up_panel(oid):
    order = svc.order_or_404(oid)
    payload = body()
    panel_code = v_str(payload, "panel_code")
    formulation_id = v_id(payload, "formulation_id")
    dye_lot_id = v_id(payload, "dye_lot_id")
    panel_color_index = v_num(payload, "panel_color_index", 2, minv="0.00", maxv="100.00")
    tolerance = v_num(payload, "tolerance_delta_e", 2, minv="0.00", maxv="20.00")

    formulation = svc.formulation_or_404(formulation_id)
    svc.lot_or_404(dye_lot_id)

    if order["fulfillment_status"] not in ("ASSIGNED", "IN_BLENDING"):
        raise ApiError(
            "ERR_ORDER_STATE_INVALID",
            "A panel may only be laid up on an ASSIGNED or IN_BLENDING order.",
        )
    if formulation["status"] != "QUALIFIED":
        raise ApiError("ERR_FORMULATION_NOT_QUALIFIED", "The body formulation is not QUALIFIED.")
    svc.require_unique(db.sample_panels, "panel_code", panel_code)

    row = new_row(
        order_id=oid,
        formulation_id=formulation_id,
        dye_lot_id=dye_lot_id,
        panel_code=panel_code,
        panel_color_index=panel_color_index,
        tolerance_delta_e=tolerance,
        pinned_formulation_version=None,
        pinned_dye_lot_code=None,
        approved_color_index=None,
        submitted_by_user_id=None,
        approved_by_user_id=None,
        approved_at=None,
        expires_at=None,
        revision_round=0,
        revision_note=None,
        status="DRAFT",
    )
    db.sample_panels[row["id"]] = row
    return response.entity_created(row)


# --------------------------------------------------------------------------
# POST /sample-panels/{id}/submit
# --------------------------------------------------------------------------
@bp.post("/sample-panels/<pid>/submit")
@endpoint(["BlendTechnician"])
def submit_panel(pid):
    panel = svc.panel_or_404(pid)
    if panel["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_PANEL_STATE_INVALID", "Only a DRAFT or REVISION_REQUESTED panel may be submitted."
        )
    formulation = db.formulations.get(panel["formulation_id"])
    if formulation is None or formulation["status"] != "QUALIFIED":
        raise ApiError("ERR_FORMULATION_NOT_QUALIFIED", "The panel's body is not QUALIFIED.")

    panel["status"] = "SUBMITTED"
    panel["submitted_by_user_id"] = actor()
    touch(panel)
    return response.entity(panel)


# --------------------------------------------------------------------------
# POST /sample-panels/{id}/request-revision
# --------------------------------------------------------------------------
@bp.post("/sample-panels/<pid>/request-revision")
@endpoint(["ArchitectReviewer"])
def request_revision(pid):
    panel = svc.panel_or_404(pid)
    payload = body()
    note = v_str(payload, "revision_note")

    if panel["status"] != "SUBMITTED":
        raise ApiError("ERR_PANEL_STATE_INVALID", "Only a SUBMITTED panel may be sent back.")
    if int(panel["revision_round"]) >= calc.PANEL_MAX_REVISION_ROUNDS:
        raise ApiError("ERR_PANEL_REVISION_LIMIT", "The panel has no revision rounds left.")

    panel["status"] = "REVISION_REQUESTED"
    panel["revision_note"] = note
    panel["revision_round"] = int(panel["revision_round"]) + 1
    touch(panel)
    return response.entity(panel)


# --------------------------------------------------------------------------
# POST /sample-panels/{id}/approve
# --------------------------------------------------------------------------
@bp.post("/sample-panels/<pid>/approve")
@endpoint(["ArchitectReviewer"])
def approve_panel(pid):
    panel = svc.panel_or_404(pid)

    if panel.get("submitted_by_user_id") is not None and panel["submitted_by_user_id"] == actor():
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approver may not be the operator who submitted the panel.",
        )

    lot = db.fired_lots.get(panel["dye_lot_id"])
    if lot is not None and lot["status"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED", "The panel's dye lot is QUARANTINED.")
    if panel["status"] != "SUBMITTED":
        raise ApiError("ERR_PANEL_STATE_INVALID", "Only a SUBMITTED panel may be approved.")
    formulation = db.formulations.get(panel["formulation_id"])
    if formulation is None or formulation["status"] != "QUALIFIED":
        raise ApiError("ERR_FORMULATION_NOT_QUALIFIED", "The panel's body is not QUALIFIED.")

    panel["status"] = "APPROVED"
    panel["pinned_formulation_version"] = int(formulation["version"])
    panel["pinned_dye_lot_code"] = lot.get("dye_lot_code") if lot is not None else None
    panel["approved_color_index"] = panel["panel_color_index"]
    panel["approved_by_user_id"] = actor()
    panel["approved_at"] = clock_str()
    panel["expires_at"] = fmt_clock(add_days(clock(), calc.PANEL_APPROVAL_VALID_DAYS))
    touch(panel)
    return response.entity(panel)
