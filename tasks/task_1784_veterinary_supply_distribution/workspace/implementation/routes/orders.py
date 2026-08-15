"""Order / OrderLine / BackorderLine endpoints (PRD 3.4 - 3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_ORDER_INVALID_STATE,
    ERR_PRODUCT_DISCONTINUED,
    ERR_DELIVERY_WINDOW_OVERLAP,
    ERR_DELIVERY_FREQUENCY_EXCEEDED,
    ERR_ORDER_BELOW_MINIMUM,
    ERR_RX_AUTHORIZATION_REQUIRED,
    ERR_DEA_REGISTRATION_REQUIRED,
    ERR_SHIP_TO_DIVERSION_MISMATCH,
    ERR_QUARTERLY_CAP_EXCEEDED,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_BACKORDER_LINE_INVALID_STATE,
)
from middleware import authorized, check_ownership
from response import success_object, success_list
from services.calculations import (
    compute_order_totals,
    fefo_allocate_order,
    mint_provisional_accrual,
    find_active_enrollment,
    qualifying_lines,
    recompute_credit_used,
    lazy_reset_quarterly_counter,
    order_lines,
)
from services.cascades import (
    cancel_order_cascade,
    increment_quarterly_counters,
    find_covering_authorization,
    recompute_order_after_backorder_cancel,
)
from services.core import (
    get_body, require_fields, require_string, public, get_or_404,
    get_clinic_or_404, require_clinic_active, paginate,
)
from util import CLOCK, new_id, now_ts, touch, iso_week_key, fmt_datetime

bp = Blueprint("orders", __name__)

READ_ROLES = ["AccountManager", "ClinicBuyer", "SupplyChainPlanner", "ComplianceOfficer"]
WINDOW_HOLDING = {"SUBMITTED", "APPROVED", "BACKORDERED"}


def _serialize_order(order):
    out = public(order)
    out["delivery_window_start"] = fmt_datetime(order["delivery_window_start"])
    out["delivery_window_end"] = fmt_datetime(order["delivery_window_end"])
    return out


def _serialize_line(line):
    return public(line)


# ---------------------------------------------------------------------------
# Order create (DRAFT with embedded PENDING lines)
# ---------------------------------------------------------------------------

@bp.route("/vet/orders", methods=["POST"])
def create_order():
    caller = authorized(["ClinicBuyer"])
    body = get_body()
    require_fields(body, ["clinic_id", "ship_to_address",
                          "delivery_window_start", "delivery_window_end", "lines"])
    # Ownership (priority 2.5) precedes existence (priority 3).
    check_ownership(caller, body.get("clinic_id"))
    clinic = get_clinic_or_404(body["clinic_id"])

    ship_to = require_string(body, "ship_to_address")
    from services.core import parse_dt_field
    window_start = parse_dt_field(body, "delivery_window_start")
    window_end = parse_dt_field(body, "delivery_window_end")
    if window_end <= window_start:
        raise_error(ERR_INVALID_REQUEST,
                    "delivery_window_end must be strictly after delivery_window_start")

    lines_in = body.get("lines")
    if not isinstance(lines_in, list):
        raise_error(ERR_INVALID_REQUEST, "lines must be an array")
    parsed_lines = []
    for item in lines_in:
        if not isinstance(item, dict):
            raise_error(ERR_INVALID_REQUEST, "each line must be an object")
        if "product_id" not in item or item["product_id"] is None:
            raise_error(ERR_INVALID_REQUEST, "line missing product_id")
        product = get_or_404("products", item["product_id"])
        qty = item.get("qty_requested")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise_error(ERR_INVALID_REQUEST, "qty_requested must be a positive integer")
        parsed_lines.append((product, qty))

    order = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
        "clinic_id": clinic["id"],
        "ship_to_address": ship_to,
        "delivery_window_start": window_start,
        "delivery_window_end": window_end,
        "status": "DRAFT",
        "merchandise_subtotal_cents": 0,
        "bundle_discount_cents": 0,
        "merchandise_net_cents": 0,
        "equipment_surcharge_cents": 0,
        "freight_fee_cents": 0,
        "total_cents": 0,
        "rejection_reason": None,
    }
    db["orders"][order["id"]] = order
    for product, qty in parsed_lines:
        line = {
            "id": new_id(),
            "created_at": now_ts(),
            "updated_at": now_ts(),
            "version": 1,
            "order_id": order["id"],
            "product_id": product["id"],
            "qty_requested": qty,
            "qty_allocated": 0,
            "lot_id": None,
            "unit_price_cents": None,
            "line_total_cents": None,
            "status": "PENDING",
        }
        db["order_lines"][line["id"]] = line
    return success_object(_serialize_order(order), status=201)


@bp.route("/vet/orders", methods=["GET"])
def list_orders():
    authorized(READ_ROLES)
    items = list(db["orders"].values())
    for param in ("clinic_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [o for o in items if str(o.get(param)) == val]
    page, total, limit, offset = paginate(items)
    return success_list([_serialize_order(o) for o in page], total, limit, offset)


@bp.route("/vet/orders/<oid>", methods=["GET"])
def get_order(oid):
    authorized(READ_ROLES)
    order = get_or_404("orders", oid)
    return success_object(_serialize_order(order))


# ---------------------------------------------------------------------------
# Submit (PRD 3.4): fixed check sequence.
# ---------------------------------------------------------------------------

@bp.route("/vet/orders/<oid>/submit", methods=["POST"])
def submit_order(oid):
    caller = authorized(["ClinicBuyer"])
    order = get_or_404("orders", oid)
    check_ownership(caller, order["clinic_id"])
    clinic = get_clinic_or_404(order["clinic_id"])

    if order["status"] != "DRAFT":
        raise_error(ERR_ORDER_INVALID_STATE,
                    f"order must be DRAFT (is {order['status']})")
    require_clinic_active(clinic)

    lines = order_lines(order["id"])
    if len(lines) < 1:
        raise_error(ERR_INVALID_REQUEST, "order must carry at least one line")

    # Delivery-window overlap (half-open): touch allowed, intersection not.
    for other in db["orders"].values():
        if other["id"] == order["id"] or other["clinic_id"] != clinic["id"]:
            continue
        if other["status"] not in WINDOW_HOLDING:
            continue
        if (order["delivery_window_start"] < other["delivery_window_end"]
                and other["delivery_window_start"] < order["delivery_window_end"]):
            raise_error(ERR_DELIVERY_WINDOW_OVERLAP,
                        "delivery window intersects another window-holding order")

    # Weekly cadence: submitting order + other window-holding orders whose
    # delivery_window_start falls in the same ISO week.
    week = iso_week_key(order["delivery_window_start"])
    count = 1
    for other in db["orders"].values():
        if other["id"] == order["id"] or other["clinic_id"] != clinic["id"]:
            continue
        if other["status"] not in WINDOW_HOLDING:
            continue
        if iso_week_key(other["delivery_window_start"]) == week:
            count += 1
    if count > clinic["delivery_frequency_per_week"]:
        raise_error(ERR_DELIVERY_FREQUENCY_EXCEEDED,
                    "weekly delivery cap would be exceeded")

    # Catalog standing: every line's product must still be LISTED.
    for line in lines:
        product = db["products"].get(line["product_id"])
        if product is None or product["status"] != "LISTED":
            raise_error(ERR_PRODUCT_DISCONTINUED,
                        "order contains a DISCONTINUED product")

    # Price snapshot + line totals.
    for line in lines:
        product = db["products"][line["product_id"]]
        line["unit_price_cents"] = product["unit_price_cents"]
        line["line_total_cents"] = product["unit_price_cents"] * line["qty_requested"]
        touch(line)

    # Order totals in pinned evaluation order.
    compute_order_totals(order)

    # Fiscal: merchandise net must reach the clinic minimum (equality passes).
    if order["merchandise_net_cents"] < clinic["minimum_order_value_cents"]:
        raise_error(ERR_ORDER_BELOW_MINIMUM,
                    "merchandise_net_cents is below the clinic minimum order value")

    order["status"] = "SUBMITTED"
    touch(order)
    return success_object(_serialize_order(order))


# ---------------------------------------------------------------------------
# Approve (PRD 3.5): safety gates, then FEFO allocation.
# ---------------------------------------------------------------------------

@bp.route("/vet/orders/<oid>/approve", methods=["POST"])
def approve_order(oid):
    authorized(["AccountManager"])
    order = get_or_404("orders", oid)
    clinic = get_clinic_or_404(order["clinic_id"])

    if order["status"] != "SUBMITTED":
        raise_error(ERR_ORDER_INVALID_STATE,
                    f"order must be SUBMITTED (is {order['status']})")
    require_clinic_active(clinic)

    lines = order_lines(order["id"])
    today = CLOCK.today()

    # --- Prescription-safety sequence -------------------------------------
    rx_manufacturers = []
    auths_by_mfr = {}
    for line in lines:
        product = db["products"].get(line["product_id"])
        if product is None or product["product_type"] != "RX_PHARMACEUTICAL":
            continue
        mfr = product["manufacturer_code"]
        auth = find_covering_authorization(clinic["id"], mfr)
        if auth is None:
            raise_error(ERR_RX_AUTHORIZATION_REQUIRED,
                        f"no APPROVED in-window authorization for manufacturer {mfr}")
        if mfr not in auths_by_mfr:
            auths_by_mfr[mfr] = auth
            rx_manufacturers.append(mfr)

    # Controlled substances require DEA registration.
    needs_dea = False
    for line in lines:
        product = db["products"].get(line["product_id"])
        if product is not None and product.get("is_controlled_substance"):
            needs_dea = True
            break
    if needs_dea and not clinic.get("dea_registration_number"):
        raise_error(ERR_DEA_REGISTRATION_REQUIRED,
                    "clinic.dea_registration_number is required for controlled substances")

    # Diversion prevention: with any Rx line present, the order's ship-to must
    # equal the authorization's approved address exactly.
    if rx_manufacturers:
        for mfr in rx_manufacturers:
            auth = auths_by_mfr[mfr]
            if order["ship_to_address"] != auth["approved_ship_to_address"]:
                raise_error(ERR_SHIP_TO_DIVERSION_MISMATCH,
                            "order ship_to_address differs from the approved address")

    # Quarterly volume cap per distinct manufacturer (cap inclusive).
    for mfr in rx_manufacturers:
        auth = auths_by_mfr[mfr]
        lazy_reset_quarterly_counter(auth)
        order_units = sum(
            l["qty_requested"] for l in lines
            if db["products"].get(l["product_id"]) is not None
            and db["products"][l["product_id"]]["product_type"] == "RX_PHARMACEUTICAL"
            and db["products"][l["product_id"]]["manufacturer_code"] == mfr
        )
        cumulative = auth["quantity_approved_this_quarter"] + order_units
        if cumulative > auth["quarterly_quantity_cap"]:
            raise_error(ERR_QUARTERLY_CAP_EXCEEDED,
                        "quarterly quantity cap would be exceeded")

    # Fiscal gate: credit_used + total <= credit_limit (equality passes).
    if clinic["credit_used_cents"] + order["total_cents"] > clinic["credit_limit_cents"]:
        raise_error(ERR_CREDIT_LIMIT_EXCEEDED,
                    "credit limit would be exceeded")

    # --- Allocation (FEFO per line, creation order) ------------------------
    fefo_allocate_order(order)

    lines = order_lines(order["id"])
    if any(l["status"] == "BACKORDERED" for l in lines):
        order["status"] = "BACKORDERED"
    else:
        order["status"] = "APPROVED"

    # Quarterly counters accrue this order's Rx units.
    increment_quarterly_counters(order, lines)

    # Provisional rebate accrual when enrolled (also when landing BACKORDERED).
    enrollment, program = find_active_enrollment(clinic["id"])
    if program is not None and qualifying_lines(lines, program):
        mint_provisional_accrual(order, enrollment, program, lines)

    touch(order)
    recompute_credit_used(clinic["id"])
    return success_object(_serialize_order(order))


# ---------------------------------------------------------------------------
# Reject / cancel
# ---------------------------------------------------------------------------

@bp.route("/vet/orders/<oid>/reject", methods=["POST"])
def reject_order(oid):
    authorized(["AccountManager"])
    order = get_or_404("orders", oid)
    if order["status"] != "SUBMITTED":
        raise_error(ERR_ORDER_INVALID_STATE,
                    f"order must be SUBMITTED (is {order['status']})")
    body = get_body()
    order["rejection_reason"] = body.get("rejection_reason")
    order["status"] = "REJECTED"  # window released (REJECTED holds no window)
    touch(order)
    return success_object(_serialize_order(order))


@bp.route("/vet/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    caller = authorized(["ClinicBuyer", "AccountManager"])
    order = get_or_404("orders", oid)
    check_ownership(caller, order["clinic_id"])
    if order["status"] not in ("DRAFT", "SUBMITTED", "APPROVED", "BACKORDERED"):
        raise_error(ERR_ORDER_INVALID_STATE,
                    f"order cannot be cancelled from {order['status']}")
    cancel_order_cascade(order)
    return success_object(_serialize_order(order))


# ---------------------------------------------------------------------------
# Order lines
# ---------------------------------------------------------------------------

@bp.route("/vet/order-lines", methods=["GET"])
def list_order_lines():
    authorized(READ_ROLES)
    items = list(db["order_lines"].values())
    for param in ("order_id", "product_id", "lot_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [l for l in items if str(l.get(param)) == val]
    page, total, limit, offset = paginate(items)
    return success_list([_serialize_line(l) for l in page], total, limit, offset)


@bp.route("/vet/order-lines/<lid>", methods=["GET"])
def get_order_line(lid):
    authorized(READ_ROLES)
    line = get_or_404("order_lines", lid)
    return success_object(_serialize_line(line))


@bp.route("/vet/order-lines/<lid>/backorder-lines", methods=["GET"])
def list_backorder_lines_of_line(lid):
    authorized(READ_ROLES)
    line = get_or_404("order_lines", lid)
    items = [b for b in db["backorder_lines"].values() if b["order_line_id"] == line["id"]]
    page, total, limit, offset = paginate(items)
    return success_list([public(b) for b in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Backorder cancel (PRD 3.6)
# ---------------------------------------------------------------------------

@bp.route("/vet/backorder-lines/<bid>/cancel", methods=["POST"])
def cancel_backorder_line(bid):
    caller = authorized(["ClinicBuyer", "AccountManager"])
    bo = get_or_404("backorder_lines", bid)
    line = get_or_404("order_lines", bo["order_line_id"])
    order = get_or_404("orders", line["order_id"])
    check_ownership(caller, order["clinic_id"])
    if bo["status"] != "OPEN":
        raise_error(ERR_BACKORDER_LINE_INVALID_STATE,
                    f"backorder line must be OPEN (is {bo['status']})")
    bo["status"] = "CANCELLED"
    touch(bo)
    if line["status"] == "BACKORDERED":
        line["status"] = "CANCELLED"
        touch(line)
    recompute_order_after_backorder_cancel(order)
    return success_object(public(bo))
