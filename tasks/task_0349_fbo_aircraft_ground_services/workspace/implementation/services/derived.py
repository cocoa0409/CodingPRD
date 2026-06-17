"""Derived-field computation and cross-entity recompute helpers."""
import math

import db


def compute_weight_class(mtow_lb):
    """PRD §3.1: LIGHT < 12500; MID >= 12500 and < 41000; HEAVY >= 41000."""
    if mtow_lb < 12500:
        return "LIGHT"
    if mtow_lb < 41000:
        return "MID"
    return "HEAVY"


def weight_class_accepted(aircraft_class, spot_max_class):
    """PRD §3.4: HEAVY spot accepts any; MID accepts {LIGHT,MID}; LIGHT accepts {LIGHT}."""
    rank = {"LIGHT": 1, "MID": 2, "HEAVY": 3}
    return rank[aircraft_class] <= rank[spot_max_class]


def compute_nights(arrival_dt, departure_dt):
    """PRD §3.3: ceil((departure - arrival) / 24h), floor of 1 night."""
    seconds = (departure_dt - arrival_dt).total_seconds()
    nights = math.ceil(seconds / 86400.0)
    if nights < 1:
        nights = 1
    return nights


def recompute_open_invoice_balance(operator):
    """PRD §3.1: sum over the operator's invoices in {ISSUED, PAST_DUE} of
    (total_cents - paid_cents). Recomputed on every invoice change. This is a
    mutation that bumps version + updated_at (PRD §2.8)."""
    total = 0
    for inv in db.invoices.values():
        if inv["operator_id"] == operator["id"] and inv["status"] in ("ISSUED", "PAST_DUE"):
            total += inv["total_cents"] - inv["paid_cents"]
    operator["open_invoice_balance_cents"] = total
    db.touch(operator)


def compute_invoice_total(visit_id):
    """PRD §3.7 invoice_total: sum of fuel orders (logistics != CANCELLED)
    priced_amount_cents, OCCUPIED parking assignment fee_cents, and COMPLETED
    ramp service charge_cents for the visit."""
    total = 0
    for fo in db.fuel_orders.values():
        if fo["service_visit_id"] == visit_id and fo["logistics_status"] != "CANCELLED":
            total += fo["priced_amount_cents"]
    for pa in db.parking_assignments.values():
        if pa["service_visit_id"] == visit_id and pa["status"] == "OCCUPIED":
            total += pa["fee_cents"]
    for rs in db.ramp_services.values():
        if rs["service_visit_id"] == visit_id and rs["status"] == "COMPLETED":
            total += rs["charge_cents"]
    return total


def visit_delivered_jeta_gallons(visit_id):
    """PRD §3.5: sum of delivered_gallons across into-plane tickets of this
    visit's FUELED, non-tankering, JET_A fuel orders."""
    total = 0
    for fo in db.fuel_orders.values():
        if (fo["service_visit_id"] == visit_id
                and fo["logistics_status"] == "FUELED"
                and not fo["tankering"]
                and fo["product"] == "JET_A"):
            for tk in db.into_plane_tickets.values():
                if tk["fuel_order_id"] == fo["id"]:
                    total += tk["delivered_gallons"]
    return total
