"""Routes: orders, order lines, energy labels."""
from flask import Blueprint, g, request

from common import (ANY_ROLE, ApiError, D, body_json, check_ownership, err400, err404,
                    list_response, need, obj_response, paginate, require_roles, v_dt,
                    v_enum, v_int, v_num, v_str)
from services import (GRID_STYLES, HARDWARE_FINISHES, SHAPES, cancel_order_cascade,
                      compute_line_fields, get_or_404, label_of_line,
                      label_recalc_provisional, lines_of_order, live_lines,
                      order_recompute, ser_label, ser_line, ser_order, transition_line,
                      wave_allocation, wave_recompute)
from store import STORE, new_entity, touch

bp_orders = Blueprint("orders", __name__)


def load_order_owned(order_id):
    order = get_or_404(STORE.orders, order_id)
    check_ownership(order["dealer_id"])
    return order


def validate_line_shape(body, current=None):
    """Validate effective (post-merge) dimensional rules for a line."""
    def eff(name):
        if name in body and body[name] is not None:
            return body[name]
        return current[name] if current else None

    shape = eff("shape")
    if shape is not None:
        v_enum(shape, "shape", SHAPES)
    grid = eff("grid_style")
    if grid is not None:
        v_enum(grid, "grid_style", GRID_STYLES)
    hw = eff("hardware_finish")
    if hw is not None:
        v_enum(hw, "hardware_finish", HARDWARE_FINISHES)
    w = eff("width_in")
    h = eff("height_in")
    if w is not None:
        v_num(w, "width_in")
        if D(w) <= 0:
            err400("width_in must be greater than zero")
    if h is not None:
        v_num(h, "height_in")
        if D(h) <= 0:
            err400("height_in must be greater than zero")
    qty = eff("quantity")
    if qty is not None:
        v_int(qty, "quantity")
        if qty < 1:
            err400("quantity must be at least 1")
    if shape == "CIRCLE" and w is not None and h is not None and D(w) != D(h):
        err400("CIRCLE lines require width_in equal to height_in")
    return {"shape": shape, "width_in": w, "height_in": h, "quantity": qty,
            "grid_style": grid, "hardware_finish": hw}


def check_series_rules(series, width_in, height_in):
    if series["status"] != "ACTIVE":
        raise ApiError("ERR_SERIES_DISCONTINUED", 409,
                       "Referenced catalog series is DISCONTINUED")
    if D(width_in) + D(height_in) > D(series["max_united_inches"]):
        raise ApiError("ERR_SIZE_EXCEEDS_SERIES_LIMIT", 422,
                       "united_inches exceeds series max_united_inches")


# ------------------------------------------------------------------ orders

@bp_orders.post("/fenestration/orders")
@require_roles("DealerRep", "PlantManager")
def create_order():
    body = body_json()
    dealer_id = v_str(need(body, "dealer_id"), "dealer_id")
    # Ownership: a DealerRep's payload dealer_id must equal X-User-ID.
    check_ownership(dealer_id)
    dealer = get_or_404(STORE.dealers, dealer_id)
    order_date = v_dt(need(body, "order_date"), "order_date")
    ship_to = dealer["ship_to_state_code"]
    if "ship_to_state_code" in body and body["ship_to_state_code"] is not None:
        ship_to = v_str(body["ship_to_state_code"], "ship_to_state_code")
    o = new_entity({
        "dealer_id": dealer_id, "ship_to_state_code": ship_to, "order_date": order_date,
        "production_status": "DRAFT", "compliance_status": "PENDING",
        "wave_id": None, "promised_date": None,
        "subtotal_cents": 0, "discount_cents": 0, "total_price_cents": 0,
        "delivered_at": None,
    })
    STORE.orders[o["id"]] = o
    return obj_response(ser_order(o), 201)


@bp_orders.get("/fenestration/orders/<orderId>")
@require_roles(*ANY_ROLE)
def get_order(orderId):
    return obj_response(ser_order(load_order_owned(orderId)), 200)


@bp_orders.get("/fenestration/orders")
@require_roles(*ANY_ROLE)
def list_orders():
    items = list(STORE.orders.values())
    for param in ("dealer_id", "wave_id", "production_status"):
        val = request.args.get(param)
        if val is not None:
            items = [o for o in items if str(o.get(param)) == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_order(o) for o in page], limit, offset, total)


@bp_orders.post("/fenestration/orders/<orderId>/confirm")
@require_roles("DealerRep", "PlantManager")
def confirm_order(orderId):
    order = load_order_owned(orderId)
    if order["production_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT order can be confirmed")
    lines = live_lines(orderId)
    if not lines:
        raise ApiError("ERR_ORDER_HAS_NO_LINES", 409,
                       "Order has no non-CANCELLED lines")
    # Re-evaluate each line's energy label (provisional basis) before the gate.
    for line in lines:
        gp = STORE.glass_packages[line["glass_package_id"]]
        label = label_of_line(line["id"])
        if label:
            label_recalc_provisional(label, line, order, gp, do_touch=False)
    for line in lines:
        label = label_of_line(line["id"])
        if label and label["compliance"] not in ("PASS", "UNEVALUATED"):
            raise ApiError("ERR_ENERGY_CODE_VIOLATION", 409,
                           "A line's energy label compliance is FAIL")
    dealer = STORE.dealers.get(order["dealer_id"])
    if dealer and dealer["credit_status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_CREDIT_HOLD", 409, "Dealer is on CREDIT_HOLD")
    # Final reprice and freeze.
    for line in lines:
        compute_line_fields(line, STORE.series[line["series_id"]],
                            STORE.glass_packages[line["glass_package_id"]])
    order_recompute(order, do_touch=False)
    order["production_status"] = "CONFIRMED"
    order["compliance_status"] = "PROVISIONALLY_COMPLIANT"
    touch(order)
    for line in lines:
        if line["status"] == "PENDING":
            transition_line(line, "CONFIRMED")
    return obj_response(ser_order(order), 200)


@bp_orders.post("/fenestration/orders/<orderId>/cancel")
@require_roles("DealerRep", "PlantManager")
def cancel_order(orderId):
    order = load_order_owned(orderId)
    cancel_order_cascade(order, g.role)
    return obj_response(ser_order(order), 200)


@bp_orders.post("/fenestration/orders/<orderId>/confirm-delivery")
@require_roles("DealerRep", "PlantManager")
def confirm_delivery(orderId):
    order = load_order_owned(orderId)
    if order["production_status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SHIPPED order can be delivered")
    from store import current_time
    order["delivered_at"] = current_time()
    order["production_status"] = "DELIVERED"
    touch(order)
    return obj_response(ser_order(order), 200)


# ------------------------------------------------------------------ order lines

@bp_orders.post("/fenestration/orders/<orderId>/lines")
@require_roles("DealerRep", "PlantManager")
def create_line(orderId):
    order = load_order_owned(orderId)
    body = body_json()
    series_id = v_str(need(body, "series_id"), "series_id")
    gp_id = v_str(need(body, "glass_package_id"), "glass_package_id")
    series = get_or_404(STORE.series, series_id)
    gp = get_or_404(STORE.glass_packages, gp_id)
    vals = validate_line_shape(body)
    for f in ("shape", "width_in", "height_in", "quantity", "grid_style", "hardware_finish"):
        if body.get(f) is None:
            err400(f"Missing required field: {f}")
    if order["production_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT", 409, "Lines can only be added to a DRAFT order")
    check_series_rules(series, vals["width_in"], vals["height_in"])
    line = new_entity({
        "order_id": order["id"], "series_id": series_id, "glass_package_id": gp_id,
        "shape": vals["shape"], "width_in": vals["width_in"], "height_in": vals["height_in"],
        "quantity": vals["quantity"], "grid_style": vals["grid_style"],
        "hardware_finish": vals["hardware_finish"], "status": "PENDING", "rack_id": None,
    })
    compute_line_fields(line, series, gp)
    STORE.lines[line["id"]] = line
    label = new_entity({
        "order_line_id": line["id"], "basis": "PROVISIONAL", "status": "PROVISIONAL",
        "u_factor": D(gp["catalog_u_factor"]), "shgc": D(gp["catalog_shgc"]),
        "applied_energy_code_rule_id": None, "compliance": "UNEVALUATED",
    })
    label_recalc_provisional(label, line, order, gp, initial=True)
    STORE.labels[label["id"]] = label
    order_recompute(order, do_touch=True)
    return obj_response(ser_line(line), 201)


@bp_orders.get("/fenestration/orders/<orderId>/lines")
@require_roles(*ANY_ROLE)
def list_order_lines(orderId):
    load_order_owned(orderId)
    page, limit, offset, total = paginate(lines_of_order(orderId))
    return list_response([ser_line(l) for l in page], limit, offset, total)


@bp_orders.get("/fenestration/order-lines/<lineId>")
@require_roles(*ANY_ROLE)
def get_line(lineId):
    line = get_or_404(STORE.lines, lineId)
    order = STORE.orders.get(line["order_id"])
    if order:
        check_ownership(order["dealer_id"])
    return obj_response(ser_line(line), 200)


@bp_orders.get("/fenestration/order-lines")
@require_roles(*ANY_ROLE)
def list_lines():
    items = list(STORE.lines.values())
    for param in ("order_id", "series_id", "glass_package_id", "rack_id"):
        val = request.args.get(param)
        if val is not None:
            items = [l for l in items if str(l.get(param)) == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_line(l) for l in page], limit, offset, total)


@bp_orders.patch("/fenestration/orders/<orderId>/lines/<lineId>")
@require_roles("DealerRep", "PlantManager")
def patch_line(orderId, lineId):
    order = load_order_owned(orderId)
    line = STORE.lines.get(lineId)
    if line is None or line["order_id"] != orderId:
        err404("Order line not found")
    body = body_json()
    # Body-referenced resources must exist (existence stage).
    if body.get("series_id") is not None:
        get_or_404(STORE.series, v_str(body["series_id"], "series_id"))
    if body.get("glass_package_id") is not None:
        get_or_404(STORE.glass_packages, v_str(body["glass_package_id"], "glass_package_id"))
    expected = v_int(need(body, "expected_order_version"), "expected_order_version")
    vals = validate_line_shape(body, current=line)
    # OCC on parent order version.
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_order_version does not match current order version")
    if order["production_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT", 409,
                       "Lines can only be edited while the order is DRAFT")
    # Apply the patch.
    for f in ("series_id", "glass_package_id", "shape", "width_in", "height_in",
              "quantity", "grid_style", "hardware_finish"):
        if body.get(f) is not None:
            line[f] = body[f]
    series = STORE.series[line["series_id"]]
    gp = STORE.glass_packages[line["glass_package_id"]]
    check_series_rules(series, line["width_in"], line["height_in"])
    compute_line_fields(line, series, gp)
    touch(line)
    label = label_of_line(line["id"])
    if label:
        label_recalc_provisional(label, line, order, gp, do_touch=True)
    order_recompute(order, do_touch=True)
    return obj_response(ser_line(line), 200)


@bp_orders.post("/fenestration/order-lines/<lineId>/resume-production")
@require_roles("ProductionLead", "PlantManager")
def resume_production(lineId):
    line = get_or_404(STORE.lines, lineId)
    if line["status"] != "GLASS_HOLD":
        raise ApiError("ERR_LINE_NOT_ON_GLASS_HOLD", 409, "Line is not on GLASS_HOLD")
    order = STORE.orders.get(line["order_id"])
    wave = STORE.waves.get(order["wave_id"]) if order and order["wave_id"] else None
    if wave is None or wave["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", 409, "The line's wave is not RELEASED")
    units, glass = wave_allocation(wave, extra_lines=[line])
    if units > wave["capacity_units"]:
        raise ApiError("ERR_WAVE_CAPACITY_EXCEEDED", 409,
                       "Resuming would exceed wave unit capacity")
    if glass > D(wave["capacity_glass_sqft"]):
        raise ApiError("ERR_WAVE_GLASS_CAPACITY_EXCEEDED", 409,
                       "Resuming would exceed wave glass capacity")
    line["status"] = "IN_PRODUCTION"
    touch(line)
    wave_recompute(wave)
    return obj_response(ser_line(line), 200)


# ------------------------------------------------------------------ energy labels

@bp_orders.get("/fenestration/order-lines/<lineId>/energy-label")
@require_roles(*ANY_ROLE)
def get_line_energy_label(lineId):
    line = get_or_404(STORE.lines, lineId)
    order = STORE.orders.get(line["order_id"])
    if order:
        check_ownership(order["dealer_id"])
    labels = [l for l in STORE.labels.values() if l["order_line_id"] == lineId]
    page, limit, offset, total = paginate(labels)
    return list_response([ser_label(l) for l in page], limit, offset, total)


@bp_orders.get("/fenestration/energy-labels/<labelId>")
@require_roles(*ANY_ROLE)
def get_energy_label(labelId):
    return obj_response(ser_label(get_or_404(STORE.labels, labelId)), 200)


@bp_orders.get("/fenestration/energy-labels")
@require_roles(*ANY_ROLE)
def list_energy_labels():
    items = list(STORE.labels.values())
    for param in ("order_line_id", "applied_energy_code_rule_id"):
        val = request.args.get(param)
        if val is not None:
            items = [l for l in items if str(l.get(param)) == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_label(l) for l in page], limit, offset, total)
