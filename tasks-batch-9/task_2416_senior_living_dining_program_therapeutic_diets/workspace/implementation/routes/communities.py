"""Community registration and community-scoped collection reads."""
from flask import Blueprint

import serialize
from auth import authenticate
from constants import (
    CARE_LEVELS, CYCLE_STATUSES, DINING_STATUSES, POSTURES,
    RECONCILIATION_STATUSES, VENUE_KINDS, VENUE_STATUSES,
)
from db import base_row, db, sort_created
from response import created, ok, ok_list
from routes.common import (
    BS, DSM, EVERY_ROLE, PA, get_community,
)
from shape import body_json, opt_int, paginate, q_enum, req_enum_array, req_str

bp = Blueprint("communities", __name__)


@bp.get("/communities/<community_id>")
def read_community(community_id):
    authenticate(EVERY_ROLE)
    row = get_community(community_id)
    return ok(serialize.community(row))


@bp.get("/communities/<community_id>/venues")
def list_venues(community_id):
    authenticate(EVERY_ROLE)
    get_community(community_id)
    venue_kind = q_enum("venue_kind", VENUE_KINDS)
    posture = q_enum("temp_compliance_posture", POSTURES)
    status = q_enum("status", VENUE_STATUSES)
    rows = [v for v in db.venues.values() if v["community_id"] == community_id]
    if venue_kind is not None:
        rows = [v for v in rows if v["venue_kind"] == venue_kind]
    if posture is not None:
        rows = [v for v in rows if v["temp_compliance_posture"] == posture]
    if status is not None:
        rows = [v for v in rows if v["status"] == status]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.venue, window), pagination)


@bp.get("/communities/<community_id>/residents")
def list_residents(community_id):
    authenticate(EVERY_ROLE)
    get_community(community_id)
    care_level = q_enum("care_level", CARE_LEVELS)
    dining_status = q_enum("dining_status", DINING_STATUSES)
    rows = [r for r in db.residents.values() if r["community_id"] == community_id]
    if care_level is not None:
        rows = [r for r in rows if r["care_level"] == care_level]
    if dining_status is not None:
        rows = [r for r in rows if r["dining_status"] == dining_status]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.resident, window), pagination)


@bp.get("/communities/<community_id>/menu-cycles")
def list_menu_cycles(community_id):
    authenticate(EVERY_ROLE)
    get_community(community_id)
    status = q_enum("status", CYCLE_STATUSES)
    rows = [c for c in db.menu_cycles.values() if c["community_id"] == community_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.menu_cycle, window), pagination)


@bp.get("/communities/<community_id>/reconciliations")
def list_reconciliations(community_id):
    authenticate([PA, DSM, BS])
    get_community(community_id)
    status = q_enum("status", RECONCILIATION_STATUSES)
    rows = [r for r in db.reconciliations.values() if r["community_id"] == community_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.reconciliation, window), pagination)


@bp.post("/communities")
def create_community():
    authenticate([PA])
    body = body_json()
    name = req_str(body, "name")
    care_levels = req_enum_array(body, "care_levels_offered", CARE_LEVELS)
    cap = opt_int(body, "guest_meal_sponsor_cap_cents", default=20000, minimum=0)
    tolerance = opt_int(body, "variance_tolerance_cents", default=5000, minimum=0)

    row = base_row()
    row.update({
        "name": name,
        "care_levels_offered": care_levels,
        "guest_meal_sponsor_cap_cents": cap,
        "variance_tolerance_cents": tolerance,
    })
    db.communities[row["id"]] = row
    return created(serialize.community(row))
