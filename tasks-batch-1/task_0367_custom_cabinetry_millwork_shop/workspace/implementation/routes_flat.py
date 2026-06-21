"""Flat read aliases: single-resource GET + FK-filtered list per entity.

These provide reverse-reachability for every FK. Role checks per the §4 table.
Ownership is NOT enforced on reads (the §1.4 priority-3 owner check applies only
to Customer-actor write endpoints: contract, draw pay, change-order decisions).
"""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_user_context, require_role
from response import success, success_list
from helpers import parse_pagination, paginate, sort_by_created
from models import (serialize_customer, serialize_project, serialize_spec,
                    serialize_material, serialize_reservation, serialize_machine,
                    serialize_build_job, serialize_finish, serialize_draw,
                    serialize_change_order, serialize_installation, serialize_punch)

bp = Blueprint("flat", __name__)


def _not_found(msg):
    raise err("ERR_NOT_FOUND", msg)


def _list_response(items, serializer):
    limit, offset = parse_pagination()
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serializer(x) for x in page], limit, offset, total)


# --------------------------------------------------------------------------
# Customer
# --------------------------------------------------------------------------
@bp.route("/customers/<customer_id>", methods=["GET"])
def flat_customer(customer_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer", "Customer"})
    c = store.customers.get(customer_id)
    if c is None:
        _not_found("Customer not found")
    return success(serialize_customer(c), 200)


@bp.route("/customers", methods=["GET"])
def flat_customers():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    shop_id = request.args.get("shop_id")
    items = list(store.customers.values())
    if shop_id is not None:
        items = [c for c in items if c["shop_id"] == shop_id]
    return _list_response(items, serialize_customer)


# --------------------------------------------------------------------------
# Project
# --------------------------------------------------------------------------
@bp.route("/projects/<project_id>", methods=["GET"])
def flat_project(project_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer", "Installer", "Customer"})
    p = store.projects.get(project_id)
    if p is None:
        _not_found("Project not found")
    return success(serialize_project(p), 200)


@bp.route("/projects", methods=["GET"])
def flat_projects():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer", "Installer", "Customer"})
    customer_id = request.args.get("customer_id")
    shop_id = request.args.get("shop_id")
    status = request.args.get("status")
    items = list(store.projects.values())
    if customer_id is not None:
        items = [p for p in items if p["customer_id"] == customer_id]
    if shop_id is not None:
        items = [p for p in items if p["shop_id"] == shop_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return _list_response(items, serialize_project)


# --------------------------------------------------------------------------
# CabinetSpec
# --------------------------------------------------------------------------
@bp.route("/specs/<spec_id>", methods=["GET"])
def flat_spec(spec_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    s = store.specs.get(spec_id)
    if s is None:
        _not_found("Cabinet spec not found")
    return success(serialize_spec(s), 200)


@bp.route("/specs", methods=["GET"])
def flat_specs():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    project_id = request.args.get("project_id")
    material_id = request.args.get("material_id")
    items = list(store.specs.values())
    if project_id is not None:
        items = [s for s in items if s["project_id"] == project_id]
    if material_id is not None:
        items = [s for s in items if s["material_id"] == material_id]
    return _list_response(items, serialize_spec)


# --------------------------------------------------------------------------
# Material
# --------------------------------------------------------------------------
@bp.route("/materials/<material_id>", methods=["GET"])
def flat_material(material_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    m = store.materials.get(material_id)
    if m is None:
        _not_found("Material not found")
    return success(serialize_material(m), 200)


@bp.route("/materials", methods=["GET"])
def flat_materials():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    shop_id = request.args.get("shop_id")
    items = list(store.materials.values())
    if shop_id is not None:
        items = [m for m in items if m["shop_id"] == shop_id]
    return _list_response(items, serialize_material)


# --------------------------------------------------------------------------
# MaterialReservation
# --------------------------------------------------------------------------
@bp.route("/material-reservations/<reservation_id>", methods=["GET"])
def flat_reservation(reservation_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    r = store.reservations.get(reservation_id)
    if r is None:
        _not_found("Material reservation not found")
    return success(serialize_reservation(r), 200)


@bp.route("/material-reservations", methods=["GET"])
def flat_reservations():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    project_id = request.args.get("project_id")
    material_id = request.args.get("material_id")
    items = list(store.reservations.values())
    if project_id is not None:
        items = [r for r in items if r["project_id"] == project_id]
    if material_id is not None:
        items = [r for r in items if r["material_id"] == material_id]
    return _list_response(items, serialize_reservation)


# --------------------------------------------------------------------------
# Machine
# --------------------------------------------------------------------------
@bp.route("/machines/<machine_id>", methods=["GET"])
def flat_machine(machine_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    m = store.machines.get(machine_id)
    if m is None:
        _not_found("Machine not found")
    return success(serialize_machine(m), 200)


@bp.route("/machines", methods=["GET"])
def flat_machines():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    shop_id = request.args.get("shop_id")
    items = list(store.machines.values())
    if shop_id is not None:
        items = [m for m in items if m["shop_id"] == shop_id]
    return _list_response(items, serialize_machine)


# --------------------------------------------------------------------------
# BuildJob
# --------------------------------------------------------------------------
@bp.route("/build-jobs/<build_job_id>", methods=["GET"])
def flat_build_job(build_job_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    b = store.build_jobs.get(build_job_id)
    if b is None:
        _not_found("Build job not found")
    return success(serialize_build_job(b), 200)


@bp.route("/build-jobs", methods=["GET"])
def flat_build_jobs():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    project_id = request.args.get("project_id")
    machine_id = request.args.get("machine_id")
    items = list(store.build_jobs.values())
    if project_id is not None:
        items = [b for b in items if b["project_id"] == project_id]
    if machine_id is not None:
        items = [b for b in items if b["machine_id"] == machine_id]
    return _list_response(items, serialize_build_job)


# --------------------------------------------------------------------------
# FinishSelection
# --------------------------------------------------------------------------
@bp.route("/finish-selections/<finish_id>", methods=["GET"])
def flat_finish(finish_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    f = store.finish_selections.get(finish_id)
    if f is None:
        _not_found("Finish selection not found")
    return success(serialize_finish(f), 200)


@bp.route("/finish-selections", methods=["GET"])
def flat_finishes():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    project_id = request.args.get("project_id")
    items = list(store.finish_selections.values())
    if project_id is not None:
        items = [f for f in items if f["project_id"] == project_id]
    return _list_response(items, serialize_finish)


# --------------------------------------------------------------------------
# Draw
# --------------------------------------------------------------------------
@bp.route("/draws/<draw_id>", methods=["GET"])
def flat_draw(draw_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Customer"})
    d = store.draws.get(draw_id)
    if d is None:
        _not_found("Draw not found")
    return success(serialize_draw(d), 200)


@bp.route("/draws", methods=["GET"])
def flat_draws():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Customer"})
    project_id = request.args.get("project_id")
    draw_type = request.args.get("draw_type")
    status = request.args.get("status")
    items = list(store.draws.values())
    if project_id is not None:
        items = [d for d in items if d["project_id"] == project_id]
    if draw_type is not None:
        items = [d for d in items if d["draw_type"] == draw_type]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return _list_response(items, serialize_draw)


# --------------------------------------------------------------------------
# ChangeOrder
# --------------------------------------------------------------------------
@bp.route("/change-orders/<co_id>", methods=["GET"])
def flat_change_order(co_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Customer"})
    c = store.change_orders.get(co_id)
    if c is None:
        _not_found("Change order not found")
    return success(serialize_change_order(c), 200)


@bp.route("/change-orders", methods=["GET"])
def flat_change_orders():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Customer"})
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    items = list(store.change_orders.values())
    if project_id is not None:
        items = [c for c in items if c["project_id"] == project_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return _list_response(items, serialize_change_order)


# --------------------------------------------------------------------------
# Installation
# --------------------------------------------------------------------------
@bp.route("/installations/<installation_id>", methods=["GET"])
def flat_installation(installation_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Installer", "Customer"})
    i = store.installations.get(installation_id)
    if i is None:
        _not_found("Installation not found")
    return success(serialize_installation(i), 200)


@bp.route("/installations", methods=["GET"])
def flat_installations():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Installer", "Customer"})
    project_id = request.args.get("project_id")
    items = list(store.installations.values())
    if project_id is not None:
        items = [i for i in items if i["project_id"] == project_id]
    return _list_response(items, serialize_installation)


# --------------------------------------------------------------------------
# PunchItem
# --------------------------------------------------------------------------
@bp.route("/punch-items/<punch_id>", methods=["GET"])
def flat_punch(punch_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Installer", "Customer"})
    pi = store.punch_items.get(punch_id)
    if pi is None:
        _not_found("Punch item not found")
    return success(serialize_punch(pi), 200)


@bp.route("/punch-items", methods=["GET"])
def flat_punches():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Installer", "Customer"})
    installation_id = request.args.get("installation_id")
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    items = list(store.punch_items.values())
    if installation_id is not None:
        items = [pi for pi in items if pi["installation_id"] == installation_id]
    if project_id is not None:
        items = [pi for pi in items if pi["project_id"] == project_id]
    if status is not None:
        items = [pi for pi in items if pi["status"] == status]
    return _list_response(items, serialize_punch)
