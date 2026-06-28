"""Orders: cart CRUD, lines, submit cascade, payment + fulfillment dimensions,
cancel/refund compensation, compliance-window reads (PRD §3.3 - §3.7, §3.10)."""
import app as A
import calculations as calc
import errors
import middleware
import response
import services
from app import app
from db import store


# ---------------------------------------------------------------------------
# Ownership helper
# ---------------------------------------------------------------------------
def _order_owner_check(role, uid, order):
    if role == A.R_CUSTOMER and uid != order["customer_id"]:
        raise errors.forbidden()


# ---------------------------------------------------------------------------
# Order create / read / list
# ---------------------------------------------------------------------------
@app.route("/orders", methods=["POST"])
def create_order():
    role, uid = middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE})
    body = A.get_body()
    customer_id = A.require_str(body, "customer_id")
    channel = A.require_str(body, "channel")
    dest_state = body.get("dest_state_code", None)

    customer = A.get_or_404(store.customers, customer_id)
    if role == A.R_CUSTOMER and uid != customer_id:
        raise errors.forbidden()

    if channel not in A.CHANNELS:
        raise errors.invalid_request("Invalid channel.")
    if channel in A.SHIPPING_CHANNELS:
        if dest_state is None:
            raise errors.missing_field("dest_state_code required for DELIVERY/SHIP.")
        if not A.is_two_letter_state(dest_state):
            raise errors.invalid_request("dest_state_code must be two uppercase letters.")
    else:
        # POS/PICKUP: dest_state_code ignored -> stored null.
        dest_state = None

    rec = {
        "customer_id": customer_id,
        "channel": channel,
        "dest_state_code": dest_state,
        "payment_status": "UNPAID",
        "fulfillment_status": "CART",
        "provisional_total_cents": 0,
        "settled_total_cents": 0,
        "discount_cents": 0,
    }
    A.stamp_create(rec)
    store.orders[rec["id"]] = rec
    return response.object_response(A.public(rec), 201)


@app.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    role, uid = middleware.require_roles(
        {A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    order = A.get_or_404(store.orders, oid)
    _order_owner_check(role, uid, order)
    return response.object_response(A.public(order))


@app.route("/orders", methods=["GET"])
def list_orders():
    role, uid = middleware.require_roles(
        {A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    limit, offset = A.get_pagination()
    items = list(store.orders.values())
    cust = A.request.args.get("customer_id")
    ff = A.request.args.get("fulfillment_status")
    ps = A.request.args.get("payment_status")
    if role == A.R_CUSTOMER:
        # Customers see only their own orders.
        items = [o for o in items if o["customer_id"] == uid]
    if cust is not None:
        items = [o for o in items if o["customer_id"] == cust]
    if ff is not None:
        items = [o for o in items if o["fulfillment_status"] == ff]
    if ps is not None:
        items = [o for o in items if o["payment_status"] == ps]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Order lines
# ---------------------------------------------------------------------------
@app.route("/orders/<oid>/lines", methods=["POST"])
def add_line(oid):
    role, uid = middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE})
    order = A.get_or_404(store.orders, oid)
    _order_owner_check(role, uid, order)
    body = A.get_body()
    vintage_id = A.require_str(body, "vintage_id")
    qty = A.require_int(body, "qty")

    vintage = A.get_or_404(store.vintages, vintage_id)
    if order["fulfillment_status"] != "CART":
        raise errors.invalid_state("Lines can only be added to a CART order.")
    if qty < 1:
        raise errors.invalid_request("qty must be >= 1.")

    rec = {
        "order_id": oid,
        "vintage_id": vintage_id,
        "qty": qty,
        "lot_id": None,
        "reservation_state": "PENDING",
        "unit_price_cents": 0,
        "line_excise_cents": 0,
    }
    A.stamp_create(rec)
    store.order_lines[rec["id"]] = rec
    A.touch(order)  # bumps Order.version
    return response.object_response(A.public(rec), 201)


@app.route("/orders/<oid>/lines", methods=["GET"])
def list_order_lines(oid):
    role, uid = middleware.require_roles(
        {A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    order = A.get_or_404(store.orders, oid)
    _order_owner_check(role, uid, order)
    limit, offset = A.get_pagination()
    items = services.lines_of_order(oid)
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)


@app.route("/order-lines/<lid>", methods=["GET"])
def get_order_line(lid):
    role, uid = middleware.require_roles(
        {A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    line = A.get_or_404(store.order_lines, lid)
    if role == A.R_CUSTOMER:
        order = store.orders.get(line["order_id"])
        if order is None or uid != order["customer_id"]:
            raise errors.forbidden()
    return response.object_response(A.public(line))


@app.route("/order-lines", methods=["GET"])
def list_order_lines_filtered():
    middleware.require_roles({A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    limit, offset = A.get_pagination()
    items = list(store.order_lines.values())
    vintage_id = A.request.args.get("vintage_id")
    lot_id = A.request.args.get("lot_id")
    if vintage_id is not None:
        items = [L for L in items if L["vintage_id"] == vintage_id]
    if lot_id is not None:
        items = [L for L in items if L["lot_id"] == lot_id]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)


@app.route("/order-lines/<lid>", methods=["DELETE"])
def delete_order_line(lid):
    role, uid = middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE})
    line = A.get_or_404(store.order_lines, lid)
    order = store.orders.get(line["order_id"])
    if order is None:
        raise errors.not_found()
    if role == A.R_CUSTOMER and uid != order["customer_id"]:
        raise errors.forbidden()
    # Only a pending line on a cart order may be removed.
    if order["fulfillment_status"] != "CART" or line["reservation_state"] != "PENDING":
        raise errors.invalid_state("Only a pending line on a cart order can be removed.")
    del store.order_lines[lid]
    A.touch(order)  # bumps Order.version
    return response.empty_response(204)


# ---------------------------------------------------------------------------
# Submit (the pivotal transition)
# ---------------------------------------------------------------------------
@app.route("/orders/<oid>/submit", methods=["POST"])
def submit_order(oid):
    role, uid = middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE})
    order = A.get_or_404(store.orders, oid)
    _order_owner_check(role, uid, order)

    body = A.get_body()
    # expected_order_version required (PRD §2.9).
    expected = A.require_int(body, "expected_order_version")

    # (4) state legality
    if order["fulfillment_status"] != "CART":
        raise errors.invalid_state()

    # (5) OCC
    if expected != order["version"]:
        raise errors.stale_order_version()

    customer = store.customers.get(order["customer_id"])
    if customer is None:
        raise errors.not_found()

    lines = services.lines_of_order(oid)
    # empty cart
    if len(lines) == 0:
        raise errors.empty_order()

    # (6) age verification
    if not customer.get("age_verified", False):
        raise errors.age_not_verified()

    # (7) blocked customer (derived compliance posture, PRD §3.2)
    if services.compliance_status_value(customer) == "BLOCKED":
        raise errors.customer_blocked()

    # vintage purchasability (per-line); ordering relative to business gates:
    # PRD §3.3 names it among submit preconditions before the priority list.
    vintages = {}
    products = {}
    for L in lines:
        v = store.vintages.get(L["vintage_id"])
        if v is None:
            raise errors.not_found()
        vintages[L["id"]] = v
        p = store.products.get(v["product_id"])
        products[L["id"]] = p
        if v["status"] not in ("RELEASED", "ALLOCATION_OPEN"):
            raise errors.vintage_not_purchasable()

    is_shipping = order["channel"] in A.SHIPPING_CHANNELS
    dest_state = order["dest_state_code"]
    dest_rule = services.state_rule_by_code(dest_state) if (is_shipping and dest_state) else None

    # (8) growler/keg state ban
    if is_shipping:
        has_draft = any(products[L["id"]]["category"] in A.DRAFT_CATEGORIES for L in lines)
        if has_draft:
            if dest_rule is None or not dest_rule.get("growler_keg_allowed", True):
                raise errors.growler_keg_state_banned()

    # (9) ship-state restriction
    if is_shipping:
        if dest_rule is None or not dest_rule.get("ship_allowed", True):
            raise errors.ship_state_restricted()

    # (10) allocation cap
    for L in lines:
        v = vintages[L["id"]]
        p = products[L["id"]]
        if p.get("is_allocated", False):
            cap = v["allocation_cap_per_customer"]
            if cap is not None:
                # customer's existing committed/fulfilled units of THIS vintage
                existing = 0
                for ol in store.order_lines.values():
                    if ol["id"] == L["id"]:
                        continue
                    if ol["vintage_id"] != v["id"]:
                        continue
                    o2 = store.orders.get(ol["order_id"])
                    if o2 is None or o2["customer_id"] != customer["id"]:
                        continue
                    if ol["reservation_state"] in ("COMMITTED", "FULFILLED"):
                        existing += ol["qty"]
                if existing + L["qty"] > cap:
                    raise errors.allocation_limit_exceeded()

    # (11) ABC monthly volume cap (DELIVERY/SHIP only)
    order_volume_ml = sum(L["qty"] * products[L["id"]]["bottle_volume_ml"] for L in lines)
    submit_month = store.clock.strftime("%Y-%m")
    if is_shipping and dest_rule is not None:
        cap = dest_rule.get("monthly_volume_limit_ml")
        if cap is not None:
            used = sum(
                w["volume_ml"] for w in services.active_windows_for_customer(customer["id"])
                if w["state_code"] == dest_state and w["window_month"] == submit_month
            )
            if used + order_volume_ml > cap:
                raise errors.abc_monthly_limit_exceeded()

    # (12) single-lot inventory sufficiency + lot selection
    selected = {}
    for L in lines:
        v = vintages[L["id"]]
        chosen = None
        for lot in A.sort_created(services.lots_of_vintage(v["id"])):
            if lot["qty_on_hand"] - lot["qty_reserved"] >= L["qty"]:
                chosen = lot
                break
        if chosen is None:
            raise errors.insufficient_inventory()
        selected[L["id"]] = chosen

    # ---- All checks passed: commit cascade ----
    affected_vintages = set()
    for L in lines:
        v = vintages[L["id"]]
        lot = selected[L["id"]]
        L["lot_id"] = lot["id"]
        L["unit_price_cents"] = v["list_price_cents"]
        L["reservation_state"] = "COMMITTED"
        A.touch(L)
        lot["qty_reserved"] += L["qty"]
        A.touch(lot)
        affected_vintages.add(v["id"])

    for vid in affected_vintages:
        v = store.vintages.get(vid)
        services.recompute_units_committed(v)
        services.auto_sold_out(v)

    # discount + provisional total
    disc_lines = []
    for L in lines:
        p = products[L["id"]]
        if p["category"] in A.DRAFT_CATEGORIES:
            continue
        v = vintages[L["id"]]
        disc_lines.append({
            "qty": L["qty"],
            "list_price_cents": L["unit_price_cents"],
            "case_pack_size": v["case_pack_size"],
        })
    order["discount_cents"] = calc.case_discount(disc_lines)
    tax_state = dest_state if is_shipping else None
    order["provisional_total_cents"] = calc.provisional_order_total(
        lines, order["discount_cents"], tax_state)

    order["fulfillment_status"] = "SUBMITTED"

    # ComplianceWindow row for DELIVERY/SHIP
    if is_shipping:
        w = {
            "customer_id": customer["id"],
            "order_id": order["id"],
            "state_code": dest_state,
            "volume_ml": order_volume_ml,
            "window_month": submit_month,
            "active": True,
        }
        A.stamp_create(w, with_version=False)
        store.compliance_windows[w["id"]] = w

    A.touch(order)  # bumps Order.version
    services.recompute_compliance_status(customer)
    return response.object_response(A.public(order))


# ---------------------------------------------------------------------------
# Payment dimension
# ---------------------------------------------------------------------------
@app.route("/orders/<oid>/authorize-payment", methods=["POST"])
def authorize_payment(oid):
    role, uid = middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE})
    order = A.get_or_404(store.orders, oid)
    _order_owner_check(role, uid, order)
    if order["payment_status"] != "UNPAID" or order["fulfillment_status"] != "SUBMITTED":
        raise errors.invalid_state()
    order["payment_status"] = "AUTHORIZED"
    A.touch(order)
    return response.object_response(A.public(order))


@app.route("/orders/<oid>/capture-payment", methods=["POST"])
def capture_payment(oid):
    middleware.require_roles({A.R_ASSOCIATE})
    order = A.get_or_404(store.orders, oid)
    if order["payment_status"] != "AUTHORIZED" or order["fulfillment_status"] != "SUBMITTED":
        raise errors.invalid_state()

    lines = services.lines_of_order(oid)
    for L in lines:
        lot = store.inventory_lots.get(L["lot_id"]) if L["lot_id"] else None
        if lot is not None and lot["tax_status"] == "BONDED":
            # Bonded -> taxed withdrawal.
            L["line_excise_cents"] = L["qty"] * lot["excise_band_cents_per_unit"]
            lot["qty_on_hand"] -= L["qty"]
            lot["qty_reserved"] -= L["qty"]
            A.touch(lot)
            # Mint/append a TAXED lot for the same vintage.
            taxed = _get_or_make_taxed_lot(lot["vintage_id"])
            taxed["qty_on_hand"] += L["qty"]
            A.touch(taxed)
            L["lot_id"] = taxed["id"]
            A.touch(L)
        else:
            L["line_excise_cents"] = 0
            A.touch(L)

    tax_state = order["dest_state_code"] if order["channel"] in A.SHIPPING_CHANNELS else None
    order["settled_total_cents"] = calc.settled_order_total(
        lines, order["discount_cents"], tax_state)
    order["payment_status"] = "CAPTURED"
    A.touch(order)
    return response.object_response(A.public(order))


def _get_or_make_taxed_lot(vintage_id):
    """Find an existing TAXED lot for the vintage to append to, else mint one."""
    for lot in A.sort_created(services.lots_of_vintage(vintage_id)):
        if lot["tax_status"] == "TAXED":
            return lot
    rec = {
        "vintage_id": vintage_id,
        "tax_status": "TAXED",
        "qty_on_hand": 0,
        "qty_reserved": 0,
        "excise_band_cents_per_unit": 0,
    }
    A.stamp_create(rec)
    store.inventory_lots[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Fulfillment dimension
# ---------------------------------------------------------------------------
@app.route("/orders/<oid>/mark-ready", methods=["POST"])
def mark_ready(oid):
    middleware.require_roles({A.R_ASSOCIATE})
    order = A.get_or_404(store.orders, oid)
    if order["fulfillment_status"] != "SUBMITTED" or order["payment_status"] != "CAPTURED":
        raise errors.invalid_state()
    for L in services.lines_of_order(oid):
        if L["reservation_state"] == "COMMITTED":
            L["reservation_state"] = "FULFILLED"
            A.touch(L)
    order["fulfillment_status"] = "READY"
    A.touch(order)
    return response.object_response(A.public(order))


@app.route("/orders/<oid>/complete", methods=["POST"])
def complete_order(oid):
    middleware.require_roles({A.R_ASSOCIATE})
    order = A.get_or_404(store.orders, oid)
    if order["fulfillment_status"] != "READY":
        raise errors.invalid_state()
    if order["channel"] in A.SHIPPING_CHANNELS:
        delivered = any(
            s["order_id"] == oid and s["status"] == "DELIVERED"
            for s in store.shipments.values())
        if not delivered:
            raise errors.invalid_state("Shipping order requires a DELIVERED shipment.")
    order["fulfillment_status"] = "COMPLETED"
    A.touch(order)

    customer = store.customers.get(order["customer_id"])
    if customer is not None:
        services.recompute_lifetime_spend(customer)
        services.recompute_compliance_status(customer)
        _accrue_club(customer, order)
    return response.object_response(A.public(order))


def _accrue_club(customer, order):
    """If customer holds an ACTIVE membership, accrue points + re-derive tier."""
    membership = None
    for m in store.club_memberships.values():
        if m["customer_id"] == customer["id"] and m["status"] == "ACTIVE":
            membership = m
            break
    if membership is None:
        return
    tier, mult = calc.club_tier_and_multiplier(customer["lifetime_spend_cents"])
    points = calc.club_points_for_order(order["settled_total_cents"], mult)
    membership["tier"] = tier
    membership["accrued_points"] += points
    A.touch(membership)


# ---------------------------------------------------------------------------
# Cancel / Refund (compensation)
# ---------------------------------------------------------------------------
@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    role, uid = middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE})
    order = A.get_or_404(store.orders, oid)
    _order_owner_check(role, uid, order)

    ff = order["fulfillment_status"]
    if ff == "CART":
        order["fulfillment_status"] = "CANCELLED"
        A.touch(order)
        return response.object_response(A.public(order))
    if ff == "SUBMITTED":
        if order["payment_status"] not in ("UNPAID", "AUTHORIZED"):
            raise errors.invalid_state()
        services.release_reservations(order)
        if order["payment_status"] == "AUTHORIZED":
            order["payment_status"] = "UNPAID"
        services.deactivate_order_windows(order["id"])
        order["fulfillment_status"] = "CANCELLED"
        A.touch(order)
        customer = store.customers.get(order["customer_id"])
        if customer is not None:
            services.recompute_compliance_status(customer)
        return response.object_response(A.public(order))
    raise errors.invalid_state()


@app.route("/orders/<oid>/refund", methods=["POST"])
def refund_order(oid):
    middleware.require_roles({A.R_COMPLIANCE})
    order = A.get_or_404(store.orders, oid)
    if order["payment_status"] != "CAPTURED" or order["fulfillment_status"] == "COMPLETED":
        raise errors.invalid_state()
    services.release_reservations(order)
    services.deactivate_order_windows(order["id"])
    order["payment_status"] = "REFUNDED"
    order["fulfillment_status"] = "CANCELLED"
    A.touch(order)
    customer = store.customers.get(order["customer_id"])
    if customer is not None:
        services.recompute_lifetime_spend(customer)
        services.recompute_compliance_status(customer)
    return response.object_response(A.public(order))


# ---------------------------------------------------------------------------
# Compliance-window reads
# ---------------------------------------------------------------------------
@app.route("/customers/<cid>/compliance-windows", methods=["GET"])
def list_customer_windows(cid):
    middleware.require_roles({A.R_COMPLIANCE, A.R_ADMIN})
    A.get_or_404(store.customers, cid)
    limit, offset = A.get_pagination()
    items = [w for w in store.compliance_windows.values() if w["customer_id"] == cid]
    state_code = A.request.args.get("state_code")
    window_month = A.request.args.get("window_month")
    active = A.request.args.get("active")
    if state_code is not None:
        items = [w for w in items if w["state_code"] == state_code]
    if window_month is not None:
        items = [w for w in items if w["window_month"] == window_month]
    if active is not None:
        want = active.lower() in ("true", "1")
        items = [w for w in items if w["active"] == want]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)


@app.route("/orders/<oid>/compliance-windows", methods=["GET"])
def list_order_windows(oid):
    middleware.require_roles({A.R_COMPLIANCE, A.R_ADMIN})
    A.get_or_404(store.orders, oid)
    limit, offset = A.get_pagination()
    items = [w for w in store.compliance_windows.values() if w["order_id"] == oid]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)
