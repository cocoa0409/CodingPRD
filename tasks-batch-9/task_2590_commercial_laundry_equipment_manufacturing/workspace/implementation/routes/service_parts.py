"""Service parts: catalogue creation, reads and stock adjustments."""

import lookup
import response
import validate
from db import base_row, bump, by_key, db
from errors import (ERR_DUPLICATE_RESOURCE_CODE, ERR_INVALID_REQUEST,
                    ERR_STOCK_ADJUSTMENT_NEGATIVE, fail)
from middleware import (CHANNEL_MANAGER, DISTRIBUTOR, PLANT_MANAGER,
                        PRODUCT_ENGINEER, TECHNICIAN, WARRANTY_ANALYST, endpoint)
from services import calc
from services.cascades import reproject_part_stock
from validate import PRODUCT_LINES

COMPONENT_CLASSES = ["DRUM", "BEARING", "CONTROL_BOARD", "PAYMENT_MODULE", "MOTOR",
                     "DIAGNOSTIC_TOOL"]
CERT_SCOPE_REQUIREMENTS = ["NONE", "DIAGNOSTICS_TOOL", "CONTROL_INTEGRATION"]
STOCK_STATES = ["IN_STOCK", "LOW", "BACKORDERED"]


def register(app):
    @app.post("/clm/service-parts")
    @endpoint([PRODUCT_ENGINEER])
    def create_service_part():
        body = validate.parse_body()
        part_number = body.code("part_number")
        component_class = body.enum("component_class", COMPONENT_CLASSES)
        fits_product_lines = body.enum_array("fits_product_lines", PRODUCT_LINES)
        fits_min = body.integer("fits_min_capacity_lb", minimum=0)
        fits_max = body.integer("fits_max_capacity_lb", minimum=0)
        rated_duty_cycles = body.integer("rated_duty_cycles", minimum=1)
        warranty_months = body.integer("warranty_months", minimum=12, maximum=60)
        unit_price_cents = body.integer("unit_price_cents", minimum=1)
        requires_cert_scope = body.enum("requires_cert_scope", CERT_SCOPE_REQUIREMENTS,
                                        required=False, default="NONE")
        reorder_point_qty = body.integer("reorder_point_qty", minimum=0,
                                         required=False, default=2)
        supersedes_part_id = body.id_ref("supersedes_part_id", required=False)
        # a fitment envelope whose upper bound sits below its lower bound
        if fits_max < fits_min:
            fail(ERR_INVALID_REQUEST,
                 "fits_max_capacity_lb must be at least fits_min_capacity_lb.")
        # rule 17: the superseded part must resolve
        if supersedes_part_id is not None:
            lookup.part(supersedes_part_id)
        # rule 48: natural-key uniqueness
        if any(p["part_number"] == part_number for p in db.parts.values()):
            fail(ERR_DUPLICATE_RESOURCE_CODE,
                 "part_number '%s' already exists." % part_number)

        row = base_row()
        row.update({
            "part_number": part_number,
            "component_class": component_class,
            "supersedes_part_id": supersedes_part_id,
            "fits_product_lines": fits_product_lines,
            "fits_min_capacity_lb": fits_min,
            "fits_max_capacity_lb": fits_max,
            "rated_duty_cycles": rated_duty_cycles,
            "warranty_months": warranty_months,
            "unit_price_cents": unit_price_cents,
            "requires_cert_scope": requires_cert_scope,
            "on_hand_qty": 0,
            "reserved_qty": 0,
            "reorder_point_qty": reorder_point_qty,
            "stock_state": calc.project_stock_state(0, reorder_point_qty),
        })
        db.parts[row["id"]] = row
        return response.created(row)

    @app.get("/clm/service-parts/<part_id>")
    @endpoint([PRODUCT_ENGINEER, PLANT_MANAGER, WARRANTY_ANALYST, CHANNEL_MANAGER,
               TECHNICIAN, DISTRIBUTOR])
    def read_service_part(part_id):
        return response.ok(lookup.part(part_id))

    @app.get("/clm/service-parts")
    @endpoint([PRODUCT_ENGINEER, PLANT_MANAGER, WARRANTY_ANALYST, DISTRIBUTOR])
    def list_service_parts():
        limit, offset = validate.q_pagination()
        component_class = validate.q_enum("component_class", COMPONENT_CLASSES)
        stock_state = validate.q_enum("stock_state", STOCK_STATES)
        supersedes_part_id = validate.q_str("supersedes_part_id")
        rows = list(db.parts.values())
        if component_class is not None:
            rows = [r for r in rows if r["component_class"] == component_class]
        if stock_state is not None:
            rows = [r for r in rows if r["stock_state"] == stock_state]
        if supersedes_part_id is not None:
            rows = [r for r in rows if r["supersedes_part_id"] == supersedes_part_id]
        rows = by_key(rows, "part_number")
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)

    @app.post("/clm/service-parts/<part_id>/stock-adjustments")
    @endpoint([PLANT_MANAGER])
    def adjust_service_part_stock(part_id):
        body = validate.parse_body()
        delta_qty = body.integer("delta_qty")
        body.string("reason", maxlen=500)
        part = lookup.part(part_id)
        # rule 57: the adjustment may not drive on_hand_qty below zero
        if part["on_hand_qty"] + delta_qty < 0:
            fail(ERR_STOCK_ADJUSTMENT_NEGATIVE,
                 "The adjustment would leave on_hand_qty below zero.")
        part["on_hand_qty"] = part["on_hand_qty"] + delta_qty
        bump(part)
        reproject_part_stock(part)
        return response.ok(part)
