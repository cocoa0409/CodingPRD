"""Dispensary: lot expiry, aggregated stock, FEFO selection, pricing, reversal."""

from datetime import timedelta
from decimal import Decimal

import config
from clock import clock, parse_date, parse_instant
from store import db, ordered, touch
from services.money import dec, round_half_up


# --- memberships (shared reads) ----------------------------------------------


def active_memberships(patient_id):
    return ordered(
        [
            m
            for m in db.memberships.values()
            if m["patient_id"] == patient_id and m["status"] == "ACTIVE"
        ]
    )


def active_membership(patient_id):
    rows = active_memberships(patient_id)
    return rows[0] if rows else None


def membership_with_visits(patient_id):
    for m in active_memberships(patient_id):
        if m["visits_remaining"] >= 1:
            return m
    return None


def membership_with_credits(patient_id, cost):
    for m in active_memberships(patient_id):
        if m["lab_credits_remaining"] >= cost:
            return m
    return None


def messaging_included(patient_id):
    return any(m["includes_messaging"] for m in active_memberships(patient_id))


# --- lots and stock -----------------------------------------------------------


def lot_is_expired(lot):
    """Inclusive of the expiry date: a lot expiring today is already expired."""
    expiry = parse_date(lot["expiry_date"])
    if expiry is None:
        return False
    return clock.today() >= expiry


def lot_is_eligible(lot):
    return not lot["is_quarantined"] and not lot_is_expired(lot)


def product_stock(product_id):
    return sum(
        lot["quantity_on_hand"]
        for lot in db.lots.values()
        if lot["product_id"] == product_id and lot_is_eligible(lot)
    )


def select_lot_fefo(product_id, quantity):
    """First-expiry-first-out; ties broken by the earlier created_at. Ids never count."""
    pool = [
        lot
        for lot in db.lots.values()
        if lot["product_id"] == product_id
        and lot_is_eligible(lot)
        and lot["quantity_on_hand"] >= quantity
    ]
    if not pool:
        return None
    pool.sort(key=lambda l: (parse_date(l["expiry_date"]), l["_created_dt"], l["_seq"]))
    return pool[0]


# --- protocol line helpers ----------------------------------------------------


def item_dispenses(item_id, status=None):
    rows = [d for d in db.dispenses.values() if d["protocol_item_id"] == item_id]
    if status:
        rows = [d for d in rows if d["status"] == status]
    return rows


def last_dose_date(item):
    """Newest DISPENSED dispense date on the line, else the line's created_at date."""
    dispensed = item_dispenses(item["id"], "DISPENSED")
    if dispensed:
        dispensed.sort(
            key=lambda d: (parse_instant(d["dispensed_at"]), d["_created_dt"], d["_seq"]),
            reverse=True,
        )
        stamp = parse_instant(dispensed[0]["dispensed_at"])
        if stamp is not None:
            return stamp.date()
    created = parse_instant(item["created_at"])
    return created.date() if created else None


# --- pricing ------------------------------------------------------------------


def price_dispense(product, patient_id, quantity, professional_sample):
    """Three-way fork, first match wins; per-unit rounding BEFORE multiplication."""
    if professional_sample:
        variant = "PRACTITIONER_COST"
        unit = product["practitioner_cost_cents"]
    else:
        membership = active_membership(patient_id)
        if membership is not None:
            variant = "MEMBER"
            pct = dec(membership["dispensary_discount_pct"])
        else:
            variant = "RETAIL"
            pct = Decimal("0")
        raw_unit = dec(product["retail_price_cents"]) * (Decimal("1") - pct)
        unit = max(round_half_up(raw_unit), product["practitioner_cost_cents"])
    return variant, unit, unit * quantity


# --- reversal -----------------------------------------------------------------


def apply_reversal(dispense, reason=None, authorized_by=None):
    """DISPENSED -> REVERSED. Restocks the lot and grows the refunded counter."""
    dispense["status"] = "REVERSED"
    dispense["reversed_at"] = clock.stamp()
    dispense["reversal_reason"] = reason
    dispense["reversal_authorized_by_user_id"] = authorized_by
    lot = db.lots.get(dispense["product_lot_id"])
    if lot is not None:
        lot["quantity_on_hand"] += dispense["quantity"]
        touch(lot)
        product = db.products.get(lot["product_id"])
        if product is not None:
            product["stock_on_hand"] = product_stock(product["id"])
            touch(product)
    patient = db.patients.get(dispense["patient_id"])
    if patient is not None:
        patient["cash_refunded_total_cents"] += dispense["total_price_cents"]
        touch(patient)


def reversible_within_window(dispense):
    """dispensed_at within ADVERSE_REVERSAL_WINDOW_DAYS of the logical clock."""
    stamp = parse_instant(dispense["dispensed_at"])
    if stamp is None:
        return False
    return (clock.now() - stamp) <= timedelta(days=config.ADVERSE_REVERSAL_WINDOW_DAYS)
