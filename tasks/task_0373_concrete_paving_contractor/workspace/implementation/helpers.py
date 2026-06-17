"""Shared service helpers: entity creation, lookup, version bumps, derived recompute, pagination."""
from flask import request

from db import db, new_id
import calculations as calc
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import array_response


# ---------------------------------------------------------------------------
# Generic record creation with common system fields
# ---------------------------------------------------------------------------
def base_record(common_fields=True):
    rec = {"id": new_id()}
    now = db.now()
    rec["created_at"] = now
    rec["_seq"] = db.next_seq()
    if common_fields:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version by 1 (one mutation)."""
    rec["updated_at"] = db.now()
    rec["version"] = rec["version"] + 1


# ---------------------------------------------------------------------------
# Lookup helpers (raise ERR_NOT_FOUND on miss)
# ---------------------------------------------------------------------------
def get_project(pid):
    p = db.projects.get(pid)
    if p is None:
        raise err(ERR_NOT_FOUND, "Project not found")
    return p


def get_material_order(mid):
    m = db.material_orders.get(mid)
    if m is None:
        raise err(ERR_NOT_FOUND, "MaterialOrder not found")
    return m


def get_permit(pid):
    p = db.permits.get(pid)
    if p is None:
        raise err(ERR_NOT_FOUND, "Permit not found")
    return p


def get_crew(cid):
    c = db.crews.get(cid)
    if c is None:
        raise err(ERR_NOT_FOUND, "Crew not found")
    return c


def get_equipment(eid):
    e = db.equipment.get(eid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Equipment not found")
    return e


def get_crew_assignment(aid):
    a = db.crew_assignments.get(aid)
    if a is None:
        raise err(ERR_NOT_FOUND, "CrewAssignment not found")
    return a


def get_change_order(cid):
    c = db.change_orders.get(cid)
    if c is None:
        raise err(ERR_NOT_FOUND, "ChangeOrder not found")
    return c


def get_draw(did):
    d = db.draws.get(did)
    if d is None:
        raise err(ERR_NOT_FOUND, "Draw not found")
    return d


def get_warranty(wid):
    w = db.warranties.get(wid)
    if w is None:
        raise err(ERR_NOT_FOUND, "Warranty not found")
    return w


# ---------------------------------------------------------------------------
# Child-collection accessors
# ---------------------------------------------------------------------------
def project_segments(pid):
    return [s for s in db.segments.values() if s["project_id"] == pid]


def project_estimates(pid):
    return [e for e in db.estimates.values() if e["project_id"] == pid]


def project_permits(pid):
    return [p for p in db.permits.values() if p["project_id"] == pid]


def project_material_orders(pid):
    return [m for m in db.material_orders.values() if m["project_id"] == pid]


def project_crew_assignments(pid):
    return [a for a in db.crew_assignments.values() if a["project_id"] == pid]


def project_change_orders(pid):
    return [c for c in db.change_orders.values() if c["project_id"] == pid]


def project_draws(pid):
    return [d for d in db.draws.values() if d["project_id"] == pid]


def project_warranties(pid):
    return [w for w in db.warranties.values() if w["project_id"] == pid]


def order_weather_readings(mid):
    return [w for w in db.weather_readings.values() if w["material_order_id"] == mid]


# ---------------------------------------------------------------------------
# Derived-field recomputation on a project
# ---------------------------------------------------------------------------
def recompute_contract_values(project):
    cos = project_change_orders(project["id"])
    project["provisional_contract_value"] = calc.provisional_contract_value(
        project["base_contract_amount"], cos)
    project["committed_contract_value"] = calc.committed_contract_value(
        project["base_contract_amount"], cos)


def recompute_total_drawn(project):
    draws = project_draws(project["id"])
    total = sum((d["amount"] for d in draws if d["status"] == "RELEASED"), 0.0)
    from util import money
    project["total_drawn_amount"] = money(total)


def recompute_warranty_risk(project):
    project["warranty_risk_score"] = calc.warranty_risk_score(
        project,
        project_segments(project["id"]),
        project_material_orders(project["id"]),
        project_warranties(project["id"]),
    )


def recompute_all_derived(project):
    recompute_contract_values(project)
    recompute_total_drawn(project)
    recompute_warranty_risk(project)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    """Return (limit, offset). limit default 10, min 1, max 100; offset default 0.

    Invalid values yield ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(items, serializer):
    """Sort by created_at ASC (tie-break _seq), paginate, return an array_response."""
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return array_response([serializer(r) for r in page], limit, offset, total)
