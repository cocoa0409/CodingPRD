"""Business-logic services: criticality classification, age band, TAT,
counter recomputation, and cascade helpers (PRD §3).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, date
from typing import Dict, Any, Optional, List

import db


# ---------- age band -------------------------------------------------------

def compute_age_band(date_of_birth_iso: str, ref_dt: datetime) -> str:
    """PRD §3.1 / §3.5 — age band derived against the server's current clock.

    NEONATE  : age < 28 days
    INFANT   : age < 1 year
    PEDIATRIC: age < 18 years
    ADULT    : age >= 18 years
    """
    dob = db.parse_iso_date(date_of_birth_iso)
    ref_date = ref_dt.date()
    if dob is None:
        return "ADULT"

    delta_days = (ref_date - dob).days
    if delta_days < 28:
        return "NEONATE"

    # year-based comparison for the >=1y, >=18y boundaries:
    # we treat one full year as having elapsed when the same (month, day) has occurred.
    def years_between(a: date, b: date) -> int:
        # b >= a expected; full years that have elapsed from a to b
        y = b.year - a.year
        if (b.month, b.day) < (a.month, a.day):
            y -= 1
        return y

    if delta_days < 365:
        return "INFANT"

    full_years = years_between(dob, ref_date)
    if full_years < 1:
        return "INFANT"
    if full_years < 18:
        return "PEDIATRIC"
    return "ADULT"


# ---------- criticality classification (PRD §3.5) --------------------------

def classify_criticality(*, numeric_value: float, critical_low: float, critical_high: float,
                          reference_low: float, reference_high: float,
                          age_band: str, analyte_code: str) -> str:
    """Two-stage rule: base tier from value vs ranges, then NEONATE override.
    """
    nv = round(float(numeric_value) + 1e-12, 10)  # avoid float dust

    # Base tier — compare at the 2-decimal resolution declared by PRD §2.4.
    if nv <= float(critical_low):
        base = "CRITICAL_LOW"
    elif nv >= float(critical_high):
        base = "CRITICAL_HIGH"
    elif nv < float(reference_low) or nv > float(reference_high):
        base = "ABNORMAL"
    else:
        base = "NORMAL"

    # NEONATE override (analyte-specific).
    if age_band == "NEONATE":
        if analyte_code == "K" and (nv >= 6.50 or nv <= 2.50):
            return "PANIC"
        if analyte_code == "GLUCOSE" and nv <= 40.00:
            return "PANIC"

    return base


# ---------- turn-around-time -----------------------------------------------

def _floor_minutes(seconds: float) -> int:
    # floor toward zero on positive deltas; for negative (shouldn't happen) clamp to 0.
    if seconds < 0:
        return 0
    return int(math.floor(seconds / 60.0))


def compute_tat_clinical(order: Dict[str, Any]) -> Optional[int]:
    """Span ordered_at → earliest released_at."""
    ordered_at = db.parse_iso_dt(order.get("ordered_at"))
    if ordered_at is None:
        return None
    rel = _earliest_released_at(order["id"])
    if rel is None:
        return None
    return _floor_minutes((rel - ordered_at).total_seconds())


def compute_tat_lab_processing(order_id: str) -> Optional[int]:
    """Span earliest accessioned_at → earliest released_at."""
    acc = _earliest_accessioned_at(order_id)
    rel = _earliest_released_at(order_id)
    if acc is None or rel is None:
        return None
    return _floor_minutes((rel - acc).total_seconds())


def _earliest_released_at(order_id: str) -> Optional[datetime]:
    rels = [
        r for r in db.results.values()
        if r.get("lab_order_id") == order_id and r.get("status") == "RELEASED" and r.get("released_at")
    ]
    if not rels:
        return None
    return min(db.parse_iso_dt(r["released_at"]) for r in rels)


def _earliest_accessioned_at(order_id: str) -> Optional[datetime]:
    accs = [
        s for s in db.specimens.values()
        if s.get("lab_order_id") == order_id and s.get("status") == "ACCESSIONED" and s.get("accessioned_at")
    ]
    # PRD §3.6 says "earliest accessioned_at of any accessioned specimen". This is the
    # earliest specimen *currently* in ACCESSIONED. We also include the historical
    # accessioned_at field, even if the specimen later moved to REJECTED, since the
    # PRD's wording says "of any accessioned specimen of the order"; but the
    # canonical reading aligned with the formula in §1.3 is currently-accessioned
    # specimens. We use that reading.
    if not accs:
        # Fall back to all specimens that have an accessioned_at recorded.
        accs_any = [
            s for s in db.specimens.values()
            if s.get("lab_order_id") == order_id and s.get("accessioned_at")
        ]
        if not accs_any:
            return None
        return min(db.parse_iso_dt(s["accessioned_at"]) for s in accs_any)
    return min(db.parse_iso_dt(s["accessioned_at"]) for s in accs)


# ---------- counter recompute ----------------------------------------------

def recompute_order_counters(order: Dict[str, Any]) -> None:
    """§1.3 order_specimens_count_recompute — call after every specimen state change."""
    oid = order["id"]
    specs = [s for s in db.specimens.values() if s.get("lab_order_id") == oid]
    order["specimens_count"] = sum(1 for s in specs if s.get("status") != "REJECTED")
    order["accessioned_count"] = sum(1 for s in specs if s.get("status") == "ACCESSIONED")


def recompute_patient_release_count(patient: Dict[str, Any]) -> None:
    """§1.3 patient_results_release_count_recompute."""
    pid = patient["id"]
    cnt = 0
    for r in db.results.values():
        if r.get("status") != "RELEASED":
            continue
        order = db.lab_orders.get(r.get("lab_order_id"))
        if order and order.get("patient_id") == pid:
            cnt += 1
    patient["results_release_count"] = cnt


# ---------- ack-deadline computation ---------------------------------------

def compute_ack_deadline(sent_at_dt: datetime, channel: str) -> datetime:
    """PRD §3.7: PHONE → +30 min, SMS → +60 min."""
    minutes = 30 if channel == "PHONE" else 60
    return sent_at_dt + timedelta(minutes=minutes)
