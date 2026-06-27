"""Rack and its network (PRD §3.4)."""
import re

from flask import Blueprint

import db
import helpers as h
from errors import err
from middleware import authenticate, authorize
from response import success, paginated
from services import calc, domain

bp = Blueprint("racks", __name__)

READ_ROLES = {"PlatformAdmin", "SystemsDesigner", "ProjectManager", "SupportEngineer", "LowVoltageTech", "Client"}

_CIDR_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})/(\d{1,2})$")


def _validate_cidr(cidr):
    m = _CIDR_RE.match(cidr)
    if not m:
        raise err("ERR_INVALID_REQUEST", "subnet_cidr must be valid CIDR notation")
    octets = [int(m.group(i)) for i in range(1, 5)]
    prefix = int(m.group(5))
    if any(o > 255 for o in octets) or prefix > 32:
        raise err("ERR_INVALID_REQUEST", "subnet_cidr out of range")


@bp.post("/projects/<project_id>/rack")
def create_rack(project_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager", "SystemsDesigner"})
    project = h.get_or_404(db.projects, project_id)
    body = h.get_body()
    rack_units_total = h.require_int(body, "rack_units_total", minimum=0)
    subnet_cidr = h.require_str(body, "subnet_cidr")
    _validate_cidr(subnet_cidr)
    entity = {
        "project_id": project_id,
        "rack_units_total": rack_units_total,
        "rack_units_used": 0,
        "subnet_cidr": subnet_cidr,
        "ip_pool_size": calc.ip_pool_size(subnet_cidr),
    }
    db.stamp_create(entity)
    db.racks[entity["id"]] = entity
    return success(h.public(entity), status=201)


@bp.get("/projects/<project_id>/rack")
def get_rack(project_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    h.get_or_404(db.projects, project_id)
    limit, offset = h.parse_pagination()
    rack = domain.rack_for_project(project_id)
    # returns an array of zero or one rack (PRD §3.4); list-based response carries
    # pagination meta per PRD §2.2.
    items = [rack] if rack else []
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(r) for r in page], limit, offset, total)
