"""ShipmentStage endpoints (PRD §3.5)."""

from flask import Blueprint, request

from calc import stage_contained, stage_gap_ok
from db import bump, new_record, sorted_records, store
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STAGE_GAP_TOO_SMALL,
    ERR_STAGE_OUTSIDE_WINDOW,
)
from middleware import require_roles
from response import list_response, success
from serializers import serialize, serialize_list
from services import project_stages
from util import get_body, pagination_params, paginate, req_datetime, req_int, req_str
from routes.common import check_customer_ownership, customer_owns, get_or_404

bp = Blueprint("stages", __name__)


def _validate_interval(window, ship_dt, ret_dt, exclude_stage_id, project_id):
    """Containment (closed bounds) + 2-day sibling gap (exactly 2 days allowed)."""
    if not stage_contained(window, ship_dt, ret_dt):
        raise ApiError(
            ERR_STAGE_OUTSIDE_WINDOW,
            "stage interval is not contained in its downtime window",
            409,
        )
    for other in project_stages(project_id):
        if other["id"] == exclude_stage_id or other["status"] == "CANCELLED":
            continue
        if not stage_gap_ok(ship_dt, ret_dt, other["_ship_dt"], other["_return_dt"]):
            raise ApiError(
                ERR_STAGE_GAP_TOO_SMALL,
                "stage is closer than 2 days to a non-CANCELLED sibling stage",
                409,
            )


@bp.post("/api/projects/<pid>/shipment-stages")
@require_roles("LogisticsCoordinator")
def create_stage(user_id, role, pid):
    body = get_body()
    window_id = req_str(body, "window_id")
    stage_sequence = req_int(body, "stage_sequence", minimum=1)
    ship_dt, ship_raw = req_datetime(body, "planned_ship_date")
    ret_dt, ret_raw = req_datetime(body, "planned_return_date")
    # Malformed interval is a body-shape error (ERR_INVALID_REQUEST).
    if ret_dt < ship_dt:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "planned_return_date must not be earlier than planned_ship_date",
            400,
        )
    get_or_404(store.projects, pid, "project")
    window = get_or_404(store.windows, window_id, "downtime window")
    if window["status"] not in ("OPEN", "LOCKED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "referenced window must be OPEN or LOCKED",
            409,
        )
    _validate_interval(window, ship_dt, ret_dt, None, pid)
    rec = new_record(
        {
            "project_id": pid,
            "window_id": window_id,
            "stage_sequence": stage_sequence,
            "planned_ship_date": ship_raw,
            "planned_return_date": ret_raw,
            "status": "PLANNED",
            "_ship_dt": ship_dt,
            "_return_dt": ret_dt,
        }
    )
    store.stages[rec["id"]] = rec
    # First referencing stage locks the window (one-way ratchet).
    if window["status"] == "OPEN":
        window["status"] = "LOCKED"
        bump(window)
    return success(serialize(rec), status=201)


@bp.get("/api/shipment-stages/<sid>")
@require_roles("LogisticsCoordinator", "ProjectManager", "Customer", "PlatformAdmin")
def get_stage(user_id, role, sid):
    rec = get_or_404(store.stages, sid, "shipment stage")
    check_customer_ownership(user_id, role, "stage", rec)
    return success(serialize(rec))


@bp.get("/api/shipment-stages")
@require_roles("LogisticsCoordinator", "ProjectManager", "Customer", "PlatformAdmin")
def list_stages(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.stages)
    for param in ("project_id", "window_id"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s[param] == value]
    if role == "Customer":
        items = [s for s in items if customer_owns(user_id, "stage", s)]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)


@bp.post("/api/shipment-stages/<sid>/ship")
@require_roles("LogisticsCoordinator")
def ship_stage(user_id, role, sid):
    stage = get_or_404(store.stages, sid, "shipment stage")
    if stage["status"] != "PLANNED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"stage in status {stage['status']} cannot be shipped",
            409,
        )
    project = store.projects[stage["project_id"]]
    if project["work_status"] not in ("ACCEPTED", "TRAINING_IN_PROGRESS", "HANDOVER_READY"):
        raise ApiError(
            ERR_INVALID_STATE,
            "project must be post-acceptance to ship a stage",
            409,
        )
    stage["status"] = "SHIPPED"
    bump(stage)
    return success(serialize(stage))


@bp.post("/api/shipment-stages/<sid>/receive")
@require_roles("LogisticsCoordinator")
def receive_stage(user_id, role, sid):
    stage = get_or_404(store.stages, sid, "shipment stage")
    if stage["status"] != "SHIPPED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"stage in status {stage['status']} cannot be received",
            409,
        )
    stage["status"] = "RECEIVED"
    bump(stage)
    return success(serialize(stage))


@bp.post("/api/shipment-stages/<sid>/install")
@require_roles("LogisticsCoordinator")
def install_stage(user_id, role, sid):
    stage = get_or_404(store.stages, sid, "shipment stage")
    if stage["status"] != "RECEIVED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"stage in status {stage['status']} cannot be installed",
            409,
        )
    stage["status"] = "INSTALLED"
    bump(stage)
    return success(serialize(stage))


@bp.post("/api/shipment-stages/<sid>/replan")
@require_roles("LogisticsCoordinator")
def replan_stage(user_id, role, sid):
    body = get_body()
    ship_dt, ship_raw = req_datetime(body, "planned_ship_date")
    ret_dt, ret_raw = req_datetime(body, "planned_return_date")
    if ret_dt < ship_dt:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "planned_return_date must not be earlier than planned_ship_date",
            400,
        )
    stage = get_or_404(store.stages, sid, "shipment stage")
    if stage["status"] not in ("ON_HOLD", "PLANNED"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"stage in status {stage['status']} cannot be replanned",
            409,
        )
    window = store.windows[stage["window_id"]]
    _validate_interval(window, ship_dt, ret_dt, stage["id"], stage["project_id"])
    stage["planned_ship_date"] = ship_raw
    stage["planned_return_date"] = ret_raw
    stage["_ship_dt"] = ship_dt
    stage["_return_dt"] = ret_dt
    if stage["status"] == "ON_HOLD":
        stage["status"] = "PLANNED"
    bump(stage)
    return success(serialize(stage))
