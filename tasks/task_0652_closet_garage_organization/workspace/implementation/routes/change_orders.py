"""ChangeOrder routes: submit, approve, reject, apply (OCC on project)."""
from flask import Blueprint, request

import db
import serialize
from errors import err
from response import object_response, array_response
from middleware import get_identity, require_roles
from validate import (get_body, require_str, require_enum, optional_str,
                      parse_pagination, paginate)
from services import calc, domain

bp = Blueprint("change_orders", __name__)

CHANGE_TYPES = {"CONFIG_REVISION", "SCHEDULE_CHANGE"}


@bp.post("/change-orders")
def create_change_order():
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer"})
    body = get_body()
    project_id = require_str(body, "project_id")
    base_quote_id = require_str(body, "base_quote_id")
    change_type = require_enum(body, "change_type", CHANGE_TYPES)
    revised_config_id = optional_str(body, "revised_config_id")

    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    base_quote = db.quotes.get(base_quote_id)
    if base_quote is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    # If a revised_config_id is supplied, it must exist.
    if revised_config_id is not None and revised_config_id not in db.component_configs:
        raise err("ERR_RESOURCE_NOT_FOUND")

    # Change-target validity (priority 20).
    if change_type == "CONFIG_REVISION":
        if revised_config_id is None:
            raise err("ERR_CHANGE_TARGET_INVALID")
        cfg = db.component_configs[revised_config_id]
        if cfg["status"] != "FINALIZED":
            raise err("ERR_CHANGE_TARGET_INVALID")
    else:  # SCHEDULE_CHANGE
        if revised_config_id is not None:
            raise err("ERR_CHANGE_TARGET_INVALID")

    rec = db.stamp_new({
        "project_id": project_id,
        "base_quote_id": base_quote_id,
        "change_type": change_type,
        "revised_config_id": revised_config_id,
        "status": "SUBMITTED",
        "delta_cents": 0,
    })
    db.change_orders[rec["id"]] = rec
    return object_response(serialize.change_order(rec), 201)


@bp.get("/change-orders/<coid>")
def get_change_order(coid):
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "PlatformAdmin"})
    rec = db.change_orders.get(coid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return object_response(serialize.change_order(rec))


@bp.get("/change-orders")
def list_change_orders():
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    base_quote_id = request.args.get("base_quote_id")
    revised_config_id = request.args.get("revised_config_id")
    status = request.args.get("status")
    items = []
    for c in db.change_orders.values():
        if project_id is not None and c["project_id"] != project_id:
            continue
        if base_quote_id is not None and c["base_quote_id"] != base_quote_id:
            continue
        if revised_config_id is not None and c.get("revised_config_id") != revised_config_id:
            continue
        if status is not None and c["status"] != status:
            continue
        items.append(c)
    page, total = paginate(items, limit, offset)
    return array_response([serialize.change_order(c) for c in page],
                          limit, offset, total)


def _price_revised(co):
    """Price the revised config (no promo carried over)."""
    cfg = db.component_configs[co["revised_config_id"]]
    project = db.projects[co["project_id"]]
    subtotal, discount, tax, total = calc.quote_estimate_pricing(
        cfg["line_items"], cfg["material_grade"], cfg["total_units"],
        project["install_region"], None)
    return subtotal, discount, tax, total


@bp.post("/change-orders/<coid>/approve")
def approve_change_order(coid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    rec = db.change_orders.get(coid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    base_quote = db.quotes.get(rec["base_quote_id"])
    project = db.projects.get(rec["project_id"])
    if base_quote is None or project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE")
    if base_quote["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE")
    if project["status"] not in {"DEPOSIT_PAID", "IN_MANUFACTURE"}:
        raise err("ERR_INVALID_STATE")

    # Compute delta.
    if rec["change_type"] == "CONFIG_REVISION":
        _, _, _, new_total = _price_revised(rec)
        rec["delta_cents"] = new_total - base_quote["total_cents"]
    else:
        rec["delta_cents"] = 0
    rec["status"] = "APPROVED"
    db.touch(rec)
    return object_response(serialize.change_order(rec))


@bp.post("/change-orders/<coid>/reject")
def reject_change_order(coid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    rec = db.change_orders.get(coid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE")
    rec["status"] = "REJECTED"
    db.touch(rec)
    return object_response(serialize.change_order(rec))


@bp.post("/change-orders/<coid>/apply")
def apply_change_order(coid):
    _, role = get_identity()
    require_roles(role, {"Designer"})
    rec = db.change_orders.get(coid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    project = db.projects.get(rec["project_id"])
    base_quote = db.quotes.get(rec["base_quote_id"])
    if project is None or base_quote is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    body = get_body()

    # State check (priority 5).
    if rec["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE")

    # OCC on project version (priority 6).
    expected = body.get("expected_project_version")
    if expected is not None and expected != project["version"]:
        raise err("ERR_STALE_PROJECT_VERSION")

    # Change-target validity for CONFIG_REVISION (priority 20).
    if rec["change_type"] == "CONFIG_REVISION":
        revised_config_id = rec.get("revised_config_id")
        if revised_config_id is None or revised_config_id not in db.component_configs:
            raise err("ERR_CHANGE_TARGET_INVALID")
        revised_cfg = db.component_configs[revised_config_id]
        if revised_cfg["status"] != "FINALIZED":
            raise err("ERR_CHANGE_TARGET_INVALID")

    # Cascade.
    if rec["change_type"] == "CONFIG_REVISION":
        revised_cfg = db.component_configs[rec["revised_config_id"]]
        subtotal, discount, tax, total = _price_revised(rec)
        new_quote = db.stamp_new({
            "project_id": project["id"],
            "component_config_id": revised_cfg["id"],
            "status": "ACCEPTED",
            "subtotal_cents": subtotal,
            "discount_cents": discount,
            "tax_cents": tax,
            "total_cents": total,
            "promo_code": None,
            "issued_at": None,
            "expires_at": None,
        })
        db.quotes[new_quote["id"]] = new_quote

        # base quote ACCEPTED -> SUPERSEDED
        base_quote["status"] = "SUPERSEDED"
        db.touch(base_quote)

        # prior FINALIZED config -> SUPERSEDED (the config behind the base quote)
        prior_cfg = db.component_configs.get(base_quote["component_config_id"])
        if prior_cfg is not None and prior_cfg["status"] == "FINALIZED":
            prior_cfg["status"] = "SUPERSEDED"
            db.touch(prior_cfg)

        project["accepted_quote_id"] = new_quote["id"]

    rec["status"] = "APPLIED"
    db.touch(rec)

    # recompute balance (delta applied) — also bumps project version.
    domain.recompute_balance(project)
    return object_response(serialize.change_order(rec))
