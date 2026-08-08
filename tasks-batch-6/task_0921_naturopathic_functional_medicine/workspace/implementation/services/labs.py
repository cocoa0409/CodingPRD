"""Functional panels: analyte banding and wash-out adjudication."""

from datetime import timedelta

import config
from clock import clock, parse_date
from store import db
from services.dispensary import last_dose_date
from services.money import dec


def classify(value, standard_low, standard_high, optimal_low, optimal_high,
             critical_low, critical_high):
    """Two bands with opposite geometry at the top, plus the panic verdict."""
    v = dec(value)
    if v < dec(standard_low):
        standard_band = "LOW"
    elif v > dec(standard_high):
        standard_band = "HIGH"
    else:
        standard_band = "IN_RANGE"           # CLOSED at both ends

    if v < dec(optimal_low):
        optimal_band = "BELOW_OPTIMAL"
    elif v >= dec(optimal_high):
        optimal_band = "ABOVE_OPTIMAL"       # HALF-OPEN at the top
    else:
        optimal_band = "OPTIMAL"

    is_critical = v <= dec(critical_low) or v >= dec(critical_high)
    return standard_band, optimal_band, is_critical


def interfering_items(patient_id, washout_class):
    """ACTIVE or HELD lines of this patient whose product matches the class."""
    hits = []
    for item in db.protocol_items.values():
        if item["status"] not in ("ACTIVE", "HELD"):
            continue
        protocol = db.protocols.get(item["protocol_id"])
        if protocol is None or protocol["patient_id"] != patient_id:
            continue
        product = db.products.get(item["product_id"])
        if product is None or product["supplement_class"] != washout_class:
            continue
        hits.append(item)
    return hits


def washout_clearance_date(patient_id, panel_code):
    """The latest per-line clearance, or None when nothing interferes."""
    panel = config.LAB_PANELS[panel_code]
    washout_class = panel["washout_class"]
    if washout_class is None:
        return None
    items = interfering_items(patient_id, washout_class)
    if not items:
        return None
    clearances = []
    for item in items:
        dose_date = last_dose_date(item)
        if dose_date is None:
            continue
        clearances.append(dose_date + timedelta(days=panel["washout_days"]))
    if not clearances:
        return None
    return max(clearances)


def washout_released(order):
    """Release is allowed once the clock reaches the clearance date (CLOSED lower
    bound) or every interfering line has moved to DISCONTINUED or COMPLETED."""
    clearance = parse_date(order.get("washout_clearance_date"))
    if clearance is not None and clock.today() >= clearance:
        return True
    washout_class = order.get("washout_class")
    if washout_class is None:
        return True
    return not interfering_items(order["patient_id"], washout_class)
