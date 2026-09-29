"""Cross-aggregate cascades (PRD 3.3, 3.5, 3.6, 3.7, 3.8)."""

import derive
from store import db, touch

REVERT_BARRIER_MAP = {
    "CLINICAL_DETERIORATION": ("PHYSICIAN_ORDER", "CLINICAL_INSTABILITY"),
    "AUTH_LOST": ("INSURANCE_AUTH", "AWAITING_AUTH"),
    "TRANSPORT_FAILED": ("TRANSPORT", "AWAITING_TRANSPORT"),
    "FAMILY_WITHDREW": ("FAMILY_DECISION", "AWAITING_FAMILY"),
}


def advance_to_planning(episode):
    """A planning artifact moves a SCREENED episode to PLANNING.  Idempotent."""
    if episode["case_status"] == "SCREENED":
        episode["case_status"] = "PLANNING"
        return True
    return False


def resolve_barriers_with_code(episode, barrier_code):
    """Every OPEN/MITIGATING barrier carrying this code moves to RESOLVED."""
    changed = False
    for b in derive.barriers_of(episode["id"]):
        if b["barrier_code"] == barrier_code and b["status"] in ("OPEN", "MITIGATING"):
            derive.close_barrier(b, "RESOLVED")
            changed = True
    return changed


def cancel_confirmed_transports(episode, reason):
    """Compensating cancellation: releases each vehicle interval and debits
    logistics_committed_cents (which is a derived sum over the committed set)."""
    for order in derive.orders_of(episode["id"]):
        if order["order_type"] == "PATIENT_TRANSPORT" and order["status"] == "CONFIRMED":
            order["status"] = "CANCELLED"
            order["cancel_reason"] = reason
            touch(order)


def revert_to_planning(episode, reason_code=None):
    """READY_FOR_DISCHARGE -> PLANNING.

    An operator-driven revert (reason_code supplied) raises the mapped
    auto-barrier; a system-cascaded revert raises none, because the barrier
    that forced it already exists.
    """
    episode["case_status"] = "PLANNING"
    episode["marked_ready_by_user_id"] = None
    episode["marked_ready_at"] = None
    if reason_code is not None:
        barrier_code, delay_reason = REVERT_BARRIER_MAP[reason_code]
        derive.make_barrier(episode, barrier_code, "HIGH", delay_reason,
                            "REVERT_AUTO", "system")
    cancel_confirmed_transports(episode, "READINESS_REVERTED")
    touch(episode)


def cancel_episode(episode):
    """reason_code == PATIENT_LEFT_AMA: the only cancellation path."""
    episode["case_status"] = "CANCELLED"
    episode["discharge_disposition"] = "AMA"
    episode["discharged_at"] = db.now_iso()
    for b in derive.barriers_of(episode["id"]):
        if b["status"] in ("OPEN", "MITIGATING"):
            derive.close_barrier(b, "WAIVED")
    for referral in derive.referrals_of(episode["id"]):
        if referral["status"] in ("DRAFT", "BROADCAST", "CHOICE_PENDING"):
            referral["status"] = "WITHDRAWN"
            touch(referral)
            for offer in derive.offers_of(referral["id"]):
                if offer["status"] == "OFFERED" and offer["round_index"] == referral["round_index"]:
                    offer["status"] = "WITHDRAWN"
                    touch(offer)
    for order in derive.orders_of(episode["id"]):
        if order["status"] in ("REQUESTED", "CONFIRMED"):
            order["status"] = "CANCELLED"
            order["cancel_reason"] = "CLINICAL_CHANGE"
            touch(order)
    touch(episode)


def discharge_episode(episode):
    episode["case_status"] = "DISCHARGED"
    episode["discharged_at"] = db.now_iso()
    for order in derive.orders_of(episode["id"]):
        if order["status"] == "CONFIRMED":
            order["status"] = "COMPLETED"
            touch(order)
    for referral in derive.referrals_of(episode["id"]):
        for offer in derive.offers_of(referral["id"]):
            if offer["status"] == "OFFERED":
                offer["status"] = "EXPIRED"
                touch(offer)
    for b in derive.barriers_of(episode["id"]):
        if b["status"] in ("OPEN", "MITIGATING"):
            derive.close_barrier(b, "RESOLVED")
    touch(episode)


def denial_cascade(episode):
    """Hops 2..4 of the authorization denial cascade (PRD 3.6)."""
    resolved = None
    for b in derive.barriers_of(episode["id"]):
        if b["barrier_code"] == "INSURANCE_AUTH" and b["status"] == "RESOLVED":
            resolved = b
    if resolved is not None:
        reopen_barrier(resolved)
    else:
        derive.make_barrier(episode, "INSURANCE_AUTH", "HIGH", "AWAITING_AUTH",
                            "AUTH_DENIAL_AUTO", "system")
    if episode["case_status"] == "READY_FOR_DISCHARGE":
        revert_to_planning(episode, reason_code=None)


def reopen_barrier(barrier):
    barrier["status"] = "OPEN"
    barrier["reopen_count"] = barrier.get("reopen_count", 0) + 1
    barrier["clock_start_at"] = db.now_iso()
    barrier["clock_stop_at"] = None
    touch(barrier)
