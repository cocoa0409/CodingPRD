"""FramingOrder endpoints + production/payment state transitions
(PRD §3.2, §3.4, §3.5, §3.6, §3.7, §3.8)."""
from flask import Blueprint

import errors
import validate
from db import db, now_iso
from middleware import get_auth, require_role
from response import ok_array, ok_object
from services import calc, domain

bp = Blueprint("orders", __name__)

PRODUCTION_STATES = {"INTAKE", "QUOTED", "IN_PRODUCTION", "READY", "PICKED_UP", "CANCELLED"}


# ---------------------------------------------------------------------------
# shared lookup + ownership helpers
# ---------------------------------------------------------------------------
def find_order_or_404(order_id):
    o = db.framing_orders.get(order_id)
    if o is None:
        errors.raise_err(errors.ERR_ORDER_NOT_FOUND, "FramingOrder not found")
    return o


def assert_customer_owns_order(auth, order):
    if auth.role == "Customer" and auth.user_id != order["customer_id"]:
        errors.raise_err(errors.ERR_FORBIDDEN_ROLE, "Customer may only access own order")


def find_customer_or_404(customer_id):
    c = db.customers.get(customer_id)
    if c is None:
        errors.raise_err(errors.ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    return c


# ---------------------------------------------------------------------------
# create / list / get
# ---------------------------------------------------------------------------
@bp.route("/framing-orders", methods=["POST"])
def create_order():
    auth = get_auth()
    require_role(auth, ("FrameDesigner", "FrontDeskClerk"))
    body = validate.get_json_body()

    customer_id = validate.require(body, "customer_id")
    if not isinstance(customer_id, str) or customer_id.strip() == "":
        errors.raise_err(errors.ERR_INVALID_REQUEST, "customer_id must be a string")
    customer = find_customer_or_404(customer_id)

    rush_requested = validate.opt(body, "rush_requested", False)
    validate.as_bool(rush_requested, "rush_requested")
    deposit_pct = validate.opt(body, "deposit_pct", 0.30)
    _validate_deposit_pct(deposit_pct)

    o = _new_order(customer_id, rush_requested, deposit_pct, reorder_of=None)
    db.framing_orders[o["id"]] = o

    # recompute owning customer open count and no-show risk
    domain.recompute_customer_open_and_risk(customer)
    domain.touch(customer)

    return ok_object(domain.serialize_order(o), status=201)


def _validate_deposit_pct(deposit_pct):
    if not validate.is_number(deposit_pct):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "deposit_pct must be a number")
    if deposit_pct < 0.10 or deposit_pct > 1.00:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "deposit_pct must be within [0.10, 1.00]")


def _new_order(customer_id, rush_requested, deposit_pct, reorder_of):
    o = {
        "customer_id": customer_id,
        "reorder_of_order_id": reorder_of,
        "rush_requested": rush_requested,
        "deposit_pct": deposit_pct,
        "production_status": "INTAKE",
        "payment_status": "UNBILLED",
        "has_fragile_line": False,
        "estimate_total": 0,
        "deposit_required": 0,
        "final_invoice_total": 0,
        "amount_paid": 0,
        "balance_due": 0,
        "turnaround_days": 0,
        "_terminal_at": None,
    }
    domain.stamp_create(o)
    return o


@bp.route("/framing-orders", methods=["GET"])
def list_orders():
    auth = get_auth()
    require_role(auth, ("FrameDesigner", "FrontDeskClerk", "FrameProductionTech"))
    from flask import request

    limit, offset = validate.parse_pagination()
    items = list(db.framing_orders.values())
    customer_id = request.args.get("customer_id")
    reorder_of = request.args.get("reorder_of_order_id")
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if reorder_of is not None:
        items = [o for o in items if o["reorder_of_order_id"] == reorder_of]
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    page, total = validate.paginate(items, limit, offset)
    return ok_array([domain.serialize_order(o) for o in page], limit, offset, total)


@bp.route("/framing-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    auth = get_auth()
    require_role(auth, ("FrameDesigner", "FrontDeskClerk", "FrameProductionTech", "Customer"))
    o = find_order_or_404(order_id)
    assert_customer_owns_order(auth, o)
    return ok_object(domain.serialize_order(o))


# ---------------------------------------------------------------------------
# QUOTE: INTAKE -> QUOTED
# ---------------------------------------------------------------------------
@bp.route("/framing-orders/<order_id>/quote", methods=["POST"])
def quote_order(order_id):
    auth = get_auth()
    require_role(auth, ("FrameDesigner",))
    o = find_order_or_404(order_id)

    # state: must be INTAKE
    if o["production_status"] != "INTAKE":
        errors.raise_err(errors.ERR_INVALID_STATE, "Order is not in INTAKE")

    # cross-entity referential: >= 1 non-VOID line
    lines = domain.non_void_lines_sorted(order_id)
    if len(lines) == 0:
        errors.raise_err(errors.ERR_NO_LINES, "Quote requires at least one non-void line")

    customer = db.customers[o["customer_id"]]

    # recompute fragility first (drives deposit + turnaround)
    domain.recompute_has_fragile_line(o)

    # estimate (sum-then-round)
    estimate = calc.quote_estimate_total(
        lines, o["rush_requested"], customer["loyalty_discount_pct"]
    )
    o["estimate_total"] = calc.to_float(estimate)

    # deposit
    dep = calc.deposit_required(estimate, o["deposit_pct"], o["has_fragile_line"])
    o["deposit_required"] = calc.to_float(dep)

    # turnaround
    o["turnaround_days"] = calc.turnaround_days(o["rush_requested"], o["has_fragile_line"])

    # production transition
    o["production_status"] = "QUOTED"

    # payment dimension: UNBILLED -> DEPOSIT_DUE
    if o["payment_status"] == "UNBILLED":
        o["payment_status"] = "DEPOSIT_DUE"

    # ledger (effective total now estimate)
    domain.recompute_ledger(o)

    domain.touch(o)

    # quote recomputes customer no-show risk (open set / ready-unpaid unchanged
    # set membership but status drives it; safe to recompute)
    domain.recompute_customer_open_and_risk(customer)
    domain.touch(customer)

    return ok_object(domain.serialize_order(o))


# ---------------------------------------------------------------------------
# REOPEN-INTAKE: QUOTED -> INTAKE
# ---------------------------------------------------------------------------
@bp.route("/framing-orders/<order_id>/reopen-intake", methods=["POST"])
def reopen_intake(order_id):
    auth = get_auth()
    require_role(auth, ("FrameDesigner",))
    o = find_order_or_404(order_id)

    if o["production_status"] != "QUOTED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Order is not in QUOTED")

    # deposit not yet paid: payment_status IN {UNBILLED, DEPOSIT_DUE}
    if o["payment_status"] not in ("UNBILLED", "DEPOSIT_DUE"):
        errors.raise_err(errors.ERR_DEPOSIT_ALREADY_PAID, "Deposit already paid")

    o["production_status"] = "INTAKE"
    domain.touch(o)
    return ok_object(domain.serialize_order(o))


# ---------------------------------------------------------------------------
# START-PRODUCTION: QUOTED -> IN_PRODUCTION
# ---------------------------------------------------------------------------
@bp.route("/framing-orders/<order_id>/start-production", methods=["POST"])
def start_production(order_id):
    auth = get_auth()
    require_role(auth, ("FrameProductionTech",))
    o = find_order_or_404(order_id)

    if o["production_status"] != "QUOTED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Order is not in QUOTED")

    # state precondition: deposit (or full) paid
    if o["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        errors.raise_err(errors.ERR_DEPOSIT_NOT_PAID, "Deposit not paid")

    # cross-entity referential: every non-VOID line MEASURED
    for l in domain.non_void_lines_sorted(order_id):
        if l["line_status"] != "MEASURED":
            errors.raise_err(errors.ERR_LINES_NOT_MEASURED, "Not all lines measured")

    o["production_status"] = "IN_PRODUCTION"
    domain.touch(o)
    return ok_object(domain.serialize_order(o))


# ---------------------------------------------------------------------------
# MARK-READY: IN_PRODUCTION -> READY
# ---------------------------------------------------------------------------
@bp.route("/framing-orders/<order_id>/mark-ready", methods=["POST"])
def mark_ready(order_id):
    auth = get_auth()
    require_role(auth, ("FrameProductionTech",))
    o = find_order_or_404(order_id)

    if o["production_status"] != "IN_PRODUCTION":
        errors.raise_err(errors.ERR_INVALID_STATE, "Order is not in IN_PRODUCTION")

    # cross-entity referential: every ProductionTask COMPLETED
    tasks = domain.order_tasks(order_id)
    for t in tasks:
        if t["task_status"] != "COMPLETED":
            errors.raise_err(errors.ERR_TASKS_INCOMPLETE, "Not all tasks completed")

    customer = db.customers[o["customer_id"]]

    measured = domain.measured_lines_sorted(order_id)
    fin = calc.final_invoice_total(measured, o["rush_requested"], customer["loyalty_discount_pct"])
    o["final_invoice_total"] = calc.to_float(fin)

    o["production_status"] = "READY"
    # payment_status unaffected by mark-ready
    domain.recompute_ledger(o)

    # emit READY notification
    _emit_notification(o, customer, kind="READY")

    domain.touch(o)

    # READY-but-unpaid raises no-show risk
    domain.recompute_customer_open_and_risk(customer)
    domain.touch(customer)

    return ok_object(domain.serialize_order(o))


# ---------------------------------------------------------------------------
# PICKUP: READY -> PICKED_UP
# ---------------------------------------------------------------------------
@bp.route("/framing-orders/<order_id>/pickup", methods=["POST"])
def pickup(order_id):
    auth = get_auth()
    require_role(auth, ("FrontDeskClerk",))
    o = find_order_or_404(order_id)

    if o["production_status"] != "READY":
        errors.raise_err(errors.ERR_INVALID_STATE, "Order is not in READY")

    # fiscal: PAID_IN_FULL required
    if o["payment_status"] != "PAID_IN_FULL":
        errors.raise_err(errors.ERR_BALANCE_OUTSTANDING, "Balance outstanding")

    customer = db.customers[o["customer_id"]]

    o["production_status"] = "PICKED_UP"
    o["_terminal_at"] = now_iso()
    domain.touch(o)

    # cascade into customer reliability
    domain.recompute_customer_open_and_risk(customer)
    domain.recompute_customer_reputation(customer)
    domain.touch(customer)

    return ok_object(domain.serialize_order(o))


# ---------------------------------------------------------------------------
# CANCEL: {INTAKE,QUOTED,IN_PRODUCTION,READY} -> CANCELLED
# ---------------------------------------------------------------------------
@bp.route("/framing-orders/<order_id>/cancel", methods=["POST"])
def cancel(order_id):
    auth = get_auth()
    require_role(auth, ("FrontDeskClerk",))
    o = find_order_or_404(order_id)

    if o["production_status"] not in ("INTAKE", "QUOTED", "IN_PRODUCTION", "READY"):
        errors.raise_err(errors.ERR_INVALID_STATE, "Order is in a terminal state")

    customer = db.customers[o["customer_id"]]

    # release all SCHEDULED/COMPLETED tasks
    for t in domain.order_tasks(order_id):
        if t["task_status"] in ("SCHEDULED", "COMPLETED"):
            t["task_status"] = "RELEASED"
            domain.touch(t)

    # refund if amount_paid > 0
    domain.recompute_ledger(o)
    if o["amount_paid"] > 0:
        refund = {
            "order_id": order_id,
            "kind": "REFUND",
            "amount": o["amount_paid"],
            "payment_status": "APPLIED",
        }
        domain.stamp_create(refund)
        db.payments[refund["id"]] = refund
        domain.recompute_ledger(o)
        o["payment_status"] = "REFUNDED"

    o["production_status"] = "CANCELLED"
    o["_terminal_at"] = now_iso()
    domain.touch(o)

    # customer reliability cascade
    domain.recompute_customer_open_and_risk(customer)
    domain.recompute_customer_reputation(customer)
    domain.touch(customer)

    return ok_object(domain.serialize_order(o))


# ---------------------------------------------------------------------------
# REORDER: clone a PICKED_UP order into a new INTAKE order
# ---------------------------------------------------------------------------
@bp.route("/framing-orders/<order_id>/reorder", methods=["POST"])
def reorder(order_id):
    auth = get_auth()
    require_role(auth, ("FrameDesigner", "FrontDeskClerk"))
    src = find_order_or_404(order_id)
    body = validate.get_json_body()

    if src["production_status"] != "PICKED_UP":
        errors.raise_err(errors.ERR_NOT_PICKED_UP, "Source order is not PICKED_UP")

    rush_requested = validate.opt(body, "rush_requested", False)
    validate.as_bool(rush_requested, "rush_requested")
    deposit_pct = validate.opt(body, "deposit_pct", 0.30)
    _validate_deposit_pct(deposit_pct)

    customer = db.customers[src["customer_id"]]

    new_order = _new_order(src["customer_id"], rush_requested, deposit_pct, reorder_of=order_id)
    db.framing_orders[new_order["id"]] = new_order

    # copy non-VOID source lines as fresh DRAFT lines
    for sl in domain.non_void_lines_sorted(order_id):
        nl = {
            "order_id": new_order["id"],
            "artwork_label": sl["artwork_label"],
            "nominal_width_in": sl["nominal_width_in"],
            "nominal_height_in": sl["nominal_height_in"],
            "measured_width_in": None,
            "measured_height_in": None,
            "mat_border_in": sl["mat_border_in"],
            "mat_layers": sl["mat_layers"],
            "glass_type": sl["glass_type"],
            "molding_rate_per_ui": sl["molding_rate_per_ui"],
            "mounting_type": sl["mounting_type"],
            "conservation_package": sl["conservation_package"],
            "is_fragile": sl["is_fragile"],
            "line_status": "DRAFT",
            "estimate_subtotal": 0,
            "final_subtotal": 0,
        }
        domain.stamp_create(nl)
        sub = calc.line_cost(nl, "NOMINAL")
        nl["estimate_subtotal"] = calc.to_float(sub)
        db.frame_lines[nl["id"]] = nl

    domain.recompute_has_fragile_line(new_order)

    # recompute owning customer open count and no-show risk
    domain.recompute_customer_open_and_risk(customer)
    domain.touch(customer)

    return ok_object(domain.serialize_order(new_order), status=201)


# ---------------------------------------------------------------------------
# notification emission helper
# ---------------------------------------------------------------------------
def _emit_notification(order, customer, kind):
    # channel/sent_to chosen from customer contact: prefer EMAIL when email
    # present, else SMS using phone.
    email = customer.get("email")
    phone = customer.get("phone")
    if email:
        channel = "EMAIL"
        sent_to = email
    else:
        channel = "SMS"
        sent_to = phone
    n = {
        "order_id": order["id"],
        "channel": channel,
        "kind": kind,
        "sent_to": sent_to,
    }
    domain.stamp_create(n, with_version=False)
    db.notifications[n["id"]] = n
    return n
