"""Cascade engine: state transitions that ripple across multiple entities.

The logic lives here so route handlers stay declarative.
"""
from __future__ import annotations

from datetime import timedelta

import clock
import db
from common import now_iso, stamp_update, new_id
from services.referral import estimated_amount, payable_amount


APPLICATION_NON_TERMINAL = {"APPLIED", "SCREENING", "INTERVIEWING", "OFFER_EXTENDED"}
OFFER_NON_TERMINAL = {"PENDING_APPROVAL", "APPROVED", "EXTENDED"}
OFFER_NON_TERMINAL_OR_ACCEPTED = {"PENDING_APPROVAL", "APPROVED", "EXTENDED", "ACCEPTED"}
BGC_NON_TERMINAL = {"INITIATED", "IN_PROGRESS"}


# ---------------------------------------------------------------------------
# Application/Requisition propagation
# ---------------------------------------------------------------------------


def maybe_auto_close_requisition(req_id: str) -> None:
    req = db.requisitions.get(req_id)
    if not req:
        return
    if req["status"] != "APPROVED":
        return
    filled = sum(
        1 for a in db.applications.values()
        if a["requisition_id"] == req_id and a["status"] == "HIRED"
    )
    if filled >= req["openings"]:
        req["status"] = "CLOSED"
        stamp_update(req)


def maybe_reopen_requisition(req_id: str) -> None:
    """When a hire is rolled back: if requisition is CLOSED, it must re-open to APPROVED."""
    req = db.requisitions.get(req_id)
    if not req:
        return
    if req["status"] != "CLOSED":
        return
    filled = sum(
        1 for a in db.applications.values()
        if a["requisition_id"] == req_id and a["status"] == "HIRED"
    )
    if filled < req["openings"]:
        req["status"] = "APPROVED"
        stamp_update(req)


def reject_other_non_terminal_applications_for_candidate(candidate_id: str, except_application_id: str) -> None:
    """When a candidate is HIRED elsewhere, reject every OTHER non-terminal app."""
    for app in list(db.applications.values()):
        if app["id"] == except_application_id:
            continue
        if app["candidate_id"] != candidate_id:
            continue
        if app["status"] in {"HIRED", "REJECTED", "WITHDRAWN"}:
            continue
        app["status"] = "REJECTED"
        stamp_update(app)


def transition_application_to_hired(application_id: str) -> None:
    """Cascade application -> HIRED. Bubbles to requisition.filled_count."""
    app = db.applications[application_id]
    if app["status"] == "HIRED":
        return
    app["status"] = "HIRED"
    stamp_update(app)
    reject_other_non_terminal_applications_for_candidate(app["candidate_id"], application_id)
    maybe_auto_close_requisition(app["requisition_id"])


def transition_application_to_rejected(application_id: str) -> None:
    """For the FAILED-BGC rollback path."""
    app = db.applications.get(application_id)
    if not app:
        return
    if app["status"] == "REJECTED":
        return
    app["status"] = "REJECTED"
    stamp_update(app)


# ---------------------------------------------------------------------------
# BackgroundCheck / ReferralBonus
# ---------------------------------------------------------------------------


def find_background_check_by_offer(offer_id: str) -> dict | None:
    for b in db.background_checks.values():
        if b["offer_id"] == offer_id:
            return b
    return None


def find_referral_bonus_by_offer(offer_id: str) -> dict | None:
    for r in db.referral_bonuses.values():
        if r["offer_id"] == offer_id:
            return r
    return None


def cancel_background_check_for_offer(offer_id: str) -> None:
    bgc = find_background_check_by_offer(offer_id)
    if bgc and bgc["status"] in BGC_NON_TERMINAL:
        bgc["status"] = "CANCELLED"
        stamp_update(bgc)


def void_referral_bonus_for_offer(offer_id: str) -> None:
    rb = find_referral_bonus_by_offer(offer_id)
    if rb and rb["status"] != "PAID":
        # PENDING_BGC -> VOID or PAYABLE -> VOID per cascade rules.
        rb["status"] = "VOID"
        stamp_update(rb)


def create_background_check(offer: dict) -> dict:
    bgc = {
        "id": new_id(),
        "offer_id": offer["id"],
        "candidate_id": _candidate_id_of_offer(offer),
        "status": "INITIATED",
        "vendor_reference": f"VND-{new_id()[:12].upper()}",
        "completed_at": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.background_checks[bgc["id"]] = bgc
    return bgc


def _candidate_id_of_offer(offer: dict) -> str:
    app = db.applications[offer["application_id"]]
    return app["candidate_id"]


def create_referral_bonus_if_eligible(offer: dict) -> dict | None:
    app = db.applications[offer["application_id"]]
    candidate = db.candidates[app["candidate_id"]]
    req = db.requisitions[app["requisition_id"]]
    if candidate["source_channel"] != "REFERRAL" or not candidate.get("referrer_user_id"):
        return None
    est = estimated_amount(offer, candidate, req)
    rb = {
        "id": new_id(),
        "candidate_id": candidate["id"],
        "referrer_user_id": candidate["referrer_user_id"],
        "offer_id": offer["id"],
        "estimated_amount_cents": est,
        "payable_amount_cents": None,
        "status": "PENDING_BGC",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.referral_bonuses[rb["id"]] = rb
    return rb


# ---------------------------------------------------------------------------
# Offer revoke cascade (also reused by requisition cancel and auto-expiry)
# ---------------------------------------------------------------------------


def revoke_offer_cascade(offer: dict) -> None:
    """Manually revoke an APPROVED or EXTENDED offer with full downstream cascades.

    Used by: POST /offers/{id}/revoke, requisition cancel cascade, auto-expiry.
    Caller is responsible for confirming the offer's current state permits revocation.
    """
    offer["status"] = "REVOKED"
    stamp_update(offer)
    # Cascade BGC and ReferralBonus.
    cancel_background_check_for_offer(offer["id"])
    void_referral_bonus_for_offer(offer["id"])


# ---------------------------------------------------------------------------
# Auto-expiry sweep (driven by /_clock/set_current_utc).
# ---------------------------------------------------------------------------


def sweep_offer_expiry() -> list:
    """Auto-revoke every EXTENDED offer whose expires_at has been reached or passed.

    Returns the list of revoked offer ids. Applies the same downstream cascades
    as a manual revoke.
    """
    revoked_ids = []
    now_dt = clock.now()
    for off in list(db.offers.values()):
        if off["status"] != "EXTENDED":
            continue
        exp_iso = off.get("expires_at")
        if not exp_iso:
            continue
        exp = clock.parse_iso(exp_iso)
        if now_dt >= exp:
            revoke_offer_cascade(off)
            revoked_ids.append(off["id"])
    return revoked_ids


def compute_expires_at(extended_at_dt) -> str:
    return clock.iso(extended_at_dt + timedelta(days=14))
