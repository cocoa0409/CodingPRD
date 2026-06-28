"""Derived-field reconciliation and cross-aggregate cascades.

These helpers keep computed values consistent: program bed counters, cohort
slot counts, patient risk/posture, and authorization day balances. They are the
shared machinery the transition endpoints invoke.
"""
from clock import parse_iso
from db import store
from services import calc
from services.common import touch

# Clinical statuses that occupy a bed / cohort slot (PRD §2.8).
OCCUPYING_STATUSES = {"ADMITTED", "MEDICAL_HOLD", "DISCHARGE_PENDING"}


# ---------------------------------------------------------------------------
# Patient risk + posture
# ---------------------------------------------------------------------------
def recompute_patient_posture(patient):
    """Recompute medical_stability_posture from the running nutritional_risk_score."""
    patient["medical_stability_posture"] = calc.medical_stability_posture(
        patient["nutritional_risk_score"]
    )


def set_patient_number(patient, field, decimal_value):
    patient[field] = calc._to_number(decimal_value)


# ---------------------------------------------------------------------------
# Program bed counters (PRD §2.8)
# ---------------------------------------------------------------------------
def recompute_program_counters(program):
    """beds_available = max(bed_capacity - beds_occupied, 0);
    occupancy_posture = FULL if beds_occupied >= bed_capacity else OPEN."""
    occupied = program["beds_occupied"]
    capacity = program["bed_capacity"]
    program["beds_available"] = max(capacity - occupied, 0)
    program["occupancy_posture"] = "FULL" if occupied >= capacity else "OPEN"


# ---------------------------------------------------------------------------
# Authorization day balances (PRD §3.11)
# ---------------------------------------------------------------------------
def approved_windows(auth):
    """Return list of (start_dt, end_dt) for every APPROVED ConcurrentReview
    on this authorization, in approval order."""
    windows = []
    revs = [
        r for r in store.reviews.values()
        if r["authorization_id"] == auth["id"] and r["decision"] == "APPROVE"
    ]
    revs.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for r in revs:
        if r.get("window_start_iso") and r.get("window_end_iso"):
            windows.append((parse_iso(r["window_start_iso"]), parse_iso(r["window_end_iso"])))
    return windows


def recompute_auth_days(auth):
    """Recompute days_consumed (chronological) and days_remaining against the clock."""
    windows = approved_windows(auth)
    clock_dt = store.clock.now
    consumed = calc.days_consumed_chronological(windows, clock_dt)
    auth["days_consumed"] = consumed
    auth["days_remaining"] = max(auth["days_authorized"] - consumed, 0)


# ---------------------------------------------------------------------------
# Cascade: authorization -> admission DISCHARGE_PENDING (PRD §3.11)
# ---------------------------------------------------------------------------
def cascade_auth_to_admission_discharge_pending(auth):
    """If the parent admission is ADMITTED, move it to DISCHARGE_PENDING."""
    adm = store.admissions.get(auth["admission_id"])
    if adm and adm["clinical_status"] == "ADMITTED":
        adm["clinical_status"] = "DISCHARGE_PENDING"
        touch(adm)


def maybe_exhaust(auth):
    """If an APPROVED auth's days_remaining is 0, drive it EXHAUSTED and cascade
    (PRD §3.11). days_consumed/remaining must be current before calling."""
    if auth["status"] == "APPROVED" and auth["days_remaining"] == 0 and auth["days_authorized"] > 0:
        auth["status"] = "EXHAUSTED"
        touch(auth)
        cascade_auth_to_admission_discharge_pending(auth)


def reevaluate_authorizations_after_clock_change():
    """On clock advance, re-evaluate every authorization against its window.

    Recompute day balances; the automatic expiry-and-cascade is evaluated only
    when the clock is advanced *past* a covered-through instant (PRD §3.11:
    "evaluated automatically whenever the logical clock is advanced past a
    covered-through instant") — strictly after, not at the boundary. The manual
    `expire` endpoint, by contrast, is permitted once the clock has "reached or
    passed" covered_through (>=), so at the exact boundary the manual expire is
    still available and the auto-cascade has not pre-empted it. Also EXHAUST
    auths whose days hit zero.
    """
    clock_dt = store.clock.now
    for auth in list(store.authorizations.values()):
        recompute_auth_days(auth)
        if auth["status"] == "APPROVED":
            ct = auth.get("covered_through_iso")
            # The system auto-acts only once the clock has been advanced *past*
            # the covered-through instant (PRD §3.11). At or before that instant
            # the authorization stays APPROVED and remains manually expirable;
            # neither the auto-expiry nor the auto-exhaustion cascade pre-empts
            # the boundary. days_authorized is always the whole-day count of the
            # approved windows, so days_remaining can only reach zero exactly at
            # a window end — never strictly inside a window — which is why the
            # "advanced past" qualifier on the auto-cascade also governs when an
            # APPROVED authorization is driven to EXHAUSTED on a clock advance.
            if ct is not None and clock_dt > parse_iso(ct):
                auth["status"] = "EXPIRED"
                touch(auth)
                cascade_auth_to_admission_discharge_pending(auth)
