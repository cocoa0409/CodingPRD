"""State-transition side effects and cascades (scaffold §1.2 / PRD §3).

The functions here mutate stores in place and bump the version + updated_at
of any row touched, per PRD §2.9 ("There are no silent mutations: if a row's
domain content changes — even by side-effect from another endpoint — its
version ticks.").
"""
from __future__ import annotations

from typing import Dict, Any, List

import db
from services import calculations as calc


# ---- AuthorizationGrant.units_consumed / units_finalized refresh ------------


def refresh_grant_units_consumed(grant: Dict[str, Any]) -> None:
    """Recompute grant.units_consumed and auto-EXHAUSTED transition.

    Called after every Visit status mutation per scaffold §1.3 units_consumed_running.
    PRD §3.4: 'When a visit-side mutation pushes units_consumed to a value at
    least equal to total_units_granted (boundary inclusive), the grant
    auto-transitions from ACTIVE to EXHAUSTED.'
    """
    old_consumed = grant.get("units_consumed", 0)
    new_consumed = calc.grant_units_consumed(grant["id"])
    status_changed = False
    if grant["status"] == "ACTIVE" and new_consumed >= grant["total_units_granted"]:
        grant["status"] = "EXHAUSTED"
        status_changed = True
    if new_consumed != old_consumed or status_changed:
        grant["units_consumed"] = new_consumed
        db.bump(grant)


def refresh_grant_units_finalized(grant: Dict[str, Any]) -> None:
    """Recompute grant.units_finalized after a Visit FINALIZED transition."""
    old = grant.get("units_finalized", 0)
    new = calc.grant_units_finalized(grant["id"])
    if new != old:
        grant["units_finalized"] = new
        db.bump(grant)


# ---- PlanOfCare cumulative_billed + capped_status refresh -------------------


def refresh_poc_after_visit_finalize(poc: Dict[str, Any]) -> None:
    """Refresh cumulative_billed_cents then re-evaluate capped_status.

    Bumps PlanOfCare.version by 1 (scaffold §1.2 Visit COMPLETED -> FINALIZED;
    PRD §3.5 'The plan's version increments and its updated_at refreshes —
    these are the side effects that make the OCC pin on
    expected_plan_of_care_version non-trivial.').
    """
    poc["cumulative_billed_cents"] = calc.poc_cumulative_billed_cents(poc["id"])
    poc["capped_status"] = calc.capped_posture(
        poc["cumulative_billed_cents"], poc["capped_dollar_limit_cents"]
    )
    db.bump(poc)


# ---- PlanOfCare DRAFT -> ACTIVE side effects (PRD §3.2) ---------------------


def cascade_poc_activate(poc: Dict[str, Any]) -> None:
    """Pin cap, set posture UNDER_CAP, cascade VA referral CONSUMED + sibling
    drafts to EXPIRED. Bumps the activated POC's version.

    Cascade chain:
      hop 0:  POC.status DRAFT -> ACTIVE; capped_dollar_limit_cents pinned;
              capped_status = UNDER_CAP; POC.version++.
      hop 1:  Linked VeteranReferral.status ISSUED -> CONSUMED (if VA-backed).
      hop 2:  Every other PlanOfCare still in DRAFT referencing the same
              veteran_referral_id transitions DRAFT -> EXPIRED, with its own
              version bump.
    """
    patient = db.patients[poc["patient_id"]]
    poc["capped_dollar_limit_cents"] = calc.capped_dollar_limit_cents(
        patient["insurance_type"]
    )
    poc["cumulative_billed_cents"] = poc.get("cumulative_billed_cents", 0) or 0
    poc["capped_status"] = "UNDER_CAP"
    poc["status"] = "ACTIVE"
    db.bump(poc)

    if patient["insurance_type"] == "VA_TRICARE" and poc.get("veteran_referral_id"):
        referral = db.veteran_referrals.get(poc["veteran_referral_id"])
        if referral is not None and referral["status"] == "ISSUED":
            referral["status"] = "CONSUMED"
            db.bump(referral)
            # hop 2: every other DRAFT POC pointing at this referral cascades to EXPIRED
            for other in db.plans_of_care.values():
                if other["id"] == poc["id"]:
                    continue
                if other.get("veteran_referral_id") != referral["id"]:
                    continue
                if other["status"] != "DRAFT":
                    continue
                other["status"] = "EXPIRED"
                db.bump(other)


# ---- PlanOfCare ACTIVE -> DISCHARGED side effects (PRD §3.6) ----------------


def cascade_poc_discharge(poc: Dict[str, Any]) -> None:
    """Depth-3 cascade triggered by POC discharge.

      hop 1:  every SCHEDULED Visit under any grant of this POC -> CANCELLED
      hop 2:  each affected grant's units_consumed recomputed
      hop 3:  each AuthorizationGrant ACTIVE -> CANCELLED
      parallel: every ACTIVE HomeExerciseProgram under this POC -> DISCONTINUED
      patient: Patient.status ACTIVE -> DISCHARGED iff no other ACTIVE POC

    PRD §3.6: 'every AuthorizationGrant whose effective window is still open
    transitions ACTIVE → CANCELLED'. We interpret the discharge transition as
    cancelling every ACTIVE grant on this POC; an EXPIRED grant has already
    reached a terminal state and is not re-cancelled. (The 'still open' phrase
    refers to having not already terminated.) The scaffold §1.2 phrasing is
    similarly broad — "Each AuthorizationGrant whose effective window is still
    open transitions ACTIVE -> CANCELLED".
    """
    grants = [
        g
        for g in db.authorization_grants.values()
        if g["plan_of_care_id"] == poc["id"]
    ]
    # hop 1: cancel SCHEDULED visits
    for grant in grants:
        for visit in list(db.visits.values()):
            if visit["authorization_grant_id"] != grant["id"]:
                continue
            if visit["status"] == "SCHEDULED":
                visit["status"] = "CANCELLED"
                db.bump(visit)
    # hop 2 + 3: recompute units_consumed then ACTIVE -> CANCELLED on the grant
    for grant in grants:
        # Re-aggregate units_consumed (cancelled visits drop out of eligible set).
        refresh_grant_units_consumed(grant)
        if grant["status"] == "ACTIVE":
            grant["status"] = "CANCELLED"
            db.bump(grant)
    # Parallel: discontinue ACTIVE HEPs
    for hep in db.home_exercise_programs.values():
        if hep["plan_of_care_id"] != poc["id"]:
            continue
        if hep["status"] == "ACTIVE":
            hep["status"] = "DISCONTINUED"
            db.bump(hep)
    # POC itself
    poc["status"] = "DISCHARGED"
    db.bump(poc)
    # Patient.status flip iff no other ACTIVE POC for this patient
    other_active = any(
        p["patient_id"] == poc["patient_id"]
        and p["id"] != poc["id"]
        and p["status"] == "ACTIVE"
        for p in db.plans_of_care.values()
    )
    if not other_active:
        patient = db.patients.get(poc["patient_id"])
        if patient is not None and patient["status"] == "ACTIVE":
            patient["status"] = "DISCHARGED"
            db.bump(patient)


# ---- Clock-driven cascades (PRD §2.10 / §3.6) -------------------------------


def cascade_poc_expired_from_recert_due(poc: Dict[str, Any], today) -> None:
    """RECERT_DUE -> EXPIRED auto-transition cascade.

    PRD §3.6: 'every SCHEDULED visit reachable through any of the plan's
    grants is cancelled, every AuthorizationGrant whose effective_to has now
    passed transitions from ACTIVE to EXPIRED, and every ACTIVE
    HomeExerciseProgram under the plan is discontinued.'
    """
    grants = [
        g
        for g in db.authorization_grants.values()
        if g["plan_of_care_id"] == poc["id"]
    ]
    # cancel SCHEDULED visits
    for grant in grants:
        for visit in list(db.visits.values()):
            if visit["authorization_grant_id"] != grant["id"]:
                continue
            if visit["status"] == "SCHEDULED":
                visit["status"] = "CANCELLED"
                db.bump(visit)
        # refresh consumed
        refresh_grant_units_consumed(grant)
    # grant ACTIVE -> EXPIRED if effective_to < today
    for grant in grants:
        if grant["status"] != "ACTIVE":
            continue
        eff_to = db.parse_iso_date(grant["effective_to"])
        if eff_to is not None and eff_to < today:
            grant["status"] = "EXPIRED"
            db.bump(grant)
    # discontinue ACTIVE HEPs
    for hep in db.home_exercise_programs.values():
        if hep["plan_of_care_id"] != poc["id"]:
            continue
        if hep["status"] == "ACTIVE":
            hep["status"] = "DISCONTINUED"
            db.bump(hep)
    # POC itself
    poc["status"] = "EXPIRED"
    db.bump(poc)


def reevaluate_time_gated_transitions() -> None:
    """Apply every time-gated auto-transition listed in PRD §2.10.

    Ordering (each PASS visits rows in deterministic created_at order):

      1. PlanOfCare ACTIVE -> RECERT_DUE
         when: today > certified_end_date - 7 days AND today <= certified_end_date
      2. PlanOfCare RECERT_DUE -> EXPIRED
         when: today > certified_end_date
      3. AuthorizationGrant ACTIVE -> EXPIRED
         when: today > effective_to
      4. VeteranReferral ISSUED -> EXPIRED
         when: today > expires_on
    """
    from datetime import timedelta

    iso = db.get_current_utc()
    today = db.parse_iso_dt(iso).date()  # type: ignore[union-attr]

    # 1. ACTIVE -> RECERT_DUE
    pocs = sorted(
        [p for p in db.plans_of_care.values() if p["status"] == "ACTIVE"],
        key=db.created_then_id,
    )
    for poc in pocs:
        ce = db.parse_iso_date(poc["certified_end_date"])
        if ce is None:
            continue
        warn_from = ce - timedelta(days=7)
        if warn_from < today <= ce:
            poc["status"] = "RECERT_DUE"
            db.bump(poc)

    # 2. RECERT_DUE -> EXPIRED
    pocs = sorted(
        [p for p in db.plans_of_care.values() if p["status"] == "RECERT_DUE"],
        key=db.created_then_id,
    )
    for poc in pocs:
        ce = db.parse_iso_date(poc["certified_end_date"])
        if ce is None:
            continue
        if today > ce:
            cascade_poc_expired_from_recert_due(poc, today)

    # 3. Grant ACTIVE -> EXPIRED (also applies to grants whose POC didn't expire)
    grants = sorted(
        [g for g in db.authorization_grants.values() if g["status"] == "ACTIVE"],
        key=db.created_then_id,
    )
    for grant in grants:
        eff_to = db.parse_iso_date(grant["effective_to"])
        if eff_to is None:
            continue
        if today > eff_to:
            grant["status"] = "EXPIRED"
            db.bump(grant)

    # 4. VeteranReferral ISSUED -> EXPIRED
    referrals = sorted(
        [r for r in db.veteran_referrals.values() if r["status"] == "ISSUED"],
        key=db.created_then_id,
    )
    for referral in referrals:
        exp = db.parse_iso_date(referral["expires_on"])
        if exp is None:
            continue
        if today > exp:
            referral["status"] = "EXPIRED"
            db.bump(referral)
