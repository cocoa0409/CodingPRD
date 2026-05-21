"""Cross-aggregate cascades: calibration commit, PIP creation, termination,
cycle close compensation, and PIP-fail comp-plan rejection."""

from datetime import timedelta
from typing import Dict, Optional

import config
from clock import clock
from db import _format_iso, new_id, store, utcnow_iso
from services.audit import log_event


# -----------------------------------------------------------------------------
# Generic helpers for child entity creation / mutation
# -----------------------------------------------------------------------------

def _bump(entity: Dict) -> None:
    entity["updated_at"] = utcnow_iso()
    if "version" in entity:
        entity["version"] = int(entity["version"]) + 1


# -----------------------------------------------------------------------------
# PIP creation cascade
# -----------------------------------------------------------------------------

def create_pip_case(
    cycle_id: str,
    subject_employee_id: str,
    triggering_review_case_id: str,
    triggering_rating: str,
) -> Optional[Dict]:
    """Auto-create a PIPCase from a finalised review with a low rating.

    Returns the created PIPCase or None if one already exists for the
    (cycle, subject) pair (which is the SCAFFOLD-prescribed concurrency win:
    the caller is expected to check first; this guard is defensive).
    """
    # Uniqueness on (cycle_id, subject_employee_id) — first-writer-wins.
    for p in store.pip_cases.values():
        if p["cycle_id"] == cycle_id and p["subject_employee_id"] == subject_employee_id:
            return None

    duration_days = (
        config.PIP_DURATION_DAYS_NEEDS_IMPROVEMENT
        if triggering_rating == "NEEDS_IMPROVEMENT"
        else config.PIP_DURATION_DAYS_UNSATISFACTORY
    )
    starts_dt = clock.now()
    ends_dt = starts_dt + timedelta(days=duration_days)

    now = utcnow_iso()
    pip = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "cycle_id": cycle_id,
        "subject_employee_id": subject_employee_id,
        "triggering_review_case_id": triggering_review_case_id,
        "duration_days": duration_days,
        "starts_at": _format_iso(starts_dt),
        "ends_at": _format_iso(ends_dt),
        "status": "ACTIVE",
    }
    store.pip_cases[pip["id"]] = pip

    # Subject Employee.status flips ACTIVE -> ON_PIP
    emp = store.employees.get(subject_employee_id)
    if emp and emp["status"] == "ACTIVE":
        emp["status"] = "ON_PIP"
        _bump(emp)

    log_event("PIPCase", pip["id"], "pip_case.create_auto", payload={
        "cycle_id": cycle_id,
        "subject_employee_id": subject_employee_id,
        "triggering_review_case_id": triggering_review_case_id,
    })
    return pip


# -----------------------------------------------------------------------------
# Calibration session commit cascade
# -----------------------------------------------------------------------------

def commit_calibration_session(cycle: Dict, session: Dict) -> None:
    """Hop 1: every covered case LOCKED -> FINALIZED with final_rating set.
    Hop 2: any low rating spawns a PIPCase.
    Hop 3: subject's status flips ACTIVE -> ON_PIP via create_pip_case.

    Coverage and bell-curve compliance must already be checked by the caller.
    """
    proposed = session.get("proposed_ratings") or []
    for entry in proposed:
        rc_id = entry["review_case_id"]
        rating = entry["proposed_rating"]
        rc = store.review_cases.get(rc_id)
        if not rc:
            continue
        # The case appears exactly once and was LOCKED prior to commit.
        rc["final_rating"] = rating
        rc["status"] = "FINALIZED"
        _bump(rc)

        if rating in ("NEEDS_IMPROVEMENT", "UNSATISFACTORY"):
            create_pip_case(
                cycle_id=cycle["id"],
                subject_employee_id=rc["subject_employee_id"],
                triggering_review_case_id=rc["id"],
                triggering_rating=rating,
            )

    session["status"] = "COMMITTED"
    session["committed_at"] = utcnow_iso()
    _bump(session)

    # If this is the last session, drive cycle to COMP_PLANNING.
    remaining = [
        s for s in store.calibration_sessions.values()
        if s["cycle_id"] == cycle["id"] and s["status"] in ("SCHEDULED", "IN_SESSION")
    ]
    if not remaining:
        # also require every LOCKED case has a final_rating
        locked_unrated = [
            rc for rc in store.review_cases.values()
            if rc["cycle_id"] == cycle["id"]
            and rc["status"] == "LOCKED"
        ]
        if not locked_unrated:
            cycle["status"] = "COMP_PLANNING"
            _bump(cycle)


# -----------------------------------------------------------------------------
# Lock-reviews cascade
# -----------------------------------------------------------------------------

def lock_reviews(cycle: Dict) -> None:
    """Cycle OPEN -> IN_CALIBRATION; cascade SUBMITTED ReviewCases -> LOCKED."""
    for rc in store.review_cases.values():
        if rc["cycle_id"] == cycle["id"] and rc["status"] == "SUBMITTED":
            rc["status"] = "LOCKED"
            _bump(rc)
    cycle["status"] = "IN_CALIBRATION"
    _bump(cycle)


# -----------------------------------------------------------------------------
# Cycle close cascade — apply approved CompPlans to employees
# -----------------------------------------------------------------------------

def close_cycle(cycle: Dict) -> None:
    plans = [
        cp for cp in store.comp_plans.values()
        if cp["cycle_id"] == cycle["id"] and cp["status"] == "APPROVED"
    ]
    for cp in plans:
        emp = store.employees.get(cp["subject_employee_id"])
        if not emp:
            continue
        changed = False
        if cp.get("merit_increase_cents", 0) > 0:
            emp["base_salary_cents"] = int(emp["base_salary_cents"]) + int(cp["merit_increase_cents"])
            changed = True
        if cp.get("equity_refresh_units", 0) > 0:
            emp["equity_units_outstanding"] = int(emp.get("equity_units_outstanding", 0)) + int(cp["equity_refresh_units"])
            changed = True
        if cp.get("promotion_to_level") is not None:
            emp["job_level"] = int(cp["promotion_to_level"])
            changed = True
        if changed:
            _bump(emp)
    cycle["status"] = "CLOSED"
    _bump(cycle)


# -----------------------------------------------------------------------------
# PIP-fail cascade: any DRAFT/PROPOSED CompPlan -> REJECTED
# -----------------------------------------------------------------------------

def reject_open_comp_plans_for(cycle_id: str, subject_employee_id: str) -> None:
    for cp in store.comp_plans.values():
        if (
            cp["cycle_id"] == cycle_id
            and cp["subject_employee_id"] == subject_employee_id
            and cp["status"] in ("DRAFT", "PROPOSED")
        ):
            cp["status"] = "REJECTED"
            _bump(cp)


# -----------------------------------------------------------------------------
# Termination cascade
# -----------------------------------------------------------------------------

def terminate_employee_cascade(employee: Dict) -> None:
    """Force-withdraw ACTIVE PIPs and reject DRAFT/PROPOSED comp plans for this subject.
    Then flip Employee.status to TERMINATED."""
    emp_id = employee["id"]
    # Withdraw any ACTIVE PIP for this subject in any cycle.
    for p in store.pip_cases.values():
        if p["subject_employee_id"] == emp_id and p["status"] == "ACTIVE":
            p["status"] = "WITHDRAWN"
            _bump(p)
    # Reject open comp plans.
    for cp in store.comp_plans.values():
        if cp["subject_employee_id"] == emp_id and cp["status"] in ("DRAFT", "PROPOSED"):
            cp["status"] = "REJECTED"
            _bump(cp)
    employee["status"] = "TERMINATED"
    _bump(employee)
