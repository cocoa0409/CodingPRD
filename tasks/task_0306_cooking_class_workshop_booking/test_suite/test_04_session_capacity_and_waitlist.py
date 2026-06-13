"""Session seat capacity, the OPEN<->FULL cycle, waitlist promotion, and seat OCC.

Queue A: non_linear_state_machine (session cycle), transitive_cascade (waitlist
depth-3), resource_temporal_overlap (seat-count aggregate). Queue B: OCC version
increment/stale, derived confirmed_seats reconciliation, waitlist-join error.
"""
from test_helpers import (
    validate_success,
    validate_error,
    create_member,
    create_open_session,
    create_booking,
    confirm_booking,
    create_confirmed_booking,
    create_gift_card,
    join_waitlist,
    set_clock,
    get_session_version,
    make_member_headers,
    make_instructor_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["studio_admin_headers"]


def test_session_cycles_open_full_open(api):
    """PRD §3.5: "If confirmed_seats reaches planned_seats exactly, the session
    automatically transitions OPEN -> FULL".
    PRD §3.7: "If no waitlist entry refills the freed seats and the session was
    FULL, the session automatically returns FULL -> OPEN."

    A planned_seats=1 session goes OPEN -> FULL on the confirm, then FULL -> OPEN
    when the sole confirmed booking is cancelled with an empty waitlist;
    confirmed_seats returns to 0.

    Design: Difficulty/non_linear_state_machine/session_open_full_open_cycle
    """
    set_clock("2026-07-01T00:00:00Z")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 1,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 1, "station_id": "ST-CYCLE",
            "start_at": "2026-08-20T14:00:00Z", "end_at": "2026-08-20T16:00:00Z",
        },
        ingredient_overrides={"name": "water", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    member = create_member()
    booking = create_booking(session["id"], member["id"], 1)
    confirm_booking(booking["id"], session["id"], member["id"])
    full = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert full["status"] == "FULL"

    validate_success(api.cancel_booking(booking["id"], make_member_headers(member["id"])), 200)
    after = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert after["status"] == "OPEN", "FULL -> OPEN when no waitlist refills the seat"
    assert after["confirmed_seats"] == 0


def test_session_full_blocks_further_confirm_second_witness(api):
    """PRD §3.5: "If confirmed_seats reaches planned_seats exactly, the session
    automatically transitions OPEN -> FULL, after which no further pending booking
    may confirm and newcomers must join the waitlist instead."
    PRD §3.5: "A confirm is permitted only when the booking is PENDING, the session
    is OPEN, ..."
    PRD §2.9: "Only after those pass does the system evaluate state validity for
    transition endpoints (ERR_INVALID_STATE), ... and finally the domain-specific
    business rules ... a state error surfaces before ... a seat-count or other
    business error."

    A second witness on the OPEN->FULL edge: once a planned_seats=1 session is
    FULL, a second pending booking's confirm fails the "session is OPEN" state
    precondition, which per §2.9 surfaces ERR_INVALID_STATE before the seat-count
    business check.

    Design: Difficulty/non_linear_state_machine/session_open_full_open_cycle
    """
    set_clock("2026-07-01T00:00:00Z")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 1,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 1, "station_id": "ST-FULL2",
            "start_at": "2026-08-21T14:00:00Z", "end_at": "2026-08-21T16:00:00Z",
        },
        ingredient_overrides={"name": "water", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    mem_a = create_member()
    mem_b = create_member()
    create_confirmed_booking(session["id"], mem_a["id"], 1)  # session now FULL
    bk_b = create_booking(session["id"], mem_b["id"], 1)
    sv = get_session_version(session["id"])
    res = api.confirm_booking(bk_b["id"], sv, make_member_headers(mem_b["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_booking_cancel_promotes_waitlist_depth3(api):
    """PRD §3.8: "When a candidate is found, the system creates a new CONFIRMED
    booking for that waiting member with their requested seats and a freshly
    computed charge, runs the payment waterfall for that new booking, marks the
    waitlist entry PROMOTED with its promoted_booking_id set to the new booking,
    sets the cancelled booking's refilled_from_waitlist to true, and increases the
    session's confirmed_seats by the promoted entry's seats."
    PRD §3.8: "This is a depth-three cascade: a cancel triggers a promotion, which
    creates a confirmed booking, which itself runs the waterfall."

    Member B (waiting, funded by a gift card) is promoted when Member A cancels:
    entry PROMOTED, A.refilled_from_waitlist true, confirmed_seats back to 1, and
    B's gift card debited the 9000 charge (20000 -> 11000).

    Design: Difficulty/transitive_cascade/booking_cancel_promotes_waitlist_depth3
    """
    set_clock("2026-07-01T00:00:00Z")
    instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 1,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 1, "station_id": "ST-WL3",
            "start_at": "2026-08-30T14:00:00Z", "end_at": "2026-08-30T16:00:00Z",
        },
        ingredient_overrides={"name": "butter", "qty_per_seat": 0.05, "unit_cost_cents": 400},
    )
    mem_a = create_member()
    mem_b = create_member()
    gc_b = create_gift_card(mem_b["id"], 20000, code="GC-WL3")
    bk_a = create_booking(session["id"], mem_a["id"], 1)
    confirm_booking(bk_a["id"], session["id"], mem_a["id"])  # session FULL
    wl_b = join_waitlist(session["id"], mem_b["id"], 1)

    validate_success(api.cancel_booking(bk_a["id"], make_member_headers(mem_a["id"])), 200)

    entry_after = validate_success(api.get_waitlist_entry(wl_b["id"], make_member_headers(mem_b["id"])), 200)
    assert entry_after["queue_status"] == "PROMOTED"
    bk_a_after = validate_success(api.get_booking(bk_a["id"], make_member_headers(mem_a["id"])), 200)
    assert bk_a_after["refilled_from_waitlist"] is True
    session_after = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert session_after["confirmed_seats"] == 1, "seat refilled by the promoted booking"
    gc_b_after = validate_success(api.get_gift_card(gc_b["id"], make_member_headers(mem_b["id"])), 200)
    assert gc_b_after["balance_cents"] == 11000, (
        f"promoted booking's waterfall debited 9000 from the gift card, got {gc_b_after['balance_cents']}"
    )


def test_seat_capacity_aggregate_overlap_rejected(api):
    """PRD §3.5: "If confirmed_seats plus this booking's seats_requested would
    exceed planned_seats, the confirm is rejected with ERR_INSUFFICIENT_SEATS."

    planned_seats=3 already holding confirmed_seats=2; a 2-seat confirm pushes the
    aggregate to 4 > 3 and is rejected; confirmed_seats stays 2.

    Design: Difficulty/resource_temporal_overlap/seat_capacity_aggregate_overlap_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 3,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 3, "station_id": "ST-SEATAGG",
            "start_at": "2026-09-28T14:00:00Z", "end_at": "2026-09-28T16:00:00Z",
        },
        ingredient_overrides={"name": "s", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    mem_a = create_member()
    mem_b = create_member()
    create_confirmed_booking(session["id"], mem_a["id"], 2)  # confirmed_seats = 2
    bk_b = create_booking(session["id"], mem_b["id"], 2)
    sv = get_session_version(session["id"])
    res = api.confirm_booking(bk_b["id"], sv, make_member_headers(mem_b["id"]))
    validate_error(res, "ERR_INSUFFICIENT_SEATS", expected_status=409)
    session_after = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert session_after["confirmed_seats"] == 2, "unchanged after the rejected confirm"


def test_seat_capacity_exact_fit_confirms_at_boundary(api):
    """PRD §3.5: "the seat block fits" is a confirm precondition, and "If
    confirmed_seats plus this booking's seats_requested would exceed planned_seats,
    the confirm is rejected with ERR_INSUFFICIENT_SEATS."
    PRD §3.5: "If confirmed_seats reaches planned_seats exactly, the session
    automatically transitions OPEN -> FULL".

    The complementary boundary to the over-subscription rejection: with
    confirmed_seats=2 on planned_seats=3, a 1-seat confirm fits exactly (aggregate
    == 3), succeeds, and drives the session to FULL.

    Design: Difficulty/resource_temporal_overlap/seat_capacity_aggregate_overlap_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 3,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 3, "station_id": "ST-SEATFIT",
            "start_at": "2026-09-29T14:00:00Z", "end_at": "2026-09-29T16:00:00Z",
        },
        ingredient_overrides={"name": "s", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    mem_a = create_member()
    mem_b = create_member()
    create_confirmed_booking(session["id"], mem_a["id"], 2)  # confirmed_seats = 2
    bk_b = create_booking(session["id"], mem_b["id"], 1)
    sv = get_session_version(session["id"])
    confirmed = validate_success(api.confirm_booking(bk_b["id"], sv, make_member_headers(mem_b["id"])), 200)
    assert confirmed["lifecycle_status"] == "CONFIRMED"
    session_after = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert session_after["confirmed_seats"] == 3
    assert session_after["status"] == "FULL"


def test_promoted_waitlist_booking_is_confirmed_with_charge(api):
    """PRD §3.8: "the system creates a new CONFIRMED booking for that waiting
    member with their requested seats and a freshly computed charge ... marks the
    waitlist entry PROMOTED with its promoted_booking_id set to the new booking".

    A second witness on the depth-3 promotion cascade: the promoted entry's
    promoted_booking_id points to a CONFIRMED booking carrying the freshly computed
    INTERMEDIATE 1-seat charge (9000).

    Design: Difficulty/transitive_cascade/booking_cancel_promotes_waitlist_depth3
    """
    set_clock("2026-07-01T00:00:00Z")
    instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "INTERMEDIATE", "base_price_cents": 8500, "default_capacity": 1,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 1, "station_id": "ST-WL3B",
            "start_at": "2026-08-31T14:00:00Z", "end_at": "2026-08-31T16:00:00Z",
        },
        ingredient_overrides={"name": "butter", "qty_per_seat": 0.05, "unit_cost_cents": 400},
    )
    mem_a = create_member()
    mem_b = create_member()
    create_gift_card(mem_b["id"], 20000, code="GC-WL3B")
    bk_a = create_booking(session["id"], mem_a["id"], 1)
    confirm_booking(bk_a["id"], session["id"], mem_a["id"])
    wl_b = join_waitlist(session["id"], mem_b["id"], 1)

    validate_success(api.cancel_booking(bk_a["id"], make_member_headers(mem_a["id"])), 200)
    entry_after = validate_success(api.get_waitlist_entry(wl_b["id"], make_member_headers(mem_b["id"])), 200)
    assert entry_after["queue_status"] == "PROMOTED"
    promoted_booking_id = entry_after["promoted_booking_id"]
    assert promoted_booking_id is not None
    promoted = validate_success(api.get_booking(promoted_booking_id, make_member_headers(mem_b["id"])), 200)
    assert promoted["lifecycle_status"] == "CONFIRMED"
    assert promoted["member_id"] == mem_b["id"]
    assert promoted["charge_cents"] == 9000


def test_confirm_increments_session_version(api):
    """PRD §3.5: "On success the system runs the payment waterfall ... increments
    the session's confirmed_seats by seats_requested, refreshes the session's
    per-seat prep cost, and increments the session's version by one."

    A single confirm advances the session's version by exactly one (and
    confirmed_seats by the booked seat). The absolute version is not asserted
    because PRD §2.4 makes version "increment by one on every mutation of the
    resource", so the count after create/ingredient-add/open is not uniquely
    pinned; only the confirm delta of +1 is PRD-derivable.

    Design: Corner/cross_cutting_complexity_layers/occ_session_version_increments_on_confirm
    """
    set_clock("2026-07-01T00:00:00Z")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 3,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 3, "station_id": "ST-VINC",
            "start_at": "2026-11-27T14:00:00Z", "end_at": "2026-11-27T16:00:00Z",
        },
        ingredient_overrides={"name": "z", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    member = create_member()
    booking = create_booking(session["id"], member["id"], 1)
    before_version = get_session_version(session["id"])
    confirm_booking(booking["id"], session["id"], member["id"])
    after = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert after["version"] == before_version + 1, (
        f"version increments by one on confirm, got {after['version']} from {before_version}"
    )
    assert after["confirmed_seats"] == 1


def test_confirm_with_stale_session_version_rejected(api):
    """PRD §2.6: "If the session's current version no longer equals the supplied
    expected_session_version - because another writer has since confirmed or
    cancelled a booking and advanced the session - the confirm is rejected with
    ERR_STALE_SESSION_VERSION at HTTP status 412."

    Member A's confirm advances the session version; Member B's confirm carrying
    the now-stale earlier version is rejected; B's booking stays PENDING.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_session_version_rejected_on_confirm
    """
    set_clock("2026-07-01T00:00:00Z")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 3,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 3, "station_id": "ST-STALE",
            "start_at": "2026-11-28T14:00:00Z", "end_at": "2026-11-28T16:00:00Z",
        },
        ingredient_overrides={"name": "z", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    mem_a = create_member()
    mem_b = create_member()
    bk_a = create_booking(session["id"], mem_a["id"], 1)
    bk_b = create_booking(session["id"], mem_b["id"], 1)
    stale_v = get_session_version(session["id"])
    # A confirms with the fresh version, advancing the session.
    validate_success(api.confirm_booking(bk_a["id"], stale_v, make_member_headers(mem_a["id"])), 200)
    # B confirms with the now-stale version.
    res = api.confirm_booking(bk_b["id"], stale_v, make_member_headers(mem_b["id"]))
    validate_error(res, "ERR_STALE_SESSION_VERSION", expected_status=412)
    bk_b_after = validate_success(api.get_booking(bk_b["id"], make_member_headers(mem_b["id"])), 200)
    assert bk_b_after["lifecycle_status"] == "PENDING"


def test_confirmed_seats_reconciles_after_cancel(api):
    """PRD §3.7: "the session's confirmed_seats is decremented by seats_requested,
    the per-seat prep cost is refreshed, and the session's version is
    incremented."

    confirmed_seats is 2 after a 2-seat confirm and reconciles to 0 after that
    booking cancels with an empty waitlist.

    Design: Corner/cross_cutting_complexity_layers/derived_confirmed_seats_reconciled_after_cancel
    """
    set_clock("2026-07-01T00:00:00Z")
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 4,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={
            "planned_seats": 4, "station_id": "ST-RECON",
            "start_at": "2026-12-01T14:00:00Z", "end_at": "2026-12-01T16:00:00Z",
        },
        ingredient_overrides={"name": "z", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    member = create_member()
    booking = create_booking(session["id"], member["id"], 2)
    confirm_booking(booking["id"], session["id"], member["id"])
    after_confirm = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert after_confirm["confirmed_seats"] == 2

    validate_success(api.cancel_booking(booking["id"], make_member_headers(member["id"])), 200)
    after_cancel = validate_success(api.get_session(session["id"], ADMIN), 200)
    assert after_cancel["confirmed_seats"] == 0


def test_waitlist_join_on_non_full_session_rejected(api):
    """PRD §3.8: "A join is permitted only when the session's status is FULL and
    the joining member has neither an existing WAITING entry nor a CONFIRMED
    booking on that same session; any other case is rejected with
    ERR_WAITLIST_NOT_ALLOWED."

    Joining the waitlist of an OPEN (not FULL) session is rejected
    ERR_WAITLIST_NOT_ALLOWED.

    Design: Corner/validations/waitlist_join_on_non_full_session_rejected
    """
    _instr, _tmpl, session = create_open_session(
        template_overrides={
            "skill_level": "BEGINNER", "base_price_cents": 5000, "default_capacity": 4,
            "station_fixed_cost_cents": 1000,
        },
        session_overrides={"planned_seats": 4, "station_id": "ST-WLJOIN"},
        ingredient_overrides={"name": "w", "qty_per_seat": 1, "unit_cost_cents": 1},
    )
    member = create_member()
    res = api.join_waitlist(
        session["id"], {"member_id": member["id"], "seats_requested": 1},
        make_member_headers(member["id"]),
    )
    validate_error(res, "ERR_WAITLIST_NOT_ALLOWED", expected_status=409)
