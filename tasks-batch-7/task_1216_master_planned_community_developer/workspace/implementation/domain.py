"""Domain cascades and the logical-clock sweep."""
from datetime import timedelta
from decimal import Decimal

from core import (
    DB, touch, new_entity, calendar_days, round_half_up,
    TOTAL_SEATS, TRANCHE_OPEN_LEAD_DAYS, REQUIRED_OWNER_SEATS, STAGE_ORDER,
    VENUE_TO_AMENITY,
)
import serializers


# ---------------------------------------------------------------------------
# Amenity delinquency cascade
# ---------------------------------------------------------------------------
def mark_amenity_delinquent(amenity):
    if amenity["status"] in ("OPEN", "DELINQUENT"):
        return
    amenity["status"] = "DELINQUENT"
    amenity["delinquency_recorded_at"] = DB.now()
    touch(amenity)
    # Cancel SCHEDULED events at venues mapped to this amenity type, with RSVPs.
    for ev in list(DB.events.values()):
        if ev["community_id"] != amenity["community_id"]:
            continue
        if ev["status"] != "SCHEDULED":
            continue
        if VENUE_TO_AMENITY.get(ev["venue"]) != amenity["amenity_type"]:
            continue
        ev["status"] = "CANCELLED"
        touch(ev)
        for r in list(DB.rsvps.values()):
            if r["event_id"] == ev["id"] and r["status"] in ("CONFIRMED", "WAITLISTED"):
                r["status"] = "CANCELLED"
                touch(r)
    # Auto-create a DRAFT AMENITY_DELINQUENCY notice for the community.
    notice = new_entity()
    notice.update({
        "community_id": amenity["community_id"],
        "notice_type": "AMENITY_DELINQUENCY",
        "subject": f"Amenity delivery delinquency: {amenity['amenity_type']}",
        "body": f"Amenity {amenity['id']} ({amenity['amenity_type']}) is delinquent.",
        "send_at": DB.now(),
        "sent_at": None,
        "effective_date": None,
        "budget_id": None,
        "assessment_rate_id": None,
        "supersedes_notice_id": None,
        "status": "DRAFT",
    })
    DB.notices[notice["id"]] = notice


def check_amenity_trigger_breach(phase):
    """After phase.closed_lot_count increments: breach amenities keyed to it."""
    for amenity in list(DB.amenities.values()):
        if amenity["community_id"] != phase["community_id"]:
            continue
        if amenity["trigger_phase_id"] != phase["id"]:
            continue
        if amenity["status"] in ("OPEN", "DELINQUENT"):
            continue
        if phase["closed_lot_count"] > amenity["trigger_unit_count"]:
            mark_amenity_delinquent(amenity)


# ---------------------------------------------------------------------------
# Builder standing cascades
# ---------------------------------------------------------------------------
def demote_builder_to_probation(builder):
    if builder["standing"] == "GOOD_STANDING":
        builder["standing"] = "PROBATION"
        touch(builder)


def suspend_builder(builder):
    if builder["standing"] != "SUSPENDED":
        builder["standing"] = "SUSPENDED"
        touch(builder)
    # Cascade: the builder's OTHER agreements in {DRAFT, EXECUTED} -> TERMINATED,
    # their tranches in {SCHEDULED, OPEN} -> CANCELLED.
    for ag in list(DB.agreements.values()):
        if ag["builder_id"] != builder["id"]:
            continue
        if ag["status"] in ("DRAFT", "EXECUTED"):
            ag["status"] = "TERMINATED"
            touch(ag)
            for t in list(DB.tranches.values()):
                if t["agreement_id"] == ag["id"] and t["status"] in ("SCHEDULED", "OPEN"):
                    t["status"] = "CANCELLED"
                    touch(t)


# ---------------------------------------------------------------------------
# Agreement completion
# ---------------------------------------------------------------------------
def check_agreement_completion(agreement):
    if agreement["status"] != "ACTIVE":
        return
    if agreement["lots_closed_count"] != agreement["total_lots_committed"]:
        return
    for t in DB.tranches.values():
        if t["agreement_id"] != agreement["id"]:
            continue
        if t["status"] not in ("SATISFIED", "CURED", "WAIVED"):
            return
    agreement["status"] = "COMPLETED"
    touch(agreement)


# ---------------------------------------------------------------------------
# Community governance ratchet and seat conversion
# ---------------------------------------------------------------------------
def community_pct(community):
    return round_half_up(
        Decimal(community["closed_unit_count"])
        / Decimal(community["total_planned_units"]) * 100,
        2,
    )


def stage_for_pct(pct):
    if pct >= Decimal("75.00"):
        return "OWNER_MAJORITY"
    if pct >= Decimal("50.00"):
        return "PARITY"
    if pct >= Decimal("25.00"):
        return "OWNER_REPRESENTATION"
    return "DECLARANT_CONTROL"


def recompute_community_stage(community):
    """Ratchet the transition_stage up (never down) and convert board seats."""
    pct = community_pct(community)
    target = stage_for_pct(pct)
    if STAGE_ORDER[target] > STAGE_ORDER[community["transition_stage"]]:
        community["transition_stage"] = target
        # Convert DECLARANT_APPOINTED FILLED seats, highest seat_no first.
        seats = [s for s in DB.board_seats.values()
                 if s["community_id"] == community["id"]]
        owner_elected = sum(1 for s in seats if s["seat_class"] == "OWNER_ELECTED")
        required = REQUIRED_OWNER_SEATS[target]
        to_convert = required - owner_elected
        if to_convert > 0:
            candidates = sorted(
                (s for s in seats
                 if s["seat_class"] == "DECLARANT_APPOINTED" and s["status"] == "FILLED"),
                key=lambda s: -s["seat_no"],
            )
            for seat in candidates[:to_convert]:
                seat["seat_class"] = "OWNER_ELECTED"
                seat["status"] = "VACANT"
                seat["holder_name"] = None
                seat["holder_resident_id"] = None
                touch(seat)
    if pct >= Decimal("100.00"):
        # All remaining DECLARANT_APPOINTED seats convert to OWNER_ELECTED VACANT.
        for seat in sorted(
            (s for s in DB.board_seats.values()
             if s["community_id"] == community["id"]
             and s["seat_class"] == "DECLARANT_APPOINTED"),
            key=lambda s: -s["seat_no"],
        ):
            seat["seat_class"] = "OWNER_ELECTED"
            seat["status"] = "VACANT"
            seat["holder_name"] = None
            seat["holder_resident_id"] = None
            touch(seat)


# ---------------------------------------------------------------------------
# Clock sweep
# ---------------------------------------------------------------------------
def run_sweep():
    """Apply every scheduled transition whose moment has arrived.
    Returns the number of primary transitions applied (one per affected entity;
    cascade side effects such as builder probation or event cancellation do not
    add to the count)."""
    now = DB.now()
    transitioned = set()

    # Tranches: SCHEDULED -> OPEN once the clock reaches 30 days before due.
    # A clock jump that lands past the due date still passes through OPEN first,
    # so a past-due SCHEDULED tranche with an unmet count becomes MISSED below.
    for t in list(DB.tranches.values()):
        if t["status"] == "SCHEDULED":
            if t["due_date"] - timedelta(days=TRANCHE_OPEN_LEAD_DAYS) <= now:
                t["status"] = "OPEN"
                touch(t)
                transitioned.add(("tranche", t["id"]))

    # Tranches: OPEN -> MISSED (now > due_date and count short); builder probation
    for t in list(DB.tranches.values()):
        if t["status"] == "OPEN":
            if now > t["due_date"] and t["lots_credited"] < t["lot_count_due"]:
                t["status"] = "MISSED"
                touch(t)
                transitioned.add(("tranche", t["id"]))
                agreement = DB.agreements.get(t["agreement_id"])
                if agreement is not None:
                    builder = DB.builders.get(agreement["builder_id"])
                    if builder is not None:
                        demote_builder_to_probation(builder)

    # Notices: SCHEDULED -> SENT (send_at <= now); sent_at = send_at
    for n in list(DB.notices.values()):
        if n["status"] == "SCHEDULED" and n["send_at"] <= now:
            n["status"] = "SENT"
            n["sent_at"] = n["send_at"]
            touch(n)
            transitioned.add(("notice", n["id"]))

    # Events: SCHEDULED -> COMPLETED (end_at <= now)
    for ev in list(DB.events.values()):
        if ev["status"] == "SCHEDULED" and ev["end_at"] <= now:
            ev["status"] = "COMPLETED"
            touch(ev)
            transitioned.add(("event", ev["id"]))

    # Rates: ARMED -> EFFECTIVE at fiscal-year start (Jan 1 00:00 UTC)
    from datetime import datetime, timezone
    for r in list(DB.rates.values()):
        if r["status"] == "ARMED":
            fy_start = datetime(r["fiscal_year"], 1, 1, tzinfo=timezone.utc)
            if now >= fy_start:
                r["status"] = "EFFECTIVE"
                touch(r)
                transitioned.add(("rate", r["id"]))

    # Applications: APPROVED -> EXPIRED (now > construction_start_by, no start recorded)
    for a in list(DB.applications.values()):
        if a["status"] == "APPROVED" and not a.get("_construction_started"):
            csb = a["construction_start_by"]
            if csb is not None and now > csb:
                a["status"] = "EXPIRED"
                touch(a)
                transitioned.add(("application", a["id"]))

    # Board seats: ELECTION_CALLED -> LAPSED (now > election_deadline)
    for s in list(DB.board_seats.values()):
        if s["status"] == "ELECTION_CALLED" and s["election_deadline"] is not None:
            if now > s["election_deadline"]:
                s["status"] = "LAPSED"
                touch(s)
                transitioned.add(("board_seat", s["id"]))

    # Amenities: past hard_deadline_date -> DELINQUENT
    for a in list(DB.amenities.values()):
        if a["status"] in ("COMMITTED", "IN_DESIGN", "UNDER_CONSTRUCTION"):
            if now > a["hard_deadline_date"]:
                mark_amenity_delinquent(a)
                transitioned.add(("amenity", a["id"]))

    return len(transitioned)
