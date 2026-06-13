"""House Painting Contractor API — Flask entry point.

In-memory store (db.py); no seeding at boot. Validation order per PRD §3.12:
auth(401) -> role(403) -> existence path+body FK(404) -> body well-formedness(422)
-> state(409) -> OCC(412) -> domain checks.
"""
import os

from flask import Flask, request

import calc
import services as svc
from db import store
from errors import ApiError, err
from middleware import require_auth, require_role
from pagination import get_pagination, paginate
from response import object_response, array_response, error_response

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_INVALID_REQUEST", "Unknown route.", 422)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 422)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 422)


def body_json():
    """Parse JSON body leniently; never raise for malformed/empty -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def list_response(collection_values, predicate=None):
    items = list(collection_values)
    if predicate is not None:
        items = [e for e in items if predicate(e)]
    items = svc.sorted_by_creation(items)
    limit, offset = get_pagination()
    page, total = paginate(items, limit, offset)
    data = [svc.serialize(e) for e in page]
    return array_response(data, limit, offset, total)


# ===========================================================================
# PaintProduct
# ===========================================================================
@app.route("/painting/paint-products", methods=["POST"])
def create_paint_product():
    _, role = require_auth()
    require_role(role, {"Estimator"})
    body = body_json()
    name = svc.as_str(svc.need(body, "name"), "name")
    surface_kind = svc.as_enum(svc.need(body, "surface_kind"), "surface_kind", svc.PRODUCT_SURFACE_KINDS)
    finish_type = svc.as_enum(svc.need(body, "finish_type"), "finish_type", svc.FINISH_TYPES)
    price = svc.as_int(svc.need(body, "price_per_gallon_cents"), "price_per_gallon_cents")
    if price < 1:
        raise err("ERR_INVALID_REQUEST", "price_per_gallon_cents must be >= 1.")
    coverage = svc.as_int(svc.need(body, "coverage_sqft_per_gallon_per_coat"), "coverage_sqft_per_gallon_per_coat")
    if coverage < 1:
        raise err("ERR_INVALID_REQUEST", "coverage_sqft_per_gallon_per_coat must be >= 1.")
    active = True
    if "active" in body and body["active"] is not None:
        active = svc.as_bool(body["active"], "active")
    entity = {
        "name": name,
        "surface_kind": surface_kind,
        "finish_type": finish_type,
        "price_per_gallon_cents": price,
        "coverage_sqft_per_gallon_per_coat": coverage,
        "active": active,
    }
    svc.add_common(entity)
    store.paint_products[entity["id"]] = entity
    return object_response(svc.serialize(entity), 201)


@app.route("/painting/paint-products", methods=["GET"])
def list_paint_products():
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer", "CrewMember"})
    sk = request.args.get("surface_kind")
    pred = (lambda e: e["surface_kind"] == sk) if sk is not None else None
    return list_response(store.paint_products.values(), pred)


@app.route("/painting/paint-products/<pid>", methods=["GET"])
def get_paint_product(pid):
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer", "CrewMember"})
    return object_response(svc.serialize(svc.get_paint_product(pid)))


# ===========================================================================
# CrewMember
# ===========================================================================
@app.route("/painting/crew-members", methods=["POST"])
def create_crew_member():
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    body = body_json()
    full_name = svc.as_str(svc.need(body, "full_name"), "full_name")
    skill = svc.as_enum(svc.need(body, "skill_level"), "skill_level", svc.SKILL_LEVELS)
    rate = svc.as_int(svc.need(body, "daily_rate_cents"), "daily_rate_cents")
    if rate < 1:
        raise err("ERR_INVALID_REQUEST", "daily_rate_cents must be >= 1.")
    active = True
    if "active" in body and body["active"] is not None:
        active = svc.as_bool(body["active"], "active")
    entity = {
        "full_name": full_name,
        "skill_level": skill,
        "daily_rate_cents": rate,
        "scheduled_day_count": 0,
        "active": active,
    }
    svc.add_common(entity)
    store.crew_members[entity["id"]] = entity
    return object_response(svc.serialize(entity), 201)


@app.route("/painting/crew-members", methods=["GET"])
def list_crew_members():
    _, role = require_auth()
    require_role(role, {"ProjectManager", "Estimator"})
    return list_response(store.crew_members.values())


@app.route("/painting/crew-members/<cid>", methods=["GET"])
def get_crew_member_route(cid):
    _, role = require_auth()
    require_role(role, {"ProjectManager", "Estimator"})
    return object_response(svc.serialize(svc.get_crew_member(cid)))


# ===========================================================================
# Equipment
# ===========================================================================
@app.route("/painting/equipment", methods=["POST"])
def create_equipment():
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    body = body_json()
    name = svc.as_str(svc.need(body, "name"), "name")
    kind = svc.as_enum(svc.need(body, "equipment_kind"), "equipment_kind", svc.EQUIPMENT_KINDS)
    total_units = svc.as_int(svc.need(body, "total_units"), "total_units")
    if total_units < 1:
        raise err("ERR_INVALID_REQUEST", "total_units must be >= 1.")
    entity = {
        "name": name,
        "equipment_kind": kind,
        "total_units": total_units,
        "units_reserved": 0,
    }
    svc.add_common(entity)
    store.equipment[entity["id"]] = entity
    return object_response(svc.serialize(entity), 201)


@app.route("/painting/equipment", methods=["GET"])
def list_equipment():
    _, role = require_auth()
    require_role(role, {"ProjectManager", "Estimator"})
    return list_response(store.equipment.values())


@app.route("/painting/equipment/<eid>", methods=["GET"])
def get_equipment_route(eid):
    _, role = require_auth()
    require_role(role, {"ProjectManager", "Estimator"})
    return object_response(svc.serialize(svc.get_equipment(eid)))


# ===========================================================================
# WeatherWindow
# ===========================================================================
@app.route("/painting/weather-windows", methods=["POST"])
def create_weather_window():
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    body = body_json()
    window_date = svc.as_str(svc.need(body, "window_date"), "window_date")
    # validate ISO date form
    try:
        svc.parse_date(window_date)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "window_date must be an ISO date 'YYYY-MM-DD'.")
    temp = svc.as_int(svc.need(body, "forecast_temp_f"), "forecast_temp_f")
    precip = svc.as_int(svc.need(body, "precipitation_pct"), "precipitation_pct")
    if precip < 0 or precip > 100:
        raise err("ERR_INVALID_REQUEST", "precipitation_pct must be 0..100.")
    # window_date must be unique across all rows
    for w in store.weather_windows.values():
        if w["window_date"] == window_date:
            raise err("ERR_INVALID_REQUEST", "window_date must be unique.")
    entity = {
        "window_date": window_date,
        "forecast_temp_f": temp,
        "precipitation_pct": precip,
        "exterior_suitable": calc.weather_suitable(temp, precip),
    }
    svc.add_common(entity)
    store.weather_windows[entity["id"]] = entity
    return object_response(svc.serialize(entity), 201)


@app.route("/painting/weather-windows", methods=["GET"])
def list_weather_windows():
    _, role = require_auth()
    require_role(role, {"ProjectManager", "Estimator", "CrewMember"})
    wd = request.args.get("window_date")
    pred = (lambda e: e["window_date"] == wd) if wd is not None else None
    return list_response(store.weather_windows.values(), pred)


@app.route("/painting/weather-windows/<wid>", methods=["GET"])
def get_weather_window_route(wid):
    _, role = require_auth()
    require_role(role, {"ProjectManager", "Estimator", "CrewMember"})
    return object_response(svc.serialize(svc.get_weather_window(wid)))


# ===========================================================================
# Project
# ===========================================================================
def serialize_project(p):
    return svc.serialize(p)


@app.route("/painting/projects", methods=["POST"])
def create_project():
    _, role = require_auth()
    require_role(role, {"Estimator"})
    body = body_json()
    customer_id = svc.as_str(svc.need(body, "customer_id"), "customer_id")
    site_address = svc.as_str(svc.need(body, "site_address"), "site_address")
    scope = svc.as_enum(svc.need(body, "scope"), "scope", svc.PROJECT_SCOPES)
    deposit_pct = 30
    if "deposit_pct" in body and body["deposit_pct"] is not None:
        deposit_pct = svc.as_int(body["deposit_pct"], "deposit_pct")
        if deposit_pct < 0 or deposit_pct > 100:
            raise err("ERR_INVALID_REQUEST", "deposit_pct must be 0..100.")
    warranty_months = 12
    if "warranty_months" in body and body["warranty_months"] is not None:
        warranty_months = svc.as_int(body["warranty_months"], "warranty_months")
    entity = {
        "customer_id": customer_id,
        "site_address": site_address,
        "scope": scope,
        "deposit_pct": deposit_pct,
        "workflow_status": "DRAFT",
        "payment_status": "UNPAID",
        "estimate_material_cents": 0,
        "estimate_labor_cents": 0,
        "estimate_total_cents": 0,
        "revised_total_cents": 0,
        "final_total_cents": None,
        "deposit_due_cents": 0,
        "amount_paid_cents": 0,
        "balance_due_cents": 0,
        "warranty_months": warranty_months,
        "warranty_expires_at": None,
    }
    svc.add_common(entity)
    store.projects[entity["id"]] = entity
    return object_response(serialize_project(entity), 201)


@app.route("/painting/projects", methods=["GET"])
def list_projects():
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    cid = request.args.get("customer_id")
    pred = (lambda e: e["customer_id"] == cid) if cid is not None else None
    items = list(store.projects.values())
    if pred is not None:
        items = [e for e in items if pred(e)]
    items = svc.sorted_by_creation(items)
    limit, offset = get_pagination()
    page, total = paginate(items, limit, offset)
    data = [serialize_project(e) for e in page]
    return array_response(data, limit, offset, total)


@app.route("/painting/projects/<pid>", methods=["GET"])
def get_project_route(pid):
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    return object_response(serialize_project(svc.get_project(pid)))


@app.route("/painting/projects/<pid>/finalize-estimate", methods=["POST"])
def finalize_estimate(pid):
    _, role = require_auth()
    require_role(role, {"Estimator"})
    project = svc.get_project(pid)
    if project["workflow_status"] != "DRAFT":
        raise err("ERR_PROJECT_NOT_DRAFT", "Finalize-estimate requires DRAFT.")
    planned = [s for s in svc.project_surfaces(pid) if s["status"] == "PLANNED"]
    if not planned:
        raise err("ERR_NO_SURFACES", "Finalize-estimate requires >= 1 PLANNED surface.")
    # Recompute every line item, then freeze the estimate over PLANNED surfaces.
    est_material = 0
    est_labor = 0
    for s in planned:
        li = svc.line_item_for_surface(s["id"])
        if li is not None:
            svc.recompute_line_item(li, s)
            est_material += li["material_cost_cents"]
            est_labor += li["labor_cost_cents"]
    project["estimate_material_cents"] = est_material
    project["estimate_labor_cents"] = est_labor
    project["estimate_total_cents"] = est_material + est_labor
    project["revised_total_cents"] = project["estimate_total_cents"]
    project["deposit_due_cents"] = calc.deposit_due(project["estimate_total_cents"], project["deposit_pct"])
    project["balance_due_cents"] = project["revised_total_cents"] - project["amount_paid_cents"]
    project["workflow_status"] = "ESTIMATED"
    svc.touch(project)
    return object_response(serialize_project(project))


@app.route("/painting/projects/<pid>/schedule", methods=["POST"])
def schedule_project(pid):
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    project = svc.get_project(pid)
    if project["workflow_status"] != "ESTIMATED":
        raise err("ERR_PROJECT_NOT_ESTIMATED", "Schedule requires ESTIMATED.")
    if project["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        raise err("ERR_DEPOSIT_NOT_PAID", "Schedule requires deposit paid.")
    # Every PLANNED surface must have an APPROVED color selection.
    for s in svc.project_surfaces(pid):
        if s["status"] != "PLANNED":
            continue
        approved = any(c["surface_id"] == s["id"] and c["status"] == "APPROVED"
                       for c in store.color_selections.values())
        if not approved:
            raise err("ERR_COLOR_NOT_APPROVED", "Every PLANNED surface needs an APPROVED color.")
    has_crew = any(a["project_id"] == pid and a["status"] == "SCHEDULED"
                   for a in store.crew_assignments.values())
    if not has_crew:
        raise err("ERR_NO_CREW_SCHEDULED", "Schedule requires >= 1 SCHEDULED crew assignment.")
    project["workflow_status"] = "SCHEDULED"
    svc.touch(project)
    return object_response(serialize_project(project))


@app.route("/painting/projects/<pid>/start-work", methods=["POST"])
def start_work(pid):
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    project = svc.get_project(pid)
    if project["workflow_status"] != "SCHEDULED":
        raise err("ERR_PROJECT_NOT_SCHEDULED", "Start-work requires SCHEDULED.")
    project["workflow_status"] = "IN_PROGRESS"
    svc.touch(project)
    return object_response(serialize_project(project))


@app.route("/painting/projects/<pid>/request-walkthrough", methods=["POST"])
def request_walkthrough(pid):
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    project = svc.get_project(pid)
    if project["workflow_status"] != "IN_PROGRESS":
        raise err("ERR_PROJECT_NOT_IN_PROGRESS", "Request-walkthrough requires IN_PROGRESS.")
    for a in store.crew_assignments.values():
        if a["project_id"] == pid and a["status"] not in ("DONE", "CANCELLED"):
            raise err("ERR_CREW_NOT_DONE", "Every crew assignment must be DONE or CANCELLED.")
    # All non-REMOVED surfaces -> EXECUTED; their line items executed -> true.
    for s in svc.project_surfaces(pid):
        if s["status"] != "REMOVED":
            s["status"] = "EXECUTED"
            svc.touch(s)
            li = svc.line_item_for_surface(s["id"])
            if li is not None:
                li["executed"] = True
                svc.touch(li)
    project["workflow_status"] = "WALKTHROUGH_PENDING"
    svc.touch(project)
    # Open a fresh PENDING walkthrough.
    wt = {
        "project_id": pid,
        "punch_list_count": 0,
        "status": "PENDING",
    }
    svc.add_common(wt)
    store.walkthroughs[wt["id"]] = wt
    return object_response(serialize_project(project))


@app.route("/painting/projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    project = svc.get_project(pid)
    if project["workflow_status"] not in ("DRAFT", "ESTIMATED", "SCHEDULED"):
        raise err("ERR_PROJECT_NOT_CANCELLABLE", "Cancel requires DRAFT/ESTIMATED/SCHEDULED.")
    # Cancel SCHEDULED/IN_PROGRESS crew assignments (release counters).
    for a in store.crew_assignments.values():
        if a["project_id"] == pid and a["status"] in ("SCHEDULED", "IN_PROGRESS"):
            a["status"] = "CANCELLED"
            svc.touch(a)
            cm = store.crew_members.get(a["crew_member_id"])
            if cm is not None:
                svc.recompute_crew_scheduled_days(cm)
                svc.touch(cm)
            if a.get("equipment_id"):
                eq = store.equipment.get(a["equipment_id"])
                if eq is not None:
                    svc.recompute_equipment_units_reserved(eq)
                    svc.touch(eq)
    # Refund CAPTURED payments; recompute amount_paid to 0.
    for p in store.payments.values():
        if p["project_id"] == pid and p["status"] == "CAPTURED":
            p["status"] = "REFUNDED"
    svc.recompute_amount_paid(project)
    svc.recompute_balance(project)
    project["workflow_status"] = "CANCELLED"
    svc.touch(project)
    return object_response(serialize_project(project))


# ===========================================================================
# Surface
# ===========================================================================
@app.route("/painting/surfaces", methods=["POST"])
def create_surface():
    _, role = require_auth()
    require_role(role, {"Estimator"})
    body = body_json()
    # Body FK existence (priority 3) before body well-formedness (priority 4).
    project_id = svc.need(body, "project_id")
    project = svc.get_project(project_id)
    paint_product_id = svc.need(body, "paint_product_id")
    product = svc.get_paint_product(paint_product_id)
    # Body validation.
    label = svc.as_str(svc.need(body, "label"), "label")
    surface_kind = svc.as_enum(svc.need(body, "surface_kind"), "surface_kind", svc.SURFACE_KINDS)
    area_sqft = svc.as_int(svc.need(body, "area_sqft"), "area_sqft")
    if area_sqft < 1:
        raise err("ERR_INVALID_REQUEST", "area_sqft must be >= 1.")
    coats = svc.as_int(svc.need(body, "coats"), "coats")
    if coats < 1 or coats > 4:
        raise err("ERR_INVALID_REQUEST", "coats must be 1..4.")
    prep_level = svc.as_enum(svc.need(body, "prep_level"), "prep_level", svc.PREP_LEVELS)
    # Product/surface compatibility (priority 7).
    svc.check_product_surface_compat(product, surface_kind, project["scope"])
    surface = {
        "project_id": project_id,
        "label": label,
        "surface_kind": surface_kind,
        "area_sqft": area_sqft,
        "coats": coats,
        "prep_level": prep_level,
        "paint_product_id": paint_product_id,
        "status": "PLANNED",
        "color_locked": False,
    }
    svc.add_common(surface)
    store.surfaces[surface["id"]] = surface
    # Spawn one line item.
    svc.build_line_item(project_id, surface)
    return object_response(svc.serialize(surface), 201)


@app.route("/painting/surfaces", methods=["GET"])
def list_surfaces():
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    project_id = request.args.get("project_id")
    paint_product_id = request.args.get("paint_product_id")
    status = request.args.get("status")

    def pred(e):
        if project_id is not None and e["project_id"] != project_id:
            return False
        if paint_product_id is not None and e["paint_product_id"] != paint_product_id:
            return False
        if status is not None and e["status"] != status:
            return False
        return True

    return list_response(store.surfaces.values(), pred)


@app.route("/painting/surfaces/<sid>", methods=["GET"])
def get_surface_route(sid):
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    return object_response(svc.serialize(svc.get_surface(sid)))


# ===========================================================================
# LineItem (read-only)
# ===========================================================================
@app.route("/painting/line-items", methods=["GET"])
def list_line_items():
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    project_id = request.args.get("project_id")
    surface_id = request.args.get("surface_id")

    def pred(e):
        if project_id is not None and e["project_id"] != project_id:
            return False
        if surface_id is not None and e["surface_id"] != surface_id:
            return False
        return True

    return list_response(store.line_items.values(), pred)


@app.route("/painting/line-items/<lid>", methods=["GET"])
def get_line_item_route(lid):
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    return object_response(svc.serialize(svc.get_line_item(lid)))


# ===========================================================================
# ColorSelection
# ===========================================================================
@app.route("/painting/color-selections", methods=["POST"])
def create_color_selection():
    _, role = require_auth()
    require_role(role, {"Estimator", "Customer"})
    body = body_json()
    surface_id = svc.need(body, "surface_id")
    surface = svc.get_surface(surface_id)
    color_code = svc.as_str(svc.need(body, "color_code"), "color_code")
    entity = {
        "project_id": surface["project_id"],
        "surface_id": surface_id,
        "color_code": color_code,
        "status": "PROPOSED",
    }
    svc.add_common(entity)
    store.color_selections[entity["id"]] = entity
    return object_response(svc.serialize(entity), 201)


@app.route("/painting/color-selections", methods=["GET"])
def list_color_selections():
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    project_id = request.args.get("project_id")
    surface_id = request.args.get("surface_id")

    def pred(e):
        if project_id is not None and e["project_id"] != project_id:
            return False
        if surface_id is not None and e["surface_id"] != surface_id:
            return False
        return True

    return list_response(store.color_selections.values(), pred)


@app.route("/painting/color-selections/<cid>", methods=["GET"])
def get_color_selection_route(cid):
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    return object_response(svc.serialize(svc.get_color_selection(cid)))


@app.route("/painting/color-selections/<cid>/approve", methods=["POST"])
def approve_color_selection(cid):
    _, role = require_auth()
    require_role(role, {"Customer"})
    cs = svc.get_color_selection(cid)
    if cs["status"] != "PROPOSED":
        raise err("ERR_COLOR_NOT_PROPOSED", "Approve requires PROPOSED.")
    surface = store.surfaces.get(cs["surface_id"])
    if surface is None or surface["status"] != "PLANNED":
        raise err("ERR_SURFACE_NOT_PLANNED", "Parent surface must be PLANNED.")
    cs["status"] = "APPROVED"
    svc.touch(cs)
    surface["color_locked"] = True
    svc.touch(surface)
    return object_response(svc.serialize(cs))


@app.route("/painting/color-selections/<cid>/reject", methods=["POST"])
def reject_color_selection(cid):
    _, role = require_auth()
    require_role(role, {"Customer"})
    cs = svc.get_color_selection(cid)
    if cs["status"] != "PROPOSED":
        raise err("ERR_COLOR_NOT_PROPOSED", "Reject requires PROPOSED.")
    cs["status"] = "REJECTED"
    svc.touch(cs)
    return object_response(svc.serialize(cs))


# ===========================================================================
# ChangeOrder
# ===========================================================================
@app.route("/painting/change-orders", methods=["POST"])
def create_change_order():
    _, role = require_auth()
    require_role(role, {"Estimator"})
    body = body_json()
    # Existence: project_id (priority 3); target_surface_id resolved if present.
    project_id = svc.need(body, "project_id")
    project = svc.get_project(project_id)
    target_surface_id = body.get("target_surface_id")
    if target_surface_id is not None:
        svc.get_surface(target_surface_id)
    new_paint_product_id = body.get("new_paint_product_id")
    if new_paint_product_id is not None:
        svc.get_paint_product(new_paint_product_id)
    # Body well-formedness (priority 4).
    expected_version = svc.as_int(svc.need(body, "expected_project_version"), "expected_project_version")
    reason = svc.as_str(svc.need(body, "reason"), "reason")
    action = svc.as_enum(svc.need(body, "action"), "action", svc.CHANGE_ORDER_ACTIONS)
    new_surface_kind = body.get("new_surface_kind")
    if new_surface_kind is not None:
        svc.as_enum(new_surface_kind, "new_surface_kind", svc.SURFACE_KINDS)
    new_area_sqft = body.get("new_area_sqft")
    if new_area_sqft is not None:
        new_area_sqft = svc.as_int(new_area_sqft, "new_area_sqft")
        if new_area_sqft < 1:
            raise err("ERR_INVALID_REQUEST", "new_area_sqft must be >= 1.")
    new_coats = body.get("new_coats")
    if new_coats is not None:
        new_coats = svc.as_int(new_coats, "new_coats")
        if new_coats < 1 or new_coats > 4:
            raise err("ERR_INVALID_REQUEST", "new_coats must be 1..4.")
    new_prep_level = body.get("new_prep_level")
    if new_prep_level is not None:
        svc.as_enum(new_prep_level, "new_prep_level", svc.PREP_LEVELS)
    # OCC (priority 6).
    if expected_version != project["version"]:
        raise err("ERR_STALE_PROJECT_VERSION", "expected_project_version is stale.")
    entity = {
        "project_id": project_id,
        "reason": reason,
        "action": action,
        "target_surface_id": target_surface_id,
        "new_label": body.get("new_label"),
        "new_surface_kind": new_surface_kind,
        "new_area_sqft": new_area_sqft,
        "new_coats": new_coats,
        "new_prep_level": new_prep_level,
        "new_paint_product_id": new_paint_product_id,
        "status": "DRAFT",
        "delta_total_cents": 0,
        "applied_project_version": None,
    }
    svc.add_common(entity)
    store.change_orders[entity["id"]] = entity
    return object_response(svc.serialize(entity), 201)


def _change_order_costs_for_new(co):
    """Compute material+labor for the order's new_* fields (ADD/REVISE)."""
    product = store.paint_products[co["new_paint_product_id"]]
    gallons, material = calc.material_estimate(
        co["new_area_sqft"], co["new_coats"],
        product["coverage_sqft_per_gallon_per_coat"], product["price_per_gallon_cents"])
    _, labor = calc.labor_estimate(co["new_area_sqft"], co["new_coats"], co["new_prep_level"])
    return material + labor


def _compute_delta(co):
    action = co["action"]
    if action == "ADD_SURFACE":
        return _change_order_costs_for_new(co)
    if action == "REMOVE_SURFACE":
        target = store.surfaces[co["target_surface_id"]]
        li = svc.line_item_for_surface(target["id"])
        return -(li["material_cost_cents"] + li["labor_cost_cents"])
    # REVISE_SURFACE
    target = store.surfaces[co["target_surface_id"]]
    li = svc.line_item_for_surface(target["id"])
    current = li["material_cost_cents"] + li["labor_cost_cents"]
    revised = _change_order_costs_for_new(co)
    return revised - current


@app.route("/painting/change-orders", methods=["GET"])
def list_change_orders():
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    project_id = request.args.get("project_id")
    target_surface_id = request.args.get("target_surface_id")
    new_paint_product_id = request.args.get("new_paint_product_id")
    status = request.args.get("status")

    def pred(e):
        if project_id is not None and e["project_id"] != project_id:
            return False
        if target_surface_id is not None and e.get("target_surface_id") != target_surface_id:
            return False
        if new_paint_product_id is not None and e.get("new_paint_product_id") != new_paint_product_id:
            return False
        if status is not None and e["status"] != status:
            return False
        return True

    return list_response(store.change_orders.values(), pred)


@app.route("/painting/change-orders/<coid>", methods=["GET"])
def get_change_order_route(coid):
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    return object_response(svc.serialize(svc.get_change_order(coid)))


@app.route("/painting/change-orders/<coid>/submit", methods=["POST"])
def submit_change_order(coid):
    _, role = require_auth()
    require_role(role, {"Estimator"})
    co = svc.get_change_order(coid)
    if co["status"] != "DRAFT":
        raise err("ERR_CHANGE_ORDER_NOT_DRAFT", "Submit requires DRAFT.")
    project = store.projects[co["project_id"]]
    if project["workflow_status"] not in ("ESTIMATED", "SCHEDULED", "IN_PROGRESS"):
        raise err("ERR_PROJECT_NOT_CHANGEABLE", "Project not changeable.")
    co["delta_total_cents"] = _compute_delta(co)
    co["status"] = "SUBMITTED"
    svc.touch(co)
    return object_response(svc.serialize(co))


@app.route("/painting/change-orders/<coid>/approve", methods=["POST"])
def approve_change_order(coid):
    _, role = require_auth()
    require_role(role, {"Customer"})
    co = svc.get_change_order(coid)
    if co["status"] != "SUBMITTED":
        raise err("ERR_CHANGE_ORDER_NOT_SUBMITTED", "Approve requires SUBMITTED.")
    project = store.projects[co["project_id"]]
    if project["workflow_status"] not in ("ESTIMATED", "SCHEDULED", "IN_PROGRESS"):
        raise err("ERR_PROJECT_NOT_CHANGEABLE", "Project not changeable.")
    action = co["action"]
    if action == "ADD_SURFACE":
        surface = {
            "project_id": co["project_id"],
            "label": co["new_label"],
            "surface_kind": co["new_surface_kind"],
            "area_sqft": co["new_area_sqft"],
            "coats": co["new_coats"],
            "prep_level": co["new_prep_level"],
            "paint_product_id": co["new_paint_product_id"],
            "status": "PLANNED",
            "color_locked": False,
        }
        svc.add_common(surface)
        store.surfaces[surface["id"]] = surface
        svc.build_line_item(co["project_id"], surface)
    elif action == "REMOVE_SURFACE":
        target = store.surfaces[co["target_surface_id"]]
        target["status"] = "REMOVED"
        svc.touch(target)
    else:  # REVISE_SURFACE
        target = store.surfaces[co["target_surface_id"]]
        if co["new_label"] is not None:
            target["label"] = co["new_label"]
        if co["new_surface_kind"] is not None:
            target["surface_kind"] = co["new_surface_kind"]
        if co["new_area_sqft"] is not None:
            target["area_sqft"] = co["new_area_sqft"]
        if co["new_coats"] is not None:
            target["coats"] = co["new_coats"]
        if co["new_prep_level"] is not None:
            target["prep_level"] = co["new_prep_level"]
        if co["new_paint_product_id"] is not None:
            target["paint_product_id"] = co["new_paint_product_id"]
        svc.touch(target)
        li = svc.line_item_for_surface(target["id"])
        if li is not None:
            svc.recompute_line_item(li, target)
    # Re-derive live revised total and balance (frozen estimate/deposit untouched).
    svc.recompute_revised_total(project)
    svc.recompute_balance(project)
    co["applied_project_version"] = project["version"]
    co["status"] = "APPROVED"
    svc.touch(co)
    svc.touch(project)  # bumps Project.version by one after the cascade
    return object_response(svc.serialize(co))


@app.route("/painting/change-orders/<coid>/reject", methods=["POST"])
def reject_change_order(coid):
    _, role = require_auth()
    require_role(role, {"Customer"})
    co = svc.get_change_order(coid)
    if co["status"] != "SUBMITTED":
        raise err("ERR_CHANGE_ORDER_NOT_SUBMITTED", "Reject requires SUBMITTED.")
    co["status"] = "REJECTED"
    svc.touch(co)
    return object_response(svc.serialize(co))


@app.route("/painting/change-orders/<coid>/revise", methods=["POST"])
def revise_change_order(coid):
    _, role = require_auth()
    require_role(role, {"Estimator"})
    co = svc.get_change_order(coid)
    if co["status"] != "REJECTED":
        raise err("ERR_CHANGE_ORDER_NOT_REJECTED", "Revise requires REJECTED.")
    body = body_json()
    # Resolve any body FKs that are present (existence priority 3).
    if body.get("target_surface_id") is not None:
        svc.get_surface(body["target_surface_id"])
    if body.get("new_paint_product_id") is not None:
        svc.get_paint_product(body["new_paint_product_id"])
    # Validate editable fields if supplied.
    if "action" in body and body["action"] is not None:
        co["action"] = svc.as_enum(body["action"], "action", svc.CHANGE_ORDER_ACTIONS)
    if "reason" in body and body["reason"] is not None:
        co["reason"] = svc.as_str(body["reason"], "reason")
    if "target_surface_id" in body:
        co["target_surface_id"] = body["target_surface_id"]
    if "new_label" in body:
        co["new_label"] = body["new_label"]
    if "new_surface_kind" in body:
        if body["new_surface_kind"] is not None:
            svc.as_enum(body["new_surface_kind"], "new_surface_kind", svc.SURFACE_KINDS)
        co["new_surface_kind"] = body["new_surface_kind"]
    if "new_area_sqft" in body:
        if body["new_area_sqft"] is not None:
            v = svc.as_int(body["new_area_sqft"], "new_area_sqft")
            if v < 1:
                raise err("ERR_INVALID_REQUEST", "new_area_sqft must be >= 1.")
            co["new_area_sqft"] = v
        else:
            co["new_area_sqft"] = None
    if "new_coats" in body:
        if body["new_coats"] is not None:
            v = svc.as_int(body["new_coats"], "new_coats")
            if v < 1 or v > 4:
                raise err("ERR_INVALID_REQUEST", "new_coats must be 1..4.")
            co["new_coats"] = v
        else:
            co["new_coats"] = None
    if "new_prep_level" in body:
        if body["new_prep_level"] is not None:
            svc.as_enum(body["new_prep_level"], "new_prep_level", svc.PREP_LEVELS)
        co["new_prep_level"] = body["new_prep_level"]
    if "new_paint_product_id" in body:
        co["new_paint_product_id"] = body["new_paint_product_id"]
    co["delta_total_cents"] = 0
    co["status"] = "DRAFT"
    svc.touch(co)
    return object_response(svc.serialize(co))


# ===========================================================================
# CrewAssignment
# ===========================================================================
def _overlaps(days_a, days_b):
    return not days_a.isdisjoint(days_b)


@app.route("/painting/crew-assignments", methods=["POST"])
def create_crew_assignment():
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    body = body_json()
    # Existence (priority 3): project_id, crew_member_id, equipment_id.
    project_id = svc.need(body, "project_id")
    project = svc.get_project(project_id)
    crew_member_id = svc.need(body, "crew_member_id")
    crew_member = svc.get_crew_member(crew_member_id)
    equipment_id = body.get("equipment_id")
    equipment = None
    if equipment_id is not None:
        equipment = svc.get_equipment(equipment_id)
    # Body well-formedness (priority 4).
    start_date = svc.as_str(svc.need(body, "start_date"), "start_date")
    end_date = svc.as_str(svc.need(body, "end_date"), "end_date")
    try:
        sd = svc.parse_date(start_date)
        ed = svc.parse_date(end_date)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "start_date/end_date must be ISO dates 'YYYY-MM-DD'.")
    if ed < sd:
        raise err("ERR_INVALID_REQUEST", "end_date must be >= start_date.")
    requires_weather = False
    if "requires_exterior_weather" in body and body["requires_exterior_weather"] is not None:
        requires_weather = svc.as_bool(body["requires_exterior_weather"], "requires_exterior_weather")
    day_count = (ed - sd).days + 1
    new_days = set(range(sd.toordinal(), ed.toordinal() + 1))

    # Domain checks in PRD order: skill (8), double-booking (9), equipment (10), weather (11).
    # (8) Crew skill adequacy vs heaviest PLANNED prep level on the project.
    planned_preps = [s["prep_level"] for s in svc.project_surfaces(project_id) if s["status"] == "PLANNED"]
    if planned_preps:
        heaviest = max(planned_preps, key=lambda p: calc.PREP_HEAVINESS[p])
        if calc.SKILL_RANK[crew_member["skill_level"]] < calc.PREP_MIN_SKILL[heaviest]:
            raise err("ERR_CREW_SKILL_INSUFFICIENT", "Crew skill below required level.")

    # (9) Crew double-booking: overlap OR back-to-back (no >=1-day buffer gap).
    for a in store.crew_assignments.values():
        if a["crew_member_id"] != crew_member_id or a["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        a_sd = svc.parse_date(a["start_date"]).toordinal()
        a_ed = svc.parse_date(a["end_date"]).toordinal()
        a_days = set(range(a_sd, a_ed + 1))
        if _overlaps(new_days, a_days):
            raise err("ERR_CREW_DOUBLE_BOOKED", "Assignment overlaps another for this crew member.")
        # Require a >=1-day buffer gap: the gap between intervals must be >= 1 clear day.
        new_min, new_max = min(new_days), max(new_days)
        if new_min > a_ed:
            gap_days = new_min - a_ed - 1
        elif a_sd > new_max:
            gap_days = a_sd - new_max - 1
        else:
            gap_days = 0
        if gap_days < 1:
            raise err("ERR_CREW_DOUBLE_BOOKED", "Assignment is back-to-back (no buffer day).")

    # (10) Equipment capacity: peak overlap including the new assignment must not exceed total_units.
    if equipment is not None:
        existing = [a for a in store.crew_assignments.values()
                    if a.get("equipment_id") == equipment_id and a["status"] in ("SCHEDULED", "IN_PROGRESS")]
        day_counts = {}
        for a in existing:
            a_sd = svc.parse_date(a["start_date"]).toordinal()
            a_ed = svc.parse_date(a["end_date"]).toordinal()
            for d in range(a_sd, a_ed + 1):
                day_counts[d] = day_counts.get(d, 0) + 1
        for d in new_days:
            day_counts[d] = day_counts.get(d, 0) + 1
        peak = max(day_counts.values()) if day_counts else 0
        if peak > equipment["total_units"]:
            raise err("ERR_EQUIPMENT_OVERBOOKED", "Equipment peak overlap exceeds total_units.")

    # (11) Exterior weather: every date in window must have an exterior_suitable window.
    if requires_weather:
        for d in range(sd.toordinal(), ed.toordinal() + 1):
            from datetime import date as _date
            iso = _date.fromordinal(d).strftime("%Y-%m-%d")
            suitable = any(w["window_date"] == iso and w["exterior_suitable"]
                           for w in store.weather_windows.values())
            if not suitable:
                raise err("ERR_WEATHER_UNSUITABLE", "A date in the window is not exterior-suitable.")

    entity = {
        "project_id": project_id,
        "crew_member_id": crew_member_id,
        "equipment_id": equipment_id,
        "start_date": start_date,
        "end_date": end_date,
        "requires_exterior_weather": requires_weather,
        "status": "SCHEDULED",
        "day_count": day_count,
    }
    svc.add_common(entity)
    store.crew_assignments[entity["id"]] = entity
    # Raise utilization counters.
    svc.recompute_crew_scheduled_days(crew_member)
    svc.touch(crew_member)
    if equipment is not None:
        svc.recompute_equipment_units_reserved(equipment)
        svc.touch(equipment)
    return object_response(svc.serialize(entity), 201)


@app.route("/painting/crew-assignments", methods=["GET"])
def list_crew_assignments():
    _, role = require_auth()
    require_role(role, {"ProjectManager", "Estimator", "CrewMember"})
    project_id = request.args.get("project_id")
    crew_member_id = request.args.get("crew_member_id")
    equipment_id = request.args.get("equipment_id")
    status = request.args.get("status")

    def pred(e):
        if project_id is not None and e["project_id"] != project_id:
            return False
        if crew_member_id is not None and e["crew_member_id"] != crew_member_id:
            return False
        if equipment_id is not None and e.get("equipment_id") != equipment_id:
            return False
        if status is not None and e["status"] != status:
            return False
        return True

    return list_response(store.crew_assignments.values(), pred)


@app.route("/painting/crew-assignments/<aid>", methods=["GET"])
def get_crew_assignment_route(aid):
    _, role = require_auth()
    require_role(role, {"ProjectManager", "Estimator", "CrewMember"})
    return object_response(svc.serialize(svc.get_assignment(aid)))


@app.route("/painting/crew-assignments/<aid>/begin", methods=["POST"])
def begin_assignment(aid):
    _, role = require_auth()
    require_role(role, {"CrewMember"})
    a = svc.get_assignment(aid)
    if a["status"] != "SCHEDULED":
        raise err("ERR_ASSIGNMENT_NOT_SCHEDULED", "Begin requires SCHEDULED.")
    project = store.projects[a["project_id"]]
    if project["workflow_status"] != "IN_PROGRESS":
        raise err("ERR_PROJECT_NOT_IN_PROGRESS", "Parent project must be IN_PROGRESS.")
    a["status"] = "IN_PROGRESS"
    svc.touch(a)
    return object_response(svc.serialize(a))


@app.route("/painting/crew-assignments/<aid>/complete", methods=["POST"])
def complete_assignment(aid):
    _, role = require_auth()
    require_role(role, {"CrewMember"})
    a = svc.get_assignment(aid)
    if a["status"] != "IN_PROGRESS":
        raise err("ERR_ASSIGNMENT_NOT_IN_PROGRESS", "Complete requires IN_PROGRESS.")
    a["status"] = "DONE"
    svc.touch(a)
    cm = store.crew_members.get(a["crew_member_id"])
    if cm is not None:
        svc.recompute_crew_scheduled_days(cm)
        svc.touch(cm)
    if a.get("equipment_id"):
        eq = store.equipment.get(a["equipment_id"])
        if eq is not None:
            svc.recompute_equipment_units_reserved(eq)
            svc.touch(eq)
    return object_response(svc.serialize(a))


@app.route("/painting/crew-assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment(aid):
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    a = svc.get_assignment(aid)
    if a["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise err("ERR_ASSIGNMENT_NOT_CANCELLABLE", "Cancel requires SCHEDULED or IN_PROGRESS.")
    a["status"] = "CANCELLED"
    svc.touch(a)
    cm = store.crew_members.get(a["crew_member_id"])
    if cm is not None:
        svc.recompute_crew_scheduled_days(cm)
        svc.touch(cm)
    if a.get("equipment_id"):
        eq = store.equipment.get(a["equipment_id"])
        if eq is not None:
            svc.recompute_equipment_units_reserved(eq)
            svc.touch(eq)
    return object_response(svc.serialize(a))


# ===========================================================================
# Payment
# ===========================================================================
def _complete_project(project):
    """Compute FINAL total and warranty expiry; advance to COMPLETED."""
    total = 0
    for s in svc.project_surfaces(project["id"]):
        if s["status"] == "EXECUTED":
            li = svc.line_item_for_surface(s["id"])
            if li is not None:
                total += li["material_cost_cents"] + li["labor_cost_cents"]
    project["final_total_cents"] = total
    completion = store.clock.now()
    expiry = svc.add_months(completion, project["warranty_months"])
    project["warranty_expires_at"] = svc.format_dt(expiry)
    project["_warranty_expires_dt"] = expiry  # internal: exact instant for boundary check
    project["workflow_status"] = "COMPLETED"
    svc.touch(project)


@app.route("/painting/payments", methods=["POST"])
def create_payment():
    _, role = require_auth()
    require_role(role, {"Customer"})
    body = body_json()
    project_id = svc.need(body, "project_id")
    project = svc.get_project(project_id)
    kind = svc.as_enum(svc.need(body, "kind"), "kind", svc.PAYMENT_KINDS)
    amount = svc.as_int(svc.need(body, "amount_cents"), "amount_cents")
    if amount < 1:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be >= 1.")
    if kind == "DEPOSIT":
        # state checks
        if project["payment_status"] != "UNPAID":
            raise err("ERR_DEPOSIT_ALREADY_PAID", "Deposit already paid.")
        if project["workflow_status"] != "ESTIMATED":
            raise err("ERR_PROJECT_NOT_ESTIMATED", "Deposit requires ESTIMATED.")
        if amount != project["deposit_due_cents"]:
            raise err("ERR_DEPOSIT_AMOUNT_MISMATCH", "Deposit amount must equal deposit_due_cents.")
    else:  # FINAL
        if project["payment_status"] != "DEPOSIT_PAID":
            raise err("ERR_FINAL_BEFORE_DEPOSIT", "Final payment requires DEPOSIT_PAID.")
        if project["workflow_status"] != "WALKTHROUGH_PENDING":
            raise err("ERR_PROJECT_NOT_IN_WALKTHROUGH", "Final payment requires WALKTHROUGH_PENDING.")
        if amount != project["balance_due_cents"]:
            raise err("ERR_FINAL_AMOUNT_MISMATCH", "Final amount must equal balance_due_cents.")
    payment = {
        "project_id": project_id,
        "kind": kind,
        "amount_cents": amount,
        "status": "CAPTURED",
    }
    svc.add_common(payment, with_version=False)  # append-only ledger: id + created_at only
    store.payments[payment["id"]] = payment
    svc.recompute_amount_paid(project)
    svc.recompute_balance(project)
    if kind == "DEPOSIT":
        project["payment_status"] = "DEPOSIT_PAID"
    else:
        project["payment_status"] = "PAID_IN_FULL"
    svc.touch(project)
    # FINAL payment may tip a passed-walkthrough project into COMPLETED.
    if kind == "FINAL":
        latest = _latest_walkthrough(project_id)
        if latest is not None and latest["status"] == "PASSED" and project["workflow_status"] == "WALKTHROUGH_PENDING":
            _complete_project(project)
    return object_response(svc.serialize(payment), 201)


@app.route("/painting/payments", methods=["GET"])
def list_payments():
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    project_id = request.args.get("project_id")
    kind = request.args.get("kind")

    def pred(e):
        if project_id is not None and e["project_id"] != project_id:
            return False
        if kind is not None and e["kind"] != kind:
            return False
        return True

    return list_response(store.payments.values(), pred)


@app.route("/painting/payments/<pid>", methods=["GET"])
def get_payment_route(pid):
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    return object_response(svc.serialize(svc.get_payment(pid)))


# ===========================================================================
# Walkthrough
# ===========================================================================
def _latest_walkthrough(project_id):
    items = [w for w in store.walkthroughs.values() if w["project_id"] == project_id]
    if not items:
        return None
    return max(items, key=lambda w: w["_seq"])


@app.route("/painting/walkthroughs", methods=["GET"])
def list_walkthroughs():
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    project_id = request.args.get("project_id")
    status = request.args.get("status")

    def pred(e):
        if project_id is not None and e["project_id"] != project_id:
            return False
        if status is not None and e["status"] != status:
            return False
        return True

    return list_response(store.walkthroughs.values(), pred)


@app.route("/painting/walkthroughs/<wid>", methods=["GET"])
def get_walkthrough_route(wid):
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    return object_response(svc.serialize(svc.get_walkthrough(wid)))


@app.route("/painting/walkthroughs/<wid>/pass", methods=["POST"])
def pass_walkthrough(wid):
    _, role = require_auth()
    require_role(role, {"Customer"})
    wt = svc.get_walkthrough(wid)
    if wt["status"] != "PENDING":
        raise err("ERR_WALKTHROUGH_NOT_PENDING", "Pass requires PENDING.")
    if wt["punch_list_count"] != 0:
        raise err("ERR_PUNCH_LIST_OPEN", "Pass requires punch_list_count == 0.")
    project = store.projects[wt["project_id"]]
    if project["workflow_status"] != "WALKTHROUGH_PENDING":
        raise err("ERR_PROJECT_NOT_IN_WALKTHROUGH", "Project must be WALKTHROUGH_PENDING.")
    wt["status"] = "PASSED"
    svc.touch(wt)
    # Cascade to COMPLETED only when paid in full; else stay awaiting final payment.
    if project["payment_status"] == "PAID_IN_FULL":
        _complete_project(project)
    return object_response(svc.serialize(wt))


@app.route("/painting/walkthroughs/<wid>/fail", methods=["POST"])
def fail_walkthrough(wid):
    _, role = require_auth()
    require_role(role, {"Customer"})
    wt = svc.get_walkthrough(wid)
    if wt["status"] != "PENDING":
        raise err("ERR_WALKTHROUGH_NOT_PENDING", "Fail requires PENDING.")
    wt["status"] = "FAILED"
    svc.touch(wt)
    return object_response(svc.serialize(wt))


@app.route("/painting/walkthroughs/<wid>/reopen", methods=["POST"])
def reopen_walkthrough(wid):
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    wt = svc.get_walkthrough(wid)
    if wt["status"] != "FAILED":
        raise err("ERR_WALKTHROUGH_NOT_FAILED", "Reopen requires FAILED.")
    body = body_json()
    punch = 0
    if "punch_list_count" in body and body["punch_list_count"] is not None:
        punch = svc.as_int(body["punch_list_count"], "punch_list_count")
        if punch < 0:
            raise err("ERR_INVALID_REQUEST", "punch_list_count must be >= 0.")
    wt["punch_list_count"] = punch
    wt["status"] = "PENDING"
    svc.touch(wt)
    return object_response(svc.serialize(wt))


# ===========================================================================
# WarrantyClaim
# ===========================================================================
@app.route("/painting/warranty-claims", methods=["POST"])
def create_warranty_claim():
    _, role = require_auth()
    require_role(role, {"Customer"})
    body = body_json()
    project_id = svc.need(body, "project_id")
    project = svc.get_project(project_id)
    surface_id = svc.need(body, "surface_id")
    surface = svc.get_surface(surface_id)
    description = svc.as_str(svc.need(body, "description"), "description")
    filed_at_raw = svc.as_str(svc.need(body, "filed_at"), "filed_at")
    try:
        filed_at_dt = svc.parse_iso8601(filed_at_raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "filed_at must be an ISO 8601 UTC timestamp.")
    # State: project must be COMPLETED (checked before window — priority 13).
    if project["workflow_status"] != "COMPLETED":
        raise err("ERR_PROJECT_NOT_COMPLETED", "Warranty claim requires a COMPLETED project.")
    # Window: filed_at <= warranty_expires_at (inclusive — priority 14).
    expiry_dt = project.get("_warranty_expires_dt")
    if expiry_dt is not None and filed_at_dt > expiry_dt:
        raise err("ERR_WARRANTY_EXPIRED", "filed_at is after warranty_expires_at.")
    # Provisional payout from the target surface's line-item labor cost.
    li = svc.line_item_for_surface(surface_id)
    provisional = calc.provisional_payout(li["labor_cost_cents"]) if li is not None else 0
    entity = {
        "project_id": project_id,
        "surface_id": surface_id,
        "description": description,
        "filed_at": filed_at_raw,
        "status": "FILED",
        "provisional_payout_cents": provisional,
        "final_payout_cents": None,
        "logged_touchup_hours": None,
    }
    svc.add_common(entity)
    store.warranty_claims[entity["id"]] = entity
    return object_response(svc.serialize(entity), 201)


@app.route("/painting/warranty-claims", methods=["GET"])
def list_warranty_claims():
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    project_id = request.args.get("project_id")
    surface_id = request.args.get("surface_id")
    status = request.args.get("status")

    def pred(e):
        if project_id is not None and e["project_id"] != project_id:
            return False
        if surface_id is not None and e["surface_id"] != surface_id:
            return False
        if status is not None and e["status"] != status:
            return False
        return True

    return list_response(store.warranty_claims.values(), pred)


@app.route("/painting/warranty-claims/<cid>", methods=["GET"])
def get_warranty_claim_route(cid):
    _, role = require_auth()
    require_role(role, {"Estimator", "ProjectManager", "Customer"})
    return object_response(svc.serialize(svc.get_warranty_claim(cid)))


@app.route("/painting/warranty-claims/<cid>/approve", methods=["POST"])
def approve_warranty_claim(cid):
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    c = svc.get_warranty_claim(cid)
    if c["status"] != "FILED":
        raise err("ERR_CLAIM_NOT_FILED", "Approve requires FILED.")
    c["status"] = "APPROVED"
    svc.touch(c)
    return object_response(svc.serialize(c))


@app.route("/painting/warranty-claims/<cid>/deny", methods=["POST"])
def deny_warranty_claim(cid):
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    c = svc.get_warranty_claim(cid)
    if c["status"] != "FILED":
        raise err("ERR_CLAIM_NOT_FILED", "Deny requires FILED.")
    c["status"] = "DENIED"
    svc.touch(c)
    return object_response(svc.serialize(c))


@app.route("/painting/warranty-claims/<cid>/resolve", methods=["POST"])
def resolve_warranty_claim(cid):
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    c = svc.get_warranty_claim(cid)
    if c["status"] != "APPROVED":
        raise err("ERR_CLAIM_NOT_APPROVED", "Resolve requires APPROVED.")
    body = body_json()
    hours = body.get("logged_touchup_hours")
    if hours is None or isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours < 0:
        raise err("ERR_TOUCHUP_HOURS_REQUIRED", "logged_touchup_hours must be supplied and >= 0.")
    c["logged_touchup_hours"] = hours
    c["final_payout_cents"] = calc.final_payout(hours)
    c["status"] = "RESOLVED"
    svc.touch(c)
    return object_response(svc.serialize(c))


# ===========================================================================
# Test-driving clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_auth()
    require_role(role, {"ProjectManager"})
    body = body_json()
    to_iso = svc.as_str(svc.need(body, "to_iso8601"), "to_iso8601")
    try:
        dt = svc.parse_iso8601(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 timestamp.")
    store.clock.set(dt)
    return object_response({})


# ===========================================================================
# Health
# ===========================================================================
@app.route("/", methods=["GET"])
def health():
    return object_response({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
