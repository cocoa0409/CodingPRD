"""Deposit and ManufactureOrder routes."""
from datetime import timedelta

from flask import Blueprint, request

import db
import serialize
from errors import err
from response import object_response, array_response
from middleware import get_identity, require_roles
from validate import get_body, require_str, require_int, parse_pagination, paginate
from services import calc, clock, domain

bp = Blueprint("deposits", __name__)


# ---------------- Deposits ----------------
@bp.post("/deposits")
def create_deposit():
    user_id, role = get_identity()
    require_roles(role, {"Customer", "PlatformAdmin"})
    body = get_body()
    project_id = require_str(body, "project_id")
    quote_id = require_str(body, "quote_id")
    amount_cents = require_int(body, "amount_cents", minimum=0)
    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    quote = db.quotes.get(quote_id)
    if quote is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    # Customer creating a deposit must own the project.
    domain.check_project_owner(project, user_id, role)
    # Required deposit floor from the target quote total and room type.
    floor = calc.required_deposit_cents(quote["total_cents"], project["room_type"])
    if amount_cents < floor:
        raise err("ERR_DEPOSIT_BELOW_MINIMUM")
    rec = db.stamp_new({
        "project_id": project_id,
        "quote_id": quote_id,
        "amount_cents": amount_cents,
        "status": "PENDING",
    })
    db.deposits[rec["id"]] = rec
    return object_response(serialize.deposit(rec), 201)


@bp.get("/deposits/<did>")
def get_deposit(did):
    _, role = get_identity()
    require_roles(role, {"Customer", "PlatformAdmin"})
    rec = db.deposits.get(did)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return object_response(serialize.deposit(rec))


@bp.get("/deposits")
def list_deposits():
    _, role = get_identity()
    require_roles(role, {"Customer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    quote_id = request.args.get("quote_id")
    items = []
    for d in db.deposits.values():
        if project_id is not None and d["project_id"] != project_id:
            continue
        if quote_id is not None and d["quote_id"] != quote_id:
            continue
        items.append(d)
    page, total = paginate(items, limit, offset)
    return array_response([serialize.deposit(d) for d in page],
                          limit, offset, total)


@bp.post("/deposits/<did>/capture")
def capture_deposit(did):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin"})
    rec = db.deposits.get(did)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    body = get_body()
    quote = db.quotes.get(rec["quote_id"])
    project = db.projects.get(rec["project_id"])
    # existence of FK targets
    if quote is None or project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")

    # State checks (priority 5) before OCC (priority 7).
    if rec["status"] != "PENDING":
        raise err("ERR_INVALID_STATE")
    if quote["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE")
    if project["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE")

    # OCC on quote version (priority 7).
    expected = body.get("expected_quote_version")
    if expected is not None:
        if expected != quote["version"]:
            raise err("ERR_STALE_QUOTE_VERSION")

    # Deposit floor (priority 17).
    floor = calc.required_deposit_cents(quote["total_cents"], project["room_type"])
    if rec["amount_cents"] < floor:
        raise err("ERR_DEPOSIT_BELOW_MINIMUM")

    # Commit: capture, set accepted_quote, create ManufactureOrder, advance project.
    rec["status"] = "CAPTURED"
    db.touch(rec)

    project["accepted_quote_id"] = rec["quote_id"]

    mo = db.stamp_new({
        "project_id": project["id"],
        "quote_id": rec["quote_id"],
        "status": "QUEUED",
        "lead_time_days": 0,
        "promised_ready_date": None,
        "started_at": None,
    })
    db.manufacture_orders[mo["id"]] = mo

    project["status"] = "DEPOSIT_PAID"
    # recompute_balance bumps project version (covers the advance + balance recompute).
    domain.recompute_balance(project)

    # quote version bump (cascade).
    db.touch(quote)
    return object_response(serialize.deposit(rec))


@bp.post("/deposits/<did>/refund")
def refund_deposit(did):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin"})
    rec = db.deposits.get(did)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    project = db.projects.get(rec["project_id"])
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "CAPTURED":
        raise err("ERR_INVALID_STATE")
    if project["status"] != "DEPOSIT_PAID":
        raise err("ERR_INVALID_STATE")
    rec["status"] = "REFUNDED"
    db.touch(rec)
    domain.recompute_balance(project)
    return object_response(serialize.deposit(rec))


# ---------------- Manufacture orders ----------------
@bp.get("/manufacture-orders/<mid>")
def get_order(mid):
    _, role = get_identity()
    require_roles(role, {"ManufacturingOps", "Scheduler", "Designer", "PlatformAdmin"})
    rec = db.manufacture_orders.get(mid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return object_response(serialize.manufacture_order(rec))


@bp.get("/manufacture-orders")
def list_orders():
    _, role = get_identity()
    require_roles(role, {"ManufacturingOps", "Scheduler", "PlatformAdmin"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    quote_id = request.args.get("quote_id")
    status = request.args.get("status")
    items = []
    for m in db.manufacture_orders.values():
        if project_id is not None and m["project_id"] != project_id:
            continue
        if quote_id is not None and m["quote_id"] != quote_id:
            continue
        if status is not None and m["status"] != status:
            continue
        items.append(m)
    page, total = paginate(items, limit, offset)
    return array_response([serialize.manufacture_order(m) for m in page],
                          limit, offset, total)


@bp.post("/manufacture-orders/<mid>/start")
def start_order(mid):
    _, role = get_identity()
    require_roles(role, {"ManufacturingOps"})
    rec = db.manufacture_orders.get(mid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    project = db.projects.get(rec["project_id"])
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "QUEUED":
        raise err("ERR_INVALID_STATE")
    if project["status"] != "DEPOSIT_PAID":
        raise err("ERR_INVALID_STATE")

    # Lead time uses the accepted quote's finalized config + project region.
    quote = db.quotes.get(rec["quote_id"])
    config = db.component_configs.get(quote["component_config_id"])
    lead = calc.lead_time_days(config["total_units"], config["material_grade"],
                               project["install_region"])
    now = clock.now()
    rec["lead_time_days"] = lead
    rec["started_at"] = now
    rec["promised_ready_date"] = now + timedelta(days=lead)
    rec["status"] = "IN_PRODUCTION"
    db.touch(rec)

    project["status"] = "IN_MANUFACTURE"
    db.touch(project)
    return object_response(serialize.manufacture_order(rec))


@bp.post("/manufacture-orders/<mid>/complete")
def complete_order(mid):
    _, role = get_identity()
    require_roles(role, {"ManufacturingOps"})
    rec = db.manufacture_orders.get(mid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    project = db.projects.get(rec["project_id"])
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "IN_PRODUCTION":
        raise err("ERR_INVALID_STATE")
    if project["status"] != "IN_MANUFACTURE":
        raise err("ERR_INVALID_STATE")
    # Lead-time gate: now must be >= promised_ready_date (inclusive boundary).
    if rec["promised_ready_date"] is not None and clock.now() < rec["promised_ready_date"]:
        raise err("ERR_LEAD_TIME_NOT_ELAPSED")
    rec["status"] = "READY"
    db.touch(rec)
    project["status"] = "READY_TO_INSTALL"
    db.touch(project)
    return object_response(serialize.manufacture_order(rec))
