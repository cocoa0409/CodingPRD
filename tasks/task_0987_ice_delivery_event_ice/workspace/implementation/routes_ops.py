"""Routes: delivery slots, cold-storage holds, dispatch runs, waitlist
entries, invoices, payments."""
from datetime import timedelta

import core
import domain
from core import (ALL_ROLES, agent_owns, as_enum, as_int, as_str,
                  authenticate, authorize, fail, get_body, need, ok, paginate,
                  parse_date_str, parse_time_str, reject_unknown)
from server import app, fetch, new_record
from store import (CUSTOMERS, DEPOTS, ENTRIES, HOLDS, INVOICES, ORDERS,
                   PAYMENTS, RUNS, SLOTS)
from views import (entry_view, hold_view, invoice_view, order_view,
                   payment_view, run_view, slot_view)

BILLING_READ_ROLES = {"PlatformAdmin", "BillingClerk", "CustomerAgent"}
DISPATCHER = {"Dispatcher"}


# ---------------------------------------------------------------------------
# Delivery slots
# ---------------------------------------------------------------------------
@app.route("/delivery-slots", methods=["POST"])
def create_slot():
    uid, role = authenticate()
    authorize(role, DISPATCHER)
    data = get_body()
    reject_unknown(data, {"depot_id", "date", "window_start", "window_end",
                          "capacity_pallets"})
    depot_id = as_str(need(data, "depot_id"), "depot_id")
    d = parse_date_str(need(data, "date"), "date")
    ws = parse_time_str(need(data, "window_start"), "window_start")
    we = parse_time_str(need(data, "window_end"), "window_end")
    if ws >= we:
        fail("ERR_INVALID_REQUEST", 400, "window_start must be before window_end")
    cap = as_int(need(data, "capacity_pallets"), "capacity_pallets", minimum=1)
    fetch(DEPOTS, depot_id, "Depot")  # rung 5: body FK existence
    if d < core.today():                # priority 12
        fail("ERR_DELIVERY_WINDOW_PAST", 409,
             "Slot date is before the current logical date")
    s = new_record()
    s.update({"depot_id": depot_id, "date": d, "window_start": ws,
              "window_end": we, "capacity_pallets": cap, "closed": False})
    SLOTS[s["id"]] = s
    return ok(slot_view(s), 201)


@app.route("/depots/<depot_id>/delivery-slots", methods=["GET"])
def list_slots(depot_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    fetch(DEPOTS, depot_id, "Depot")
    items = sorted((s for s in SLOTS.values() if s["depot_id"] == depot_id),
                   key=lambda s: s["_seq"])
    q = core.request.args
    if q.get("date") is not None:
        items = [s for s in items if s["date"].isoformat() == q.get("date")]
    if q.get("status") is not None:
        items = [s for s in items if domain.slot_status(s) == q.get("status")]
    return paginate(items, slot_view)


# ---------------------------------------------------------------------------
# Cold-storage holds
# ---------------------------------------------------------------------------
@app.route("/depots/<depot_id>/holds", methods=["GET"])
def list_depot_holds(depot_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    fetch(DEPOTS, depot_id, "Depot")
    items = sorted((h for h in HOLDS.values() if h["depot_id"] == depot_id),
                   key=lambda h: h["_seq"])
    q = core.request.args
    if q.get("status") is not None:
        items = [h for h in items if h["status"] == q.get("status")]
    if q.get("zone") is not None:
        items = [h for h in items if h["zone"] == q.get("zone")]
    return paginate(items, hold_view)


@app.route("/cold-storage-holds/<hold_id>/release", methods=["POST"])
def release_hold_endpoint(hold_id):
    uid, role = authenticate()
    authorize(role, {"DepotManager"})
    h = fetch(HOLDS, hold_id, "ColdStorageHold")
    if h["status"] in ("RELEASED", "EXPIRED"):
        fail("ERR_ALREADY_TERMINAL", 409, "Hold is already %s" % h["status"])
    domain.release_hold(h, "RELEASED")
    return ok(hold_view(h))


# ---------------------------------------------------------------------------
# Dispatch runs
# ---------------------------------------------------------------------------
@app.route("/dispatch-runs", methods=["POST"])
def create_run():
    uid, role = authenticate()
    authorize(role, DISPATCHER)
    data = get_body()
    reject_unknown(data, {"depot_id", "run_date", "vehicle_label", "max_pallets",
                          "ventilated_dry_ice_cap_lbs"})
    depot_id = as_str(need(data, "depot_id"), "depot_id")
    run_date = parse_date_str(need(data, "run_date"), "run_date")
    label = as_str(need(data, "vehicle_label"), "vehicle_label")
    max_pallets = as_int(need(data, "max_pallets"), "max_pallets", minimum=1)
    vent = as_int(need(data, "ventilated_dry_ice_cap_lbs"),
                  "ventilated_dry_ice_cap_lbs", minimum=0)
    fetch(DEPOTS, depot_id, "Depot")
    if run_date < core.today():         # priority 12
        fail("ERR_DELIVERY_WINDOW_PAST", 409,
             "Run date is before the current logical date")
    r = new_record()
    r.update({"depot_id": depot_id, "run_date": run_date, "vehicle_label": label,
              "max_pallets": max_pallets, "ventilated_dry_ice_cap_lbs": vent,
              "status": "PLANNED"})
    RUNS[r["id"]] = r
    return ok(run_view(r), 201)


@app.route("/dispatch-runs/<run_id>", methods=["GET"])
def get_run(run_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(run_view(fetch(RUNS, run_id, "DispatchRun")))


@app.route("/depots/<depot_id>/dispatch-runs", methods=["GET"])
def list_runs(depot_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    fetch(DEPOTS, depot_id, "Depot")
    items = sorted((r for r in RUNS.values() if r["depot_id"] == depot_id),
                   key=lambda r: r["_seq"])
    q = core.request.args
    if q.get("run_date") is not None:
        items = [r for r in items if r["run_date"].isoformat() == q.get("run_date")]
    if q.get("status") is not None:
        items = [r for r in items if r["status"] == q.get("status")]
    return paginate(items, run_view)


def run_terminal_guard(r):
    if r["status"] in ("COMPLETED", "CANCELLED"):
        fail("ERR_ALREADY_TERMINAL", 409, "Dispatch run is %s" % r["status"])


@app.route("/dispatch-runs/<run_id>/assign", methods=["POST"])
def assign_run(run_id):
    uid, role = authenticate()
    authorize(role, DISPATCHER)
    data = get_body()
    reject_unknown(data, {"order_ids"})
    order_ids = need(data, "order_ids")
    if not isinstance(order_ids, list) or any(
            not isinstance(x, str) for x in order_ids):
        fail("ERR_INVALID_REQUEST", 400, "Field 'order_ids' must be an array of strings")
    r = fetch(RUNS, run_id, "DispatchRun")
    run_terminal_guard(r)
    if r["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", 409, "Only a PLANNED run accepts assignments")
    candidates = []
    for oid in order_ids:               # rung 5: body FK existence
        candidates.append(fetch(ORDERS, oid, "Order"))
    for o in candidates:                # rung 8: per-order state checks
        if (o["fulfillment_status"] != "STAGED" or o["channel"] != "DELIVERY"
                or o["depot_id"] != r["depot_id"]
                or o["event_date"] != r["run_date"]
                or o["dispatch_run_id"] is not None):
            fail("ERR_INVALID_STATE", 409,
                 "Every assigned order must be STAGED, DELIVERY-channel, "
                 "homed at the run depot, dated to the run date, and unlinked")
    # Aggregates: ventilation (priority 10) before deck capacity (priority 23).
    cur_pallets, cur_dry = domain.run_assignment_totals(r["id"])
    add_pallets = 0
    add_dry = 0
    for o in candidates:
        p, d = domain.order_measures(o["id"])
        add_pallets += p
        add_dry += d
    if cur_dry + add_dry > r["ventilated_dry_ice_cap_lbs"]:
        fail("ERR_DRY_ICE_VENTILATION_EXCEEDED", 409,
             "Assign would exceed ventilated_dry_ice_cap_lbs")
    if cur_pallets + add_pallets > r["max_pallets"]:
        fail("ERR_RUN_CAPACITY_EXCEEDED", 409, "Assign would exceed max_pallets")
    # Atomic commit: no partial links.
    for o in candidates:
        o["dispatch_run_id"] = r["id"]
        domain.touch_order(o)
    r["version"] += 1
    r["updated_at"] = core.stamp()
    return ok(run_view(r))


@app.route("/dispatch-runs/<run_id>/lock", methods=["POST"])
def lock_run(run_id):
    uid, role = authenticate()
    authorize(role, DISPATCHER)
    r = fetch(RUNS, run_id, "DispatchRun")
    run_terminal_guard(r)
    if r["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", 409, "Only a PLANNED run can be locked")
    r["status"] = "LOCKED"
    r["version"] += 1
    r["updated_at"] = core.stamp()
    return ok(run_view(r))


@app.route("/dispatch-runs/<run_id>/start", methods=["POST"])
def start_run(run_id):
    uid, role = authenticate()
    authorize(role, DISPATCHER)
    r = fetch(RUNS, run_id, "DispatchRun")
    run_terminal_guard(r)
    if r["status"] != "LOCKED":
        fail("ERR_INVALID_STATE", 409, "Only a LOCKED run can be started")
    assigned = [o for o in ORDERS.values()
                if o["dispatch_run_id"] == r["id"]
                and o["fulfillment_status"] == "STAGED"]
    if not assigned:
        fail("ERR_INVALID_STATE", 409, "Run has no assigned orders")
    r["status"] = "IN_PROGRESS"
    r["version"] += 1
    r["updated_at"] = core.stamp()
    for o in sorted(assigned, key=lambda o: o["_seq"]):
        o["fulfillment_status"] = "IN_TRANSIT"
        domain.touch_order(o)
        hold = domain.active_hold_for_order(o["id"])
        if hold is not None and hold["status"] == "OCCUPIED":
            # Product left the freezer: release + depot recompute + sweep.
            domain.release_hold(hold, "RELEASED")
    return ok(run_view(r))


@app.route("/dispatch-runs/<run_id>/complete", methods=["POST"])
def complete_run(run_id):
    uid, role = authenticate()
    authorize(role, DISPATCHER)
    r = fetch(RUNS, run_id, "DispatchRun")
    run_terminal_guard(r)
    if r["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", 409, "Only an IN_PROGRESS run can be completed")
    r["status"] = "COMPLETED"
    r["version"] += 1
    r["updated_at"] = core.stamp()
    for o in sorted((o for o in ORDERS.values()
                     if o["dispatch_run_id"] == r["id"]
                     and o["fulfillment_status"] == "IN_TRANSIT"),
                    key=lambda o: o["_seq"]):
        o["fulfillment_status"] = "DELIVERED"
        o["fulfilled_at"] = core.stamp()
        domain.touch_order(o)
    return ok(run_view(r))


@app.route("/dispatch-runs/<run_id>/cancel", methods=["POST"])
def cancel_run(run_id):
    uid, role = authenticate()
    authorize(role, DISPATCHER)
    r = fetch(RUNS, run_id, "DispatchRun")
    run_terminal_guard(r)
    if r["status"] not in ("PLANNED", "LOCKED"):
        fail("ERR_INVALID_STATE", 409,
             "Only a PLANNED or LOCKED run can be cancelled")
    for o in ORDERS.values():
        if o["dispatch_run_id"] == r["id"]:
            o["dispatch_run_id"] = None
            domain.touch_order(o)
    r["status"] = "CANCELLED"
    r["version"] += 1
    r["updated_at"] = core.stamp()
    return ok(run_view(r))


@app.route("/dispatch-runs/<run_id>/orders", methods=["GET"])
def list_run_orders(run_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    r = fetch(RUNS, run_id, "DispatchRun")
    items = sorted((o for o in ORDERS.values() if o["dispatch_run_id"] == r["id"]),
                   key=lambda o: o["_seq"])
    if role == "CustomerAgent":
        items = [o for o in items if o["customer_id"] == uid]
    return paginate(items, order_view)


# ---------------------------------------------------------------------------
# Waitlist entries
# ---------------------------------------------------------------------------
@app.route("/depots/<depot_id>/waitlist-entries", methods=["GET"])
def list_depot_entries(depot_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    fetch(DEPOTS, depot_id, "Depot")
    items = sorted((e for e in ENTRIES.values() if e["depot_id"] == depot_id),
                   key=lambda e: e["_seq"])
    if role == "CustomerAgent":
        items = [e for e in items
                 if ORDERS[e["order_id"]]["customer_id"] == uid]
    q = core.request.args
    if q.get("status") is not None:
        items = [e for e in items if e["status"] == q.get("status")]
    return paginate(items, entry_view)


@app.route("/waitlist-entries/<entry_id>/withdraw", methods=["POST"])
def withdraw_entry(entry_id):
    uid, role = authenticate()
    authorize(role, {"CustomerAgent"})
    e = fetch(ENTRIES, entry_id, "WaitlistEntry")
    o = ORDERS[e["order_id"]]
    agent_owns(uid, role, o["customer_id"])
    if e["status"] in ("PROMOTED", "WITHDRAWN", "EXPIRED"):
        fail("ERR_ALREADY_TERMINAL", 409, "Waitlist entry is %s" % e["status"])
    e["status"] = "WITHDRAWN"
    if o["fulfillment_status"] == "WAITLISTED":
        o["fulfillment_status"] = "CANCELLED"
        domain.release_slot_reservation(o)
        domain.touch_order(o)
    return ok(entry_view(e))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@app.route("/invoices/generate", methods=["POST"])
def generate_invoice():
    uid, role = authenticate()
    authorize(role, {"BillingClerk"})
    data = get_body()
    reject_unknown(data, {"customer_id", "period_start", "period_end"})
    cid = as_str(need(data, "customer_id"), "customer_id")
    ps = parse_date_str(need(data, "period_start"), "period_start")
    pe = parse_date_str(need(data, "period_end"), "period_end")
    if ps >= pe:
        fail("ERR_INVALID_REQUEST", 400, "period_start must be before period_end")
    fetch(CUSTOMERS, cid, "Customer")   # rung 5: body FK existence
    # Period conflict checked first (priority 24), then eligibility (25).
    for inv in INVOICES.values():
        if (inv["customer_id"] == cid and inv["period_start"] == ps
                and inv["period_end"] == pe and inv["status"] != "VOID"):
            fail("ERR_INVOICE_PERIOD_CONFLICT", 409,
                 "A non-VOID invoice already exists for this customer and period")
    eligible = [o for o in ORDERS.values()
                if o["customer_id"] == cid
                and o["billing_status"] == "UNBILLED"
                and o["fulfillment_status"] in domain.BILLABLE_FULFILLMENTS
                and o["fulfilled_at"] is not None
                and ps <= core.parse_date_str(
                    o["fulfilled_at"][:10], "fulfilled_at") < pe]
    if not eligible:
        fail("ERR_NO_BILLABLE_ORDERS", 409,
             "No eligible billable orders for this customer and period")
    # Attachment order: fulfilled_at ASC, tie-break created_at ASC.
    eligible.sort(key=lambda o: (o["fulfilled_at"], o["created_at"]))
    inv = new_record()
    inv.update({
        "customer_id": cid, "period_start": ps, "period_end": pe,
        "status": "DRAFT",
        "merchandise_subtotal_cents": sum(o["merchandise_subtotal_cents"] for o in eligible),
        "discount_cents": sum(o["discount_cents"] for o in eligible),
        "delivery_fee_cents": sum(o["delivery_fee_cents"] for o in eligible),
        "surcharge_cents": sum(o["surcharge_cents"] for o in eligible),
        "deposit_cents": sum(o["deposit_cents"] for o in eligible),
        "total_cents": sum(o["total_cents"] for o in eligible),
        "amount_paid_cents": 0, "due_date": None,
        "issued_by_user_id": None, "voided_by_user_id": None,
    })
    inv["balance_due_cents"] = inv["total_cents"]
    INVOICES[inv["id"]] = inv
    for o in eligible:
        o["billing_status"] = "INVOICED"
        o["invoice_id"] = inv["id"]
        domain.touch_order(o)
    return ok(invoice_view(inv), 201)


@app.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    uid, role = authenticate()
    authorize(role, BILLING_READ_ROLES)
    inv = fetch(INVOICES, invoice_id, "Invoice")
    agent_owns(uid, role, inv["customer_id"])
    return ok(invoice_view(inv))


@app.route("/customers/<customer_id>/invoices", methods=["GET"])
def list_customer_invoices(customer_id):
    uid, role = authenticate()
    authorize(role, BILLING_READ_ROLES)
    c = fetch(CUSTOMERS, customer_id, "Customer")
    agent_owns(uid, role, c["id"])
    items = sorted((i for i in INVOICES.values() if i["customer_id"] == customer_id),
                   key=lambda i: i["_seq"])
    status = core.request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return paginate(items, invoice_view)


@app.route("/invoices/<invoice_id>/issue", methods=["POST"])
def issue_invoice(invoice_id):
    uid, role = authenticate()
    authorize(role, {"BillingClerk"})
    inv = fetch(INVOICES, invoice_id, "Invoice")
    if inv["status"] in ("VOID", "PAID"):
        fail("ERR_ALREADY_TERMINAL", 409,
             "Invoice is %s" % inv["status"])
    if inv["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "Only a DRAFT invoice can be issued")
    cust = CUSTOMERS[inv["customer_id"]]
    inv["status"] = "ISSUED"
    inv["issued_by_user_id"] = uid
    inv["due_date"] = core.today() + timedelta(
        days=domain.TERMS_DAYS[cust["credit_terms"]])
    inv["version"] += 1
    inv["updated_at"] = core.stamp()
    return ok(invoice_view(inv))


@app.route("/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    uid, role = authenticate()
    authorize(role, {"BillingClerk"})
    inv = fetch(INVOICES, invoice_id, "Invoice")
    if inv["status"] == "VOID":
        fail("ERR_ALREADY_TERMINAL", 409, "Invoice is already VOID")
    # Segregation of duties is evaluated before the PAID prohibition (PRD §3.8).
    if inv["issued_by_user_id"] is not None and inv["issued_by_user_id"] == uid:
        fail("ERR_SEGREGATION_OF_DUTIES", 403,
             "The clerk who issued an invoice cannot void it")
    if inv["status"] == "PAID":
        fail("ERR_INVOICE_NOT_VOIDABLE", 409, "A PAID invoice cannot be voided")
    for o in domain.invoice_orders(inv["id"]):
        if o["billing_status"] == "INVOICED":
            o["billing_status"] = "UNBILLED"
            o["invoice_id"] = None
            domain.touch_order(o)
    if inv["amount_paid_cents"] > 0:
        cust = CUSTOMERS[inv["customer_id"]]
        cust["credit_balance_cents"] += inv["amount_paid_cents"]
        cust["version"] += 1
        cust["updated_at"] = core.stamp()
        inv["amount_paid_cents"] = 0
        inv["balance_due_cents"] = inv["total_cents"]
    inv["status"] = "VOID"
    inv["voided_by_user_id"] = uid
    inv["version"] += 1
    inv["updated_at"] = core.stamp()
    return ok(invoice_view(inv))


@app.route("/invoices/<invoice_id>/orders", methods=["GET"])
def list_invoice_orders(invoice_id):
    uid, role = authenticate()
    authorize(role, BILLING_READ_ROLES)
    inv = fetch(INVOICES, invoice_id, "Invoice")
    agent_owns(uid, role, inv["customer_id"])
    return paginate(domain.invoice_orders(inv["id"]), order_view)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@app.route("/payments", methods=["POST"])
def create_payment():
    uid, role = authenticate()
    authorize(role, {"BillingClerk"})
    data = get_body()
    reject_unknown(data, {"customer_id", "amount_cents", "method"})
    cid = as_str(need(data, "customer_id"), "customer_id")
    amount = need(data, "amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool):
        fail("ERR_INVALID_REQUEST", 400, "Field 'amount_cents' must be an integer")
    method = as_enum(need(data, "method"), "method", {"ACH", "CARD", "CASH"})
    cust = fetch(CUSTOMERS, cid, "Customer")
    if amount < 1:                      # priority 28
        fail("ERR_PAYMENT_AMOUNT_INVALID", 400, "Payment amount_cents must be >= 1")
    p = {"id": core.new_id(), "_seq": core.next_seq(),
         "customer_id": cid, "amount_cents": amount, "method": method,
         "received_at": core.stamp(), "applied_cents": 0,
         "overpayment_cents": 0, "allocations": [],
         "created_at": core.stamp()}
    domain.payment_waterfall(cust, p)
    PAYMENTS[p["id"]] = p
    return ok(payment_view(p), 201)


@app.route("/customers/<customer_id>/payments", methods=["GET"])
def list_customer_payments(customer_id):
    uid, role = authenticate()
    authorize(role, BILLING_READ_ROLES)
    c = fetch(CUSTOMERS, customer_id, "Customer")
    agent_owns(uid, role, c["id"])
    items = sorted((p for p in PAYMENTS.values() if p["customer_id"] == customer_id),
                   key=lambda p: p["_seq"])
    return paginate(items, payment_view)
