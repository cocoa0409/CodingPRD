"""Area restriction endpoints (PRD §3.2)."""

from flask import Blueprint, request

import errors
from db import db, new_id
from middleware import require_roles
from response import success_list, success_object
from services.domain import serialize_area_restriction
from util import (
    get_json_body,
    now_iso,
    paginate,
    parse_pagination,
    require_field,
    require_str,
)

bp = Blueprint("area_restrictions", __name__)


@bp.post("/api/v1/area-restrictions")
def create_area_restriction():
    require_roles("OperationsManager")
    body = get_json_body()
    name = require_str(body, "name")
    postal_codes = require_field(body, "postal_codes")
    if not isinstance(postal_codes, list):
        raise errors.validation("postal_codes must be an array")
    restricted_kinds = require_field(body, "restricted_kinds")
    if not isinstance(restricted_kinds, list):
        raise errors.validation("restricted_kinds must be an array")
    restricted_species = require_field(body, "restricted_species")
    if not isinstance(restricted_species, list):
        raise errors.validation("restricted_species must be an array")
    ws = require_str(body, "enforcement_window_start")
    we = require_str(body, "enforcement_window_end")
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise errors.validation("active must be a boolean")
    ts = now_iso()
    rid = new_id()
    record = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "name": name,
        "postal_codes": postal_codes,
        "restricted_kinds": restricted_kinds,
        "restricted_species": restricted_species,
        "enforcement_window_start": ws,
        "enforcement_window_end": we,
        "active": active,
    }
    db.area_restrictions[rid] = record
    return success_object(serialize_area_restriction(record), status=201)


def _get_or_404(rid):
    r = db.area_restrictions.get(rid)
    if not r:
        raise errors.not_found(f"AreaRestriction {rid} not found")
    return r


@bp.get("/api/v1/area-restrictions/<rid>")
def get_area_restriction(rid):
    require_roles("CustomerService", "OperationsManager", "RoutePlanner")
    return success_object(serialize_area_restriction(_get_or_404(rid)))


@bp.get("/api/v1/area-restrictions")
def list_area_restrictions():
    require_roles("CustomerService", "OperationsManager", "RoutePlanner")
    limit, offset = parse_pagination()
    items = list(db.area_restrictions.values())
    pc = request.args.get("postal_code")
    if pc is not None:
        items = [r for r in items if pc in r.get("postal_codes", [])]
    a = request.args.get("active")
    if a is not None:
        aval = a.lower() in ("true", "1", "yes")
        items = [r for r in items if r.get("active", True) == aval]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_area_restriction(r) for r in page], total, limit, offset)
