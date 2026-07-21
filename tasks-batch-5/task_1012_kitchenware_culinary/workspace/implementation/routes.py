"""All API route handlers."""
from datetime import timedelta

from flask import request

import db
from db import serialize, touch, new_entity, sort_key
from util import new_id, parse_dt
from errors import err
from envelope import success, success_list
from auth import (
    authenticate,
    authorize,
    require_ownership,
    body_json,
    get_str,
    get_enum,
    get_int,
    get_bool,
    parse_pagination,
    paginate,
)
from constants import (
    ROLE_ADMIN,
    ROLE_ASSOCIATE,
    ROLE_MEMBER,
    STORE_STATES,
    STORE_STATUSES,
    SKU_CATEGORIES,
    SKU_STATUSES,
    FULFILLMENT_TYPES,
    CLASS_STATIONS,
    SERVICE_TYPES,
    RETURN_REASONS,
    REFUND_DESTINATIONS,
    REGISTRY_EVENTS,
    TIER_STANDARD,
    RETURN_WINDOW_DAYS,
    SERVICE_BUFFER_MINUTES,
)
from calc import (
    order_pricing,
    loyalty_points,
    points_reversed as calc_points_reversed,
    compute_tier,
    recompute_available,
    recompute_registered_count,
    line_gross,
)

ALL_ROLES = {ROLE_ADMIN, ROLE_ASSOCIATE, ROLE_MEMBER}
STAFF = {ROLE_ADMIN, ROLE_ASSOCIATE}
ADMIN_ONLY = {ROLE_ADMIN}


def fetch(coll, id_, err_id):
    entity = coll.get(id_)
    if entity is None:
        raise err(err_id, f"{err_id}")
    return entity


def list_response(coll, predicate=None):
    limit, offset = parse_pagination()
    items = [e for e in coll.values() if (predicate is None or predicate(e))]
    items.sort(key=sort_key)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize(e) for e in page], limit, offset, total)


# =====================================================================
# Registration
# =====================================================================

def register(app):
    # ---- clock ----
    @app.post("/_clock/set_current_utc")
    def set_clock():
        ctx = authenticate()
        authorize(ctx, ADMIN_ONLY)
        body = body_json()
        iso = get_str(body, "to_iso8601")
        db.set_clock(parse_dt(iso))
        return success({}, 200)

    # ================= Stores =================
    @app.post("/stores")
    def create_store():
        ctx = authenticate()
        authorize(ctx, ADMIN_ONLY)
        body = body_json()
        name = get_str(body, "name")
        state_code = get_enum(body, "state_code", STORE_STATES)
        status = get_enum(body, "status", STORE_STATUSES, required=False) or "OPEN"
        store = new_entity()
        store.update(name=name, state_code=state_code, status=status)
        db.stores[store["id"]] = store
        return success(serialize(store), 201)

    @app.get("/stores/<sid>")
    def get_store(sid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        return success(serialize(fetch(db.stores, sid, "ERR_STORE_NOT_FOUND")), 200)

    # ================= Skus =================
    @app.post("/skus")
    def create_sku():
        ctx = authenticate()
        authorize(ctx, ADMIN_ONLY)
        body = body_json()
        name = get_str(body, "name")
        category = get_enum(body, "category", SKU_CATEGORIES)
        list_price_cents = get_int(body, "list_price_cents", minimum=0)
        on_hand_qty = get_int(body, "on_hand_qty", minimum=0)
        is_bundle = get_bool(body, "is_bundle", default=False)
        status = get_enum(body, "status", SKU_STATUSES, required=False) or "ACTIVE"
        if is_bundle:
            comp = body.get("component_sku_ids", [])
            if comp is None:
                comp = []
            if not isinstance(comp, list) or not all(isinstance(x, str) for x in comp):
                raise err("ERR_VALIDATION", "component_sku_ids must be an array of strings")
            bundle_price_cents = get_int(body, "bundle_price_cents", minimum=0)
        else:
            comp = []
            bundle_price_cents = None
        sku = new_entity()
        sku.update(
            name=name,
            category=category,
            list_price_cents=list_price_cents,
            is_bundle=bool(is_bundle),
            component_sku_ids=comp,
            bundle_price_cents=bundle_price_cents,
            on_hand_qty=on_hand_qty,
            reserved_qty=0,
            available_qty=on_hand_qty,
            status=status,
        )
        db.skus[sku["id"]] = sku
        return success(serialize(sku), 201)

    @app.get("/skus/<sid>")
    def get_sku(sid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        return success(serialize(fetch(db.skus, sid, "ERR_SKU_NOT_FOUND")), 200)

    # ================= Members =================
    @app.post("/members")
    def create_member():
        ctx = authenticate()
        authorize(ctx, STAFF)
        body = body_json()
        email = get_str(body, "email")
        full_name = get_str(body, "full_name")
        home_store_id = get_str(body, "home_store_id")
        fetch(db.stores, home_store_id, "ERR_STORE_NOT_FOUND")
        member = new_entity()
        member.update(
            email=email,
            full_name=full_name,
            home_store_id=home_store_id,
            tier=TIER_STANDARD,
            annual_spend_cents=0,
            pending_points=0,
            earned_points=0,
            wallet_credit_cents=0,
        )
        db.members[member["id"]] = member
        return success(serialize(member), 201)

    @app.get("/members/<mid>")
    def get_member(mid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        return success(serialize(fetch(db.members, mid, "ERR_MEMBER_NOT_FOUND")), 200)

    @app.get("/members")
    def list_members():
        ctx = authenticate()
        authorize(ctx, STAFF)
        home_store_id = request.args.get("home_store_id")
        pred = (lambda m: m["home_store_id"] == home_store_id) if home_store_id else None
        return list_response(db.members, pred)

    @app.post("/members/<mid>/redeem")
    def redeem(mid):
        ctx = authenticate()
        authorize(ctx, {ROLE_MEMBER, ROLE_ASSOCIATE})
        body = body_json()
        points = get_int(body, "points", minimum=1)
        member = fetch(db.members, mid, "ERR_MEMBER_NOT_FOUND")
        require_ownership(ctx, member["id"])
        if points > member["earned_points"]:
            raise err("ERR_INSUFFICIENT_POINTS", "Redemption exceeds earned points")
        member["earned_points"] -= points
        member["wallet_credit_cents"] += points
        touch(member)
        return success(serialize(member), 200)

    # ================= Orders =================
    @app.post("/orders")
    def create_order():
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        body = body_json()
        member_id = get_str(body, "member_id")
        store_id = get_str(body, "store_id")
        fulfillment_type = get_enum(body, "fulfillment_type", FULFILLMENT_TYPES)
        lines_in = body.get("lines")
        if not isinstance(lines_in, list):
            raise err("ERR_VALIDATION", "lines must be an array")
        parsed = []
        for l in lines_in:
            if not isinstance(l, dict):
                raise err("ERR_VALIDATION", "each line must be an object")
            parsed.append({
                "sku_id": get_str(l, "sku_id"),
                "qty": get_int(l, "qty", minimum=1),
                "is_gift": bool(get_bool(l, "is_gift", default=False)),
            })
        # existence: member, store, then each sku left-to-right
        member = fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
        store = fetch(db.stores, store_id, "ERR_STORE_NOT_FOUND")
        line_skus = [fetch(db.skus, pl["sku_id"], "ERR_SKU_NOT_FOUND") for pl in parsed]
        # state: sku must be ACTIVE
        for sku in line_skus:
            if sku["status"] != "ACTIVE":
                raise err("ERR_DISCONTINUED_SKU", "SKU is discontinued")
        # constraint: availability (cumulative per sku, left-to-right)
        running = {}
        for pl, sku in zip(parsed, line_skus):
            running[sku["id"]] = running.get(sku["id"], 0) + pl["qty"]
            if running[sku["id"]] > sku["available_qty"]:
                raise err("ERR_INSUFFICIENT_STOCK", "Insufficient stock")
        # build order
        order = new_entity()
        lines = []
        reserved_add = {}
        for pl, sku in zip(parsed, line_skus):
            unit_price = sku["bundle_price_cents"] if sku["is_bundle"] else sku["list_price_cents"]
            lines.append({
                "line_id": new_id(),
                "sku_id": sku["id"],
                "qty": pl["qty"],
                "unit_price_cents": unit_price,
                "line_status": "RESERVED",
                "is_gift": pl["is_gift"],
            })
            reserved_add[sku["id"]] = reserved_add.get(sku["id"], 0) + pl["qty"]
        tier = member["tier"]
        subtotal, discount, tax, total = order_pricing(lines, tier, store["state_code"])
        pending = loyalty_points(lines, tier)
        order.update(
            member_id=member_id,
            store_id=store_id,
            fulfillment_type=fulfillment_type,
            lines=lines,
            payment_status="UNPAID",
            fulfillment_status="RESERVED",
            tier_at_pricing=tier,
            subtotal_cents=subtotal,
            tier_discount_cents=discount,
            tax_cents=tax,
            total_cents=total,
            pending_points=pending,
            earned_points=0,
            refunded_cents=0,
            fulfilled_at=None,
        )
        db.orders[order["id"]] = order
        for sid, add in reserved_add.items():
            sku = db.skus[sid]
            sku["reserved_qty"] += add
            recompute_available(sku)
            touch(sku)
        member["pending_points"] += pending
        touch(member)
        return success(serialize(order), 201)

    @app.get("/orders/<oid>")
    def get_order(oid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        return success(serialize(fetch(db.orders, oid, "ERR_ORDER_NOT_FOUND")), 200)

    @app.get("/orders")
    def list_orders():
        ctx = authenticate()
        authorize(ctx, STAFF)
        member_id = request.args.get("member_id")
        store_id = request.args.get("store_id")

        def pred(o):
            if member_id and o["member_id"] != member_id:
                return False
            if store_id and o["store_id"] != store_id:
                return False
            return True

        return list_response(db.orders, pred)

    @app.post("/orders/<oid>/pay")
    def pay_order(oid):
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        order = fetch(db.orders, oid, "ERR_ORDER_NOT_FOUND")
        if order["fulfillment_status"] != "RESERVED" or order["payment_status"] != "UNPAID":
            raise err("ERR_INVALID_STATE", "Order cannot be paid in its current state")
        order["payment_status"] = "PAID"
        touch(order)
        return success(serialize(order), 200)

    @app.post("/orders/<oid>/fulfill")
    def fulfill_order(oid):
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        body = body_json()
        exclude = body.get("exclude_line_ids", [])
        if exclude is None:
            exclude = []
        if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
            raise err("ERR_VALIDATION", "exclude_line_ids must be an array of strings")
        exclude_set = set(exclude)
        order = fetch(db.orders, oid, "ERR_ORDER_NOT_FOUND")
        # state
        if order["fulfillment_status"] != "RESERVED":
            raise err("ERR_INVALID_STATE", "Order is not RESERVED")
        if order["payment_status"] != "PAID":
            raise err("ERR_PAYMENT_REQUIRED", "Order must be paid before fulfillment")
        store = db.stores.get(order["store_id"])
        if store is None or store["status"] != "OPEN":
            raise err("ERR_STORE_CLOSED", "Store is closed")
        member = db.members[order["member_id"]]
        affected_skus = {}
        for line in order["lines"]:
            if line["line_status"] != "RESERVED":
                continue
            sku = db.skus[line["sku_id"]]
            if line["line_id"] in exclude_set:
                line["line_status"] = "VOID"
                sku["reserved_qty"] -= line["qty"]
            else:
                line["line_status"] = "FULFILLED"
                sku["on_hand_qty"] -= line["qty"]
                sku["reserved_qty"] -= line["qty"]
            affected_skus[sku["id"]] = sku
        for sku in affected_skus.values():
            recompute_available(sku)
            touch(sku)
        fulfilled_lines = [l for l in order["lines"] if l["line_status"] == "FULFILLED"]
        subtotal, discount, tax, total = order_pricing(
            fulfilled_lines, order["tier_at_pricing"], store["state_code"]
        )
        earned = loyalty_points(fulfilled_lines, order["tier_at_pricing"])
        fulfilled_gross = sum(line_gross(l) for l in fulfilled_lines)
        order.update(
            subtotal_cents=subtotal,
            tier_discount_cents=discount,
            tax_cents=tax,
            total_cents=total,
            earned_points=earned,
            fulfilled_at=db.clock_iso(),
            fulfillment_status="FULFILLED",
        )
        touch(order)
        member["earned_points"] += earned
        member["pending_points"] -= order["pending_points"]
        member["annual_spend_cents"] = max(member["annual_spend_cents"] + fulfilled_gross, 0)
        member["tier"] = compute_tier(member["annual_spend_cents"])
        touch(member)
        return success(serialize(order), 200)

    @app.post("/orders/<oid>/cancel")
    def cancel_order(oid):
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        order = fetch(db.orders, oid, "ERR_ORDER_NOT_FOUND")
        if order["fulfillment_status"] != "RESERVED":
            raise err("ERR_INVALID_STATE", "Only RESERVED orders can be canceled")
        member = db.members[order["member_id"]]
        affected_skus = {}
        for line in order["lines"]:
            if line["line_status"] == "RESERVED":
                line["line_status"] = "VOID"
                sku = db.skus[line["sku_id"]]
                sku["reserved_qty"] -= line["qty"]
                affected_skus[sku["id"]] = sku
        for sku in affected_skus.values():
            recompute_available(sku)
            touch(sku)
        member["pending_points"] -= order["pending_points"]
        if order["payment_status"] == "PAID":
            member["wallet_credit_cents"] += order["total_cents"]
            order["refunded_cents"] += order["total_cents"]
            order["payment_status"] = "REFUNDED"
        touch(member)
        order["fulfillment_status"] = "CANCELED"
        touch(order)
        return success(serialize(order), 200)

    # ================= Cooking Classes =================
    @app.post("/cooking-classes")
    def create_class():
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        body = body_json()
        store_id = get_str(body, "store_id")
        title = get_str(body, "title")
        station = get_enum(body, "station", CLASS_STATIONS)
        start_at = get_str(body, "start_at")
        end_at = get_str(body, "end_at")
        capacity = get_int(body, "capacity", minimum=1)
        price_cents = get_int(body, "price_cents", minimum=0)
        s_dt = parse_dt(start_at)
        e_dt = parse_dt(end_at)
        if e_dt <= s_dt:
            raise err("ERR_VALIDATION", "end_at must be after start_at")
        fetch(db.stores, store_id, "ERR_STORE_NOT_FOUND")
        # station overlap (half-open) among non-canceled classes
        for c in db.cooking_classes.values():
            if c["store_id"] != store_id or c["station"] != station:
                continue
            if c["status"] == "CANCELED":
                continue
            cs = parse_dt(c["start_at"])
            ce = parse_dt(c["end_at"])
            if s_dt < ce and cs < e_dt:
                raise err("ERR_CLASS_STATION_CONFLICT", "Station is already booked")
        cls = new_entity()
        cls.update(
            store_id=store_id,
            title=title,
            station=station,
            start_at=start_at,
            end_at=end_at,
            capacity=capacity,
            price_cents=price_cents,
            registered_count=0,
            status="DRAFT",
        )
        db.cooking_classes[cls["id"]] = cls
        return success(serialize(cls), 201)

    @app.get("/cooking-classes/<cid>")
    def get_class(cid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        return success(serialize(fetch(db.cooking_classes, cid, "ERR_CLASS_NOT_FOUND")), 200)

    @app.get("/cooking-classes")
    def list_classes():
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        store_id = request.args.get("store_id")
        pred = (lambda c: c["store_id"] == store_id) if store_id else None
        return list_response(db.cooking_classes, pred)

    @app.post("/cooking-classes/<cid>/open")
    def open_class(cid):
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        cls = fetch(db.cooking_classes, cid, "ERR_CLASS_NOT_FOUND")
        if cls["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Class is not DRAFT")
        cls["status"] = "OPEN"
        touch(cls)
        return success(serialize(cls), 200)

    @app.post("/cooking-classes/<cid>/complete")
    def complete_class(cid):
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        cls = fetch(db.cooking_classes, cid, "ERR_CLASS_NOT_FOUND")
        if cls["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Class is not OPEN")
        cls["status"] = "COMPLETED"
        touch(cls)
        return success(serialize(cls), 200)

    @app.post("/cooking-classes/<cid>/cancel")
    def cancel_class(cid):
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        cls = fetch(db.cooking_classes, cid, "ERR_CLASS_NOT_FOUND")
        if cls["status"] not in ("DRAFT", "OPEN"):
            raise err("ERR_INVALID_STATE", "Class cannot be canceled")
        for reg in db.class_registrations.values():
            if reg["class_id"] == cls["id"] and reg["status"] == "BOOKED":
                reg["status"] = "CANCELED"
                touch(reg)
        cls["status"] = "CANCELED"
        recompute_registered_count(cls, db.class_registrations)
        touch(cls)
        return success(serialize(cls), 200)

    # ================= Class Registrations =================
    @app.post("/class-registrations")
    def create_registration():
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        body = body_json()
        class_id = get_str(body, "class_id")
        member_id = get_str(body, "member_id")
        order_id = get_str(body, "order_id", required=False)
        cls = fetch(db.cooking_classes, class_id, "ERR_CLASS_NOT_FOUND")
        member = fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
        if order_id is not None:
            fetch(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
        require_ownership(ctx, member["id"])
        if cls["status"] != "OPEN":
            raise err("ERR_CLASS_NOT_OPEN", "Class is not open for registration")
        if db.get_clock() >= parse_dt(cls["start_at"]):
            raise err("ERR_REGISTRATION_CLOSED", "Registration is closed")
        if cls["registered_count"] >= cls["capacity"]:
            raise err("ERR_CLASS_FULL", "Class is full")
        reg = new_entity()
        reg.update(
            class_id=class_id,
            member_id=member_id,
            order_id=order_id,
            seat_price_cents=cls["price_cents"],
            status="BOOKED",
        )
        db.class_registrations[reg["id"]] = reg
        recompute_registered_count(cls, db.class_registrations)
        touch(cls)
        return success(serialize(reg), 201)

    @app.get("/class-registrations/<rid>")
    def get_registration(rid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        return success(
            serialize(fetch(db.class_registrations, rid, "ERR_REGISTRATION_NOT_FOUND")), 200
        )

    @app.get("/class-registrations")
    def list_registrations():
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        class_id = request.args.get("class_id")
        member_id = request.args.get("member_id")
        order_id = request.args.get("order_id")

        def pred(r):
            if class_id and r["class_id"] != class_id:
                return False
            if member_id and r["member_id"] != member_id:
                return False
            if order_id and r["order_id"] != order_id:
                return False
            return True

        return list_response(db.class_registrations, pred)

    @app.post("/class-registrations/<rid>/mark-attendance")
    def mark_attendance(rid):
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        body = body_json()
        attended = get_bool(body, "attended", required=True)
        reg = fetch(db.class_registrations, rid, "ERR_REGISTRATION_NOT_FOUND")
        if reg["status"] != "BOOKED":
            raise err("ERR_INVALID_STATE", "Registration is not BOOKED")
        reg["status"] = "ATTENDED" if attended else "NO_SHOW"
        touch(reg)
        cls = db.cooking_classes[reg["class_id"]]
        recompute_registered_count(cls, db.class_registrations)
        touch(cls)
        return success(serialize(reg), 200)

    @app.post("/class-registrations/<rid>/cancel")
    def cancel_registration(rid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        reg = fetch(db.class_registrations, rid, "ERR_REGISTRATION_NOT_FOUND")
        require_ownership(ctx, reg["member_id"])
        if reg["status"] != "BOOKED":
            raise err("ERR_INVALID_STATE", "Registration is not BOOKED")
        reg["status"] = "CANCELED"
        touch(reg)
        cls = db.cooking_classes[reg["class_id"]]
        recompute_registered_count(cls, db.class_registrations)
        touch(cls)
        return success(serialize(reg), 200)

    # ================= Service Tickets =================
    @app.post("/service-tickets")
    def create_service_ticket():
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        body = body_json()
        store_id = get_str(body, "store_id")
        service_type = get_enum(body, "service_type", SERVICE_TYPES)
        start_at = get_str(body, "start_at")
        end_at = get_str(body, "end_at")
        price_cents = get_int(body, "price_cents", minimum=0)
        member_id = get_str(body, "member_id", required=False)
        s_dt = parse_dt(start_at)
        e_dt = parse_dt(end_at)
        if e_dt <= s_dt:
            raise err("ERR_VALIDATION", "end_at must be after start_at")
        fetch(db.stores, store_id, "ERR_STORE_NOT_FOUND")
        if member_id is not None:
            fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
        buf = timedelta(minutes=SERVICE_BUFFER_MINUTES)
        for t in db.service_tickets.values():
            if t["store_id"] != store_id or t["service_type"] != service_type:
                continue
            if t["status"] == "CANCELED":
                continue
            ts = parse_dt(t["start_at"])
            te = parse_dt(t["end_at"])
            if (s_dt - buf) < te and ts < (e_dt + buf):
                raise err("ERR_SERVICE_SLOT_CONFLICT", "Service slot conflict")
        ticket = new_entity()
        ticket.update(
            store_id=store_id,
            member_id=member_id,
            service_type=service_type,
            start_at=start_at,
            end_at=end_at,
            price_cents=price_cents,
            status="SCHEDULED",
        )
        db.service_tickets[ticket["id"]] = ticket
        return success(serialize(ticket), 201)

    @app.get("/service-tickets/<tid>")
    def get_service_ticket(tid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        return success(
            serialize(fetch(db.service_tickets, tid, "ERR_SERVICE_TICKET_NOT_FOUND")), 200
        )

    @app.get("/service-tickets")
    def list_service_tickets():
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        store_id = request.args.get("store_id")
        member_id = request.args.get("member_id")

        def pred(t):
            if store_id and t["store_id"] != store_id:
                return False
            if member_id and t["member_id"] != member_id:
                return False
            return True

        return list_response(db.service_tickets, pred)

    @app.post("/service-tickets/<tid>/complete")
    def complete_service_ticket(tid):
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        ticket = fetch(db.service_tickets, tid, "ERR_SERVICE_TICKET_NOT_FOUND")
        if ticket["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Ticket is not SCHEDULED")
        ticket["status"] = "COMPLETED"
        touch(ticket)
        return success(serialize(ticket), 200)

    @app.post("/service-tickets/<tid>/cancel")
    def cancel_service_ticket(tid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        ticket = fetch(db.service_tickets, tid, "ERR_SERVICE_TICKET_NOT_FOUND")
        if ticket["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Ticket is not SCHEDULED")
        ticket["status"] = "CANCELED"
        touch(ticket)
        return success(serialize(ticket), 200)

    # ================= Returns =================
    @app.post("/returns")
    def create_return():
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        body = body_json()
        order_id = get_str(body, "order_id")
        member_id = get_str(body, "member_id")
        line_id = get_str(body, "line_id")
        return_qty = get_int(body, "return_qty", minimum=1)
        reason = get_enum(body, "reason", RETURN_REASONS)
        refund_destination = get_enum(body, "refund_destination", REFUND_DESTINATIONS)
        order = fetch(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
        fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
        line = next((l for l in order["lines"] if l["line_id"] == line_id), None)
        if line is None:
            raise err("ERR_LINE_NOT_FOUND", "Line not found on order")
        # ownership: member must own the underlying order
        require_ownership(ctx, order["member_id"])
        # state
        if order["fulfillment_status"] != "FULFILLED":
            raise err("ERR_ORDER_NOT_FULFILLED", "Order is not fulfilled")
        if line["line_status"] != "FULFILLED":
            raise err("ERR_INVALID_STATE", "Target line is not fulfilled")
        # temporal
        deadline = parse_dt(order["fulfilled_at"]) + timedelta(days=RETURN_WINDOW_DAYS)
        if db.get_clock() > deadline:
            raise err("ERR_RETURN_WINDOW_EXPIRED", "Return window expired")
        # value bound relative to the line
        if return_qty > line["qty"]:
            raise err("ERR_VALIDATION", "return_qty exceeds line quantity")
        ret = new_entity()
        ret.update(
            order_id=order_id,
            member_id=member_id,
            line_id=line_id,
            return_qty=return_qty,
            reason=reason,
            refund_destination=refund_destination,
            refund_amount_cents=None,
            points_reversed=None,
            status="REQUESTED",
        )
        db.returns[ret["id"]] = ret
        return success(serialize(ret), 201)

    @app.get("/returns/<rid>")
    def get_return(rid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        return success(serialize(fetch(db.returns, rid, "ERR_RETURN_NOT_FOUND")), 200)

    @app.get("/returns")
    def list_returns():
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        order_id = request.args.get("order_id")
        member_id = request.args.get("member_id")

        def pred(r):
            if order_id and r["order_id"] != order_id:
                return False
            if member_id and r["member_id"] != member_id:
                return False
            return True

        return list_response(db.returns, pred)

    @app.post("/returns/<rid>/approve")
    def approve_return(rid):
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        ret = fetch(db.returns, rid, "ERR_RETURN_NOT_FOUND")
        if ret["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Return is not REQUESTED")
        order = db.orders[ret["order_id"]]
        line = next((l for l in order["lines"] if l["line_id"] == ret["line_id"]), None)
        if line is None:
            raise err("ERR_LINE_NOT_FOUND", "Line not found on order")
        # state: line must be fulfilled and not already returned
        if line["line_status"] == "RETURNED":
            raise err("ERR_LINE_ALREADY_RETURNED", "Line already returned")
        if line["line_status"] != "FULFILLED":
            raise err("ERR_INVALID_STATE", "Line is not fulfilled")
        # fiscal: refund must not exceed the order's unrefunded paid amount
        refund_amount = line["unit_price_cents"] * ret["return_qty"]
        already_refunded = sum(
            r["refund_amount_cents"] or 0
            for r in db.returns.values()
            if r["order_id"] == order["id"] and r["status"] == "APPROVED"
        )
        if refund_amount > order["total_cents"] - already_refunded:
            raise err("ERR_REFUND_EXCEEDS_PAID", "Refund exceeds unrefunded paid amount")
        pts_reversed = calc_points_reversed(line, ret["return_qty"], order["tier_at_pricing"])
        returned_gross = refund_amount
        member = db.members[order["member_id"]]
        # cascade
        line["line_status"] = "RETURNED"
        sku = db.skus[line["sku_id"]]
        sku["on_hand_qty"] += ret["return_qty"]
        recompute_available(sku)
        touch(sku)
        member["annual_spend_cents"] = max(member["annual_spend_cents"] - returned_gross, 0)
        member["earned_points"] = max(member["earned_points"] - pts_reversed, 0)
        member["tier"] = compute_tier(member["annual_spend_cents"])
        if ret["refund_destination"] == "WALLET":
            member["wallet_credit_cents"] += refund_amount
        else:
            order["refunded_cents"] += refund_amount
        touch(member)
        touch(order)
        ret["refund_amount_cents"] = refund_amount
        ret["points_reversed"] = pts_reversed
        ret["status"] = "APPROVED"
        touch(ret)
        return success(serialize(ret), 200)

    @app.post("/returns/<rid>/reject")
    def reject_return(rid):
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        ret = fetch(db.returns, rid, "ERR_RETURN_NOT_FOUND")
        if ret["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Return is not REQUESTED")
        ret["status"] = "REJECTED"
        touch(ret)
        return success(serialize(ret), 200)

    # ================= Special Orders =================
    @app.post("/special-orders")
    def create_special_order():
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        body = body_json()
        member_id = get_str(body, "member_id")
        store_id = get_str(body, "store_id")
        description = get_str(body, "description")
        estimated_cost_cents = get_int(body, "estimated_cost_cents", minimum=0)
        fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
        fetch(db.stores, store_id, "ERR_STORE_NOT_FOUND")
        so = new_entity()
        so.update(
            member_id=member_id,
            store_id=store_id,
            description=description,
            estimated_cost_cents=estimated_cost_cents,
            quoted_total_cents=None,
            quote_revision=0,
            deposit_cents=None,
            status="DRAFT",
        )
        db.special_orders[so["id"]] = so
        return success(serialize(so), 201)

    @app.get("/special-orders/<sid>")
    def get_special_order(sid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        return success(
            serialize(fetch(db.special_orders, sid, "ERR_SPECIAL_ORDER_NOT_FOUND")), 200
        )

    @app.get("/special-orders")
    def list_special_orders():
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        member_id = request.args.get("member_id")
        store_id = request.args.get("store_id")

        def pred(s):
            if member_id and s["member_id"] != member_id:
                return False
            if store_id and s["store_id"] != store_id:
                return False
            return True

        return list_response(db.special_orders, pred)

    @app.post("/special-orders/<sid>/quote")
    def quote_special_order(sid):
        ctx = authenticate()
        authorize(ctx, {ROLE_ASSOCIATE, ROLE_ADMIN})
        body = body_json()
        expected = get_int(body, "expected_special_order_version")
        quoted_total_cents = get_int(body, "quoted_total_cents", minimum=0)
        deposit_cents = get_int(body, "deposit_cents", required=False, minimum=0)
        so = fetch(db.special_orders, sid, "ERR_SPECIAL_ORDER_NOT_FOUND")
        # OCC (priority 5)
        if expected != so["version"]:
            raise err("ERR_STALE_VERSION", "Special order version is stale")
        # state (priority 6)
        if so["status"] not in ("DRAFT", "REVISION_REQUESTED"):
            raise err("ERR_INVALID_STATE", "Special order cannot be quoted")
        so["quoted_total_cents"] = quoted_total_cents
        so["deposit_cents"] = deposit_cents
        so["quote_revision"] += 1
        so["status"] = "QUOTED"
        touch(so)
        return success(serialize(so), 200)

    @app.post("/special-orders/<sid>/request-revision")
    def request_revision(sid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        so = fetch(db.special_orders, sid, "ERR_SPECIAL_ORDER_NOT_FOUND")
        require_ownership(ctx, so["member_id"])
        if so["status"] != "QUOTED":
            raise err("ERR_INVALID_STATE", "Special order is not QUOTED")
        so["status"] = "REVISION_REQUESTED"
        touch(so)
        return success(serialize(so), 200)

    @app.post("/special-orders/<sid>/accept")
    def accept_special_order(sid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        so = fetch(db.special_orders, sid, "ERR_SPECIAL_ORDER_NOT_FOUND")
        require_ownership(ctx, so["member_id"])
        if so["status"] != "QUOTED":
            raise err("ERR_INVALID_STATE", "Special order is not QUOTED")
        so["status"] = "ACCEPTED"
        touch(so)
        return success(serialize(so), 200)

    @app.post("/special-orders/<sid>/cancel")
    def cancel_special_order(sid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        so = fetch(db.special_orders, sid, "ERR_SPECIAL_ORDER_NOT_FOUND")
        require_ownership(ctx, so["member_id"])
        if so["status"] == "ACCEPTED":
            raise err("ERR_INVALID_STATE", "Accepted special orders cannot be canceled")
        so["status"] = "CANCELED"
        touch(so)
        return success(serialize(so), 200)

    # ================= Registries =================
    @app.post("/registries")
    def create_registry():
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        body = body_json()
        member_id = get_str(body, "member_id")
        event_type = get_enum(body, "event_type", REGISTRY_EVENTS)
        event_date = get_str(body, "event_date")
        items_in = body.get("items", [])
        if items_in is None:
            items_in = []
        if not isinstance(items_in, list):
            raise err("ERR_VALIDATION", "items must be an array")
        items = []
        for it in items_in:
            if not isinstance(it, dict):
                raise err("ERR_VALIDATION", "each item must be an object")
            items.append({
                "sku_id": get_str(it, "sku_id"),
                "desired_qty": get_int(it, "desired_qty", minimum=1),
                "purchased_qty": 0,
            })
        fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
        reg = new_entity()
        reg.update(
            member_id=member_id,
            event_type=event_type,
            event_date=event_date,
            items=items,
            status="ACTIVE",
        )
        db.registries[reg["id"]] = reg
        return success(serialize(reg), 201)

    @app.get("/registries/<rid>")
    def get_registry(rid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        return success(serialize(fetch(db.registries, rid, "ERR_REGISTRY_NOT_FOUND")), 200)

    @app.get("/registries")
    def list_registries():
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        member_id = request.args.get("member_id")
        pred = (lambda r: r["member_id"] == member_id) if member_id else None
        return list_response(db.registries, pred)

    @app.post("/registries/<rid>/purchase")
    def purchase_registry(rid):
        ctx = authenticate()
        authorize(ctx, ALL_ROLES)
        body = body_json()
        sku_id = get_str(body, "sku_id")
        qty = get_int(body, "qty", minimum=1)
        reg = fetch(db.registries, rid, "ERR_REGISTRY_NOT_FOUND")
        item = next((it for it in reg["items"] if it["sku_id"] == sku_id), None)
        if item is None:
            raise err("ERR_VALIDATION", "SKU is not on this registry")
        item["purchased_qty"] = min(item["purchased_qty"] + qty, item["desired_qty"])
        touch(reg)
        return success(serialize(reg), 200)
