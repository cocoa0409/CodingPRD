"""Shared domain services: derived aggregates, quoting, the blank ledger,
settlement appends and the multi-hop cascades."""

from datetime import timedelta

import calc
from errors import ApiError
from store import db, fmt_dt, now, sorted_rows, stamp_common, stamp_event, touch
from validate import parse_date


# --- lookups ---------------------------------------------------------------

def get_or_404(collection, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def order_prescription(order):
    return db.prescriptions.get(order["prescription_id"])


def order_design(order):
    return db.lens_designs.get(order["lens_design_id"])


def order_patient(order):
    return db.patients.get(order["patient_id"])


def patient_plan(patient):
    if patient is None or not patient.get("insurance_plan_id"):
        return None
    return db.insurance_plans.get(patient["insurance_plan_id"])


def newest_layout(rx_order_id):
    rows = [l for l in sorted_rows(db.frame_layouts, reverse=True)
            if l["rx_order_id"] == rx_order_id]
    return rows[0] if rows else None


def order_jobs(rx_order_id):
    return [j for j in sorted_rows(db.lab_jobs) if j["rx_order_id"] == rx_order_id]


def newest_job(rx_order_id):
    rows = order_jobs(rx_order_id)
    return rows[-1] if rows else None


def active_job(rx_order_id):
    """The order's newest job that is not in a terminal state."""
    for job in reversed(order_jobs(rx_order_id)):
        if job["status"] not in ("RELEASED", "SCRAPPED"):
            return job
    return None


def routed_job(rx_order_id):
    """The newest non-scrapped job -- the one whose route the final quote uses."""
    for job in reversed(order_jobs(rx_order_id)):
        if job["status"] != "SCRAPPED":
            return job
    return None


def job_operations(lab_job_id):
    return [o for o in sorted_rows(db.lab_operations) if o["lab_job_id"] == lab_job_id]


def job_inspections(lab_job_id):
    return [i for i in sorted_rows(db.quality_inspections) if i["lab_job_id"] == lab_job_id]


def order_entries(rx_order_id):
    return [e for e in sorted_rows(db.settlement_entries) if e["rx_order_id"] == rx_order_id]


# --- derived aggregates ----------------------------------------------------

BENEFIT_QUALIFYING_BILLING = ("BENEFIT_APPLIED", "PATIENT_SETTLED", "REFUND_DUE")


def verified_rx_count(prescriber_id):
    return sum(
        1
        for rx in db.prescriptions.values()
        if rx["prescriber_id"] == prescriber_id and rx["verification_status"] == "VERIFIED"
    )


def benefit_used_cents(patient, exclude_order_id=None):
    start_date = parse_date(patient.get("benefit_period_start"))
    if start_date is None:
        return 0
    window_start = calc.expiration_instant(start_date, 0)
    window_end = calc.expiration_instant(start_date, calc.BENEFIT_PERIOD_MONTHS)
    total = 0
    for order in db.rx_orders.values():
        if order["patient_id"] != patient["id"]:
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        if order["billing_status"] not in BENEFIT_QUALIFYING_BILLING:
            continue
        applied = order.get("benefit_applied_at")
        if applied is None or applied < window_start or applied >= window_end:
            continue
        total += int(order.get("insurance_benefit_cents") or 0)
    return total


# --- settlement ledger ----------------------------------------------------

def append_entry(rx_order_id, entry_type, amount_cents, memo=None):
    row = stamp_event(
        {
            "rx_order_id": rx_order_id,
            "entry_type": entry_type,
            "amount_cents": int(amount_cents),
            "memo": memo,
            "effective_at": now(),
        }
    )
    db.settlement_entries[row["id"]] = row
    return row


def has_entry(rx_order_id, entry_type):
    return any(e["entry_type"] == entry_type for e in order_entries(rx_order_id))


# --- blank ledger ---------------------------------------------------------

def allocate_blank(lot):
    lot["on_hand_qty"] -= 1
    lot["allocated_qty"] += 1
    if lot["on_hand_qty"] == 0:
        lot["status"] = "DEPLETED"
    touch(lot)


def return_blank(lot):
    lot["allocated_qty"] -= 1
    lot["on_hand_qty"] += 1
    if lot["status"] == "DEPLETED" and lot["on_hand_qty"] > 0:
        lot["status"] = "AVAILABLE"
    touch(lot)


def scrap_blank(lot):
    lot["allocated_qty"] -= 1
    lot["scrapped_qty"] += 1
    touch(lot)


def consume_blank(lot):
    lot["allocated_qty"] -= 1
    lot["consumed_qty"] += 1
    touch(lot)


def job_holds_blank(job):
    return bool(job.get("_holds_allocation")) and job.get("blank_lot_id")


def release_job_allocation(job, mode):
    """mode: 'return' | 'scrap' | 'consume'."""
    if not job_holds_blank(job):
        return None
    lot = db.lens_blank_lots.get(job["blank_lot_id"])
    if lot is None:
        return None
    if mode == "return":
        return_blank(lot)
    elif mode == "scrap":
        scrap_blank(lot)
    else:
        consume_blank(lot)
    job["_holds_allocation"] = False
    return lot


# --- turnaround / quoting -------------------------------------------------

def repromise(order, route, variant):
    hours, _fee = calc.turnaround(
        order["product_tier"], bool(order.get("expedite_requested")), route, variant, 0
    )
    order["promised_tat_hours"] = hours
    order["promised_due_at"] = order["created_at"] + timedelta(
        hours=hours + calc.BACKORDER_EXTENSION_HOURS * order.get("_backorder_count", 0)
    )


def apply_provisional_quote(order):
    design = order_design(order)
    q = calc.quote(order, design, None, "PROVISIONAL")
    plan = patient_plan(order_patient(order))
    estimated = calc.benefit_waterfall(
        q["components"], design, plan, q["expedite_fee_cents"], apply_annual_cap=False
    )
    order["gross_charge_cents"] = q["gross_charge_cents"]
    order["expedite_fee_cents"] = q["expedite_fee_cents"]
    order["estimated_benefit_cents"] = estimated
    order["patient_portion_cents"] = q["gross_charge_cents"] - estimated
    order["quote_variant"] = "PROVISIONAL"
    order["promised_tat_hours"] = q["promised_tat_hours"]
    order["promised_due_at"] = order["created_at"] + timedelta(hours=q["promised_tat_hours"])


def final_quote(order, route):
    design = order_design(order)
    return calc.quote(order, design, route, "FINAL")


# --- cancellation ---------------------------------------------------------

def cancel_order_effects(order):
    """The single withdrawal side-effect set shared by the manual cancel and by
    hop 3 of the prescriber-standing cascade (PRD 3.9)."""
    job = active_job(order["id"])
    if job is not None:
        for op in job_operations(job["id"]):
            if op["status"] == "SCHEDULED":
                op["status"] = "CANCELLED"
                op["cancel_reason"] = "ORDER_CANCELLED"
                touch(op)
        release_job_allocation(job, "return")
        job["status"] = "SCRAPPED"
        job["scrap_reason"] = "ORDER_CANCELLED"
        touch(job)
    order["fulfillment_status"] = "CANCELLED"
    order["billing_status"] = "CANCELLED_NO_CHARGE"
    order["gross_charge_cents"] = 0
    order["patient_portion_cents"] = 0
    order["expedite_fee_cents"] = 0
    order["estimated_benefit_cents"] = 0
    order["insurance_benefit_cents"] = 0
    touch(order)


# --- prescriber-standing cascade -----------------------------------------

def prescriber_standing_cascade(prescriber):
    """Hop 2 and hop 3; hop 1 (the status write) is done by the caller."""
    rejected_ids = []
    for rx in sorted_rows(db.prescriptions):
        if rx["prescriber_id"] != prescriber["id"]:
            continue
        if rx["verification_status"] != "VERIFIED":
            continue
        rx["verification_status"] = "REJECTED"
        rx["verification_note"] = "PRESCRIBER_STANDING_LOST"
        rx["verified_at"] = None
        touch(rx)
        rejected_ids.append(rx["id"])
    if not rejected_ids:
        return
    for order in sorted_rows(db.rx_orders):
        if order["prescription_id"] not in rejected_ids:
            continue
        if order["fulfillment_status"] not in ("DRAFT", "LAYOUT_READY"):
            continue
        if order["billing_status"] != "PROVISIONAL_QUOTED":
            continue
        cancel_order_effects(order)


# --- blank backorder promotion -------------------------------------------

def promote_backordered_jobs(lot):
    """After a replenishment, waiting jobs are promoted oldest-first, one blank
    each, while on-hand stock lasts (PRD 3.5)."""
    waiting = [
        j
        for j in sorted_rows(db.lab_jobs)
        if j["status"] == "BLANK_BACKORDER"
    ]
    waiting.sort(key=lambda j: (j["created_at"], j["_seq"]))
    for job in waiting:
        if lot["on_hand_qty"] <= 0:
            break
        order = db.rx_orders.get(job["rx_order_id"])
        layout = db.frame_layouts.get(job["frame_layout_id"])
        if order is None or layout is None:
            continue
        if lot["lens_design_id"] != order["lens_design_id"]:
            continue
        if calc.D(lot["diameter_mm"]) < calc.D(layout["required_blank_diameter_mm"]):
            continue
        if lot["status"] != "AVAILABLE":
            continue
        allocate_blank(lot)
        job["blank_lot_id"] = lot["id"]
        job["_holds_allocation"] = True
        job["status"] = "QUEUED"
        touch(job)
