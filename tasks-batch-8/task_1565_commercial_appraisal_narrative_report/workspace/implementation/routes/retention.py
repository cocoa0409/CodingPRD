from flask import Blueprint, request

import response
from db import store, touch, serialize
from errors import ApiError, ERR_INVALID_STATE, ERR_RETENTION_NOT_ELAPSED
from middleware import auth, require_role
from response import sort_by_creation
from services import domain

bp = Blueprint("retention", __name__)


@bp.get("/retention-records/<recordId>")
def get_retention_record(recordId):
    auth()
    rec = domain.get_retention_record(recordId)
    return response.success(serialize(rec))


@bp.get("/retention-records")
def list_retention_records():
    auth()
    items = list(store.retention_records.values())
    v = request.args.get("engagement_id")
    if v is not None:
        items = [r for r in items if r.get("engagement_id") == v]
    items = sort_by_creation(items)
    return response.list_response([serialize(r) for r in items])


@bp.post("/retention-records/<recordId>/authorize_destruction")
def authorize_destruction(recordId):
    _, role = auth()
    require_role(role, {"RecordsManager"})
    rec = domain.get_retention_record(recordId)
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Retention record is not ACTIVE")
    clock_date = store.clock.date()
    retain_date = rec["retain_until_date"].date()
    if clock_date < retain_date:
        raise ApiError(
            ERR_RETENTION_NOT_ELAPSED,
            409,
            "The retention period has not fully elapsed",
        )
    rec["status"] = "RELEASED_PENDING_DESTRUCTION"
    touch(rec)
    return response.success(serialize(rec))


@bp.post("/retention-records/<recordId>/confirm_destruction")
def confirm_destruction(recordId):
    _, role = auth()
    require_role(role, {"RecordsManager"})
    rec = domain.get_retention_record(recordId)
    if rec["status"] != "RELEASED_PENDING_DESTRUCTION":
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Retention record is not RELEASED_PENDING_DESTRUCTION",
        )
    rec["status"] = "DESTROYED"
    touch(rec)
    return response.success(serialize(rec))
