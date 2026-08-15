"""Intervention catalog endpoints (incl. flat aliases)."""

from flask import Blueprint, request

from db import DB
from errors import err, ERR_CATALOG_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import (
    require_role, ALL_ROLES, get_json_body, check_unknown_fields, require_fields,
    req_string, req_int, req_enum, opt_bool, base_fields, paginate, sort_created,
)
from response import success_object, success_list
from services import (
    SUBJECTS, TIER_TARGETS, PROBE_FREQUENCIES,
    serialize_catalog_entry, serialize_plan, resolve_district, resolve_catalog_entry,
)

bp = Blueprint("catalog", __name__)


@bp.post("/districts/<districtId>/intervention-catalog")
def create_catalog_entry(districtId):
    require_role("DistrictCoordinator")
    body = get_json_body()
    check_unknown_fields(body, {
        "title", "subject", "tier_target", "grade_min", "grade_max",
        "session_minutes", "sessions_per_week", "probe_frequency", "is_active",
    })
    require_fields(body, [
        "title", "subject", "tier_target", "grade_min", "grade_max",
        "session_minutes", "sessions_per_week", "probe_frequency",
    ])
    title = req_string(body, "title")
    subject = req_enum(body, "subject", SUBJECTS)
    tier_target = req_enum(body, "tier_target", TIER_TARGETS)
    grade_min = req_int(body, "grade_min")
    grade_max = req_int(body, "grade_max")
    session_minutes = req_int(body, "session_minutes")
    sessions_per_week = req_int(body, "sessions_per_week")
    probe_frequency = req_enum(body, "probe_frequency", PROBE_FREQUENCIES)
    is_active = opt_bool(body, "is_active", default=True)
    resolve_district(districtId)
    c = base_fields()
    c.update({
        "district_id": districtId,
        "title": title,
        "subject": subject,
        "tier_target": tier_target,
        "grade_min": grade_min,
        "grade_max": grade_max,
        "session_minutes": session_minutes,
        "sessions_per_week": sessions_per_week,
        "probe_frequency": probe_frequency,
        "is_active": is_active,
    })
    DB.catalog_entries[c["id"]] = c
    return success_object(serialize_catalog_entry(c), status=201)


def _list_catalog(districtId):
    q = request.args
    items = [c for c in DB.catalog_entries.values() if c["district_id"] == districtId]
    subj = q.get("subject")
    if subj is not None:
        items = [c for c in items if c["subject"] == subj]
    tt = q.get("tier_target")
    if tt is not None:
        items = [c for c in items if c["tier_target"] == tt]
    act = q.get("is_active")
    if act is not None:
        if act.lower() == "true":
            items = [c for c in items if c["is_active"] is True]
        elif act.lower() == "false":
            items = [c for c in items if c["is_active"] is False]
        else:
            raise err(ERR_INVALID_REQUEST, 400, "is_active filter must be true or false")
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_catalog_entry(c) for c in page], limit, offset, total)


@bp.get("/districts/<districtId>/intervention-catalog")
def list_catalog(districtId):
    require_role(*ALL_ROLES)
    resolve_district(districtId)
    return _list_catalog(districtId)


@bp.get("/districts/<districtId>/intervention-catalog/<entryId>")
def get_catalog_entry(districtId, entryId):
    require_role(*ALL_ROLES)
    c = resolve_catalog_entry(districtId, entryId)
    return success_object(serialize_catalog_entry(c))


@bp.get("/intervention-catalog/<entryId>")
def get_catalog_entry_flat(entryId):
    require_role(*ALL_ROLES)
    c = DB.catalog_entries.get(entryId)
    if c is None:
        raise err(ERR_CATALOG_NOT_FOUND, 404, "entryId does not exist")
    return success_object(serialize_catalog_entry(c))


@bp.get("/intervention-catalog/<id>/plans")
def list_plans_for_catalog_entry(id):
    require_role(*ALL_ROLES)
    c = DB.catalog_entries.get(id)
    if c is None:
        raise err(ERR_CATALOG_NOT_FOUND, 404, "catalog entry id does not exist")
    items = sort_created(
        p for p in DB.plans.values() if p["catalog_entry_id"] == id
    )
    page, limit, offset, total = paginate(items)
    return success_list([serialize_plan(p) for p in page], limit, offset, total)
