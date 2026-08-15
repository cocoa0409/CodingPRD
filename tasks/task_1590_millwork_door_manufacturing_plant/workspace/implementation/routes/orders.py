"""MillworkOrder endpoints (PRD §3.2/§3.3)."""

from flask import Blueprint, request

import db
from errors import err
from middleware import (get_context, require_role, raw_body, validate_fields,
                        req_string, req_enum, require_existence)
from response import success, list_response, parse_pagination
from services import pricing, cascade

bp = Blueprint("orders", __name__)

SPECIES = ("OAK", "MAPLE", "CHERRY", "WALNUT", "PAINT_GRADE")
FINISH_SYSTEMS = ("CLEAR_COAT", "STAIN", "PAINT")
SHEENS = ("MATTE", "SATIN", "SEMI_GLOSS", "HIGH_GLOSS")
PREP_MODES = ("TEMPLATE_PREP", "INSTALLER_PREP")
FIRE_RATINGS = ("NONE", "MIN_20", "MIN_45", "MIN_90")
ORDER_STATUSES = ("DRAFT", "CONFIGURED", "SUBMITTED", "APPROVED", "IN_PRODUCTION",
                  "FINISHING", "READY_TO_SHIP", "SHIPPED", "CLOSED", "CANCELLED")

CONFIG_FIELDS = ("species", "profile_code", "finish_system", "sheen_target",
                 "hardware_prep_mode", "hardware_template_id", "fire_rating_required")

TARGET_ACTORS = {
    "CONFIGURED": ("Estimator",),
    "IN_PRODUCTION": ("ProductionLead",),
    "FINISHING": ("ProductionLead",),
    "READY_TO_SHIP": ("ProductionLead",),
    "SHIPPED": ("ShippingCoordinator",),
    "CLOSED": ("PlantManager",),
    "CANCELLED": ("Estimator",),
}
ALL_STATUS_ACTORS = ("Estimator", "ProductionLead", "ShippingCoordinator", "PlantManager")

OPEN_PUNCH_STATES = ("REPORTED", "TRIAGED", "REWORK_AUTHORIZED", "IN_REWORK", "RESOLVED")


def serialize(o):
    return {
        "id": o["id"],
        "project_id": o["project_id"],
        "order_code": o["order_code"],
        "species": o["species"],
        "profile_code": o["profile_code"],
        "finish_system": o["finish_system"],
        "sheen_target": o["sheen_target"],
        "hardware_prep_mode": o["hardware_prep_mode"],
        "hardware_template_id": o["hardware_template_id"],
        "fire_rating_required": o["fire_rating_required"],
        "config_locked": o["config_locked"],
        "budget_quote_cents": o["budget_quote_cents"],
        "merchandise_total_cents": o["merchandise_total_cents"],
        "freight_fee_cents": o["freight_fee_cents"],
        "contract_price_cents": o["contract_price_cents"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def _non_cancelled_openings(order_id):
    return [o for o in db.openings.values()
            if o["order_id"] == order_id and o["fab_status"] != "CANCELLED"]


@bp.post("/orders")
def create_order():
    _, role = get_context()
    require_role(role, "Estimator")
    body = raw_body()
    # Rung 3: body FK existence in declared input order.
    if body.get("project_id") is not None:
        project = require_existence(db.projects, body["project_id"], "ERR_PROJECT_NOT_FOUND", "Project")
    else:
        project = None
    if body.get("hardware_template_id") is not None:
        require_existence(db.hardware_templates, body["hardware_template_id"],
                          "ERR_TEMPLATE_NOT_FOUND", "HardwareTemplate")
    # Rung 4: payload well-formedness.
    validate_fields(body,
                    required=("project_id", "order_code", "species", "profile_code",
                              "finish_system", "sheen_target", "hardware_prep_mode",
                              "fire_rating_required"),
                    optional=("hardware_template_id",))
    order_code = req_string(body, "order_code")
    species = req_enum(body, "species", SPECIES)
    profile_code = req_string(body, "profile_code")
    finish_system = req_enum(body, "finish_system", FINISH_SYSTEMS)
    sheen_target = req_enum(body, "sheen_target", SHEENS)
    prep_mode = req_enum(body, "hardware_prep_mode", PREP_MODES)
    fire_rating = req_enum(body, "fire_rating_required", FIRE_RATINGS)
    # Rung 6: project must be OPEN.
    if project["status"] != "OPEN":
        raise err("ERR_PROJECT_NOT_OPEN", "Order creation requires Project.status == OPEN")
    # Rung 8: order_code unique within the project.
    for existing in db.orders.values():
        if existing["project_id"] == project["id"] and existing["order_code"] == order_code:
            raise err("ERR_ORDER_CODE_NOT_UNIQUE", "order_code already used within the project")
    rec = db.new_record()
    rec.update({
        "project_id": project["id"],
        "order_code": order_code,
        "species": species,
        "profile_code": profile_code,
        "finish_system": finish_system,
        "sheen_target": sheen_target,
        "hardware_prep_mode": prep_mode,
        "hardware_template_id": body.get("hardware_template_id"),
        "fire_rating_required": fire_rating,
        "config_locked": False,
        "budget_quote_cents": None,
        "merchandise_total_cents": None,
        "freight_fee_cents": None,
        "contract_price_cents": None,
        "status": "DRAFT",
    })
    db.orders[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/orders")
def list_orders():
    get_context()
    limit, offset = parse_pagination(request.args)
    project_id = request.args.get("project_id")
    template_id = request.args.get("hardware_template_id")
    status = request.args.get("status")
    items = [o for o in db.orders.values()
             if (project_id is None or o["project_id"] == project_id)
             and (template_id is None or o["hardware_template_id"] == template_id)
             and (status is None or o["status"] == status)]
    return list_response(items, limit, offset, serialize)


@bp.get("/orders/<oid>")
def get_order(oid):
    get_context()
    order = require_existence(db.orders, oid, "ERR_ORDER_NOT_FOUND", "MillworkOrder")
    return success(serialize(order))


@bp.put("/orders/<oid>")
def edit_order(oid):
    _, role = get_context()
    require_role(role, "Estimator")
    order = require_existence(db.orders, oid, "ERR_ORDER_NOT_FOUND", "MillworkOrder")
    body = raw_body()
    if body.get("hardware_template_id") is not None:
        require_existence(db.hardware_templates, body["hardware_template_id"],
                          "ERR_TEMPLATE_NOT_FOUND", "HardwareTemplate")
    validate_fields(body, required=(), optional=CONFIG_FIELDS)
    # Rung 6: configuration is editable only while DRAFT or CONFIGURED.
    if order["status"] not in ("DRAFT", "CONFIGURED"):
        raise err("ERR_ORDER_CONFIG_LOCKED",
                  "Order configuration is locked once past CONFIGURED")
    if "species" in body:
        order["species"] = req_enum(body, "species", SPECIES)
    if "profile_code" in body:
        order["profile_code"] = req_string(body, "profile_code")
    if "finish_system" in body:
        order["finish_system"] = req_enum(body, "finish_system", FINISH_SYSTEMS)
    if "sheen_target" in body:
        order["sheen_target"] = req_enum(body, "sheen_target", SHEENS)
    if "hardware_prep_mode" in body:
        order["hardware_prep_mode"] = req_enum(body, "hardware_prep_mode", PREP_MODES)
    if "hardware_template_id" in body:
        order["hardware_template_id"] = body["hardware_template_id"]
    if "fire_rating_required" in body:
        order["fire_rating_required"] = req_enum(body, "fire_rating_required", FIRE_RATINGS)
    db.touch(order)
    return success(serialize(order))


@bp.put("/orders/<oid>/status")
def transition_order(oid):
    user_id, role = get_context()
    body = raw_body()
    # Peek at target_status for per-target authorization (rung 2) without
    # validating payload — existence (rung 3) must precede payload errors (rung 4).
    target = body.get("target_status")
    allowed = TARGET_ACTORS.get(target, ALL_STATUS_ACTORS)
    require_role(role, *allowed)
    order = require_existence(db.orders, oid, "ERR_ORDER_NOT_FOUND", "MillworkOrder")
    validate_fields(body, required=("target_status",))
    if not isinstance(target, str) or target not in ORDER_STATUSES:
        raise err("ERR_INVALID_ORDER_STATUS_TRANSITION",
                  "Unknown order status: %s" % target)
    current = order["status"]

    if target == "CONFIGURED":
        if current != "DRAFT":
            raise err("ERR_INVALID_ORDER_STATUS_TRANSITION",
                      "Order cannot transition from %s to CONFIGURED" % current)
        # PRD §3.2 gate order: openings, template reference, rated prep mode, template rating.
        if not _non_cancelled_openings(oid):
            raise err("ERR_NO_OPENINGS", "Configure requires at least one non-CANCELLED opening")
        if order["hardware_prep_mode"] == "TEMPLATE_PREP" and not order["hardware_template_id"]:
            raise err("ERR_TEMPLATE_REQUIRED", "TEMPLATE_PREP order requires hardware_template_id")
        if order["fire_rating_required"] != "NONE":
            if order["hardware_prep_mode"] != "TEMPLATE_PREP":
                raise err("ERR_RATED_ORDER_REQUIRES_TEMPLATE_PREP",
                          "Rated orders require TEMPLATE_PREP")
            template = db.hardware_templates.get(order["hardware_template_id"])
            if template is None:
                raise err("ERR_TEMPLATE_NOT_FOUND", "HardwareTemplate not found")
            if not template["fire_rated_compatible"]:
                raise err("ERR_TEMPLATE_NOT_FIRE_RATED",
                          "Rated order's template must be fire-rated compatible")
        order["budget_quote_cents"] = pricing.compute_budget_quote(order)
        order["status"] = "CONFIGURED"

    elif target == "IN_PRODUCTION":
        if current != "APPROVED":
            raise err("ERR_INVALID_ORDER_STATUS_TRANSITION",
                      "Order cannot transition from %s to IN_PRODUCTION" % current)
        approved_ids = {d["id"] for d in db.shop_drawings.values()
                        if d["order_id"] == oid and d["status"] == "APPROVED"}
        released = any(p for p in db.machining_programs.values()
                       if p["drawing_id"] in approved_ids and p["status"] == "RELEASED")
        if not released:
            raise err("ERR_NO_RELEASED_PROGRAM",
                      "IN_PRODUCTION requires a RELEASED program on the current approved drawing")
        order["status"] = "IN_PRODUCTION"

    elif target == "FINISHING":
        if current != "IN_PRODUCTION":
            raise err("ERR_INVALID_ORDER_STATUS_TRANSITION",
                      "Order cannot transition from %s to FINISHING" % current)
        for opening in _non_cancelled_openings(oid):
            if opening["fab_status"] not in ("MACHINED", "FINISHED", "LABELED", "STAGED"):
                raise err("ERR_OPENINGS_NOT_MACHINED",
                          "Every non-CANCELLED opening must be MACHINED or beyond")
        order["status"] = "FINISHING"

    elif target == "READY_TO_SHIP":
        if current != "FINISHING":
            raise err("ERR_INVALID_ORDER_STATUS_TRANSITION",
                      "Order cannot transition from %s to READY_TO_SHIP" % current)
        for opening in _non_cancelled_openings(oid):
            if opening["fab_status"] != "STAGED":
                raise err("ERR_OPENINGS_NOT_STAGED",
                          "Every non-CANCELLED opening must be STAGED")
        order["status"] = "READY_TO_SHIP"

    elif target == "SHIPPED":
        if current != "READY_TO_SHIP":
            raise err("ERR_INVALID_ORDER_STATUS_TRANSITION",
                      "Order cannot transition from %s to SHIPPED" % current)
        for opening in _non_cancelled_openings(oid):
            if opening["ship_status"] not in ("SHIPPED", "DELIVERED", "PUNCH_LISTED", "ACCEPTED"):
                raise err("ERR_OPENINGS_NOT_SHIPPED",
                          "Every non-CANCELLED opening must be SHIPPED or beyond")
        order["status"] = "SHIPPED"

    elif target == "CLOSED":
        if current != "SHIPPED":
            raise err("ERR_INVALID_ORDER_STATUS_TRANSITION",
                      "Order cannot transition from %s to CLOSED" % current)
        for opening in _non_cancelled_openings(oid):
            if opening["ship_status"] != "ACCEPTED":
                raise err("ERR_OPENINGS_NOT_ACCEPTED",
                          "Every non-CANCELLED opening must be ACCEPTED")
        opening_ids = {o["id"] for o in db.openings.values() if o["order_id"] == oid}
        for punch in db.punch_items.values():
            if punch["opening_id"] in opening_ids and punch["status"] in OPEN_PUNCH_STATES:
                raise err("ERR_OPEN_PUNCH_ITEMS", "Order has open punch items")
        order["status"] = "CLOSED"

    elif target == "CANCELLED":
        if current not in ("DRAFT", "CONFIGURED", "SUBMITTED", "APPROVED"):
            raise err("ERR_ORDER_NOT_CANCELLABLE",
                      "Cancel requires status in DRAFT, CONFIGURED, SUBMITTED or APPROVED")
        cascade.cancel_order_cascade(order)
        order["status"] = "CANCELLED"

    else:  # SUBMITTED / APPROVED are system cascades only
        raise err("ERR_INVALID_ORDER_STATUS_TRANSITION",
                  "Order cannot transition from %s to %s via this endpoint" % (current, target))

    db.touch(order)
    return success(serialize(order))


@bp.post("/orders/<oid>/change-order")
def change_order(oid):
    _, role = get_context()
    require_role(role, "Estimator")
    order = require_existence(db.orders, oid, "ERR_ORDER_NOT_FOUND", "MillworkOrder")
    body = raw_body()
    validate_fields(body)
    if order["status"] != "APPROVED":
        raise err("ERR_INVALID_ORDER_STATUS_TRANSITION",
                  "Change order requires APPROVED status, not %s" % order["status"])
    approved = [d for d in db.shop_drawings.values()
                if d["order_id"] == oid and d["status"] == "APPROVED"]
    approved_ids = {d["id"] for d in approved}
    for program in db.machining_programs.values():
        if program["drawing_id"] in approved_ids and program["status"] == "RELEASED":
            raise err("ERR_PRODUCTION_ALREADY_RELEASED",
                      "A RELEASED program exists for the current approved drawing")
    for drawing in approved:
        cascade.supersede_drawing(drawing)
    order["status"] = "CONFIGURED"
    order["config_locked"] = False
    db.touch(order)
    return success(serialize(order))


@bp.get("/orders/<oid>/invoice-summary")
def invoice_summary(oid):
    get_context()
    order = require_existence(db.orders, oid, "ERR_ORDER_NOT_FOUND", "MillworkOrder")
    lines = pricing.contract_lines(order)
    merchandise = sum(lines)
    freight = pricing.freight_fee(merchandise)
    data = {
        "merchandise_total_cents": merchandise,
        "freight_fee_cents": freight,
        "contract_price_cents": merchandise + freight,
        "budget_quote_cents": pricing.compute_budget_quote(order),
        "line_count": len(lines),
    }
    return success(data)
