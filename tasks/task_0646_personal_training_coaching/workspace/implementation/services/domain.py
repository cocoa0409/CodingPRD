"""Domain service: lookups, ownership, mutation bookkeeping, and the cascade /
recompute engine (PRD §2.9, §3.2-§3.7).

This module is the single source of truth for the derived/computed quantities:
  - SessionPack.sessions_committed / sessions_remaining / status (seat accounting)
  - Engagement auto-pause on pack depletion / auto-resume on seat release
  - Client.no_show_strikes / booking_privilege (threshold cascade)
  - Client.latest_weight_kg (latest ASSESSED check-in)
  - MacroPlan provisional recompute on check-in assess
Every reconciliation that touches a versioned entity bumps its version + updated_at.
"""

from flask import g

import errors
from db import db, now_ts
from clock import clock, parse_iso8601
from services import calculations as calc


# --------------------------------------------------------------------------
# Mutation bookkeeping
# --------------------------------------------------------------------------
def touch(record):
    """Refresh updated_at and increment version on a common-fields entity."""
    record["updated_at"] = now_ts()
    record["version"] = record.get("version", 0) + 1


# --------------------------------------------------------------------------
# Existence lookups (raise the entity-specific not-found error)
# --------------------------------------------------------------------------
def get_trainer(trainer_id):
    t = db.trainers.get(trainer_id)
    if t is None:
        raise errors.not_found(errors.ERR_TRAINER_NOT_FOUND, "Trainer not found")
    return t


def get_client(client_id):
    c = db.clients.get(client_id)
    if c is None:
        raise errors.not_found(errors.ERR_CLIENT_NOT_FOUND, "Client not found")
    return c


def get_engagement(engagement_id):
    e = db.engagements.get(engagement_id)
    if e is None:
        raise errors.not_found(errors.ERR_ENGAGEMENT_NOT_FOUND, "Engagement not found")
    return e


def get_pack(pack_id):
    p = db.session_packs.get(pack_id)
    if p is None:
        raise errors.not_found(errors.ERR_PACK_NOT_FOUND, "Session pack not found")
    return p


def get_booking(booking_id):
    b = db.bookings.get(booking_id)
    if b is None:
        raise errors.not_found(errors.ERR_BOOKING_NOT_FOUND, "Booking not found")
    return b


def get_program(program_id):
    p = db.program_assignments.get(program_id)
    if p is None:
        raise errors.not_found(errors.ERR_PROGRAM_NOT_FOUND, "Program assignment not found")
    return p


def get_macro_plan(macro_plan_id):
    m = db.macro_plans.get(macro_plan_id)
    if m is None:
        raise errors.not_found(errors.ERR_MACROPLAN_NOT_FOUND, "Macro plan not found")
    return m


def get_check_in(check_in_id):
    c = db.check_ins.get(check_in_id)
    if c is None:
        raise errors.not_found(errors.ERR_CHECKIN_NOT_FOUND, "Check-in not found")
    return c


def get_habit_log(habit_log_id):
    h = db.habit_logs.get(habit_log_id)
    if h is None:
        raise errors.not_found(errors.ERR_CHECKIN_NOT_FOUND, "Habit log not found")
    return h


def get_message(message_id):
    m = db.messages.get(message_id)
    if m is None:
        raise errors.not_found(errors.ERR_CHECKIN_NOT_FOUND, "Message not found")
    return m


# --------------------------------------------------------------------------
# Ownership (entity_backed roles) — PRD §2.1
# A Trainer may act on resources whose owning engagement/client carries its id;
# a Client may act on resources scoped to its own id (directly or via engagement).
# PlatformAdmin is an opaque operator with no ownership binding.
# --------------------------------------------------------------------------
def assert_trainer_owns_client(client):
    if g.user_role == "Trainer" and client["trainer_id"] != g.user_id:
        raise errors.forbidden_role("Trainer does not own this client")


def assert_client_is_self(client):
    if g.user_role == "Client" and client["id"] != g.user_id:
        raise errors.forbidden_role("Client may only act on its own record")


def assert_owns_client(client):
    """Generic ownership for a Client resource based on the acting role."""
    if g.user_role == "Trainer":
        assert_trainer_owns_client(client)
    elif g.user_role == "Client":
        assert_client_is_self(client)


def assert_owns_engagement(engagement):
    if g.user_role == "Trainer":
        if engagement["trainer_id"] != g.user_id:
            raise errors.forbidden_role("Trainer does not own this engagement")
    elif g.user_role == "Client":
        if engagement["client_id"] != g.user_id:
            raise errors.forbidden_role("Client does not own this engagement")


# --------------------------------------------------------------------------
# Session-pack seat accounting (scaffold §1.3 session_pack_balance)
# --------------------------------------------------------------------------
COMMITTED_STATUSES = {"BOOKED", "COMPLETED", "NO_SHOW", "LATE_CANCELLED"}


def recompute_pack_balance(pack):
    """Recompute sessions_committed / sessions_remaining from this pack's bookings.

    Does NOT itself change pack.status (that is the depletion/release transition's
    job) and does NOT touch version — callers that mutate balance bump version
    explicitly via touch().
    """
    committed = sum(
        1 for b in db.bookings.values()
        if b["session_pack_id"] == pack["id"] and b["status"] in COMMITTED_STATUSES
    )
    pack["sessions_committed"] = committed
    pack["sessions_remaining"] = pack["total_sessions"] - committed
    return pack


def apply_seat_commit(pack):
    """A booking just committed a seat on this pack. Recompute balance, bump the
    pack version, and if it depleted, transition pack -> DEPLETED and pause the
    parent engagement (PACK_DEPLETED). Returns nothing; mutates in place."""
    recompute_pack_balance(pack)
    touch(pack)
    if pack["sessions_remaining"] <= 0 and pack["status"] == "ACTIVE":
        pack["status"] = "DEPLETED"
        touch(pack)
        engagement = db.engagements.get(pack["engagement_id"])
        if engagement is not None and engagement["status"] == "ACTIVE":
            engagement["status"] = "PAUSED"
            engagement["pause_reason"] = "PACK_DEPLETED"
            touch(engagement)


def apply_seat_release(pack):
    """A committed booking was released (free cancel). Recompute balance, bump
    the pack version, and if a DEPLETED pack now has a seat, return it to ACTIVE."""
    recompute_pack_balance(pack)
    touch(pack)
    if pack["sessions_remaining"] > 0 and pack["status"] == "DEPLETED":
        pack["status"] = "ACTIVE"
        touch(pack)


# --------------------------------------------------------------------------
# Calendar overlap geometry (scaffold §1.3 booking_overlap_check, PRD §3.4)
# Live bookings are those in {BOOKED, COMPLETED}.
# --------------------------------------------------------------------------
LIVE_BOOKING_STATUSES = {"BOOKED", "COMPLETED"}


def check_calendar_clear(trainer_id, client_id, start, end, exclude_booking_id=None):
    """Enforce both calendar geometries for a proposed [start, end) interval.

    Trainer (11a): pad each live trainer booking by TRAINER_BUFFER_SECONDS on
    BOTH sides; any intersection -> ERR_BOOKING_OVERLAP (back-to-back/touching
    rejected). Client (11b): strict half-open against the same client's live
    bookings, no buffer; touching (end == start) allowed -> ERR_CLIENT_DOUBLE_BOOKED.

    Ordering matches scaffold validation priority: 11a (trainer) before 11b (client).
    exclude_booking_id lets a reschedule ignore the original booking being moved.
    """
    buffer = calc.TRAINER_BUFFER_SECONDS

    # 11a — trainer geometry, padded both sides.
    for b in db.bookings.values():
        if b["id"] == exclude_booking_id:
            continue
        if b["status"] not in LIVE_BOOKING_STATUSES:
            continue
        if b["trainer_id"] != trainer_id:
            continue
        b_start = parse_iso8601(b["start_utc"])
        b_end = parse_iso8601(b["end_utc"])
        padded_start = b_start.timestamp() - buffer
        padded_end = b_end.timestamp() + buffer
        if start.timestamp() < padded_end and padded_start < end.timestamp():
            raise errors.invalid_state(errors.ERR_BOOKING_OVERLAP,
                                       "Booking overlaps a trainer session (incl. buffer)")

    # 11b — client geometry, strict half-open, no buffer.
    for b in db.bookings.values():
        if b["id"] == exclude_booking_id:
            continue
        if b["status"] not in LIVE_BOOKING_STATUSES:
            continue
        # the proposed booking's client comes from its engagement; compare the
        # candidate booking's engagement client to client_id.
        cand_eng = db.engagements.get(b["engagement_id"])
        if cand_eng is None or cand_eng["client_id"] != client_id:
            continue
        b_start = parse_iso8601(b["start_utc"])
        b_end = parse_iso8601(b["end_utc"])
        if start < b_end and b_start < end:
            raise errors.invalid_state(errors.ERR_CLIENT_DOUBLE_BOOKED,
                                       "Booking overlaps another session for this client")


# --------------------------------------------------------------------------
# No-show strikes / booking privilege (scaffold §1.3 no_show_strikes_and_privilege)
# --------------------------------------------------------------------------
def recompute_strikes_and_privilege(client):
    """Recompute the client's no_show_strikes across ALL its engagements and set
    booking_privilege. Bumps client version (this is a versioned reconciliation)."""
    client_engagement_ids = {
        e["id"] for e in db.engagements.values() if e["client_id"] == client["id"]
    }
    strikes = sum(
        1 for b in db.bookings.values()
        if b["engagement_id"] in client_engagement_ids
        and b["status"] in ("NO_SHOW", "LATE_CANCELLED")
    )
    new_privilege = "SUSPENDED" if strikes >= calc.NO_SHOW_STRIKE_LIMIT else "ALLOWED"
    changed = (client["no_show_strikes"] != strikes) or (client["booking_privilege"] != new_privilege)
    client["no_show_strikes"] = strikes
    client["booking_privilege"] = new_privilege
    if changed:
        touch(client)


# --------------------------------------------------------------------------
# Latest weight + provisional macro recompute (scaffold §1.3 macro_plan_targets)
# --------------------------------------------------------------------------
def recompute_latest_weight(client):
    """Latest weight = weight_kg of the most recent ASSESSED check-in for any of
    this client's engagements (latest by measured_at; ties -> earlier created_at).
    Null until the first such check-in. Bumps client version when it changes."""
    client_engagement_ids = {
        e["id"] for e in db.engagements.values() if e["client_id"] == client["id"]
    }
    candidates = [
        c for c in db.check_ins.values()
        if c["engagement_id"] in client_engagement_ids and c["status"] == "ASSESSED"
    ]
    if not candidates:
        new_weight = None
    else:
        # "Most recent" = latest by measured_at; ties broken by the EARLIER
        # created_at (i.e. smaller insertion sequence). Sort ascending by
        # measured_at, then descending by _seq, so the last element is the
        # latest measured_at with the earliest created_at on a tie.
        candidates_sorted = sorted(
            candidates,
            key=lambda c: (parse_iso8601(c["measured_at"]), -c["_seq"]),
        )
        new_weight = candidates_sorted[-1]["weight_kg"]
    if client["latest_weight_kg"] != new_weight:
        client["latest_weight_kg"] = new_weight
        touch(client)


def recompute_provisional_macro_plans(engagement_id):
    """Recompute every PROVISIONAL macro plan of an engagement from the client's
    current latest_weight_kg (scaffold §1.3 provisional_estimate variant)."""
    engagement = db.engagements.get(engagement_id)
    if engagement is None:
        return
    client = db.clients.get(engagement["client_id"])
    if client is None:
        return
    weight = client["latest_weight_kg"]
    for m in db.macro_plans.values():
        if m["engagement_id"] != engagement_id or m["status"] != "PROVISIONAL":
            continue
        if weight is None:
            continue
        age = clock.now().year - client["birth_year"]
        tc, p, cb, f = calc.macro_targets(
            client["sex"], client["height_cm"], age, weight,
            m["goal"], m["activity_level"],
        )
        m["snapshot_weight_kg"] = weight
        m["target_calories"] = tc
        m["protein_g"] = p
        m["carb_g"] = cb
        m["fat_g"] = f
        touch(m)
