"""Shared route helpers: serialization, filtering, lookups, ledger recomputes."""
from decimal import Decimal

import auth
import calc
import clock
import store
from errors import err
from shape import D, q

ZERO = Decimal("0")


def view(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def views(rows):
    return [view(r) for r in rows]


# ------------------------------------------------------------- lookups ---
def need(collection, rid, error_id):
    row = store.get(collection, rid)
    if row is None:
        raise err(error_id, "%s not found" % collection[:-1])
    return row


def grade_by_code(code):
    for r in store.all_rows("fiber_grades"):
        if r["grade_code"] == code:
            return r
    return None


def spec_by_code(code):
    for r in store.all_rows("paper_grade_specs"):
        if r["product_code"] == code:
            return r
    return None


def need_grade(code):
    g = grade_by_code(code)
    if g is None:
        raise err("ERR_GRADE_CODE_NOT_FOUND", "fiber grade %s not declared" % code)
    return g


def need_spec(code):
    s = spec_by_code(code)
    if s is None:
        raise err("ERR_GRADE_CODE_NOT_FOUND", "paper grade spec %s not declared" % code)
    return s


def current_quote(symbol, month):
    for r in store.all_rows("market_index_quotes"):
        if r["index_symbol"] == symbol and r["effective_month"] == month and not r["superseded"]:
            return r
    return None


def prior_month(month):
    y, m = month.split("-")
    y, m = int(y), int(m)
    m -= 1
    if m == 0:
        m = 12
        y -= 1
    return "%04d-%02d" % (y, m)


def unique_or_conflict(collection, field, value):
    for r in store.all_rows(collection):
        if r.get(field) == value:
            raise err("ERR_DUPLICATE_KEY", "%s '%s' already exists" % (field, value))


# ------------------------------------------------------------ listing ---
def filtered(collection, filters, extra=None):
    """filters: {query_param: row_field}. extra: optional predicate."""
    from flask import request
    rows = store.all_rows(collection)
    for param, field in filters.items():
        val = request.args.get(param)
        if val is None:
            continue
        if val in ("true", "false"):
            want = (val == "true")
            rows = [r for r in rows if bool(r.get(field)) == want]
        else:
            rows = [r for r in rows if str(r.get(field)) == val]
    if extra is not None:
        rows = [r for r in rows if extra(r)]
    return rows


def scope_supplier(rows):
    if auth.role() == "Supplier":
        return [r for r in rows if r.get("supplier_id") == auth.user_id()]
    return rows


def scope_customer(rows):
    if auth.role() == "Customer":
        return [r for r in rows if r.get("customer_id") == auth.user_id()]
    return rows


# ------------------------------------------------- reject stream ledger ---
def append_reject(source_kind, source_ref_id, dry_solids_tons, disposition="PENDING"):
    return store.insert("reject_streams", {
        "source_kind": source_kind,
        "source_ref_id": source_ref_id,
        "dry_solids_tons": float(q(D(dry_solids_tons), 3)),
        "disposition": disposition,
        "manifest_id": None,
        "reversal_of_id": None,
    })


# ------------------------------------------------------- fiber ledger ---
def recompute_lot(lot):
    """tons_consumed / tons_available / status from live pulp batches."""
    consumed = ZERO
    for b in store.all_rows("pulp_batches"):
        if b["status"] == "CANCELLED":
            continue
        if b.get("_reserved") is not True:
            continue
        for ln in b["furnish_lines"]:
            if ln["inventory_lot_id"] == lot["id"]:
                consumed += D(ln["tons_charged"])
    consumed = q(consumed, 3)
    avail = q(D(lot["tons_received"]) - consumed, 3)
    if avail < ZERO:
        avail = ZERO
    lot["tons_consumed"] = float(consumed)
    lot["tons_available"] = float(avail)
    if lot["status"] != "QUARANTINED":
        lot["status"] = "DEPLETED" if avail == ZERO else "AVAILABLE"
    store.touch("fiber_inventory_lots", lot)
    return lot


def recompute_batch_available(batch):
    consumed = ZERO
    for r in store.all_rows("production_runs"):
        # §3.5: the draw is booked by run START ("Starting a run has four side
        # effects. The run's `pulp_draw_tons` is added into the batch's
        # `consumed_tons`") and released by abort, so a run still SCHEDULED has
        # drawn nothing.
        if (r.get("pulp_batch_id") == batch["id"]
                and r["run_status"] in ("RUNNING", "COMPLETED")):
            consumed += D(r["pulp_draw_tons"])
    batch["consumed_tons"] = float(q(consumed, 3))
    if batch["status"] == "APPROVED" and batch.get("final_accepted_tons") is not None:
        batch["available_tons"] = float(q(D(batch["final_accepted_tons"]) - consumed, 3))
    else:
        batch["available_tons"] = float(q(ZERO, 3))
    return batch


# ------------------------------------------------------ purchase order ---
def recompute_po_received(po):
    total = ZERO
    for r in store.all_rows("fiber_receipts"):
        if r["purchase_order_id"] == po["id"] and r["status"] in ("ACCEPTED", "DOWNGRADED"):
            total += D(r["net_tons"])
    po["received_net_tons"] = float(q(total, 2))
    return po


def advance_po_on_receipt(po):
    """PRD §3.1 tonnage-driven advance; recompute + version bump."""
    recompute_po_received(po)
    threshold = q(D(po["contracted_tons"]) * Decimal("0.98"), 10)
    got = D(po["received_net_tons"])
    if po["status"] == "CONFIRMED":
        po["status"] = "CLOSED" if got >= threshold else "PARTIALLY_RECEIVED"
    elif po["status"] == "PARTIALLY_RECEIVED":
        if got >= threshold:
            po["status"] = "CLOSED"
    store.touch("fiber_purchase_orders", po)


# ----------------------------------------------------- supplier posture ---
def strike_count(supplier_id):
    n = 0
    for r in store.all_rows("fiber_receipts"):
        if r["supplier_id"] != supplier_id:
            continue
        if r["status"] in ("DOWNGRADED", "REJECTED") and r.get("dispositioned_by_user_id"):
            n += 1
    return n


def recompute_supplier(sup):
    n = strike_count(sup["id"])
    posture = calc.supplier_qualification_posture(n)
    prev = sup["qualification_status"]
    sup["contamination_strike_count"] = n
    sup["qualification_status"] = posture
    if posture == "PROBATION":
        if prev != "PROBATION":
            sup["probation_entered_at"] = clock.now_iso()
    elif posture == "QUALIFIED":
        sup["probation_entered_at"] = None
    store.touch("suppliers", sup)
    return posture, prev


# ----------------------------------------------------------- permit ---
def the_permit():
    """The mill discharges under a single permit; return the first, or None."""
    rows = store.all_rows("effluent_permits")
    return rows[0] if rows else None


def permit_window_readings(permit):
    live = [r for r in store.all_rows("effluent_readings")
            if r["permit_id"] == permit["id"] and not r["voided"]]
    return calc.effluent_rolling_compliance(live, permit)


def recompute_permit(permit):
    res = permit_window_readings(permit)
    prev = permit["compliance_posture"]
    permit["rolling_bod_kg_per_day"] = res["rolling_bod_kg_per_day"]
    permit["rolling_tss_kg_per_day"] = res["rolling_tss_kg_per_day"]
    permit["exceedance_day_count"] = res["exceedance_day_count"]
    permit["compliance_posture"] = res["compliance_posture"]
    if res["compliance_posture"] != prev:
        permit["posture_changed_at"] = clock.now_iso()
    store.touch("effluent_permits", permit)
    if res["compliance_posture"] == "EXCEEDANCE" and prev != "EXCEEDANCE":
        _exceedance_cascade()
    return permit


def _exceedance_cascade():
    """PRD §3.7 three hops: void DRAFT LAND_APPLICATION manifests, unclaim rows."""
    for m in store.all_rows("sludge_manifests"):
        if m["status"] == "DRAFT" and m["destination"] == "LAND_APPLICATION":
            m["status"] = "VOIDED"
            store.touch("sludge_manifests", m)
            for rs in store.all_rows("reject_streams"):
                if rs.get("manifest_id") == m["id"]:
                    rs["manifest_id"] = None
                    rs["disposition"] = "PENDING"


# ------------------------------------------------------- order ledger ---
def order_roll_sets(order_id):
    return [r for r in store.all_rows("roll_sets") if r.get("allocated_order_id") == order_id]


def recompute_order_ledger(order):
    alloc = ZERO
    shipped = ZERO
    for rs in order_roll_sets(order["id"]):
        if rs["status"] in ("ALLOCATED", "SHIPPED"):
            alloc += D(rs["net_tons"])
        if rs["status"] == "SHIPPED":
            shipped += D(rs["net_tons"])
    order["allocated_tons"] = float(q(alloc, 3))
    order["shipped_tons"] = float(q(shipped, 3))
    short = D(order["ordered_tons"]) - alloc
    if short < ZERO:
        short = ZERO
    order["shortfall_tons"] = float(q(short, 3))
    return order


def advance_order_on_allocation(order):
    """PRD §3.6 status drive after an allocation lands."""
    recompute_order_ledger(order)
    alloc = D(order["allocated_tons"])
    ordered = D(order["ordered_tons"])
    if order["status"] in ("IN_PRODUCTION", "PARTIALLY_ALLOCATED"):
        if alloc >= ordered:
            order["status"] = "ALLOCATED"
            order["shortfall_tons"] = float(q(ZERO, 3))
        else:
            order["status"] = "PARTIALLY_ALLOCATED"
    store.touch("customer_orders", order)
    return order


def unwind_order_after_quarantine(order):
    """PRD §3.6 reverse move: ALLOCATED -> PARTIALLY_ALLOCATED when tonnage strips."""
    recompute_order_ledger(order)
    if order["status"] == "ALLOCATED" and D(order["allocated_tons"]) < D(order["ordered_tons"]):
        order["status"] = "PARTIALLY_ALLOCATED"
    store.touch("customer_orders", order)
    return order


# --------------------------------------------------------- run ledger ---
def run_roll_sets(run_id):
    return [r for r in store.all_rows("roll_sets") if r["production_run_id"] == run_id]


def recompute_run_produced(run):
    total = ZERO
    for rs in run_roll_sets(run["id"]):
        if rs["status"] != "REWOUND":
            total += D(rs["net_tons"])
    run["produced_tons"] = float(q(total, 3))
    return run


def deschedule_orders_of_run(run_id):
    for o in store.all_rows("customer_orders"):
        if o.get("scheduled_run_id") == run_id and o["status"] in ("SCHEDULED", "IN_PRODUCTION"):
            o["status"] = "SUBMITTED"
            o["scheduled_run_id"] = None
            o["deschedule_count"] = int(o["deschedule_count"]) + 1
            recompute_order_ledger(o)
            store.touch("customer_orders", o)


# ------------------------------------------------- supplier suspension cascade ---
def supplier_suspension_cascade(supplier_id):
    """PRD §3.2 hops two, three and four."""
    quarantined = []
    for lot in store.all_rows("fiber_inventory_lots"):
        receipt = store.get("fiber_receipts", lot["receipt_id"])
        if receipt is None or receipt["supplier_id"] != supplier_id:
            continue
        if lot["status"] == "AVAILABLE":
            lot["status"] = "QUARANTINED"
            store.touch("fiber_inventory_lots", lot)
            quarantined.append(lot["id"])
    if not quarantined:
        return
    cancelled_batches = []
    for b in store.all_rows("pulp_batches"):
        if b["status"] != "QUEUED":
            continue
        if any(ln["inventory_lot_id"] in quarantined for ln in b["furnish_lines"]):
            b["status"] = "CANCELLED"
            b["_reserved"] = False
            store.touch("pulp_batches", b)
            cancelled_batches.append(b["id"])
    if not cancelled_batches:
        return
    for run in store.all_rows("production_runs"):
        if run.get("pulp_batch_id") in cancelled_batches and run["run_status"] == "SCHEDULED":
            run["run_status"] = "ABORTED"
            run["quality_status"] = "CONDEMNED"
            store.touch("production_runs", run)
            deschedule_orders_of_run(run["id"])
