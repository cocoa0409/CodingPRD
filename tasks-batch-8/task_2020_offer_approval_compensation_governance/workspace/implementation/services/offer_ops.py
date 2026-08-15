"""Offer lifecycle operations: events, cascades, state transitions, expiry."""

from datetime import timedelta, datetime

import db
from services import calc


def append_event(offer_id, event_type, actor_user_id, detail=None):
    seq = sum(1 for e in db.offer_events.values() if e["offer_id"] == offer_id) + 1
    ev = {
        "id": db.new_id(),
        "created_at": db.now_ms(),
        "offer_id": offer_id,
        "sequence": seq,
        "event_type": event_type,
        "actor_user_id": actor_user_id,
        "detail": detail,
    }
    db.offer_events[ev["id"]] = ev
    return ev


def void_perks(offer_id, from_statuses, actor="system"):
    for p in db.perks.values():
        if p["offer_id"] == offer_id and p["status"] in from_statuses:
            p["status"] = "VOIDED"
            calc.touch(p)
            append_event(offer_id, "PERK_VOIDED", actor, None)


def supersede_steps(offer_id, from_statuses=("WAITING", "ACTIONABLE", "APPROVED"), actor="system"):
    steps = sorted(
        [s for s in db.approval_steps.values()
         if s["offer_id"] == offer_id and s["status"] in from_statuses],
        key=lambda s: s["sequence"],
    )
    for s in steps:
        s["status"] = "SUPERSEDED"
        calc.touch(s)
        append_event(offer_id, "STEP_SUPERSEDED", actor, f"sequence={s['sequence']}")


def withdraw_proposed_round(offer_id, actor="system"):
    for r in db.negotiation_rounds.values():
        if r["offer_id"] == offer_id and r["status"] == "PROPOSED":
            r["status"] = "WITHDRAWN"
            calc.touch(r)
            append_event(offer_id, "ROUND_WITHDRAWN", actor, None)


def cancel_inflight_checks(offer_id, actor="system"):
    for c in db.clearance_checks.values():
        if c["offer_id"] == offer_id and c["status"] in ("INITIATED", "IN_PROGRESS", "FLAGGED"):
            c["status"] = "CANCELLED"
            calc.touch(c)
            append_event(offer_id, "CHECK_CANCELLED", actor, None)


def requisition_cascade(req, detail):
    """Auto-withdraw every live offer of the requisition (PRD 3.9)."""
    affected = sorted(
        [o for o in db.offers.values()
         if o["requisition_id"] == req["id"] and o["status"] in calc.REQ_CASCADE_STATUSES],
        key=lambda o: o["created_at"],
    )
    for offer in affected:
        # non-terminal approval steps -> SUPERSEDED
        supersede_steps(offer["id"], ("WAITING", "ACTIONABLE"))
        # PROPOSED negotiation rounds -> WITHDRAWN
        withdraw_proposed_round(offer["id"])
        # perks in DRAFT/LOCKED/APPROVED -> VOIDED
        void_perks(offer["id"], ("DRAFT", "LOCKED", "APPROVED"))
        offer["status"] = "WITHDRAWN"
        calc.touch_no_version(offer)
        append_event(offer["id"], "WITHDRAWN", "system", detail)
    calc.recompute_committed_budget(req)


def hire_cascade(offer, req, actor="system"):
    """ACCEPTED -> HIRED when clearance posture resolves CLEARED."""
    offer["status"] = "HIRED"
    calc.touch_no_version(offer)
    # perks APPROVED -> ACTIVE
    for p in db.perks.values():
        if p["offer_id"] == offer["id"] and p["status"] == "APPROVED":
            p["status"] = "ACTIVE"
            calc.touch(p)
    candidate = db.candidates.get(offer["candidate_id"])
    if candidate and candidate["status"] == "IN_PROCESS":
        candidate["status"] = "HIRED"
        calc.touch(candidate)
    closed = calc.recompute_headcount(req)
    append_event(offer["id"], "HIRED", actor, None)
    if closed:
        requisition_cascade(req, "REQUISITION_FILLED")


def auto_rescind_failure(offer, req, actor="system"):
    """ACCEPTED -> RESCINDED when posture resolves FAILED."""
    offer["status"] = "RESCINDED"
    offer["rescind_reason"] = "CONTIGENCY_FAILED"
    calc.touch_no_version(offer)
    cancel_inflight_checks(offer["id"])
    void_perks(offer["id"], ("APPROVED",))
    calc.recompute_committed_budget(req)
    append_event(offer["id"], "RESCINDED", actor, "CONTIGENCY_FAILED")


def recompute_posture_and_resolve(offer, actor="system"):
    """Recompute clearance posture; fire hire/auto-rescind when ACCEPTED."""
    posture = calc.clearance_posture(offer["id"])
    if posture != offer["clearance_posture"]:
        offer["clearance_posture"] = posture
        calc.touch_no_version(offer)
    if offer["status"] != "ACCEPTED":
        return
    req = db.requisitions[offer["requisition_id"]]
    if posture == "CLEARED":
        hire_cascade(offer, req, actor)
    elif posture == "FAILED":
        auto_rescind_failure(offer, req, actor)


def expire_offer(offer, actor="system"):
    """Lazy expiry: EXTENDED/COUNTERED -> EXPIRED with full side effects."""
    req = db.requisitions[offer["requisition_id"]]
    was_countered = offer["status"] == "COUNTERED"
    offer["status"] = "EXPIRED"
    calc.touch_no_version(offer)
    if was_countered:
        withdraw_proposed_round(offer["id"])
    void_perks(offer["id"], ("APPROVED",))
    calc.recompute_committed_budget(req)
    append_event(offer["id"], "EXPIRED", actor, None)


def _parse_iso(s):
    from datetime import timezone
    txt = s[:-1] + "+00:00" if s.endswith("Z") else s
    return datetime.fromisoformat(txt).astimezone(timezone.utc)


def check_lazy_expiry(offer):
    """Returns True when the offer just expired (persisted)."""
    if offer["status"] in ("EXTENDED", "COUNTERED") and offer["expires_at"] is not None:
        if db.clock_now() >= _parse_iso(offer["expires_at"]):
            expire_offer(offer)
            return True
    return False


def set_expires_at(offer):
    dt = db.clock_now() + timedelta(days=db.OFFER_EXPIRY_DAYS)
    offer["expires_at"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
