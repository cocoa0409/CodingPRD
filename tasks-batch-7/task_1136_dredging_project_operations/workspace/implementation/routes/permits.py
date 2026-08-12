"""Permit endpoints (PRD 3.2)."""
import uuid

from flask import Blueprint

from db import store
from errors import ApiError, ERR_NOT_FOUND, ERR_PERMIT_WINDOW_OVERLAP
from middleware import require_roles, ALL_ROLES
from response import ok
from routes.common import list_response
from services import serialize_permit, refresh_posture
from util import (
    as_int,
    as_str,
    check,
    get_body,
    new_entity,
    parse_dt,
    req_present,
)

bp = Blueprint("permits", __name__)


@bp.post("/permits")
@require_roles("OwnerEngineer")
def create_permit():
    body = get_body()
    # Existence (class 3): body FK project_id.
    project_id = body.get("project_id")
    if project_id is not None and project_id not in store.projects:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    # Request shape (class 5).
    project_id = as_str(req_present(body, "project_id"), "project_id")
    permit_number = as_str(req_present(body, "permit_number"), "permit_number")
    window_start = parse_dt(req_present(body, "window_start_utc"), "window_start_utc")
    window_end = parse_dt(req_present(body, "window_end_utc"), "window_end_utc")
    check(window_end > window_start, "window_end_utc must be > window_start_utc")
    limit = as_int(req_present(body, "turbidity_limit_ntu"), "turbidity_limit_ntu")
    check(limit > 0, "turbidity_limit_ntu must be > 0")
    ceiling = as_int(req_present(body, "turbidity_ceiling_ntu"), "turbidity_ceiling_ntu")
    check(ceiling > limit, "turbidity_ceiling_ntu must be > turbidity_limit_ntu")
    averaging = as_int(
        req_present(body, "turbidity_averaging_hours"), "turbidity_averaging_hours"
    )
    check(averaging > 0, "turbidity_averaging_hours must be > 0")
    standdown = as_int(
        req_present(body, "species_standdown_hours"), "species_standdown_hours"
    )
    check(standdown >= 0, "species_standdown_hours must be >= 0")
    # Temporal (class 9): CLOSED-interval overlap with another ISSUED permit of
    # the same project; touching endpoints conflict.
    for p in store.permits.values():
        if p["project_id"] != project_id or p["status"] != "ISSUED":
            continue
        if window_start <= p["window_end_utc"] and p["window_start_utc"] <= window_end:
            raise ApiError(
                ERR_PERMIT_WINDOW_OVERLAP,
                "Permit window overlaps another ISSUED permit of this project",
                409,
            )
    rec = new_entity(
        {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "permit_number": permit_number,
            "window_start_utc": window_start,
            "window_end_utc": window_end,
            "turbidity_limit_ntu": limit,
            "turbidity_ceiling_ntu": ceiling,
            "turbidity_averaging_hours": averaging,
            "species_standdown_hours": standdown,
            "status": "ISSUED",
        }
    )
    store.permits[rec["id"]] = rec
    refresh_posture(project_id)
    return ok(serialize_permit(rec), 201)


@bp.get("/permits/<pid>")
@require_roles(*ALL_ROLES)
def get_permit(pid):
    permit = store.permits.get(pid)
    if permit is None:
        raise ApiError(ERR_NOT_FOUND, "Permit not found", 404)
    return ok(serialize_permit(permit))


@bp.get("/permits")
@require_roles(*ALL_ROLES)
def list_permits():
    return list_response(store.permits, serialize_permit, ["project_id", "status"])
