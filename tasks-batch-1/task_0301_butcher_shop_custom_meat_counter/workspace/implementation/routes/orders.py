"""HolidayWindow, CustomOrder, OrderLine: placement, confirm, fill, cancel,
draw, short (PRD §3.5, §3.6)."""
from flask import request

import db
import errors
import response
import serializers
import validation as v
from middleware import authenticate, require_role
from routes._helpers import list_response
from services import common
from services import pricing

ORDER_KINDS = {"STANDARD", "HOLIDAY"}


def register(app):
    # ---- HolidayWindow ----
    @app.route("/holiday-windows", methods=["POST"])
    def create_holiday_window():
        _uid, role = authenticate()
        require_role(role, {"ShiftManager"})
        body = v.get_body()
        name = v.as_str(v.require(body, "name"), "name")
        pickup_date = v.require(body, "pickup_date")
        common.parse_iso(pickup_date, "pickup_date")
        capacity = v.as_int(v.require(body, "capacity_g"), "capacity_g", minimum=1)
        cutoff_at = v.require(body, "cutoff_at")
        common.parse_iso(cutoff_at, "cutoff_at")
        for w in db.holiday_windows.values():
            if w["name"] == name:
                errors.fail(errors.ERR_INVALID_REQUEST,
                            "Holiday window name must be unique: %s" % name)

        record = {
            "name": name,
            "pickup_date": pickup_date,
            "capacity_g": capacity,
            "committed_g": 0,
            "cutoff_at": cutoff_at,
        }
        db.stamp_create(record)
        db.holiday_windows[record["id"]] = record
        return response.object_response(serializers.holiday_window(record), 201)

    @app.route("/holiday-windows/<rid>", methods=["GET"])
    def get_holiday_window(rid):
        _uid, role = authenticate()
        require_role(role, {"ShiftManager", "CounterClerk", "Customer"})
        record = common.get_or_404(db.holiday_windows, rid)
        return response.object_response(serializers.holiday_window(record))

    # ---- CustomOrder ----
    @app.route("/custom-orders", methods=["GET"])
    def list_custom_orders():
        _uid, role = authenticate()
        require_role(role, {"CounterClerk", "ShiftManager", "Customer", "Butcher"})
        records = list(db.custom_orders.values())
        customer_id = request.args.get("customer_id")
        holiday_window_id = request.args.get("holiday_window_id")
        order_status = request.args.get("order_status")
        if customer_id is not None:
            records = [r for r in records if r["customer_id"] == customer_id]
        if holiday_window_id is not None:
            records = [r for r in records
                       if r.get("holiday_window_id") == holiday_window_id]
        if order_status is not None:
            records = [r for r in records if r["order_status"] == order_status]
        return list_response(records, request.args, serializers.custom_order)

    @app.route("/custom-orders", methods=["POST"])
    def place_custom_order():
        uid, role = authenticate()
        require_role(role, {"Customer", "CounterClerk"})
        body = v.get_body()
        customer_id = v.as_str(v.require(body, "customer_id"), "customer_id")
        order_kind = v.as_enum(v.require(body, "order_kind"), "order_kind",
                               ORDER_KINDS)
        lines_in = v.require(body, "lines")
        if not isinstance(lines_in, list) or len(lines_in) == 0:
            errors.fail(errors.ERR_INVALID_REQUEST,
                        "lines must be a non-empty array.")

        holiday_window_id = v.opt(body, "holiday_window_id", None)
        pickup_date = v.opt(body, "pickup_date", None)

        # FK: customer
        customer = common.fk_or_404(db.customers, customer_id)

        # Validate each line's shape + cut-type FK first.
        parsed_lines = []
        for i, ln in enumerate(lines_in):
            if not isinstance(ln, dict):
                errors.fail(errors.ERR_INVALID_REQUEST,
                            "lines[%d] must be an object." % i)
            cut_type_id = v.as_str(v.require(ln, "cut_type_id"),
                                   "lines[%d].cut_type_id" % i)
            ordered = v.as_int(v.require(ln, "ordered_weight_g"),
                               "lines[%d].ordered_weight_g" % i, minimum=1)
            cut = common.fk_or_404(db.cut_types, cut_type_id)
            parsed_lines.append((cut_type_id, ordered, cut))

        window = None
        if order_kind == "HOLIDAY":
            if holiday_window_id is None:
                errors.fail(errors.ERR_INVALID_REQUEST,
                            "HOLIDAY order requires holiday_window_id.")
            if pickup_date is None:
                errors.fail(errors.ERR_INVALID_REQUEST,
                            "HOLIDAY order requires pickup_date.")
            common.parse_iso(pickup_date, "pickup_date")
            window = common.fk_or_404(db.holiday_windows, holiday_window_id)
        else:
            # STANDARD: both null (PRD §3.5).
            holiday_window_id = None
            pickup_date = None

        policy = common.active_policy_or_400()

        # Holiday timing gate (PRD §3.6) before capacity gate.
        if order_kind == "HOLIDAY":
            now = db.current_utc()
            cutoff = common.parse_iso(window["cutoff_at"], "cutoff_at")
            if now > cutoff:
                errors.fail(errors.ERR_WINDOW_CUTOFF_PASSED,
                            "Holiday window cutoff has passed.")
            # Capacity gate (inclusive at equality).
            ordered_grams = sum(o for (_c, o, _ct) in parsed_lines)
            if window["committed_g"] + ordered_grams > window["capacity_g"]:
                errors.fail(errors.ERR_HOLIDAY_CAPACITY_EXCEEDED,
                            "Holiday capacity exceeded.")

        # Build the order + its lines, compute estimate pricing.
        order = {
            "customer_id": customer_id,
            "order_kind": order_kind,
            "pickup_date": pickup_date,
            "holiday_window_id": holiday_window_id,
            "deposit_cents": 0,
            "estimated_total_cents": 0,
            "final_total_cents": None,
            "order_status": "PLACED",
        }
        db.stamp_create(order)
        db.custom_orders[order["id"]] = order

        estimated_total = 0
        for cut_type_id, ordered, cut in parsed_lines:
            est = pricing.estimated_line_cents(
                ordered, cut, policy, customer["loyalty_tier"])
            estimated_total += est
            line = {
                "custom_order_id": order["id"],
                "cut_type_id": cut_type_id,
                "ordered_weight_g": ordered,
                "catch_weight_g": None,
                "est_line_cents": est,
                "final_line_cents": None,
                "drawn_lot_id": None,
                "line_status": "PENDING",
            }
            db.stamp_create(line)
            db.order_lines[line["id"]] = line

        order["estimated_total_cents"] = estimated_total

        if order_kind == "HOLIDAY":
            deposit = pricing.holiday_deposit_cents(estimated_total)
            order["deposit_cents"] = deposit
            # Charge the deposit: it is a charge, not a refund; store credit is
            # only a refund destination, so we do not touch store_credit here.
            common.reconcile_window_committed(window)
            db.touch(window)
        db.touch(order)

        return response.object_response(serializers.custom_order(order), 201)

    @app.route("/custom-orders/<rid>", methods=["GET"])
    def get_custom_order(rid):
        _uid, role = authenticate()
        require_role(role, {"Customer", "CounterClerk", "ShiftManager", "Butcher"})
        record = common.get_or_404(db.custom_orders, rid)
        return response.object_response(serializers.custom_order(record))

    @app.route("/custom-orders/<rid>/order-lines", methods=["GET"])
    def list_order_lines_for_order(rid):
        _uid, role = authenticate()
        require_role(role, {"Customer", "CounterClerk", "ShiftManager", "Butcher"})
        common.get_or_404(db.custom_orders, rid)
        records = [l for l in db.order_lines.values()
                   if l["custom_order_id"] == rid]
        line_status = request.args.get("line_status")
        if line_status is not None:
            records = [r for r in records if r["line_status"] == line_status]
        return list_response(records, request.args, serializers.order_line)

    @app.route("/custom-orders/<rid>/confirm", methods=["POST"])
    def confirm_order(rid):
        _uid, role = authenticate()
        require_role(role, {"CounterClerk"})
        order = common.get_or_404(db.custom_orders, rid)
        if order["order_status"] != "PLACED":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Order is not PLACED; cannot confirm.")
        lines = [l for l in db.order_lines.values()
                 if l["custom_order_id"] == rid]
        if len(lines) < 1:
            errors.fail(errors.ERR_INVALID_STATE, "Order has no lines.")
        # Holiday cutoff gate on confirm (PRD §3.5).
        if order["order_kind"] == "HOLIDAY":
            window = db.holiday_windows.get(order["holiday_window_id"])
            if window is not None:
                now = db.current_utc()
                cutoff = common.parse_iso(window["cutoff_at"], "cutoff_at")
                if now > cutoff:
                    errors.fail(errors.ERR_WINDOW_CUTOFF_PASSED,
                                "Holiday window cutoff has passed.")
        order["order_status"] = "CONFIRMED"
        db.touch(order)
        return response.object_response(serializers.custom_order(order))

    @app.route("/custom-orders/<rid>/fill", methods=["POST"])
    def fill_order(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher"})
        order = common.get_or_404(db.custom_orders, rid)
        if order["order_status"] != "CONFIRMED":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Order is not CONFIRMED; cannot fill.")
        lines = [l for l in db.order_lines.values()
                 if l["custom_order_id"] == rid]
        statuses = [l["line_status"] for l in lines]
        all_drawn = all(s == "DRAWN" for s in statuses)
        any_shorted = any(s == "SHORTED" for s in statuses)
        any_drawn = any(s == "DRAWN" for s in statuses)

        if all_drawn:
            # Branch A: FILLED. final_total over all lines.
            final_total = sum(l["final_line_cents"] or 0 for l in lines)
            order["order_status"] = "FILLED"
        elif any_shorted and any_drawn:
            # Branch B: SHORT_FILLED. final_total over DRAWN lines only.
            final_total = sum(
                l["final_line_cents"] or 0 for l in lines
                if l["line_status"] == "DRAWN")
            order["order_status"] = "SHORT_FILLED"
        else:
            # No defined fill outcome (e.g. PENDING lines remain, or all shorted).
            errors.fail(errors.ERR_INVALID_STATE,
                        "Order lines are not in a fillable configuration.")

        order["final_total_cents"] = final_total
        # Holiday deposit reconciliation: refund overage to store credit.
        if order["order_kind"] == "HOLIDAY":
            overage = order["deposit_cents"] - final_total
            if overage > 0:
                common.credit_customer(order["customer_id"], overage)
        db.touch(order)
        return response.object_response(serializers.custom_order(order))

    @app.route("/custom-orders/<rid>/cancel", methods=["POST"])
    def cancel_order(rid):
        uid, role = authenticate()
        require_role(role, {"Customer", "CounterClerk"})
        order = common.get_or_404(db.custom_orders, rid)

        # Ownership for Customer (PRD §2.10 #3) before state.
        if role == "Customer" and order["customer_id"] != uid:
            errors.fail(errors.ERR_NOT_RESOURCE_OWNER,
                        "Customer does not own this order.")

        status = order["order_status"]
        if role == "Customer":
            # A customer may cancel their own order while PLACED.
            if status != "PLACED":
                errors.fail(errors.ERR_INVALID_STATE,
                            "Order is not PLACED; cannot cancel.")
        else:  # CounterClerk
            # A clerk may cancel a PLACED order or a CONFIRMED order with no
            # drawn line.
            if status == "PLACED":
                pass
            elif status == "CONFIRMED":
                drawn = any(
                    l["line_status"] == "DRAWN"
                    for l in db.order_lines.values()
                    if l["custom_order_id"] == rid)
                if drawn:
                    errors.fail(errors.ERR_INVALID_STATE,
                                "Order has drawn lines; cannot cancel.")
            else:
                errors.fail(errors.ERR_INVALID_STATE,
                            "Order cannot be cancelled from %s." % status)

        order["order_status"] = "CANCELLED"
        # Holiday: refund deposit + recompute committed_g.
        if order["order_kind"] == "HOLIDAY":
            if order["deposit_cents"] > 0:
                common.credit_customer(order["customer_id"], order["deposit_cents"])
            window = db.holiday_windows.get(order["holiday_window_id"])
            if window is not None:
                common.reconcile_window_committed(window)
                db.touch(window)
        db.touch(order)
        return response.object_response(serializers.custom_order(order))

    # ---- OrderLine ----
    @app.route("/order-lines/<rid>", methods=["GET"])
    def get_order_line(rid):
        _uid, role = authenticate()
        require_role(role, {"Customer", "CounterClerk", "ShiftManager", "Butcher"})
        record = common.get_or_404(db.order_lines, rid)
        return response.object_response(serializers.order_line(record))

    @app.route("/order-lines", methods=["GET"])
    def list_order_lines():
        _uid, role = authenticate()
        require_role(role, {"Customer", "CounterClerk", "ShiftManager", "Butcher"})
        records = list(db.order_lines.values())
        custom_order_id = request.args.get("custom_order_id")
        cut_type_id = request.args.get("cut_type_id")
        drawn_lot_id = request.args.get("drawn_lot_id")
        line_status = request.args.get("line_status")
        if custom_order_id is not None:
            records = [r for r in records
                       if r["custom_order_id"] == custom_order_id]
        if cut_type_id is not None:
            records = [r for r in records if r["cut_type_id"] == cut_type_id]
        if drawn_lot_id is not None:
            records = [r for r in records if r.get("drawn_lot_id") == drawn_lot_id]
        if line_status is not None:
            records = [r for r in records if r["line_status"] == line_status]
        return list_response(records, request.args, serializers.order_line)

    @app.route("/order-lines/<rid>/draw", methods=["POST"])
    def draw_order_line(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher"})
        line = common.get_or_404(db.order_lines, rid)
        body = v.get_body()
        drawn_lot_id = v.as_str(v.require(body, "drawn_lot_id"), "drawn_lot_id")
        catch_weight_g = v.as_int(
            v.require(body, "catch_weight_g"), "catch_weight_g", minimum=1)
        expected_version = v.as_int(
            v.require(body, "expected_inventory_lot_version"),
            "expected_inventory_lot_version")

        lot = common.fk_or_404(db.inventory_lots, drawn_lot_id)
        order = db.custom_orders.get(line["custom_order_id"])

        # State: line must be PENDING (transition defined), order CONFIRMED.
        if line["line_status"] != "PENDING":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Order line is not PENDING; cannot draw.")
        if order is None or order["order_status"] != "CONFIRMED":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Parent order is not CONFIRMED.")

        # Lot availability (PRD §3.5 ordering): not-available, with the ON_HOLD/
        # quarantined locker case surfacing ERR_LOCKER_QUARANTINED.
        if lot["lot_status"] != "AVAILABLE":
            if lot["lot_status"] == "ON_HOLD":
                locker = db.dry_age_lockers.get(lot.get("locker_id"))
                if locker is not None and locker["locker_status"] == "QUARANTINED":
                    errors.fail(errors.ERR_LOCKER_QUARANTINED,
                                "Lot is held under a quarantined locker.")
            errors.fail(errors.ERR_LOT_NOT_AVAILABLE, "Lot is not AVAILABLE.")

        # Cut-type match.
        if lot["cut_type_id"] != line["cut_type_id"]:
            errors.fail(errors.ERR_CUT_TYPE_MISMATCH,
                        "Lot cut type does not match the line.")
        # Sufficient remaining weight.
        if lot["remaining_weight_g"] < catch_weight_g:
            errors.fail(errors.ERR_INSUFFICIENT_LOT_WEIGHT,
                        "Lot has insufficient remaining weight.")
        # OCC: expected_inventory_lot_version.
        if expected_version != lot["version"]:
            errors.fail(errors.ERR_STALE_LOT_VERSION, "Stale lot version.")

        # Commit the draw.
        draw = {
            "inventory_lot_id": lot["id"],
            "order_line_id": line["id"],
            "batch_input_id": None,
            "weight_g": catch_weight_g,
            "draw_status": "COMMITTED",
        }
        db.stamp_create(draw)
        db.lot_draws[draw["id"]] = draw

        common.reconcile_lot_remaining(lot)
        db.touch(lot)
        if lot["remaining_weight_g"] == 0 and lot["lot_status"] == "AVAILABLE":
            lot["lot_status"] = "DEPLETED"
            db.touch(lot)

        # Final-variant pricing.
        cut = db.cut_types.get(line["cut_type_id"])
        customer = db.customers.get(order["customer_id"])
        policy = common.active_policy_or_400()
        final_cents = pricing.final_line_cents(
            catch_weight_g, cut, policy, customer["loyalty_tier"])

        line["catch_weight_g"] = catch_weight_g
        line["drawn_lot_id"] = lot["id"]
        line["final_line_cents"] = final_cents
        line["line_status"] = "DRAWN"
        db.touch(line)
        return response.object_response(serializers.order_line(line))

    @app.route("/order-lines/<rid>/short", methods=["POST"])
    def short_order_line(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher"})
        line = common.get_or_404(db.order_lines, rid)
        order = db.custom_orders.get(line["custom_order_id"])
        if line["line_status"] != "PENDING":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Order line is not PENDING; cannot short.")
        if order is None or order["order_status"] != "CONFIRMED":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Parent order is not CONFIRMED.")
        line["final_line_cents"] = 0
        line["line_status"] = "SHORTED"
        db.touch(line)
        return response.object_response(serializers.order_line(line))
