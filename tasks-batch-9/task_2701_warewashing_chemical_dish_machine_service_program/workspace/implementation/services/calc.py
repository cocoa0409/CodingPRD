"""Stateless calculations (PRD 3.9 and the pinned rounding points of 2.6)."""

from datetime import timedelta
from decimal import Decimal

import db
from util import (
    UTC, add_months, ceil_div, dec, midnight, minute_of_day, rhu,
)

OPEN_ALERT_STATUSES = ("OPEN", "ACKNOWLEDGED")
OPEN_TICKET_STATUSES = ("QUEUED", "DISPATCHED", "ON_SITE", "PENDING_VERIFICATION")
TECH_LOAD_STATUSES = ("DISPATCHED", "ON_SITE", "PENDING_VERIFICATION")
RACK_PLACEMENT_STATUSES = ("INSTALLED", "RETRIEVAL_SCHEDULED", "RETRIEVED")
EQUIPMENT_PLACEMENT_STATUSES = ("PENDING_INSTALL", "INSTALLED", "RETRIEVAL_SCHEDULED")
LIVE_AGREEMENT_STATUSES = ("ACTIVE", "RENEWAL_PENDING")

SYMPTOM_BASE = {
    "MACHINE_DOWN": 400,
    "LOW_TEMP": 300,
    "NO_CHEMICAL": 250,
    "LEAK": 200,
    "RACK_QUALITY": 100,
}

CERT_RANK = {"SANITATION_CERTIFIED": 3, "L2": 2, "L1": 1}


# --------------------------------------------------------------------------
# operating window
# --------------------------------------------------------------------------

def in_operating_window(instant, site):
    minute = minute_of_day(instant)
    start = site["operating_window_start_minute_utc"]
    end = site["operating_window_end_minute_utc"]
    if start < end:
        return start <= minute < end
    if start == end:
        # A zero-length window admits nothing but the wrap rule below keeps
        # the comparison well defined.
        return minute >= start or minute < end
    return minute >= start or minute < end


# --------------------------------------------------------------------------
# dispatch scoring
# --------------------------------------------------------------------------

def has_open_alert(placement_id, alert_type):
    for alert in db.rows("telemetry_alerts"):
        if (alert["placement_id"] == placement_id
                and alert["alert_type"] == alert_type
                and alert["status"] in OPEN_ALERT_STATUSES):
            return True
    return False


def requires_sanitation_cert(symptom, alert):
    if symptom in ("LOW_TEMP", "NO_CHEMICAL"):
        return True
    if alert is not None and alert["alert_type"] == "LOW_FINAL_RINSE_TEMP":
        return True
    return False


def priority_score(placement, site, symptom, instant):
    score = SYMPTOM_BASE[symptom]
    health = placement["operational_status"]
    if health == "DOWN":
        score += 300 if in_operating_window(instant, site) else 90
    elif health == "DEGRADED":
        score += 60
    if site["priority_tier"] == "PREMIUM":
        score += 120
    if has_open_alert(placement["id"], "LOW_FINAL_RINSE_TEMP"):
        score += 200
    if site["service_posture"] == "ELEVATED":
        score += 80
    return min(score, 1000)


def sla_minutes(score):
    if score >= 700:
        return 120
    if score >= 400:
        return 240
    return 480


def response_deadline(instant, score):
    deadline = instant + timedelta(minutes=sla_minutes(score))
    return deadline.replace(microsecond=0)


# --------------------------------------------------------------------------
# agreement term and termination fee
# --------------------------------------------------------------------------

def term_end_date(start_date, months):
    return add_months(start_date, months)


def remaining_months(effective_date, end_date):
    days = (end_date - effective_date).days
    if days <= 0:
        return 0
    return ceil_div(days, 30)


def early_termination_fee(agreement, placements, model_of):
    months = remaining_months(
        agreement["termination_effective_date"], agreement["term_end_date"]
    )
    if months == 0:
        return 0, months
    variant_a = int(rhu(
        dec(months) * dec(agreement["monthly_minimum_spend_cents"])
        * Decimal("0.60"), 0
    ))
    variant_b = 0
    for placement in placements:
        if placement["placement_status"] not in EQUIPMENT_PLACEMENT_STATUSES:
            continue
        model = model_of(placement)
        if model is None:
            continue
        # Rounding is pinned per machine, before the sum.
        variant_b += int(rhu(
            dec(model["equipment_value_cents"]) * dec(months)
            / dec(agreement["minimum_term_months"]), 0
        ))
    return max(variant_a, variant_b), months


# --------------------------------------------------------------------------
# delivery pricing (rounds early, per container)
# --------------------------------------------------------------------------

def delivery_discount_rate(unit_count):
    if unit_count >= 25:
        return Decimal("0.12")
    if unit_count >= 10:
        return Decimal("0.05")
    return Decimal("0")


def delivery_amount(product, unit_count):
    quantity_ml = dec(product["unit_size_ml"]) * dec(unit_count)
    rate = delivery_discount_rate(unit_count)
    unit_price = rhu(dec(product["unit_price_cents"]) * (Decimal(1) - rate), 0)
    amount = int(unit_price) * unit_count
    return quantity_ml, amount


# --------------------------------------------------------------------------
# calibration verdicts
# --------------------------------------------------------------------------

def drift_pct(measured_ppm, target_ppm):
    return rhu(
        (dec(measured_ppm) - dec(target_ppm)) / dec(target_ppm) * Decimal(100), 2
    )


def calibration_verdict(drift, tolerance_pct, efficacy_result):
    if efficacy_result == "FAIL":
        return "FAIL"
    magnitude = abs(drift)
    if magnitude > Decimal("25.00"):
        return "FAIL"
    if magnitude > dec(tolerance_pct):
        return "ADJUSTED"
    return "PASS"


def latest_device_reading(placement_id):
    best = None
    for reading in db.rows("telemetry_readings"):
        if reading["placement_id"] != placement_id:
            continue
        if reading["source"] != "DEVICE":
            continue
        if best is None:
            best = reading
            continue
        if reading["reading_at"] > best["reading_at"]:
            best = reading
        # A tie keeps the earlier created_at, i.e. the first one seen.
    return best


def efficacy_verdict(product, model, placement_id, measured_ppm,
                     contact_seconds):
    if product["product_type"] != "SANITIZER":
        return "NOT_APPLICABLE"
    measured = dec(measured_ppm)
    if measured < dec(product["sanitizer_min_ppm"]):
        return "FAIL"
    if measured > dec(product["sanitizer_max_ppm"]):
        return "FAIL"
    if contact_seconds is None:
        return "FAIL"
    if contact_seconds < product["min_contact_seconds"]:
        return "FAIL"
    reading = latest_device_reading(placement_id)
    if reading is not None:
        if reading["final_rinse_temp_f"] < model["min_final_rinse_temp_f"]:
            return "FAIL"
    return "PASS"


# --------------------------------------------------------------------------
# theft chargeback
# --------------------------------------------------------------------------

def theft_chargeback(review, product):
    actual = dec(review["actual_consumption_ml"] or 0)
    expected = dec(review["expected_consumption_ml"] or 0)
    excess = actual - expected
    if excess <= 0:
        return 0
    units = ceil_div(excess, product["unit_size_ml"])
    return units * product["unit_price_cents"]


# --------------------------------------------------------------------------
# technician selection
# --------------------------------------------------------------------------

def technician_eligible(technician, site, needs_cert):
    if technician["status"] != "AVAILABLE":
        return False
    if technician["region_code"] != site["region_code"]:
        return False
    if needs_cert and technician["certification_level"] != "SANITATION_CERTIFIED":
        return False
    if technician["open_ticket_count"] >= 3:
        return False
    return True


def rank_technicians(candidates):
    return sorted(
        candidates,
        key=lambda t: (
            t["open_ticket_count"],
            -CERT_RANK.get(t["certification_level"], 0),
            t["created_at"],
            t["_seq"],
        ),
    )
