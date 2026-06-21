"""Core domain operations shared across routes: lookups, status events,
risk recompute + cascade transitions, fee re-derivation, and compensation.
"""
from __future__ import annotations

from typing import Optional

import db
from errors import APIError, ERR_NOT_FOUND, ERR_FK_NOT_FOUND
from routes._helpers import stamp_create, touch
from services import calculations as calc


# =============================================================================
# Lookups
# =============================================================================
def get_or_404(store: dict, rid: str, what: str) -> dict:
    rec = store.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{what} not found")
    return rec


def get_or_fk(store: dict, rid: str, what: str) -> dict:
    rec = store.get(rid)
    if rec is None:
        raise APIError(ERR_FK_NOT_FOUND, 422, f"{what} does not exist")
    return rec


# =============================================================================
# Required-document set (depends on application_type)
# =============================================================================
def required_doc_categories(application: dict) -> list:
    """Required verification factors for the application's type.

    Base identity + citizenship for all types. MINOR adds GUARDIAN_CONSENT.
    Any application requesting a name change adds NAME_CHANGE_EVIDENCE.
    """
    cats = ["IDENTITY", "CITIZENSHIP"]
    if application["application_type"] == "MINOR":
        cats.append("GUARDIAN_CONSENT")
    if application.get("name_change_requested"):
        cats.append("NAME_CHANGE_EVIDENCE")
    return cats


def docs_for_application(application_id: str) -> list:
    return [d for d in db.supporting_documents.values() if d["application_id"] == application_id]


def required_progress(application: dict):
    """(total, accepted) over the required category set.

    A category is 'accepted' when at least one of its documents is ACCEPTED.
    """
    cats = required_doc_categories(application)
    docs = docs_for_application(application["id"])
    accepted = 0
    for c in cats:
        if any(d["doc_category"] == c and d["verification_status"] == "ACCEPTED" for d in docs):
            accepted += 1
    return len(cats), accepted


def all_required_accepted(application: dict) -> bool:
    total, accepted = required_progress(application)
    return total == accepted


# =============================================================================
# Status events (append-only audit trail)
# =============================================================================
def append_status_event(application_id: str, from_status: Optional[str], to_status: str, actor_role: str) -> dict:
    ev = {
        "application_id": application_id,
        "from_status": from_status,
        "to_status": to_status,
        "actor_role": actor_role,
        "occurred_at": db.clock.now_iso(),
    }
    stamp_create(ev, full=False)  # id + created_at only (immutable, lighter-weight)
    db.status_events[ev["id"]] = ev
    return ev


# =============================================================================
# Fee re-derivation (only while UNPAID)
# =============================================================================
def fee_for_application(application_id: str) -> Optional[dict]:
    for fa in db.fee_assessments.values():
        if fa["application_id"] == application_id:
            return fa
    return None


def rederive_fee_if_unpaid(application: dict) -> None:
    fa = fee_for_application(application["id"])
    if fa is None or fa["payment_status"] != "UNPAID":
        return
    comps = calc.compute_fee_components(application, fa["one_day_delivery"])
    fa.update(comps)
    touch(fa)


# =============================================================================
# Risk recompute (FINAL) stored on applicant; bumps applicant version
# =============================================================================
def recompute_risk_final(applicant: dict) -> float:
    score = calc.compute_risk_score_for_applicant(applicant["id"])
    applicant["verification_risk_score"] = score
    touch(applicant)
    return score


def recompute_risk_provisional(applicant: dict, application: dict) -> float:
    score = calc.compute_risk_score_provisional(application)
    applicant["verification_risk_score"] = score
    touch(applicant)
    return score


# =============================================================================
# Application status transition helper
# =============================================================================
def set_status(application: dict, to_status: str, actor_role: str) -> None:
    """Move the main status, append the event, and bump version."""
    frm = application["status"]
    application["status"] = to_status
    append_status_event(application["id"], frm, to_status, actor_role)
    touch(application)


# =============================================================================
# Auto-advance out of verification (cascade tail of last-required-accept)
# =============================================================================
def maybe_auto_advance_verification(application: dict, actor_role: str) -> None:
    """Called after a document accept while IN_VERIFICATION.

    If all required docs are ACCEPTED and name_change_status is NONE or APPROVED,
    auto-advance IN_VERIFICATION -> ADJUDICATING (stamping verification_completed_at,
    recomputing FINAL risk). If that FINAL risk > 50, land in REVIEW_HOLD instead.
    """
    if application["status"] != "IN_VERIFICATION":
        return
    if not all_required_accepted(application):
        return
    if application["name_change_status"] not in ("NONE", "APPROVED"):
        return

    application["verification_completed_at"] = db.clock.now_iso()
    applicant = db.applicants[application["applicant_id"]]
    score = recompute_risk_final(applicant)
    if score > 50:
        set_status(application, "REVIEW_HOLD", "system")
    else:
        set_status(application, "ADJUDICATING", "system")


def maybe_review_hold_on_risk(application: dict, score: float) -> None:
    """Independent risk gate: while IN_VERIFICATION a FINAL risk > 50 forces hold."""
    if application["status"] == "IN_VERIFICATION" and score > 50:
        set_status(application, "REVIEW_HOLD", "system")


# =============================================================================
# Compensation cascade (REJECT / WITHDRAW)
# =============================================================================
def refund_fee(application: dict) -> None:
    fa = fee_for_application(application["id"])
    if fa is None or fa["payment_status"] != "PAID":
        return
    refunded = fa["amount_paid_cents"]
    applicant = db.applicants[application["applicant_id"]]
    applicant["total_fees_paid_cents"] -= refunded
    touch(applicant)
    fa["amount_paid_cents"] = 0
    fa["payment_status"] = "REFUNDED"
    touch(fa)


def cancel_booked_appointments(application: dict) -> None:
    for ap in db.appointments.values():
        if ap["application_id"] == application["id"] and ap["status"] == "BOOKED":
            ap["status"] = "CANCELLED"
            touch(ap)
    # After cancellations, urgent flag drops if no BOOKED urgent appointment remains.
    if application.get("urgent_travel") and not has_booked_urgent(application["id"]):
        application["urgent_travel"] = False
        # Re-derivation only matters while UNPAID; harmless otherwise.
        rederive_fee_if_unpaid(application)


def complete_booked_appointments(application: dict) -> None:
    for ap in db.appointments.values():
        if ap["application_id"] == application["id"] and ap["status"] == "BOOKED":
            ap["status"] = "COMPLETED"
            touch(ap)


def has_booked_urgent(application_id: str) -> bool:
    return any(
        ap["application_id"] == application_id
        and ap["resource_kind"] == "URGENT_TRAVEL_COUNTER"
        and ap["status"] == "BOOKED"
        for ap in db.appointments.values()
    )
