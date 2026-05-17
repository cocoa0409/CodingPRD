"""Time-driven cascades + status-driven cascades — PRD §2.11, §3.8.

Centralised here so that every entry point (clock advance, claim pay) goes
through the same primitives and every cascaded row gets updated_at + version
refreshed.
"""
from ..clock import add_days, parse_iso
from ..store import get_store, stamp_update
from .calculations import (
    adjudicated_balance,
    recompute_authorization_consumption,
)


def expire_authorization(auth: dict, now_ts: str) -> None:
    """Move Authorization ACTIVE → EXPIRED and cascade SCHEDULED sessions → CANCELLED."""
    auth["status"] = "EXPIRED"
    stamp_update(auth, now=now_ts)
    store = get_store()
    for s in store.sessions.values():
        if s["authorization_id"] == auth["id"] and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            stamp_update(s, now=now_ts)


def expire_treatment_plan(plan: dict, now_ts: str) -> None:
    """Move TreatmentPlan ACTIVE → EXPIRED and cascade-expire patient's ACTIVE
    authorizations (which in turn cascade-cancel their SCHEDULED sessions)."""
    plan["status"] = "EXPIRED"
    stamp_update(plan, now=now_ts)
    store = get_store()
    for auth in store.authorizations.values():
        if auth["patient_id"] == plan["patient_id"] and auth["status"] == "ACTIVE":
            expire_authorization(auth, now_ts)


def evaluate_time_gated_transitions(clinic_id: str) -> None:
    """Re-evaluate time-gated transitions after a clock advance.

    Order per PRD §3.8:
      1. TreatmentPlan ACTIVE → EXPIRED when now_ts > activated_at + 365 days
         (cascades patient's ACTIVE authorizations → EXPIRED, which cascade
         SCHEDULED sessions → CANCELLED).
      2. Authorization APPROVED → ACTIVE when now_ts >= effective_start.
      3. Authorization ACTIVE → EXPIRED when now_ts > effective_end
         (cascades SCHEDULED sessions → CANCELLED).
    """
    store = get_store()
    clinic = store.clinics.get(clinic_id)
    if clinic is None:
        return
    now_ts = clinic["now_ts"]
    now_dt = parse_iso(now_ts)

    # ----- 1. Treatment plan auto-expiry (cascades through authorizations + sessions)
    for plan in list(store.treatment_plans.values()):
        if plan["status"] != "ACTIVE":
            continue
        # The plan's patient must belong to this clinic.
        patient = store.patients.get(plan["patient_id"])
        if patient is None or patient.get("clinic_id") != clinic_id:
            continue
        if not plan.get("activated_at"):
            continue
        deadline = add_days(plan["activated_at"], 365)
        if now_dt > parse_iso(deadline):
            expire_treatment_plan(plan, now_ts)

    # ----- 2. Authorizations APPROVED → ACTIVE when start arrives
    for auth in list(store.authorizations.values()):
        if auth["status"] != "APPROVED":
            continue
        patient = store.patients.get(auth["patient_id"])
        if patient is None or patient.get("clinic_id") != clinic_id:
            continue
        if now_dt >= parse_iso(auth["effective_start"]):
            auth["status"] = "ACTIVE"
            stamp_update(auth, now=now_ts)

    # ----- 3. Authorizations ACTIVE → EXPIRED when end is passed (strict >)
    for auth in list(store.authorizations.values()):
        if auth["status"] != "ACTIVE":
            continue
        patient = store.patients.get(auth["patient_id"])
        if patient is None or patient.get("clinic_id") != clinic_id:
            continue
        if now_dt > parse_iso(auth["effective_end"]):
            expire_authorization(auth, now_ts)


def maybe_auto_exhaust(auth: dict, now_ts: str) -> None:
    """Auto ACTIVE → EXHAUSTED if adjudicated balance drops to zero or below."""
    recompute_authorization_consumption(auth)
    if auth["status"] == "ACTIVE" and adjudicated_balance(auth) <= 0:
        auth["status"] = "EXHAUSTED"
        stamp_update(auth, now=now_ts)
