"""Work orders, part lines, flat-rate labor (PRD §3.6)."""
import calc
import errors
from db import db, make_common, touch
from errors import err
from middleware import require_roles
from routes.common import lookup, list_and_respond, respond
from services import (
    available_qty_for,
    recompute_wo_parts_charge,
    reserved_qty_for,
    serialize_generic,
)
from validation import (
    get_json,
    require_fk,
    require_string,
    require_int,
    require_number,
    optional_number,
    optional_fk,
)

WO_READ_ROLES = ("ServiceAdvisor", "DealerAdmin", "FinanceManager")
PL_READ_ROLES = ("ServiceAdvisor", "PartsClerk", "DealerAdmin")


def _recompute_labor(wo, hours):
    wo["labor_charge_cents"] = calc.labor_charge(hours, wo["labor_rate_cents"])
    recompute_wo_parts_charge(wo)


def register(app):

    @app.route("/work-orders", methods=["POST"])
    @require_roles("ServiceAdvisor", "DealerAdmin")
    def create_wo():
        body = get_json()
        unit_id = require_fk(body, "unit_id")
        customer_id = require_fk(body, "customer_id")
        complaint = require_string(body, "complaint")
        labor_rate_cents = require_int(body, "labor_rate_cents", gt=0)
        flat_rate_hours = require_number(body, "flat_rate_hours", minimum=0)
        actual_hours = optional_number(body, "actual_hours", default=0, minimum=0)
        warranty_claim_id = optional_fk(body, "warranty_claim_id")

        lookup(db.units, unit_id)
        lookup(db.customers, customer_id)
        if warranty_claim_id is not None:
            lookup(db.warranty_claims, warranty_claim_id)

        wo = {
            "unit_id": unit_id,
            "customer_id": customer_id,
            "complaint": complaint,
            "labor_rate_cents": labor_rate_cents,
            "flat_rate_hours": flat_rate_hours,
            "actual_hours": actual_hours,
            "warranty_claim_id": warranty_claim_id,
            "labor_charge_cents": 0,
            "parts_charge_cents": 0,
            "total_charge_cents": 0,
            "status": "OPEN",
        }
        make_common(wo)
        db.work_orders[wo["id"]] = wo
        return respond(serialize_generic(wo), status=201)

    @app.route("/work-orders", methods=["GET"])
    @require_roles(*WO_READ_ROLES)
    def list_wos():
        from flask import request
        items = list(db.work_orders.values())
        for key in ("unit_id", "customer_id", "warranty_claim_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [w for w in items if w.get(key) == val]
        return list_and_respond(items, serialize_generic)

    @app.route("/work-orders/<wo_id>", methods=["GET"])
    @require_roles(*WO_READ_ROLES)
    def get_wo(wo_id):
        wo = lookup(db.work_orders, wo_id)
        return respond(serialize_generic(wo))

    # ---- part lines ----
    @app.route("/work-orders/<wo_id>/part-lines", methods=["POST"])
    @require_roles("ServiceAdvisor", "PartsClerk")
    def add_part_line(wo_id):
        wo = lookup(db.work_orders, wo_id)
        body = get_json()
        part_id = require_fk(body, "part_id")
        quantity = require_int(body, "quantity", gt=0)
        part = lookup(db.parts, part_id)

        line = {
            "work_order_id": wo_id,
            "part_id": part_id,
            "quantity": quantity,
            "unit_price_cents": part["unit_price_cents"],
            "extended_cents": quantity * part["unit_price_cents"],
        }
        make_common(line)
        db.part_lines[line["id"]] = line

        recompute_wo_parts_charge(wo)
        touch(wo)
        # recompute part reserved_qty (read-derived; stored snapshot refreshed)
        part["reserved_qty"] = reserved_qty_for(part_id)
        touch(part)
        return respond(serialize_generic(line), status=201)

    @app.route("/work-orders/<wo_id>/part-lines", methods=["GET"])
    @require_roles(*PL_READ_ROLES)
    def list_wo_part_lines(wo_id):
        lookup(db.work_orders, wo_id)
        items = [l for l in db.part_lines.values() if l["work_order_id"] == wo_id]
        return list_and_respond(items, serialize_generic)

    @app.route("/part-lines", methods=["GET"])
    @require_roles(*PL_READ_ROLES)
    def list_part_lines():
        from flask import request
        items = list(db.part_lines.values())
        for key in ("work_order_id", "part_id"):
            val = request.args.get(key)
            if val is not None:
                items = [l for l in items if l.get(key) == val]
        return list_and_respond(items, serialize_generic)

    @app.route("/part-lines/<line_id>", methods=["GET"])
    @require_roles(*PL_READ_ROLES)
    def get_part_line(line_id):
        line = lookup(db.part_lines, line_id)
        return respond(serialize_generic(line))

    # ---- transitions ----
    @app.route("/work-orders/<wo_id>/start", methods=["POST"])
    @require_roles("ServiceAdvisor")
    def start_wo(wo_id):
        wo = lookup(db.work_orders, wo_id)
        if wo["status"] != "OPEN":
            raise err(errors.ERR_INVALID_STATE, "Work order is not OPEN.")
        wo["status"] = "IN_PROGRESS"
        # labor_charge reflects flat-rate estimate
        _recompute_labor(wo, wo["flat_rate_hours"])
        touch(wo)
        return respond(serialize_generic(wo))

    @app.route("/work-orders/<wo_id>/hold-for-parts", methods=["POST"])
    @require_roles("ServiceAdvisor")
    def hold_wo(wo_id):
        wo = lookup(db.work_orders, wo_id)
        if wo["status"] != "IN_PROGRESS":
            raise err(errors.ERR_INVALID_STATE, "Work order is not IN_PROGRESS.")
        # at least one PartLine references a Part with available < line qty
        short = False
        for line in db.part_lines.values():
            if line["work_order_id"] != wo_id:
                continue
            part = db.parts.get(line["part_id"])
            if part is None:
                continue
            if available_qty_for(part) < line["quantity"]:
                short = True
                break
        if not short:
            raise err(errors.ERR_PARTS_SHORTAGE,
                      "No part line is short; cannot hold for parts.")
        wo["status"] = "AWAITING_PARTS"
        touch(wo)
        return respond(serialize_generic(wo))

    @app.route("/work-orders/<wo_id>/resume", methods=["POST"])
    @require_roles("ServiceAdvisor")
    def resume_wo(wo_id):
        wo = lookup(db.work_orders, wo_id)
        if wo["status"] != "AWAITING_PARTS":
            raise err(errors.ERR_INVALID_STATE, "Work order is not AWAITING_PARTS.")
        wo["status"] = "IN_PROGRESS"
        touch(wo)
        return respond(serialize_generic(wo))

    @app.route("/work-orders/<wo_id>/close", methods=["POST"])
    @require_roles("ServiceAdvisor")
    def close_wo(wo_id):
        wo = lookup(db.work_orders, wo_id)
        body = get_json()
        actual_hours = require_number(body, "actual_hours", gt=0)
        if wo["status"] != "IN_PROGRESS":
            raise err(errors.ERR_INVALID_STATE, "Work order is not IN_PROGRESS.")

        # parts availability check at close
        for line in db.part_lines.values():
            if line["work_order_id"] != wo_id:
                continue
            part = db.parts.get(line["part_id"])
            if part is None:
                continue
            if line["quantity"] > available_qty_for(part):
                raise err(errors.ERR_PARTS_SHORTAGE,
                          "Part line quantity exceeds availability at close.")

        wo["actual_hours"] = actual_hours
        wo["status"] = "CLOSED"
        # recompute labor from actual hours
        _recompute_labor(wo, actual_hours)
        # decrement consumed parts from on_hand_qty (reservations release as WO
        # leaves the reserving states)
        for line in db.part_lines.values():
            if line["work_order_id"] != wo_id:
                continue
            part = db.parts.get(line["part_id"])
            if part is None:
                continue
            part["on_hand_qty"] -= line["quantity"]
            part["reserved_qty"] = reserved_qty_for(part["id"])
            touch(part)
        # total_charge frozen
        touch(wo)
        return respond(serialize_generic(wo))

    @app.route("/work-orders/<wo_id>/void", methods=["POST"])
    @require_roles("ServiceAdvisor")
    def void_wo(wo_id):
        wo = lookup(db.work_orders, wo_id)
        if wo["status"] != "OPEN":
            raise err(errors.ERR_INVALID_STATE, "Work order is not OPEN.")
        wo["status"] = "VOID"
        touch(wo)
        # reserved parts release as the WO leaves the reserving states;
        # refresh reserved_qty snapshots on referenced parts.
        for line in db.part_lines.values():
            if line["work_order_id"] != wo_id:
                continue
            part = db.parts.get(line["part_id"])
            if part is not None:
                part["reserved_qty"] = reserved_qty_for(part["id"])
                touch(part)
        return respond(serialize_generic(wo))
