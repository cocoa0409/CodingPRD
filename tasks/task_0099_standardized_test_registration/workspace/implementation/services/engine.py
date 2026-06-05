"""Shared seat-accounting, version, cascade, and recompute engine.

Centralizes the cross-resource settlements described in PRD §2.7-2.10 & §3.6:
  - seat pool +/- and TestSession.version bump moving together
  - standby promotion cascade (mint offer-hold registration)
  - super-score recompute across a candidate's released sittings
"""
from db import store, stamp_create, touch, now_iso_ms
from services.common import parse_iso_dt
from services import calculations as calc


def bump_session_version(session):
    """Bump TestSession version + updated_at (every seat movement does this)."""
    touch(session)


def add_standard_seat(session):
    session["standard_seats_reserved"] += 1
    bump_session_version(session)


def remove_standard_seat(session):
    session["standard_seats_reserved"] -= 1
    bump_session_version(session)


def add_accommodated_seat(session):
    session["accommodated_seats_reserved"] += 1


def remove_accommodated_seat(session):
    session["accommodated_seats_reserved"] -= 1


# ---------------------------------------------------------------------------
# Super-score recompute (PRD §3.8 / §2.10)
# ---------------------------------------------------------------------------
def recompute_super_scores(candidate_id, exam_type):
    """Recompute super_composite for every RELEASED ScoreReport of this
    candidate + exam_type. Qualifying = report's registration.score_status==RELEASED.
    """
    qualifying = []
    for sr in store.score_reports.values():
        if sr.get("candidate_id") != candidate_id:
            continue
        if sr.get("exam_type") != exam_type:
            continue
        reg = store.registrations.get(sr.get("registration_id"))
        if reg is None:
            continue
        if reg.get("score_status") == "RELEASED":
            qualifying.append(sr)

    new_super = calc.super_composite(exam_type, qualifying)
    for sr in qualifying:
        if sr.get("super_composite") != new_super:
            sr["super_composite"] = new_super
            touch(sr)


# ---------------------------------------------------------------------------
# Standby promotion cascade (PRD §3.6 / §2.10)
# ---------------------------------------------------------------------------
def promote_top_standby(session, promoted_from_entry_id=None):
    """If a STANDARD seat is free and a WAITING entry exists, promote the
    top-ranked one: WAITING->OFFERED, mint an offer-hold Registration,
    re-take the seat, bump version.

    Returns the promoted entry, or None if nothing fired.
    """
    center = store.test_centers.get(session["test_center_id"])
    if center is None:
        return None
    # Only promote when a standard seat is genuinely free.
    if session["standard_seats_reserved"] >= center["room_capacity_standard"]:
        return None

    clock_now = store.get_clock_now()

    # Recompute promotion scores for all WAITING entries on this session and pick top.
    waiting = [
        e for e in store.standby_entries.values()
        if e.get("test_session_id") == session["id"] and e.get("status") == "WAITING"
    ]
    if not waiting:
        return None

    for e in waiting:
        created = parse_iso_dt(e["created_at"])
        score = calc.standby_promotion_score(e["priority_tier"], created, clock_now)
        if e.get("promotion_score") != score:
            e["promotion_score"] = score
            # promotion_score is a computed ranking field; recompute is internal
            # bookkeeping. Refresh updated_at without bumping the entry version.
            e["updated_at"] = now_iso_ms()

    # Selection: promotion_score DESC, then created_at ASC (oldest first).
    # _seq breaks same-millisecond ties preserving true creation order.
    waiting.sort(key=lambda e: (-e["promotion_score"], e["created_at"], e.get("_seq", 0)))
    chosen = waiting[0]

    # Mint offer-hold registration.
    reg = {
        "test_session_id": session["id"],
        "candidate_id": chosen["candidate_id"],
        "accommodation_request_id": None,
        "seat_kind": "STANDARD",
        "allotted_minutes": calc.allotted_minutes(session["exam_type"], None),
        "amount_paid_cents": 0,
        "amount_refunded_cents": 0,
        "refund_tier": None,
        "lifecycle_status": "RESERVED",
        "score_status": "PENDING",
        "is_standby_origin": True,
    }
    stamp_create(reg)
    store.registrations[reg["id"]] = reg

    # Re-take the freed seat + bump version.
    add_standard_seat(session)

    # Update the entry.
    chosen["status"] = "OFFERED"
    chosen["offered_registration_id"] = reg["id"]
    if promoted_from_entry_id is not None:
        chosen["promoted_from_entry_id"] = promoted_from_entry_id
    touch(chosen)

    return chosen
