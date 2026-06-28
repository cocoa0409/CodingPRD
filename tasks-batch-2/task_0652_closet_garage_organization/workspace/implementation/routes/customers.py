"""Customer and Project routes."""
from flask import Blueprint

import db
import serialize
from errors import err
from response import object_response, array_response
from middleware import get_identity, require_roles
from validate import (get_body, require_str, require_enum, parse_pagination,
                      paginate)
from services import domain

bp = Blueprint("customers", __name__)

ROOM_TYPES = {"REACH_IN_CLOSET", "WALK_IN_CLOSET", "GARAGE", "PANTRY", "HOME_OFFICE"}


# ---------------- Customers ----------------
@bp.post("/customers")
def create_customer():
    # Anonymous registration: no auth headers required.
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    zip_code = require_str(body, "zip_code")
    if not (zip_code.isdigit() and len(zip_code) == 5):
        raise err("ERR_VALIDATION", "zip_code must be a 5-digit string.")
    # unique email, case-insensitive
    lowered = email.lower()
    for c in db.customers.values():
        if c["email"].lower() == lowered:
            raise err("ERR_VALIDATION", "email already registered.")

    rec = db.stamp_new({
        "email": email,
        "full_name": full_name,
        "zip_code": zip_code,
        "install_region": domain.derive_region(zip_code),
    })
    db.customers[rec["id"]] = rec
    return object_response(serialize.customer(rec), 201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "Scheduler",
                         "ManufacturingOps", "PlatformAdmin"})
    rec = db.customers.get(cid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return object_response(serialize.customer(rec))


# ---------------- Projects ----------------
@bp.post("/projects")
def create_project():
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer"})
    body = get_body()
    customer_id = require_str(body, "customer_id")
    room_type = require_enum(body, "room_type", ROOM_TYPES)
    customer = db.customers.get(customer_id)
    if customer is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    rec = db.stamp_new({
        "customer_id": customer_id,
        "room_type": room_type,
        "status": "LEAD",
        "financing_application_id": None,
        "accepted_quote_id": None,
        "balance_due_cents": 0,
        "install_region": customer["install_region"],
    })
    db.projects[rec["id"]] = rec
    return object_response(serialize.project(rec), 201)


@bp.get("/projects/<pid>")
def get_project(pid):
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "Scheduler",
                         "ManufacturingOps", "PlatformAdmin"})
    rec = db.projects.get(pid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    # Read-triggered quote-expiry sweep on the project's quotes.
    domain.sweep_project_quotes(pid)
    return object_response(serialize.project(rec))


@bp.get("/projects")
def list_projects():
    from flask import request
    _, role = get_identity()
    require_roles(role, {"Designer", "Scheduler", "ManufacturingOps",
                         "PlatformAdmin"})
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    accepted_quote_id = request.args.get("accepted_quote_id")
    financing_application_id = request.args.get("financing_application_id")
    status = request.args.get("status")
    items = []
    for p in db.projects.values():
        if customer_id is not None and p["customer_id"] != customer_id:
            continue
        if accepted_quote_id is not None and p.get("accepted_quote_id") != accepted_quote_id:
            continue
        if financing_application_id is not None and p.get("financing_application_id") != financing_application_id:
            continue
        if status is not None and p["status"] != status:
            continue
        items.append(p)
    page, total = paginate(items, limit, offset)
    return array_response([serialize.project(p) for p in page],
                          limit, offset, total)


@bp.post("/projects/<pid>/cancel")
def cancel_project(pid):
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    rec = db.projects.get(pid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    domain.check_project_owner(rec, user_id, role)
    if rec["status"] not in {"LEAD", "DESIGNING", "QUOTED"}:
        raise err("ERR_INVALID_STATE")
    # Cascade: non-terminal consults -> CANCELLED; DRAFT/ISSUED quotes -> VOID.
    for consult in db.design_consults.values():
        if consult["project_id"] == pid and consult["status"] in {"SCHEDULED", "RENDERED"}:
            consult["status"] = "CANCELLED"
            db.touch(consult)
    for q in db.quotes.values():
        if q["project_id"] == pid and q["status"] in {"DRAFT", "ISSUED"}:
            q["status"] = "VOID"
            db.touch(q)
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return object_response(serialize.project(rec))


@bp.get("/projects/<pid>/balance")
def project_balance(pid):
    _, role = get_identity()
    require_roles(role, {"Customer", "Designer", "PlatformAdmin"})
    rec = db.projects.get(pid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    domain.recompute_balance(rec)
    return object_response(serialize.project(rec))
