"""Ticket tiers and the sales window (PRD 3.6, 3.7)."""
from db import clock_dt, clock_raw, db, new_row, touch
from errors import fail
from middleware import (
    ROLE_FINANCE_CONTROLLER,
    ROLE_SERIES_PROMOTER,
    ROLE_SPONSOR_REP,
    ROLE_TICKETING_MANAGER,
    auth,
    enum_filter,
    pagination,
    string_filter,
)
from response import list_response, object_response
from services import calc, derive, flow, serialize
import validate

ORDER_STATUSES = ("PENDING", "PAID", "REFUNDED", "VOID")


def register(app):
    # ------------------------------------------------------------------- tiers
    @app.route("/tour-stops/<stop_id>/ticket-tiers", methods=["POST"])
    def create_tier(stop_id):
        auth(ROLE_TICKETING_MANAGER)
        payload = validate.body()
        tier_code = validate.field_string(payload, "tier_code")
        price = validate.field_int(payload, "price_cents", minimum=0)
        allotment = validate.field_int(payload, "allotment", minimum=1)
        start_raw, start_dt = validate.field_datetime(payload, "on_sale_start_utc")
        end_raw, end_dt = validate.field_datetime(payload, "on_sale_end_utc")
        group_min = validate.field_int(
            payload, "group_min_qty", required=False, default=20, minimum=1
        )
        group_pct = validate.field_number(
            payload, "group_discount_pct", required=False, default=0.125, minimum=0, maximum=1
        )

        stop = derive.get_stop(stop_id)
        flow.ensure_stop_writable(stop)
        flow.ensure_not_frozen(stop)

        show_start = calc.dt(stop["show_start_utc"])
        if start_dt >= end_dt:
            fail("ERR_TIER_WINDOW_INVALID")
        if show_start is not None and end_dt > show_start:
            fail("ERR_TIER_WINDOW_INVALID")
        for other in derive.tiers_of_stop(stop["id"]):
            if other["tier_code"] == tier_code:
                fail("ERR_DUPLICATE_TIER_CODE")

        row = new_row(
            tour_stop_id=stop["id"],
            tier_code=tier_code,
            price_cents=price,
            allotment=allotment,
            group_min_qty=group_min,
            group_discount_pct=group_pct,
            on_sale_start_utc=start_raw,
            on_sale_end_utc=end_raw,
        )
        db.tiers[row["id"]] = row
        touch(stop)  # expected_attendance moved

        plan = flow.refresh_plan_requirements(stop)
        if plan is not None and plan["state"] == "CERTIFIED" and flow.plan_shortfall(plan):
            flow.cascade_b(stop, plan)
        else:
            flow.apply_posture(stop)
        return object_response(serialize.tier(row), 201)

    @app.route("/tour-stops/<stop_id>/ticket-tiers", methods=["GET"])
    def list_tiers(stop_id):
        auth(
            ROLE_SERIES_PROMOTER,
            ROLE_TICKETING_MANAGER,
            ROLE_FINANCE_CONTROLLER,
            ROLE_SPONSOR_REP,
        )
        limit, offset = pagination()
        stop = derive.get_stop(stop_id)
        rows = derive.tiers_of_stop(stop["id"])
        return list_response([serialize.tier(r) for r in rows], limit, offset)

    @app.route("/ticket-tiers/<tier_id>", methods=["GET"])
    def read_tier(tier_id):
        auth(
            ROLE_SERIES_PROMOTER,
            ROLE_TICKETING_MANAGER,
            ROLE_FINANCE_CONTROLLER,
            ROLE_SPONSOR_REP,
        )
        return object_response(serialize.tier(derive.get_tier(tier_id)))

    # ------------------------------------------------------------------ orders
    @app.route("/ticket-orders", methods=["POST"])
    def create_order():
        auth(ROLE_TICKETING_MANAGER)
        payload = validate.body()
        stop_id = validate.field_id(payload, "tour_stop_id")
        tier_id = validate.field_id(payload, "ticket_tier_id")
        purchaser_name = validate.field_string(payload, "purchaser_name")
        purchaser_email = validate.field_string(payload, "purchaser_email")
        qty = validate.field_int(payload, "qty", minimum=1)
        expected_version = validate.field_int(payload, "expected_ticket_tier_version")
        is_group = validate.field_bool(payload, "is_group", default=False)
        addon_qty = validate.field_int(
            payload, "pit_party_addon_qty", required=False, default=0, minimum=0
        )

        stop = derive.get_stop(stop_id)
        tier = derive.get_tier(tier_id)

        if expected_version != tier["version"]:
            fail("ERR_STALE_TIER_VERSION")

        flow.ensure_stop_writable(stop)
        if stop["sales_state"] != "ON_SALE":
            fail("ERR_SALES_NOT_OPEN")
        flow.ensure_not_frozen(stop)

        if tier["tour_stop_id"] != stop["id"]:
            fail("ERR_CHILD_STOP_MISMATCH")

        now = clock_dt()
        if now < calc.dt(tier["on_sale_start_utc"]) or now > calc.dt(tier["on_sale_end_utc"]):
            fail("ERR_TIER_WINDOW_CLOSED")
        if is_group and qty < tier["group_min_qty"]:
            fail("ERR_GROUP_MINIMUM_NOT_MET")
        if addon_qty > qty:
            fail("ERR_PIT_PARTY_CAPACITY_EXCEEDED")
        if derive.stop_pit_party_sold_count(stop) + addon_qty > stop["pit_party_capacity"]:
            fail("ERR_PIT_PARTY_CAPACITY_EXCEEDED")
        if derive.tier_available(tier) < qty:
            fail("ERR_TIER_SOLD_OUT")

        booking = derive.booking_of_stop(stop)
        amounts = calc.ticket_order_amounts(tier, stop, booking, qty, is_group, addon_qty)
        row = new_row(
            tour_stop_id=stop["id"],
            ticket_tier_id=tier["id"],
            purchaser_name=purchaser_name,
            purchaser_email=purchaser_email,
            qty=qty,
            is_group=is_group,
            pit_party_addon_qty=addon_qty,
            status="PENDING",
            paid_at=None,
            refunded_at=None,
            void_reason=None,
            **amounts
        )
        db.orders[row["id"]] = row
        touch(tier)  # reserved_seat_count / available_seat_count moved
        return object_response(serialize.order(row), 201)

    @app.route("/ticket-orders", methods=["GET"])
    def list_orders():
        auth(ROLE_SERIES_PROMOTER, ROLE_TICKETING_MANAGER, ROLE_FINANCE_CONTROLLER)
        limit, offset = pagination()
        stop_id = string_filter("tour_stop_id")
        tier_id = string_filter("ticket_tier_id")
        status = enum_filter("status", ORDER_STATUSES)
        rows = derive.all_orders()
        if stop_id is not None:
            rows = [r for r in rows if r["tour_stop_id"] == stop_id]
        if tier_id is not None:
            rows = [r for r in rows if r["ticket_tier_id"] == tier_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return list_response([serialize.order(r) for r in rows], limit, offset)

    @app.route("/ticket-orders/<order_id>", methods=["GET"])
    def read_order(order_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_TICKETING_MANAGER, ROLE_FINANCE_CONTROLLER)
        return object_response(serialize.order(derive.get_order(order_id)))

    @app.route("/ticket-orders/<order_id>/pay", methods=["POST"])
    def pay_order(order_id):
        auth(ROLE_TICKETING_MANAGER)
        validate.body()
        order = derive.get_order(order_id)
        stop = db.stops[order["tour_stop_id"]]
        flow.ensure_stop_writable(stop)
        if order["status"] != "PENDING":
            fail("ERR_INVALID_STATE_TRANSITION")
        if stop["sales_state"] not in ("ON_SALE", "SALES_HALTED"):
            fail("ERR_INVALID_STATE_TRANSITION")
        flow.ensure_not_frozen(stop)

        order["status"] = "PAID"
        order["paid_at"] = clock_raw()
        touch(order)
        tier = db.tiers.get(order["ticket_tier_id"])
        if tier is not None:
            touch(tier)
        touch(stop)  # the stop's revenue and count roll-ups moved
        return object_response(serialize.order(order))

    @app.route("/ticket-orders/<order_id>/refund", methods=["POST"])
    def refund_order(order_id):
        auth(ROLE_TICKETING_MANAGER)
        payload = validate.body()
        validate.field_string(payload, "reason")
        order = derive.get_order(order_id)
        stop = db.stops[order["tour_stop_id"]]
        flow.ensure_season_open(derive.season_of_stop(stop))
        if stop["sales_state"] == "SETTLED":
            fail("ERR_INVALID_STATE_TRANSITION", "the owning tour stop is SETTLED")
        if order["status"] != "PAID":
            fail("ERR_INVALID_STATE_TRANSITION")

        order["status"] = "REFUNDED"
        order["refunded_at"] = clock_raw()
        touch(order)
        tier = db.tiers.get(order["ticket_tier_id"])
        if tier is not None:
            touch(tier)
        touch(stop)
        return object_response(serialize.order(order))
