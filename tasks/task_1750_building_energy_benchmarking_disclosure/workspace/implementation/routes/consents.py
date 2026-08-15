"""Consent grant endpoints: request, grant, deny, revoke, list, get."""
from datetime import date

from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services import core
from validation import parse_body, require_path_entity, parse_date

bp = Blueprint("consents", __name__)


def _require_tenant_ownership(grant, uid):
    if grant["tenant_unit_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "TenantRep does not represent this grant's unit")


@bp.post("/v1/tenant-units/<unit_id>/consent-grants")
def request_consent(unit_id):
    uid, _ = get_context()
    require_roles(["BuildingOwner"])
    unit = require_path_entity(store.tenant_units, unit_id)
    building = store.buildings.get(unit["building_id"])
    if building is None or building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own this unit's building")
    for g in store.consent_grants.values():
        if g["tenant_unit_id"] == unit["id"] and g["status"] == "REQUESTED":
            raise ApiError("ERR_CONSENT_REQUEST_OPEN", 409,
                           "A REQUESTED consent grant already exists for this unit")
    grant = db.new_common({
        "id": db.new_id(),
        "tenant_unit_id": unit["id"],
        "scope": "WHOLE_BUILDING_AGGREGATION",
        "status": "REQUESTED",
        "valid_from": None,
        "valid_to": None,
        "decided_at": None,
    })
    store.consent_grants[grant["id"]] = grant
    return created(grant)


@bp.post("/v1/consent-grants/<grant_id>/grant")
def grant_consent(grant_id):
    uid, _ = get_context()
    require_roles(["TenantRep"])
    grant = require_path_entity(store.consent_grants, grant_id)
    _require_tenant_ownership(grant, uid)
    body = parse_body({
        "valid_from": ("string", True, None),
        "valid_to": ("string", True, None),
    }, allow_empty=False)
    valid_from = parse_date(body["valid_from"])
    valid_to = parse_date(body["valid_to"])
    if valid_from is None or valid_to is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "valid_from and valid_to must be YYYY-MM-DD dates")
    if valid_from > valid_to:
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "valid_from must not fall after valid_to")
    if grant["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a REQUESTED consent grant can be granted")
    # Closed-interval overlap against other effectively-GRANTED windows on the unit.
    for g in store.consent_grants.values():
        if g["id"] == grant["id"] or g["tenant_unit_id"] != grant["tenant_unit_id"]:
            continue
        if core.grant_effective_status(g) != "GRANTED":
            continue
        ex_from = date.fromisoformat(g["valid_from"])
        ex_to = date.fromisoformat(g["valid_to"])
        if valid_from <= ex_to and ex_from <= valid_to:
            raise ApiError("ERR_CONSENT_WINDOW_OVERLAP", 409,
                           "The new consent window overlaps an existing GRANTED window")
    grant["status"] = "GRANTED"
    grant["valid_from"] = body["valid_from"]
    grant["valid_to"] = body["valid_to"]
    grant["decided_at"] = db.LOGICAL_CLOCK
    db.touch(grant)
    # Recompute completeness on the building's DRAFT|FLAGGED|SUBMITTED reports for
    # cycles whose calendar year the new window covers.
    unit = store.tenant_units.get(grant["tenant_unit_id"])
    building = store.buildings.get(unit["building_id"]) if unit else None
    if building is not None:
        for r in store.reports.values():
            if r["building_id"] != building["id"]:
                continue
            if r["status"] not in ("DRAFT", "FLAGGED", "SUBMITTED"):
                continue
            cycle = store.cycles.get(r["cycle_id"])
            if cycle is None or not core.window_covers_year(grant, cycle["cycle_year"]):
                continue
            r["data_completeness_pct"] = core.compute_completeness(building, cycle)
            db.touch(r)
    return ok(grant)


@bp.post("/v1/consent-grants/<grant_id>/deny")
def deny_consent(grant_id):
    uid, _ = get_context()
    require_roles(["TenantRep"])
    grant = require_path_entity(store.consent_grants, grant_id)
    _require_tenant_ownership(grant, uid)
    if grant["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a REQUESTED consent grant can be denied")
    grant["status"] = "DENIED"
    grant["decided_at"] = db.LOGICAL_CLOCK
    db.touch(grant)
    return ok(grant)


@bp.post("/v1/consent-grants/<grant_id>/revoke")
def revoke_consent(grant_id):
    uid, _ = get_context()
    require_roles(["TenantRep"])
    grant = require_path_entity(store.consent_grants, grant_id)
    _require_tenant_ownership(grant, uid)
    if core.grant_effective_status(grant) != "GRANTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a GRANTED consent grant can be revoked")
    covered_years = set()
    for c in store.cycles.values():
        if core.window_covers_year(grant, c["cycle_year"]):
            covered_years.add(c["cycle_year"])
    grant["status"] = "REVOKED"
    db.touch(grant)
    # Recompute completeness on ALL of the building's reports for affected cycles,
    # regardless of status; suppress scores on VERIFIED|CERTIFIED below 75%.
    unit = store.tenant_units.get(grant["tenant_unit_id"])
    building = store.buildings.get(unit["building_id"]) if unit else None
    if building is not None:
        for r in store.reports.values():
            if r["building_id"] != building["id"]:
                continue
            cycle = store.cycles.get(r["cycle_id"])
            if cycle is None or cycle["cycle_year"] not in covered_years:
                continue
            r["data_completeness_pct"] = core.compute_completeness(building, cycle)
            suppressed = False
            if (r["status"] in ("VERIFIED", "CERTIFIED")
                    and core.D(r["data_completeness_pct"]) < core.SCORE_MIN_COMPLETENESS_PCT):
                core.suppress_scores(r)
                suppressed = True
            db.touch(r)
            if suppressed:
                core.supersede_publications_for(r)
    return ok(grant)


@bp.get("/v1/consent-grants")
def list_consent_grants():
    get_context()
    rows = [core.present_grant(g) for g in store.consent_grants.values()]
    rows = paginate.filter(rows, "tenant_unit_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/v1/consent-grants/<grant_id>")
def get_consent_grant(grant_id):
    get_context()
    grant = require_path_entity(store.consent_grants, grant_id)
    return ok(core.present_grant(grant))
