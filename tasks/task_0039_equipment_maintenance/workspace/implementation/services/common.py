"""Shared service helpers: pagination, fetch-or-404, body parsing."""
from flask import request

from db import db
from errors import (
    ERR_BAD_REQUEST,
    ERR_NOT_FOUND,
    ERR_VERSION_CONFLICT,
    raise_err,
)


def get_json_body():
    """Parse JSON body. Returns dict (possibly empty)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_err(ERR_BAD_REQUEST, "Malformed JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_BAD_REQUEST, "Body must be a JSON object")
    return body


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3."""
    limit = request.args.get("limit", "10")
    offset = request.args.get("offset", "0")
    try:
        limit = int(limit)
    except (ValueError, TypeError):
        raise_err(ERR_BAD_REQUEST, "limit must be integer")
    try:
        offset = int(offset)
    except (ValueError, TypeError):
        raise_err(ERR_BAD_REQUEST, "offset must be integer")
    if limit < 1 or limit > 100:
        raise_err(ERR_BAD_REQUEST, "limit out of range (1..100)")
    if offset < 0:
        raise_err(ERR_BAD_REQUEST, "offset must be >= 0")
    return limit, offset


def get_site_or_404(site_id):
    s = db.sites.get(site_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, "Site not found")
    return s


def get_equipment_or_404(site_id, equipment_id):
    e = db.equipment.get(equipment_id)
    if e is None or e["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "Equipment not found")
    return e


def get_template_or_404(site_id, template_id):
    t = db.templates.get(template_id)
    if t is None or t["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "Template not found")
    return t


def get_plan_or_404(site_id, plan_id):
    p = db.plans.get(plan_id)
    if p is None or p["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "Plan not found")
    return p


def get_spare_part_or_404(site_id, part_id):
    sp = db.spare_parts.get(part_id)
    if sp is None or sp["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "Spare part not found")
    return sp


def get_technician_or_404(site_id, tech_id):
    t = db.technicians.get(tech_id)
    if t is None or t["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "Technician not found")
    return t


def get_work_order_or_404(site_id, wo_id):
    w = db.work_orders.get(wo_id)
    if w is None or w["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "WorkOrder not found")
    return w


def get_requisition_or_404(site_id, wo_id, req_id):
    r = db.requisitions.get(req_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, "Requisition not found")
    if r["work_order_id"] != wo_id:
        raise_err(ERR_NOT_FOUND, "Requisition not found")
    # Validate WO belongs to site as well
    w = db.work_orders.get(wo_id)
    if w is None or w["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "WorkOrder not found")
    return r


def check_version(entity, body):
    """If body has 'version', enforce OCC."""
    if "version" in body and body["version"] is not None:
        v = body["version"]
        if not isinstance(v, int) or v != entity.get("version"):
            raise_err(ERR_VERSION_CONFLICT, "Version mismatch")


def bump_version(entity, site_id):
    """Increment version and updated_at to site clock."""
    if "version" in entity:
        entity["version"] = entity["version"] + 1
    if "updated_at" in entity:
        entity["updated_at"] = db.site_clock(site_id)


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    return page, total
