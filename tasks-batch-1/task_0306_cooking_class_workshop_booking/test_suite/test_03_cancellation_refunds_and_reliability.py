"""Cancellation refunds (provisional vs final) and member reliability scoring.

Queue A: dual_variant_calc (refund on Booking; reliability on Member).
Queue B: refund tiers, late-cancel strike, provisional reliability read.
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    create_member,
    create_open_session,
    create_booking,
    confirm_booking,
    create_confirmed_booking,
    join_waitlist,
    set_clock,
    get_session_version,
    make_member_headers,
    make_instructor_headers,
)


def test_provisional_refund_uses_tier_not_full_charge(api):
    """PRD §3.7: "a cancellation at least 168 hours before the start refunds 100
    percent, at least 72 hours refunds 75 percent, at least 24 hours refunds 50
    percent, and anything inside 24 hours refunds 0 percent. The gross refund is
    the booking's charge_cents times that tier percentage rounded half-up to whole
    cents, and the base refund is that gross minus a flat cancellation fee of 300
    cents, floored at 0".
    PRD §3.7: "At the moment the member cancels, the provisional refund applies
    the tier formula above and credits that amount; the eventual waitlist outcome
    is not yet known, so refilled_from_waitlist does not enter the figure."

    Charge 9000 cancelled 100h before (75% tier): gross 6750 - 300 = 6450, even
    though a waitlisted member will refill the seat.

    Design: Difficulty/dual_variant_calc/refund_provisional_vs_final_on_booking
    """
    set_clock("2026-06-25T00:00:00Z")
    instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 2,
            "station_fixed_cost_cents": 6000, "prep_minutes": 60, "cleanup_minutes": 30,
        },
        session_overrides={
            "planned_seats": 2, "station_id": "ST-REFUND-PV",
            "start_at": "2026-06-29T04:00:00Z", "end_at": "2026-06-29T06:00:00Z",
        },
        ingredient_overrides={"name": "flour", "qty_per_seat": 0.125, "unit_cost_cents": 322},
    )
    mem_a = create_member()
    mem_b = create_member()
    mem_c = create_member()
    bk_a = create_booking(session["id"], mem_a["id"], 1)
    confirmed_a = confirm_booking(bk_a["id"], session["id"], mem_a["id"])
    assert confirmed_a["charge_cents"] == 9000
    # Member B confirms the 2nd seat -> session FULL. Member C (no booking on this
    # session) then joins the waitlist; PRD §3.8 forbids an already-CONFIRMED member
    # from joining its own session's waitlist, so the waitlister must be a third member.
    create_confirmed_booking(session["id"], mem_b["id"], 1)
    join_waitlist(session["id"], mem_c["id"], 1)

    cancelled = validate_success(api.cancel_booking(bk_a["id"], make_member_headers(mem_a["id"])), 200)
    assert cancelled["refund_cents"] == 6450, (
        f"provisional 75% tier of 9000 minus 300 = 6450, got {cancelled['refund_cents']}"
    )
    assert cancelled["lifecycle_status"] == "CANCELLED"


def test_final_refund_waives_tier_when_seat_refilled(api):
    """PRD §3.7: "The final refund is reconciled when the session locks and
    completes: if by then the booking's vacated seat was taken by a promoted
    waitlist booking - that is, refilled_from_waitlist is true - the refund
    becomes the full charge_cents minus the 300-cent fee (the studio lost no seat
    revenue, so the tier penalty is waived)".
    PRD §3.7: "The difference between the final and provisional figures is
    credited to or clawed back from the member's wallet at completion."

    A booking cancelled at the 75% tier (provisional refund 6450) whose seat is
    refilled from the waitlist reconciles to FINAL 9000 - 300 = 8700 at completion;
    the 2250 delta is credited to the wallet.

    Design: Difficulty/dual_variant_calc/refund_provisional_vs_final_on_booking
    """
    set_clock("2026-06-25T00:00:00Z")
    instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 2,
            "station_fixed_cost_cents": 6000, "prep_minutes": 60, "cleanup_minutes": 30,
        },
        session_overrides={
            "planned_seats": 2, "station_id": "ST-REFUND-FN",
            "start_at": "2026-06-29T04:00:00Z", "end_at": "2026-06-29T06:00:00Z",
        },
        ingredient_overrides={"name": "flour", "qty_per_seat": 0.125, "unit_cost_cents": 322},
    )
    instr_headers = make_instructor_headers(instr["id"])
    mem_a = create_member()
    mem_b = create_member()
    mem_c = create_member()
    bk_a = create_booking(session["id"], mem_a["id"], 1)
    confirm_booking(bk_a["id"], session["id"], mem_a["id"])
    create_confirmed_booking(session["id"], mem_b["id"], 1)  # session now FULL
    # PRD §3.8: an already-CONFIRMED member may not join its own session's waitlist,
    # so the refilling waitlister is a third member with no booking on this session.
    join_waitlist(session["id"], mem_c["id"], 1)

    validate_success(api.cancel_booking(bk_a["id"], make_member_headers(mem_a["id"])), 200)
    bk_a_prov = validate_success(api.get_booking(bk_a["id"], make_member_headers(mem_a["id"])), 200)
    assert bk_a_prov["refilled_from_waitlist"] is True
    assert bk_a_prov["refund_cents"] == 6450

    # Lock + complete to drive FINAL reconciliation.
    validate_success(api.lock_session(session["id"], instr_headers), 200)
    validate_success(api.complete_session(session["id"], instr_headers), 200)

    bk_a_final = validate_success(api.get_booking(bk_a["id"], make_member_headers(mem_a["id"])), 200)
    assert bk_a_final["refund_cents"] == 8700, (
        f"FINAL refund waives tier when refilled: 9000 - 300 = 8700, got {bk_a_final['refund_cents']}"
    )
    mem_a_after = validate_success(api.get_member(mem_a["id"], make_member_headers(mem_a["id"])), 200)
    assert mem_a_after["wallet_credit_cents"] == 8700, (
        "provisional 6450 + 2250 final delta credited at completion"
    )


def test_reliability_provisional_excludes_pending_strike(api):
    """PRD §3.2: "The provisional variant is what a read of a member returns: it
    counts only the member's SETTLED strikes and ignores any still-PENDING strike,
    so a member who has just incurred a no-show but whose session has not yet
    started still reads the pre-strike score."

    A member just marked NO_SHOW (strike PENDING) still reads reliability_score 100.

    Design: Difficulty/dual_variant_calc/reliability_provisional_vs_final_on_member
    """
    set_clock("2026-07-01T00:00:00Z")
    instr, _tmpl, session = create_open_session(
        instructor_max_skill="ADVANCED",
        template_overrides={
            "skill_level": "ADVANCED", "base_price_cents": 8500, "default_capacity": 3,
            "station_fixed_cost_cents": 6000, "prep_minutes": 30, "cleanup_minutes": 0,
        },
        session_overrides={
            "planned_seats": 3, "station_id": "ST-REL-PV",
            "start_at": "2026-07-10T14:00:00Z", "end_at": "2026-07-10T16:00:00Z",
        },
        ingredient_overrides={"name": "onion", "qty_per_seat": 0.2, "unit_cost_cents": 100},
    )
    instr_headers = make_instructor_headers(instr["id"])
    member = create_member()
    booking = create_booking(session["id"], member["id"], 1)
    confirm_booking(booking["id"], session["id"], member["id"])
    validate_success(api.lock_session(session["id"], instr_headers), 200)
    validate_success(api.mark_no_show(booking["id"], instr_headers), 200)

    read = validate_success(api.get_member(member["id"], make_member_headers(member["id"])), 200)
    assert read["reliability_score"] == 100, (
        f"PENDING strike excluded from provisional read, got {read['reliability_score']}"
    )
    assert read["booking_status"] == "GOOD_STANDING"


def test_reliability_final_includes_settled_strike_on_complete(api):
    """PRD §3.2: "The final variant is computed when a session completes, after
    that session's pending strikes have flipped to SETTLED: the freshly settled
    strikes are now included".
    PRD §3.2: "subtracting a penalty of 25 for each settled no-show".

    After completion the just-settled NO_SHOW strike counts: 100 - 25 = 75; the
    member stays GOOD_STANDING (75 >= 40).

    Design: Difficulty/dual_variant_calc/reliability_provisional_vs_final_on_member
    """
    set_clock("2026-07-01T00:00:00Z")
    instr, _tmpl, session = create_open_session(
        instructor_max_skill="ADVANCED",
        template_overrides={
            "skill_level": "ADVANCED", "base_price_cents": 8500, "default_capacity": 3,
            "station_fixed_cost_cents": 6000, "prep_minutes": 30, "cleanup_minutes": 0,
        },
        session_overrides={
            "planned_seats": 3, "station_id": "ST-REL-FN",
            "start_at": "2026-07-10T14:00:00Z", "end_at": "2026-07-10T16:00:00Z",
        },
        ingredient_overrides={"name": "onion", "qty_per_seat": 0.2, "unit_cost_cents": 100},
    )
    instr_headers = make_instructor_headers(instr["id"])
    member = create_member()
    booking = create_booking(session["id"], member["id"], 1)
    confirm_booking(booking["id"], session["id"], member["id"])
    validate_success(api.lock_session(session["id"], instr_headers), 200)
    validate_success(api.mark_no_show(booking["id"], instr_headers), 200)
    validate_success(api.complete_session(session["id"], instr_headers), 200)

    after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])), 200)
    assert after["reliability_score"] == 75, (
        f"FINAL settled NO_SHOW: 100 - 25 = 75, got {after['reliability_score']}"
    )
    assert after["booking_status"] == "GOOD_STANDING"


def test_refund_tier_under_24h_yields_zero(api):
    """PRD §3.7: "anything inside 24 hours refunds 0 percent. The gross refund is
    the booking's charge_cents times that tier percentage rounded half-up to whole
    cents, and the base refund is that gross minus a flat cancellation fee of 300
    cents, floored at 0 so it can never go negative."

    A 5000 BEGINNER booking cancelled 10h before start: gross 0, max(0, 0-300) = 0;
    nothing is credited to the wallet.

    Design: Corner/calculations/refund_tier_under_24h_yields_zero
    """
    set_clock("2026-11-11T04:00:00Z")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 2,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 2, "station_id": "ST-RT0",
            "start_at": "2026-11-11T14:00:00Z", "end_at": "2026-11-11T16:00:00Z",
        },
        ingredient_overrides={"name": "r", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    member = create_member()
    booking = create_booking(session["id"], member["id"], 1)
    confirm_booking(booking["id"], session["id"], member["id"])
    cancelled = validate_success(api.cancel_booking(booking["id"], make_member_headers(member["id"])), 200)
    assert cancelled["refund_cents"] == 0
    member_after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])), 200)
    assert member_after["wallet_credit_cents"] == 0


def test_late_cancel_creates_pending_strike(api):
    """PRD §3.7: "If the cancellation falls within 24 hours of start_at, the
    system also creates a LATE_CANCEL strike (settlement_status PENDING) for the
    member."
    PRD §3.2: "The provisional variant ... counts only the member's SETTLED
    strikes and ignores any still-PENDING strike".

    A cancel 10h before start creates a NoShowRecord kind=LATE_CANCEL,
    settlement_status PENDING; the member's provisional reliability stays 100.

    Design: Corner/calculations/late_cancel_strike_created_within_24h
    """
    set_clock("2026-11-12T04:00:00Z")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 2,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 2, "station_id": "ST-LC",
            "start_at": "2026-11-12T14:00:00Z", "end_at": "2026-11-12T16:00:00Z",
        },
        ingredient_overrides={"name": "r", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    member = create_member()
    booking = create_booking(session["id"], member["id"], 1)
    confirm_booking(booking["id"], session["id"], member["id"])
    validate_success(api.cancel_booking(booking["id"], make_member_headers(member["id"])), 200)

    data, meta = validate_paginated(
        api.list_member_no_show_records(member["id"], make_member_headers(member["id"]))
    )
    assert len(data) == 1
    assert data[0]["kind"] == "LATE_CANCEL"
    assert data[0]["settlement_status"] == "PENDING"
    member_after = validate_success(api.get_member(member["id"], make_member_headers(member["id"])), 200)
    assert member_after["reliability_score"] == 100
