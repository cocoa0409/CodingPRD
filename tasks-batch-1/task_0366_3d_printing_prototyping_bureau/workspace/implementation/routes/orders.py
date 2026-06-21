"""Order and OrderLine routes, plus the order lifecycle transitions."""

from flask import Blueprint, request

import errors
import validation as V
from db import DB, LOCK, stamp_create, touch
from middleware import require_auth, require_role
from pagination import paginate
from response import object_response, array_response
from services import calc, domain, ownership

bp = Blueprint("orders", __name__)

LEAD_TIERS = ("STANDARD", "EXPEDITE", "RUSH")
READ_ROLES = ("Customer", "BureauAdmin", "Operator", "QAReviewer")


def _customer_guard(principal, customer_id):
    if principal.role == "Customer" and principal.user_id != customer_id:
        raise errors.forbidden()


# --------------------------------------------------------------------------- #
# Order CRUD
# --------------------------------------------------------------------------- #
@bp.route("/bureaus/orders", methods=["POST"])
def create_order():
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Customer",))
        body = V.get_body()
        bureau_id = V.require_id(body, "bureau_id")
        customer_id = V.require_id(body, "customer_id")
        lead_tier = V.optional_enum(body, "lead_tier", LEAD_TIERS, "STANDARD")

        if bureau_id not in DB.bureaus:
            raise errors.reference_not_found()
        customer = domain.ref_or_404(DB.customers, customer_id, bureau_id)
        _customer_guard(principal, customer["id"])

        order = stamp_create({
            "bureau_id": bureau_id,
            "customer_id": customer_id,
            "lead_tier": lead_tier,
            "parts_subtotal_cents": 0,
            "finishing_subtotal_cents": 0,
            "rush_surcharge_cents": 0,
            "grand_total_cents": 0,
            "fulfillment_status": "DRAFT",
            "payment_status": "UNPAID",
        })
        DB.orders[order["id"]] = order
        return object_response(order, 201)


@bp.route("/bureaus/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        order = domain.get_or_404(DB.orders, order_id)
        _customer_guard(principal, order["customer_id"])
        return object_response(order, 200)


@bp.route("/bureaus/orders", methods=["GET"])
def list_orders():
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        items = list(DB.orders.values())
        for key in ("bureau_id", "customer_id", "fulfillment_status", "payment_status"):
            val = request.args.get(key)
            if val is not None:
                items = [o for o in items if o.get(key) == val]
        if principal.role == "Customer":
            items = [o for o in items if o["customer_id"] == principal.user_id]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


# --------------------------------------------------------------------------- #
# Order transitions
# --------------------------------------------------------------------------- #
@bp.route("/bureaus/orders/<order_id>/quote", methods=["POST"])
def quote_order(order_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Customer",))
        order = domain.get_or_404(DB.orders, order_id)
        _customer_guard(principal, order["customer_id"])

        # State legality (p6): quote permitted from DRAFT (and re-quote from QUOTED).
        if order["fulfillment_status"] not in ("DRAFT", "QUOTED"):
            raise errors.invalid_state()

        active = domain.active_lines_of_order(order["id"])
        # Business safety (p7): non-empty, then every active line printable.
        if len(active) == 0:
            raise errors.conflict(errors.ERR_ORDER_EMPTY, "Order has zero ACTIVE lines")
        for line in active:
            pf = DB.print_files.get(line["print_file_id"])
            if pf is None or pf["status"] != "PRINTABLE":
                raise errors.conflict(errors.ERR_FILE_NOT_PRINTABLE, "An active line's file is not PRINTABLE")

        domain.recompute_order_totals(order)
        if order["fulfillment_status"] != "QUOTED":
            order["fulfillment_status"] = "QUOTED"
            touch(order)
        else:
            # Re-quote of an already-QUOTED order is still a mutation observable
            # to OCC clients.
            touch(order)
        return object_response(order, 200)


@bp.route("/bureaus/orders/<order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Customer",))
        order = domain.get_or_404(DB.orders, order_id)
        _customer_guard(principal, order["customer_id"])
        body = V.get_body()
        if "expected_order_version" not in body:
            raise errors.invalid_request("Missing field: expected_order_version")
        expected = body["expected_order_version"]
        if not V.is_int(expected):
            raise errors.invalid_request("expected_order_version must be an integer")

        # State legality (p6): must be QUOTED with payment UNPAID.
        if order["fulfillment_status"] != "QUOTED" or order["payment_status"] != "UNPAID":
            raise errors.invalid_state()

        customer = DB.customers[order["customer_id"]]
        # Fiscal (p13): wallet sufficiency.
        if customer["wallet_balance_cents"] < order["grand_total_cents"]:
            raise errors.insufficient_wallet()

        # OCC (p14, last): expected_order_version must match.
        if expected != order["version"]:
            raise errors.stale_version()

        amount = order["grand_total_cents"]
        order["payment_status"] = "ESCROWED"
        order["fulfillment_status"] = "CONFIRMED"
        touch(order)

        customer["wallet_balance_cents"] -= amount
        customer["escrow_held_cents"] += amount
        touch(customer)
        return object_response(order, 200)


@bp.route("/bureaus/orders/<order_id>/ship", methods=["POST"])
def ship_order(order_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Operator",))
        order = domain.get_or_404(DB.orders, order_id)
        body = V.get_body()
        if "expected_order_version" not in body:
            raise errors.invalid_request("Missing field: expected_order_version")
        expected = body["expected_order_version"]
        if not V.is_int(expected):
            raise errors.invalid_request("expected_order_version must be an integer")

        # Business safety: must be READY.
        if order["fulfillment_status"] != "READY":
            raise errors.conflict(errors.ERR_ORDER_NOT_READY, "Order is not READY")
        # payment must be ESCROWED (parallel axis).
        if order["payment_status"] != "ESCROWED":
            raise errors.invalid_state()
        # A CREATED shipment must exist.
        shipment = next(
            (s for s in DB.shipments.values()
             if s["order_id"] == order["id"] and s["status"] == "CREATED"),
            None,
        )
        if shipment is None:
            raise errors.conflict(errors.ERR_NO_SHIPMENT, "No CREATED shipment for order")

        # OCC (last).
        if expected != order["version"]:
            raise errors.stale_version()

        amount = order["grand_total_cents"]
        order["fulfillment_status"] = "SHIPPED"
        order["payment_status"] = "CAPTURED"
        touch(order)

        customer = DB.customers[order["customer_id"]]
        customer["escrow_held_cents"] -= amount
        customer["captured_revenue_cents"] += amount
        touch(customer)

        shipment["status"] = "DISPATCHED"
        touch(shipment)
        return object_response(order, 200)


@bp.route("/bureaus/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Customer",))
        order = domain.get_or_404(DB.orders, order_id)
        _customer_guard(principal, order["customer_id"])

        status = order["fulfillment_status"]
        if status in ("DRAFT", "QUOTED"):
            _void_active_lines(order)
            order["fulfillment_status"] = "CANCELLED"
            touch(order)
            return object_response(order, 200)

        if status == "CONFIRMED":
            # Guard: no run for any line is PRINTING or DONE.
            line_ids = {l["id"] for l in domain.lines_of_order(order["id"])}
            for r in DB.print_runs.values():
                if r["order_line_id"] in line_ids and r["status"] in ("PRINTING", "DONE"):
                    raise errors.conflict(errors.ERR_PRODUCTION_STARTED, "Production has started")

            amount = order["grand_total_cents"]
            order["fulfillment_status"] = "CANCELLED"
            order["payment_status"] = "REFUNDED"
            touch(order)

            # Refund escrow to wallet (compensation).
            customer = DB.customers[order["customer_id"]]
            customer["escrow_held_cents"] -= amount
            customer["wallet_balance_cents"] += amount
            touch(customer)

            # Cancel all QUEUED runs (release committed grams).
            affected_spools = set()
            for r in DB.print_runs.values():
                if r["order_line_id"] in line_ids and r["status"] == "QUEUED":
                    r["status"] = "CANCELLED"
                    touch(r)
                    affected_spools.add(r["spool_id"])
                    if r.get("machine_id") in DB.machines:
                        domain.recompute_machine_utilization(DB.machines[r["machine_id"]])
            for spool_id in affected_spools:
                if spool_id in DB.spools:
                    domain.recompute_spool(DB.spools[spool_id])

            _void_active_lines(order)
            return object_response(order, 200)

        # IN_PRODUCTION / POST_PROCESSING / READY / SHIPPED / CANCELLED -> invalid.
        raise errors.invalid_state()


def _void_active_lines(order):
    for line in domain.active_lines_of_order(order["id"]):
        line["status"] = "VOID"
        touch(line)


# --------------------------------------------------------------------------- #
# OrderLine
# --------------------------------------------------------------------------- #
@bp.route("/bureaus/order-lines", methods=["POST"])
def create_order_line():
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Customer",))
        body = V.get_body()
        order_id = V.require_id(body, "order_id")
        print_file_id = V.require_id(body, "print_file_id")
        material_id = V.require_id(body, "material_id")
        layer_height = V.require_positive_number(body, "layer_height_mm")
        quantity = V.require_quantity(body)

        # Body FK resolution (p4). Resolve order first to learn the bureau scope.
        order = DB.orders.get(order_id)
        if order is None:
            raise errors.reference_not_found()
        bureau_id = order["bureau_id"]
        print_file = domain.ref_or_404(DB.print_files, print_file_id, bureau_id)
        material = domain.ref_or_404(DB.materials, material_id, bureau_id)

        _customer_guard(principal, order["customer_id"])

        # State legality (p6): lines may be added while DRAFT or QUOTED.
        if order["fulfillment_status"] not in ("DRAFT", "QUOTED"):
            raise errors.invalid_state()

        # Business safety (p8): material must be ACTIVE.
        if material["status"] != "ACTIVE":
            raise errors.conflict(errors.ERR_MATERIAL_RETIRED, "Material is retired")

        pm, per_part, line_total = calc.line_pricing(print_file, material, layer_height, quantity)

        line = stamp_create({
            "bureau_id": bureau_id,
            "order_id": order_id,
            "print_file_id": print_file_id,
            "material_id": material_id,
            "layer_height_mm": layer_height,
            "quantity": quantity,
            "print_minutes": pm,
            "per_part_cents": per_part,
            "line_total_cents": line_total,
            "finishing_total_cents": 0,
            "reprint_of_line_id": None,
            "reprint_cause": None,
            "status": "ACTIVE",
        })
        DB.order_lines[line["id"]] = line

        domain.recompute_order_totals(order)
        return object_response(line, 201)


@bp.route("/bureaus/order-lines/<line_id>", methods=["GET"])
def get_order_line(line_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        line = domain.get_or_404(DB.order_lines, line_id)
        _customer_guard(principal, ownership.line_customer_id(line))
        return object_response(line, 200)


@bp.route("/bureaus/order-lines", methods=["GET"])
def list_order_lines():
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        items = list(DB.order_lines.values())
        for key in ("bureau_id", "order_id", "print_file_id", "material_id",
                    "reprint_of_line_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [l for l in items if l.get(key) == val]
        if principal.role == "Customer":
            items = [l for l in items if ownership.line_customer_id(l) == principal.user_id]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)
