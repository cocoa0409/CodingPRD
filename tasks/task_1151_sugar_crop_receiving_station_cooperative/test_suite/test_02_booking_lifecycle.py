"""Booking lifecycle: initial state, campaign/member gates, slot overlap,
capacity boundary and waitlist promotion, confirm/cancel conservation, and the
campaign-close cascade."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    SLOT_AM_END,
    SLOT_AM_START,
    SLOT_PM_END,
    SLOT_PM_START,
    WEIGH_CLOCK_AM,
    accept_ticket,
    add_verified_lab_sample,
    assert_booking,
    create_booking_payload,
    create_campaign,
    create_confirmed_booking,
    create_member,
    create_requested_booking,
    create_station,
    create_weighed_ticket,
    get_success_data,
    make_accepted_ticket,
    make_member_headers,
    setup_world,
    suspend_member,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_booking_initial_state_requested(api):
    """PRD §3.2: "A new booking enters `REQUESTED` status."

    Design: Corner/state_machines/booking_initial_state_requested
    """
    world = setup_world(with_pile=False)
    booking = create_requested_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        slot_start=SLOT_AM_START, slot_end=SLOT_AM_END, estimated_tons=20)
    assert_booking(booking)
    assert booking["status"] == "REQUESTED"
    assert booking["member_id"] == world["member"]["id"]


def test_booking_create_after_campaign_close_returns_campaign_not_open(api):
    """PRD §3.2: "Booking creation requires the member to be `ACTIVE` — a
    suspended member's attempt is rejected with `ERR_MEMBER_SUSPENDED` — and the
    target campaign to be `OPEN`, otherwise `ERR_CAMPAIGN_NOT_OPEN`."

    Design: Corner/validations/booking_create_after_campaign_close_returns_campaign_not_open
    """
    campaign = create_campaign()
    member = create_member()
    station = create_station()
    validate_success(api.close_campaign(campaign["id"], ADMIN), 200)
    res = api.create_booking(
        create_booking_payload(campaign["id"], station["id"],
                               slot_start=SLOT_AM_START, slot_end=SLOT_AM_END,
                               estimated_tons=20),
        make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN.value)


def test_suspended_member_booking_create_single_failure(api):
    """PRD §3.2: "Booking creation requires the member to be `ACTIVE` — a
    suspended member's attempt is rejected with `ERR_MEMBER_SUSPENDED` — and the
    target campaign to be `OPEN`, otherwise `ERR_CAMPAIGN_NOT_OPEN`."

    Design: Corner/validations/suspended_member_booking_create_single_failure
    """
    campaign = create_campaign()
    member = create_member()
    suspended = suspend_member(member["id"])
    assert suspended["status"] == "SUSPENDED"
    station = create_station()
    res = api.create_booking(
        create_booking_payload(campaign["id"], station["id"],
                               slot_start=SLOT_AM_START, slot_end=SLOT_AM_END,
                               estimated_tons=20),
        make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_MEMBER_SUSPENDED.value)


def test_suspended_member_booking_create_beats_slot_window(api):
    """PRD §2.7: "Incoming requests are validated in a fixed priority order, so
    that when several problems afflict the same request, the earliest check
    determines the error surfaced." and "member-compliance checks seventh
    (`ERR_MEMBER_SUSPENDED`), temporal-window checks eighth (`ERR_SLOT_OUTSIDE_WINDOW`,
    `ERR_WEIGH_WINDOW_CLOSED`, `ERR_SLOT_OVERLAP`, `ERR_SURVEY_BLACKOUT`)".

    Design: Difficulty/priority_pair_validation_conflict/booking_suspended_member_beats_slot_window
    """
    campaign = create_campaign()
    member = create_member()
    station = create_station()
    suspend_member(member["id"])
    # Slot lies outside the campaign window AND the member is suspended.
    res = api.create_booking(
        create_booking_payload(campaign["id"], station["id"],
                               slot_start="2027-01-10T08:00:00Z",
                               slot_end="2027-01-10T10:00:00Z",
                               estimated_tons=20),
        make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_MEMBER_SUSPENDED.value)


def test_suspended_member_booking_create_in_window_also_rejected(api):
    """PRD §3.2: "Booking creation requires the member to be `ACTIVE` — a
    suspended member's attempt is rejected with `ERR_MEMBER_SUSPENDED`".
    PRD §2.7: "member-compliance checks seventh (`ERR_MEMBER_SUSPENDED`)".

    Design: Difficulty/priority_pair_validation_conflict/booking_suspended_member_beats_slot_window
    """
    campaign = create_campaign()
    member = create_member()
    station = create_station()
    suspend_member(member["id"])
    # In-window slot: only the member-compliance check can fire.
    res = api.create_booking(
        create_booking_payload(campaign["id"], station["id"],
                               slot_start=SLOT_AM_START, slot_end=SLOT_AM_END,
                               estimated_tons=20),
        make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_MEMBER_SUSPENDED.value)


def test_station_capacity_exactly_full_confirms(api, scheduler_headers):
    """PRD §3.2: "if the station's `booked_tons` plus the booking's
    `estimated_tons` would exceed `booking_capacity_tons` — equality is allowed
    and confirms — the booking transitions to `WAITLISTED` instead of
    `CONFIRMED`, incrementing the booking's `version` by 1."

    Design: Difficulty/boundary_precision_check/station_capacity_exactly_full_boundary
    """
    world = setup_world(with_pile=False, station_capacity_tons=100)
    camp_id, st_id, m_id = (world["campaign"]["id"], world["station"]["id"],
                            world["member"]["id"])
    create_confirmed_booking(camp_id, st_id, m_id, SLOT_AM_START, SLOT_AM_END, 30)
    create_confirmed_booking(camp_id, st_id, m_id, SLOT_PM_START, SLOT_PM_END, 20)
    bc = create_requested_booking(camp_id, st_id, m_id,
                                  "2026-10-01T12:00:00Z", "2026-10-01T14:00:00Z", 50)
    confirmed = validate_success(api.confirm_booking(bc["id"], scheduler_headers), 200)
    assert confirmed["status"] == "CONFIRMED"  # 50 + 50 == 100: equality allowed
    station = validate_success(api.get_station(st_id, scheduler_headers), 200)
    assert station["booked_tons"] == 100.0


def test_station_capacity_one_hundredth_over_routes_to_waitlist(api, scheduler_headers):
    """PRD §3.2: "if the station's `booked_tons` plus the booking's
    `estimated_tons` would exceed `booking_capacity_tons` — equality is allowed
    and confirms — the booking transitions to `WAITLISTED` instead of
    `CONFIRMED`, incrementing the booking's `version` by 1."

    Design: Difficulty/boundary_precision_check/station_capacity_exactly_full_boundary
    """
    world = setup_world(with_pile=False, station_capacity_tons=100)
    camp_id, st_id, m_id = (world["campaign"]["id"], world["station"]["id"],
                            world["member"]["id"])
    create_confirmed_booking(camp_id, st_id, m_id, SLOT_AM_START, SLOT_AM_END, 30)
    create_confirmed_booking(camp_id, st_id, m_id, SLOT_PM_START, SLOT_PM_END, 20)
    create_confirmed_booking(camp_id, st_id, m_id,
                             "2026-10-01T12:00:00Z", "2026-10-01T14:00:00Z", 50)
    bd = create_requested_booking(camp_id, st_id, m_id,
                                  "2026-10-01T14:00:00Z", "2026-10-01T16:00:00Z", 0.01)
    res = validate_success(api.confirm_booking(bd["id"], scheduler_headers), 200)
    assert res["status"] == "WAITLISTED"  # 100 + 0.01 > 100: capacity overflow
    station = validate_success(api.get_station(st_id, scheduler_headers), 200)
    assert station["booked_tons"] == 100.0


def test_station_slot_overlap_rejected(api, scheduler_headers):
    """PRD §3.2: "the slot must not overlap any other `CONFIRMED` booking at the
    same station, where overlap is judged on half-open intervals — two slots
    overlap only if the new slot starts before the other's end and the other
    starts before the new slot's end, and mere adjacency (one slot's `slot_start`
    equal to the other's `slot_end`) is not overlap (`ERR_SLOT_OVERLAP`)".

    Design: Difficulty/resource_temporal_overlap/station_slot_half_open_adjacency_vs_overlap
    """
    world = setup_world(with_pile=False, station_capacity_tons=1000)
    camp_id, st_id, m_id = (world["campaign"]["id"], world["station"]["id"],
                            world["member"]["id"])
    create_confirmed_booking(camp_id, st_id, m_id, SLOT_AM_START, SLOT_AM_END, 20)
    bb = create_requested_booking(camp_id, st_id, m_id,
                                  "2026-10-01T09:30:00Z", "2026-10-01T10:30:00Z", 20)
    res = api.confirm_booking(bb["id"], scheduler_headers)
    validate_error(res, ApiErrorId.ERR_SLOT_OVERLAP.value)


def test_station_slot_adjacency_confirms(api, scheduler_headers):
    """PRD §3.2: "mere adjacency (one slot's `slot_start` equal to the other's
    `slot_end`) is not overlap (`ERR_SLOT_OVERLAP`)".

    Design: Difficulty/resource_temporal_overlap/station_slot_half_open_adjacency_vs_overlap
    """
    world = setup_world(with_pile=False, station_capacity_tons=1000)
    camp_id, st_id, m_id = (world["campaign"]["id"], world["station"]["id"],
                            world["member"]["id"])
    create_confirmed_booking(camp_id, st_id, m_id, SLOT_AM_START, SLOT_AM_END, 20)
    bc = create_requested_booking(camp_id, st_id, m_id,
                                  "2026-10-01T10:00:00Z", "2026-10-01T11:00:00Z", 20)
    confirmed = validate_success(api.confirm_booking(bc["id"], scheduler_headers), 200)
    assert confirmed["status"] == "CONFIRMED"


def test_booking_confirm_reserves_bookable_tons(api, scheduler_headers):
    """PRD §3.2: "When capacity does fit, the booking becomes `CONFIRMED`, the
    station's `booked_tons` increases by `estimated_tons`, and both the booking's
    `version` and the station's `version` increment by 1."
    PRD §2.8: "A station's `booked_tons` is the sum of `estimated_tons` over its
    bookings currently in `CONFIRMED` status."

    Design: Difficulty/compensating_invariant/booking_confirm_then_cancel_conserves_bookable_tons
    """
    world = setup_world(with_pile=False, station_capacity_tons=100)
    booking = create_requested_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 40)
    confirmed = validate_success(api.confirm_booking(booking["id"], scheduler_headers), 200)
    assert confirmed["status"] == "CONFIRMED"
    station = validate_success(api.get_station(world["station"]["id"], scheduler_headers), 200)
    assert station["booked_tons"] == 40.0


def test_booking_cancel_restores_bookable_tons(api, scheduler_headers):
    """PRD §3.2: "cancelling a `CONFIRMED` booking releases its `estimated_tons`
    from `booked_tons` and triggers a waitlist promotion scan at that station".

    Design: Difficulty/compensating_invariant/booking_confirm_then_cancel_conserves_bookable_tons
    """
    world = setup_world(with_pile=False, station_capacity_tons=100)
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 40)
    cancelled = validate_success(api.cancel_booking(booking["id"], scheduler_headers), 200)
    assert cancelled["status"] == "CANCELLED"
    station = validate_success(api.get_station(world["station"]["id"], scheduler_headers), 200)
    assert station["booked_tons"] == 0.0


def test_waitlist_booking_waits_while_capacity_full(api, scheduler_headers):
    """PRD §3.2: "if the station's `booked_tons` plus the booking's
    `estimated_tons` would exceed `booking_capacity_tons` — equality is allowed
    and confirms — the booking transitions to `WAITLISTED` instead of `CONFIRMED`".

    Design: Difficulty/transitive_cascade/booking_cancel_releases_capacity_promotes_waitlist
    """
    world = setup_world(with_pile=False, station_capacity_tons=60)
    camp_id, st_id = world["campaign"]["id"], world["station"]["id"]
    m1 = world["member"]
    m2 = create_member(name="M2", member_code="M-1002", haul_distance_miles=12.0)
    m3 = create_member(name="M3", member_code="M-1003", haul_distance_miles=85.0)
    create_confirmed_booking(camp_id, st_id, m1["id"],
                             SLOT_AM_START, SLOT_AM_END, 30)
    bb = create_confirmed_booking(camp_id, st_id, m2["id"],
                                  SLOT_PM_START, SLOT_PM_END, 30)
    assert bb["status"] == "CONFIRMED"
    bc = create_requested_booking(camp_id, st_id, m3["id"],
                                  "2026-10-01T12:00:00Z", "2026-10-01T14:00:00Z", 30)
    res = validate_success(api.confirm_booking(bc["id"], scheduler_headers), 200)
    assert res["status"] == "WAITLISTED"
    station = validate_success(api.get_station(st_id, scheduler_headers), 200)
    assert station["booked_tons"] == 60.0


def test_confirmed_cancel_promotes_waitlist_and_restores_tons(api, scheduler_headers):
    """PRD §3.2: "cancelling a `CONFIRMED` booking releases its `estimated_tons`
    from `booked_tons` and triggers a waitlist promotion scan at that station"
    and "The top-ranked eligible booking is promoted to `CONFIRMED`, the
    station's `booked_tons` increases by its `estimated_tons`, both resources'
    `version` counters increment, and then eligibility is re-evaluated with the
    updated `booked_tons`".

    Design: Difficulty/transitive_cascade/booking_cancel_releases_capacity_promotes_waitlist
    """
    world = setup_world(with_pile=False, station_capacity_tons=60)
    camp_id, st_id = world["campaign"]["id"], world["station"]["id"]
    m1 = world["member"]
    m2 = create_member(name="M2", member_code="M-1002", haul_distance_miles=12.0)
    m3 = create_member(name="M3", member_code="M-1003", haul_distance_miles=85.0)
    create_confirmed_booking(camp_id, st_id, m1["id"], SLOT_AM_START, SLOT_AM_END, 30)
    bb = create_confirmed_booking(camp_id, st_id, m2["id"], SLOT_PM_START, SLOT_PM_END, 30)
    bc = create_requested_booking(camp_id, st_id, m3["id"],
                                  "2026-10-01T12:00:00Z", "2026-10-01T14:00:00Z", 30)
    get_success_data(api.confirm_booking(bc["id"], scheduler_headers))

    validate_success(api.cancel_booking(bb["id"], scheduler_headers), 200)
    bc_after = validate_success(api.get_booking(bc["id"], scheduler_headers), 200)
    assert bc_after["status"] == "CONFIRMED"  # promoted by the released capacity
    station = validate_success(api.get_station(st_id, scheduler_headers), 200)
    assert station["booked_tons"] == 60.0  # 60 -> 30 -> 60


def test_campaign_close_cancels_only_non_terminal_bookings(api, scheduler_headers):
    """PRD §3.1: "When the close succeeds, every booking of the campaign still
    sitting in `REQUESTED` or `WAITLISTED` is cancelled as a cascade, while
    bookings already `COMPLETED` are untouched, and the campaign's `version`
    increments by 1."

    Design: Corner/state_machines/campaign_close_cancels_only_non_terminal_bookings
    """
    world = setup_world()
    b1 = create_confirmed_booking(world["campaign"]["id"], world["station"]["id"],
                                  world["member"]["id"],
                                  SLOT_AM_START, SLOT_AM_END, 20)
    make_accepted_ticket(b1["id"], world["pile"]["id"], gross_weight_lbs=72000,
                         tare_weight_lbs=32000, clock=WEIGH_CLOCK_AM,
                         sugar_pct=16.00, trash_pct=2.00)
    b2 = create_requested_booking(world["campaign"]["id"], world["station"]["id"],
                                  world["member"]["id"],
                                  "2026-10-02T08:00:00Z", "2026-10-02T10:00:00Z", 20)
    campaign = validate_success(
        api.close_campaign(world["campaign"]["id"], ADMIN), 200)
    assert campaign["status"] == "CLOSED"
    b1_after = validate_success(api.get_booking(b1["id"], scheduler_headers), 200)
    assert b1_after["status"] == "COMPLETED"
    b2_after = validate_success(api.get_booking(b2["id"], scheduler_headers), 200)
    assert b2_after["status"] == "CANCELLED"


def test_booking_auto_in_use_then_completed(api, scheduler_headers):
    """PRD §3.2: "When the first load ticket for a booking is weighed, the
    booking moves from `CONFIRMED` to `IN_USE`. When a load ticket for an
    `IN_USE` booking is accepted into a pile, the booking completes: it moves to
    `COMPLETED`, its `estimated_tons` are released from `booked_tons` (the slot
    is considered consumed), the waitlist promotion scan runs for the station,
    and both the booking's and the station's `version` increment."

    Design: Corner/state_machines/booking_auto_in_use_then_completed
    """
    world = setup_world(station_capacity_tons=100)
    booking = create_confirmed_booking(world["campaign"]["id"], world["station"]["id"],
                                       world["member"]["id"],
                                       SLOT_AM_START, SLOT_AM_END, 25)
    create_weighed_ticket(booking["id"], 72000, 32000, WEIGH_CLOCK_AM)
    mid = validate_success(api.get_booking(booking["id"], scheduler_headers), 200)
    assert mid["status"] == "IN_USE"

    # Finish the accept path on the weighed ticket.
    ticket = get_success_data(api.list_tickets(
        scheduler_headers, params={"booking_id": booking["id"]}))[0]
    add_verified_lab_sample(ticket["id"], 16.10, 4.40)
    accept_ticket(ticket["id"], world["pile"]["id"])

    end = validate_success(api.get_booking(booking["id"], scheduler_headers), 200)
    assert end["status"] == "COMPLETED"
    station = validate_success(api.get_station(world["station"]["id"], scheduler_headers), 200)
    assert station["booked_tons"] == 0.0
    # net 40000 lbs = 20.0 t; trash 4.40 -> deducted 1.40%; 20.0 x 0.986 = 19.7200
    assert station["received_tons"] == pytest.approx(19.72, abs=1e-9)
