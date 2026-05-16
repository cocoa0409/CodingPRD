"""Cascading state transitions — orchestrate multi-entity mutations atomically.

Every entity touched by a cascade has its `updated_at` refreshed and `version`
bumped by one for that operation (PRD §2.4 / §2.12).
"""

from core.store import (
    IEPS, GOALS, SERVICES, TRANSITION_PLANS, STUDENTS, stamp_update,
)
from .computations import (
    compute_compensatory_minutes,
    recompute_iep_lre,
    recompute_service_utilization,
    recompute_student_lre_classification,
)


def _services_for_iep(iep_id: str):
    return [s for s in SERVICES.values() if s.get("iep_id") == iep_id]


def _goals_for_iep(iep_id: str):
    return [g for g in GOALS.values() if g.get("iep_id") == iep_id]


def _transition_plan_for_iep(iep_id: str):
    for tp in TRANSITION_PLANS.values():
        if tp.get("iep_id") == iep_id:
            return tp
    return None


def cascade_iep_revoke(iep: dict, district_current_date: str) -> None:
    """ACTIVE/AMENDMENT_PENDING IEP → REVOKED.

    Side effects:
      - All ACTIVE goals → DISCONTINUED
      - All ACTIVE services → SUSPENDED + compensatory_minutes_owed computed
      - Student.current_iep_id cleared; Student.lre_classification = NOT_APPLICABLE
      - Any ACTIVE TransitionPlan → SUPERSEDED
      - Any FINALIZED TransitionPlan (not yet ACTIVE because IEP never activated)
        also → SUPERSEDED per §3.5
    """
    iep["status"] = "REVOKED"
    stamp_update(iep)

    for g in _goals_for_iep(iep["id"]):
        if g.get("status") == "ACTIVE":
            g["status"] = "DISCONTINUED"
            stamp_update(g)

    for s in _services_for_iep(iep["id"]):
        if s.get("status") == "ACTIVE":
            s["status"] = "SUSPENDED"
            s["compensatory_minutes_owed"] = compute_compensatory_minutes(s, district_current_date)
            s["suspended_at"] = district_current_date
            recompute_service_utilization(s, district_current_date)
            stamp_update(s)

    recompute_iep_lre(iep)

    tp = _transition_plan_for_iep(iep["id"])
    if tp is not None and tp.get("status") in ("ACTIVE", "FINALIZED"):
        tp["status"] = "SUPERSEDED"
        stamp_update(tp)

    student = STUDENTS.get(iep["student_id"])
    if student is not None:
        if student.get("current_iep_id") == iep["id"]:
            student["current_iep_id"] = None
        student["lre_classification"] = "NOT_APPLICABLE"
        stamp_update(student)


def cascade_iep_expire(iep: dict, district_current_date: str) -> None:
    """ACTIVE IEP → EXPIRED. Goals → NOT_MET; services → SUSPENDED with comp minutes."""
    iep["status"] = "EXPIRED"
    stamp_update(iep)

    for g in _goals_for_iep(iep["id"]):
        if g.get("status") == "ACTIVE":
            g["status"] = "NOT_MET"
            stamp_update(g)

    for s in _services_for_iep(iep["id"]):
        if s.get("status") == "ACTIVE":
            s["status"] = "SUSPENDED"
            s["compensatory_minutes_owed"] = compute_compensatory_minutes(s, district_current_date)
            s["suspended_at"] = district_current_date
            recompute_service_utilization(s, district_current_date)
            stamp_update(s)

    recompute_iep_lre(iep)

    tp = _transition_plan_for_iep(iep["id"])
    if tp is not None and tp.get("status") == "ACTIVE":
        tp["status"] = "SUPERSEDED"
        stamp_update(tp)

    student = STUDENTS.get(iep["student_id"])
    if student is not None:
        if student.get("current_iep_id") == iep["id"]:
            student["current_iep_id"] = None
        student["lre_classification"] = "NOT_APPLICABLE"
        stamp_update(student)


def cascade_iep_supersede(prior_iep: dict, district_current_date: str) -> None:
    """ACTIVE IEP → SUPERSEDED (clean handoff to a new IEP).

    Services → COMPLETED with compensatory_minutes_owed = 0.
    Goals → DISCONTINUED.
    Active transition plan → SUPERSEDED.
    Does NOT clear Student.current_iep_id — caller sets it to the new IEP.
    """
    prior_iep["status"] = "SUPERSEDED"
    stamp_update(prior_iep)

    for g in _goals_for_iep(prior_iep["id"]):
        if g.get("status") == "ACTIVE":
            g["status"] = "DISCONTINUED"
            stamp_update(g)

    for s in _services_for_iep(prior_iep["id"]):
        if s.get("status") == "ACTIVE":
            s["status"] = "COMPLETED"
            s["compensatory_minutes_owed"] = 0
            s["suspended_at"] = district_current_date
            recompute_service_utilization(s, district_current_date)
            stamp_update(s)

    recompute_iep_lre(prior_iep)

    tp = _transition_plan_for_iep(prior_iep["id"])
    if tp is not None and tp.get("status") == "ACTIVE":
        tp["status"] = "SUPERSEDED"
        stamp_update(tp)


def auto_expire_eligible_ieps(district_id: str, district_current_date: str) -> None:
    """For every ACTIVE IEP in this district whose scheduled_review_date <= current_date,
    cascade-expire it. Called after clock advance (PRD §2.7).
    """
    from core.clock import date_at_or_before

    # Snapshot to avoid mutating while iterating.
    candidates = [
        iep for iep in IEPS.values()
        if iep.get("district_id") == district_id
        and iep.get("status") == "ACTIVE"
        and iep.get("scheduled_review_date")
        and date_at_or_before(iep["scheduled_review_date"], district_current_date)
    ]
    for iep in candidates:
        cascade_iep_expire(iep, district_current_date)


def cascade_consent_withdraw_related_service(consent: dict, district_current_date: str) -> None:
    """Consent (scope=RELATED_SERVICE) APPROVED → WITHDRAWN.

    For each RelatedService whose consent_id == this consent:
      - Service → SUSPENDED (only those currently in ACTIVE)
      - compensatory_minutes_owed computed
    After all services suspended, sum comp minutes across all services on the parent IEP;
    if sum > 0, parent IEP enters AMENDMENT_PENDING.
    """
    affected_services = [s for s in SERVICES.values() if s.get("consent_id") == consent["id"]]
    affected_iep_ids = set()
    for s in affected_services:
        if s.get("status") == "ACTIVE":
            s["status"] = "SUSPENDED"
            s["compensatory_minutes_owed"] = compute_compensatory_minutes(s, district_current_date)
            s["suspended_at"] = district_current_date
            recompute_service_utilization(s, district_current_date)
            stamp_update(s)
            affected_iep_ids.add(s["iep_id"])

    for iep_id in affected_iep_ids:
        iep = IEPS.get(iep_id)
        if iep is None:
            continue
        recompute_iep_lre(iep)
        stamp_update(iep)
        # Sum compensatory minutes across all services on the IEP.
        total_owed = sum(
            (s.get("compensatory_minutes_owed") or 0)
            for s in SERVICES.values()
            if s.get("iep_id") == iep_id
        )
        if total_owed > 0 and iep.get("status") == "ACTIVE":
            iep["status"] = "AMENDMENT_PENDING"
            stamp_update(iep)
        # Student LRE recompute.
        student = STUDENTS.get(iep["student_id"])
        if student is not None and student.get("current_iep_id") == iep_id:
            recompute_student_lre_classification(student)
            stamp_update(student)
