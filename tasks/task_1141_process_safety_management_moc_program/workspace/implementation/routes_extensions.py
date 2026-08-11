"""ExtensionRequest endpoints."""
from datetime import timedelta

from flask import Blueprint, g

from db import store
from errors import (
    ApiError, ERR_STALE_MOC_VERSION, ERR_MOC_INVALID_STATE, ERR_MOC_NOT_TEMPORARY,
    ERR_NOT_RESOURCE_OWNER, ERR_MAX_EXTENSIONS_REACHED,
    ERR_TEMP_EXTENSION_EXCEEDS_MAX_DAYS, ERR_TEMP_TOTAL_CAP_EXCEEDED,
    ERR_EXTENSION_NOT_PENDING, ERR_INVALID_REQUEST,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params, f_int,
)
from services import (
    new_entity, touch, get_moc, get_extension, ser_extension, sorted_rows,
)

bp = Blueprint("extensions", __name__)


@bp.post("/psm/moc-requests/<mid>/extension-requests")
@require_roles("Requester")
def create_extension(mid):
    m = get_moc(mid)
    b = body_json()
    # OCC (priority 4): before any business check.
    v = b.get("expected_moc_version")
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: expected_moc_version", 400)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_moc_version must be an integer", 400)
    if v != m["version"]:
        raise ApiError(ERR_STALE_MOC_VERSION, "expected_moc_version is stale", 412)
    if m["status"] != "IN_SERVICE":
        raise ApiError(ERR_MOC_INVALID_STATE, "Only an IN_SERVICE MOC accepts extensions", 409)
    if m["requester_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the requester may request an extension", 403)
    if m["change_class"] != "TEMPORARY":
        raise ApiError(ERR_MOC_NOT_TEMPORARY, "Extensions are a TEMPORARY-only construct", 422)
    requested_days = f_int(b, "requested_days")
    if requested_days < 1:
        raise ApiError(ERR_INVALID_REQUEST, "requested_days must be at least 1", 400)
    unit = store.units[m["unit_id"]]
    # Pinned cap order: count, then per-extension days, then the lifetime cap.
    if m["extension_count"] >= unit["max_extensions"]:
        raise ApiError(ERR_MAX_EXTENSIONS_REACHED, "Maximum approved extensions reached", 422)
    if requested_days > unit["extension_max_days"]:
        raise ApiError(ERR_TEMP_EXTENSION_EXCEEDS_MAX_DAYS,
                       f"requested_days exceeds unit extension_max_days ({unit['extension_max_days']})", 422)
    candidate_end = m["temporary_end_date"] + timedelta(days=requested_days)
    hard_cap = m["temporary_start_date"] + timedelta(days=unit["total_temp_cap_days"])
    if candidate_end > hard_cap:
        raise ApiError(ERR_TEMP_TOTAL_CAP_EXCEEDED,
                       "Extension would breach the total temporary cap", 422)
    # Supersede any PENDING sibling.
    for e in store.extensions.values():
        if e["moc_id"] == m["id"] and e["status"] == "PENDING":
            e["status"] = "VOID"
            touch(e)
    e = new_entity()
    e.update({
        "moc_id": m["id"],
        "requested_days": requested_days,
        "status": "PENDING",
        "decided_by": None,
    })
    store.extensions[e["id"]] = e
    touch(m)  # supersede decision advances the parent MOC version
    return ok(ser_extension(e), 201)


@bp.get("/psm/moc-requests/<mid>/extension-requests")
@require_roles(*ALL_ROLES)
def list_moc_extensions(mid):
    m = get_moc(mid)
    limit, offset = pagination_params()
    rows = [ser_extension(e) for e in sorted_rows(store.extensions.values())
            if e["moc_id"] == m["id"]]
    return ok_list(rows, limit, offset)


@bp.post("/psm/extension-requests/<eid>/approve")
@require_roles("PsmManager")
def approve_extension(eid):
    e = get_extension(eid)
    if e["status"] != "PENDING":
        raise ApiError(ERR_EXTENSION_NOT_PENDING, "Only a PENDING extension can be approved", 409)
    m = store.mocs[e["moc_id"]]
    e["decided_by"] = g.user_id
    e["status"] = "APPROVED"
    touch(e)
    m["extension_count"] += 1
    m["total_approved_extension_days"] += e["requested_days"]
    m["temporary_end_date"] = m["temporary_end_date"] + timedelta(days=e["requested_days"])
    touch(m)
    return ok(ser_extension(e), 200)


@bp.post("/psm/extension-requests/<eid>/deny")
@require_roles("PsmManager")
def deny_extension(eid):
    e = get_extension(eid)
    if e["status"] != "PENDING":
        raise ApiError(ERR_EXTENSION_NOT_PENDING, "Only a PENDING extension can be denied", 409)
    # Compensating invariant: denial leaves the MOC's dates and counts unchanged.
    e["decided_by"] = g.user_id
    e["status"] = "DENIED"
    touch(e)
    return ok(ser_extension(e), 200)
