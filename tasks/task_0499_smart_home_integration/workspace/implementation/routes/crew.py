"""Crew members and their assignments (PRD §3.7)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import err
from middleware import authenticate, authorize
from response import success, paginated

bp = Blueprint("crew", __name__)

ASSIGN_READ_ROLES = {"PlatformAdmin", "ProjectManager", "LowVoltageTech"}
GET_ROLES = {"PlatformAdmin", "ProjectManager", "LowVoltageTech"}


@bp.post("/crew-members")
def create_crew():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "ProjectManager"})
    body = h.get_body()
    full_name = h.require_str(body, "full_name")
    region_code = h.require_enum(body, "region_code", h.REGION_CODES)
    cert_level = h.require_enum(body, "cert_level", h.CERT_LEVELS)
    daily_visit_cap = h.optional_int(body, "daily_visit_cap", 2, minimum=0)
    active = h.optional_bool(body, "active", True)
    entity = {
        "full_name": full_name,
        "region_code": region_code,
        "cert_level": cert_level,
        "daily_visit_cap": daily_visit_cap,
        "active": active,
    }
    db.stamp_create(entity)
    db.crew_members[entity["id"]] = entity
    return success(h.public(entity), status=201)


@bp.get("/crew-members/<crew_member_id>")
def get_crew(crew_member_id):
    _, role = authenticate()
    authorize(role, GET_ROLES)
    entity = h.get_or_404(db.crew_members, crew_member_id)
    return success(h.public(entity))


@bp.get("/crew-members/<crew_member_id>/assignments")
def list_crew_assignments(crew_member_id):
    _, role = authenticate()
    authorize(role, ASSIGN_READ_ROLES)
    h.get_or_404(db.crew_members, crew_member_id)
    limit, offset = h.parse_pagination()
    status = request.args.get("status")
    items = [a for a in db.assignments.values() if a["crew_member_id"] == crew_member_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = h.sort_by_creation(items)
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(a) for a in page], limit, offset, total)
