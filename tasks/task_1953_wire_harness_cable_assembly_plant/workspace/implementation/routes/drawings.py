"""Drawings and BOM components (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import (raise_error, ERR_INVALID_REQUEST, ERR_DRAWING_NOT_DRAFT,
                    ERR_DRAWING_EMPTY_BOM, ERR_DUPLICATE_FIND_NUMBER)
from middleware import authenticate, ALL_ROLES
from response import success_object
from services import (WORKMANSHIP_CLASSES, COMPONENT_TYPES, SUPPLY_TYPES,
                      common_fields, touch, bom_lines,
                      ser_drawing, ser_component, paginated)
from util import CLOCK
from validate import (get_body, req_str, req_int, req_enum, require_path,
                      require_fk)

bp = Blueprint("drawings", __name__)

HARNESS_ENGINEER = {"HarnessEngineer"}


@bp.route("/plant/drawings", methods=["POST"])
def create_drawing():
    body = get_body()
    # Tier 1: well-formedness
    drawing_number = req_str(body, "drawing_number")
    customer_code = req_str(body, "customer_code")
    revision = req_str(body, "revision")
    workmanship_class = req_enum(body, "workmanship_class", WORKMANSHIP_CLASSES)
    # Tiers 2-3
    authenticate(HARNESS_ENGINEER)
    # Uniqueness declared by the PRD ("unique across the plant").
    for d in db["drawings"].values():
        if d["drawing_number"] == drawing_number:
            raise_error(ERR_INVALID_REQUEST, f"duplicate drawing_number: {drawing_number}")

    drawing = common_fields()
    drawing.update({
        "drawing_number": drawing_number,
        "customer_code": customer_code,
        "revision": revision,
        "workmanship_class": workmanship_class,
        "status": "DRAFT",
        "released_at": None,
        "superseded_at": None,
    })
    db["drawings"][drawing["id"]] = drawing
    return success_object(ser_drawing(drawing), 201)


@bp.route("/plant/drawings/<did>", methods=["GET"])
def get_drawing(did):
    authenticate(ALL_ROLES)
    drawing = require_path("drawings", did)
    return success_object(ser_drawing(drawing), 200)


@bp.route("/plant/drawings/<did>/release", methods=["POST"])
def release_drawing(did):
    get_body()
    authenticate(HARNESS_ENGINEER)
    drawing = require_path("drawings", did)
    # Tier 6: DRAFT check precedes the empty-BOM check (scaffold priority order).
    if drawing["status"] != "DRAFT":
        raise_error(ERR_DRAWING_NOT_DRAFT, "drawing is not DRAFT")
    if not bom_lines(drawing["id"]):
        raise_error(ERR_DRAWING_EMPTY_BOM, "release requires at least one component")
    drawing["status"] = "RELEASED"
    drawing["released_at"] = CLOCK.now()
    touch(drawing)
    return success_object(ser_drawing(drawing), 200)


@bp.route("/plant/components", methods=["POST"])
def create_component():
    body = get_body()
    drawing_id = req_str(body, "drawing_id")
    find_number = req_str(body, "find_number")
    component_type = req_enum(body, "component_type", COMPONENT_TYPES)
    mpn = req_str(body, "mpn")
    qty_per_harness = req_int(body, "qty_per_harness", minimum=1)
    supply_type = req_enum(body, "supply_type", SUPPLY_TYPES)
    unit_cost_cents = req_int(body, "unit_cost_cents", minimum=0)
    authenticate(HARNESS_ENGINEER)
    drawing = require_fk("drawings", drawing_id, "drawing_id")
    if drawing["status"] != "DRAFT":
        raise_error(ERR_DRAWING_NOT_DRAFT, "components may only be added to a DRAFT drawing")
    for c in bom_lines(drawing["id"]):
        if c["find_number"] == find_number:
            raise_error(ERR_DUPLICATE_FIND_NUMBER,
                        f"(drawing_id, find_number) already exists: {find_number}")

    comp = common_fields()
    comp.update({
        "drawing_id": drawing["id"],
        "find_number": find_number,
        "component_type": component_type,
        "mpn": mpn,
        "qty_per_harness": qty_per_harness,
        "supply_type": supply_type,
        "unit_cost_cents": unit_cost_cents,
    })
    db["components"][comp["id"]] = comp
    return success_object(ser_component(comp), 201)


@bp.route("/plant/components/<cid>", methods=["GET"])
def get_component(cid):
    authenticate(ALL_ROLES)
    comp = require_path("components", cid)
    return success_object(ser_component(comp), 200)


@bp.route("/plant/components", methods=["GET"])
def list_components():
    authenticate(ALL_ROLES)
    items = list(db["components"].values())
    drawing_id = request.args.get("drawing_id")
    if drawing_id is not None:
        items = [c for c in items if c["drawing_id"] == drawing_id]
    return paginated(items, ser_component)
