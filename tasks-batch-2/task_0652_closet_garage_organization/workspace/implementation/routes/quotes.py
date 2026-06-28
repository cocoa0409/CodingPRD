"""Quote routes: create draft, issue (price), accept, fetch/list with sweep."""
from datetime import timedelta

from flask import Blueprint, request

import db
import serialize
from errors import err
from response import object_response, array_response
from middleware import get_identity, require_roles
from validate import (get_body, require_str, optional_str, parse_pagination,
                      paginate)
from services import calc, clock, domain

bp = Blueprint("quotes", __name__)


def _require_project(pid):
    rec = db.projects.get(pid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return rec


@bp.post("/projects/<pid>/quotes")
def create_quote(pid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    _require_project(pid)
    body = get_body()
    component_config_id = require_str(body, "component_config_id")
    promo_code = optional_str(body, "promo_code")
    config = db.component_configs.get(component_config_id)
    if config is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if config["status"] != "FINALIZED":
        raise err("ERR_CONFIG_NOT_FINALIZED")
    rec = db.stamp_new({
        "project_id": pid,
        "component_config_id": component_config_id,
        "status": "DRAFT",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "promo_code": promo_code,
        "issued_at": None,
        "expires_at": None,
    })
    db.quotes[rec["id"]] = rec
    return object_response(serialize.quote(rec), 201)


@bp.get("/projects/<pid>/quotes")
def list_project_quotes(pid):
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "PlatformAdmin"})
    _require_project(pid)
    # Read-triggered expiry sweep.
    domain.sweep_project_quotes(pid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [q for q in db.quotes.values()
             if q["project_id"] == pid and (status is None or q["status"] == status)]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.quote(q) for q in page],
                          limit, offset, total)


@bp.get("/quotes/<qid>")
def get_quote(qid):
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "PlatformAdmin"})
    rec = db.quotes.get(qid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    domain.sweep_quote(rec)
    return object_response(serialize.quote(rec))


@bp.get("/quotes")
def list_quotes():
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    component_config_id = request.args.get("component_config_id")
    status = request.args.get("status")
    items = []
    for q in db.quotes.values():
        if project_id is not None and q["project_id"] != project_id:
            continue
        if component_config_id is not None and q["component_config_id"] != component_config_id:
            continue
        if status is not None and q["status"] != status:
            continue
        items.append(q)
    page, total = paginate(items, limit, offset)
    return array_response([serialize.quote(q) for q in page],
                          limit, offset, total)


@bp.post("/quotes/<qid>/issue")
def issue_quote(qid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    rec = db.quotes.get(qid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE")
    config = db.component_configs.get(rec["component_config_id"])
    if config is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if config["status"] != "FINALIZED":
        raise err("ERR_CONFIG_NOT_FINALIZED")
    project = db.projects.get(rec["project_id"])

    subtotal, discount, tax, total = calc.quote_estimate_pricing(
        config["line_items"], config["material_grade"], config["total_units"],
        project["install_region"], rec.get("promo_code"))
    rec["subtotal_cents"] = subtotal
    rec["discount_cents"] = discount
    rec["tax_cents"] = tax
    rec["total_cents"] = total
    now = clock.now()
    rec["issued_at"] = now
    rec["expires_at"] = now + timedelta(days=calc.QUOTE_VALIDITY_DAYS)
    rec["status"] = "ISSUED"
    db.touch(rec)

    # First issued quote on a DESIGNING project advances it to QUOTED.
    if project["status"] == "DESIGNING":
        project["status"] = "QUOTED"
        db.touch(project)
    return object_response(serialize.quote(rec))


@bp.post("/quotes/<qid>/accept")
def accept_quote(qid):
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    rec = db.quotes.get(qid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    project = db.projects.get(rec["project_id"])
    domain.check_project_owner(project, user_id, role)
    if rec["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE")
    # Expiry gate: now must be <= expires_at. Strictly past -> expired.
    if rec["expires_at"] is not None and clock.now() > rec["expires_at"]:
        raise err("ERR_QUOTE_EXPIRED")
    rec["status"] = "ACCEPTED"
    db.touch(rec)
    return object_response(serialize.quote(rec))
