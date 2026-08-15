"""Trip confirmation: input validation, state guards, blackout/SLA ordering, denials."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_trip,
    create_aircraft,
    create_blackout_window,
    create_trip,
    dispatch_trip,
    fly_trip,
    get_card,
    get_trip,
    make_member_headers,
    setup_active_card,
    suspend_card,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]


def test_invalid_return_time_round_trip(api):
    """PRD §3.4: "Round-trip requests additionally carry `requested_return_utc`, which
    must be strictly after `requested_departure_utc`; a return time at or before the
    outbound departure is rejected with `ERR_INVALID_RETURN_TIME` (HTTP 422)."

    Design: Corner/validations/invalid_return_time_round_trip
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "VAL1"})
    mh = make_member_headers(member["id"])
    resp = api.create_trip(
        card["id"],
        {
            "trip_kind": "ROUND_TRIP",
            "departure_icao": "KTEB",
            "arrival_icao": "KPBI",
            "requested_departure_utc": "2026-06-15T15:00:00Z",
            "requested_return_utc": "2026-06-15T14:00:00Z",
            "pax_count": 4,
            "requested_category": "LIGHT",
        },
        mh,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_RETURN_TIME, expected_status=422)


def test_confirm_from_dispatched_invalid_state(api):
    """PRD §3.5: "Confirmation is a member-only action on a trip in `QUOTE`."
    PRD §2.11: "Only after all four pass do state guards run — card-active
    (`ERR_CARD_NOT_ACTIVE`), member-active (`ERR_MEMBER_NOT_ACTIVE`), and from-state
    validity (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/trip_invalid_from_state_confirm_from_dispatched
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "SM1"})
    aircraft = create_aircraft(tail_number="N111LT")
    trip = create_trip(card["id"], member["id"])
    confirm_trip(trip["id"], member["id"])
    dispatch_trip(trip["id"], aircraft["id"])
    mh = make_member_headers(member["id"])
    resp = api.confirm_trip(trip["id"], mh)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_confirm_suspended_card_yields_card_not_active(api):
    """PRD §3.5: "Four preconditions stand between `QUOTE` and `CONFIRMED`, and they
    interact with the global validation order such that state and temporal guards surface
    before fiscal ones: the card must be `ACTIVE` (`ERR_CARD_NOT_ACTIVE`), the member must
    be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`), the requested departure must not intersect any
    `BlackoutWindow` whose `applies_to_category` matches the trip's `requested_category`
    (`ERR_BLACKOUT_PERIOD`, HTTP 422), and the card's `hours_remaining` must be at least
    the trip's `quoted_hours` (`ERR_INSUFFICIENT_HOURS`, HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_confirm
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "PRIO1"})
    trip = create_trip(card["id"], member["id"])
    suspend_card(card["id"])
    mh = make_member_headers(member["id"])
    resp = api.confirm_trip(trip["id"], mh)
    validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE, expected_status=409)


def test_confirm_suspended_card_with_low_hours_still_card_not_active(api):
    """PRD §3.5: "Four preconditions stand between `QUOTE` and `CONFIRMED`, and they
    interact with the global validation order such that state and temporal guards surface
    before fiscal ones: the card must be `ACTIVE` (`ERR_CARD_NOT_ACTIVE`), the member must
    be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`), the requested departure must not intersect any
    `BlackoutWindow` whose `applies_to_category` matches the trip's `requested_category`
    (`ERR_BLACKOUT_PERIOD`, HTTP 422), and the card's `hours_remaining` must be at least
    the trip's `quoted_hours` (`ERR_INSUFFICIENT_HOURS`, HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_confirm
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "PRIO1B"})
    aircraft = create_aircraft(tail_number="N411LT")
    # Drain 24.00 hours (1428 block + 12 taxi = 1440 min) so the fiscal guard also fails.
    fly_trip(
        card["id"], member["id"], aircraft["id"], block_minutes=1428,
        trip_overrides={
            "departure_icao": "KTEB",
            "arrival_icao": "KDEN",
            "requested_departure_utc": "2026-06-05T15:00:00Z",
        },
    )
    remaining = get_card(card["id"])["hours_remaining"]
    assert remaining == pytest.approx(1.0, abs=0.005)
    # Fresh quote on the depleted card; then suspend. Both guards could fire —
    # the card-state guard must surface.
    trip = create_trip(card["id"], member["id"])
    suspend_card(card["id"])
    mh = make_member_headers(member["id"])
    resp = api.confirm_trip(trip["id"], mh)
    validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE, expected_status=409)


def test_confirm_blackout_with_low_hours_yields_blackout(api):
    """PRD §3.5: "Four preconditions stand between `QUOTE` and `CONFIRMED`, and they
    interact with the global validation order such that state and temporal guards surface
    before fiscal ones: the card must be `ACTIVE` (`ERR_CARD_NOT_ACTIVE`), the member must
    be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`), the requested departure must not intersect any
    `BlackoutWindow` whose `applies_to_category` matches the trip's `requested_category`
    (`ERR_BLACKOUT_PERIOD`, HTTP 422), and the card's `hours_remaining` must be at least
    the trip's `quoted_hours` (`ERR_INSUFFICIENT_HOURS`, HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_confirm
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "PRIO2"})
    create_blackout_window(
        card["program_id"],
        window_start_utc="2026-06-10T00:00:00Z",
        window_end_utc="2026-06-20T00:00:00Z",
        applies_to_category="LIGHT",
        reason="Maintenance",
    )
    aircraft = create_aircraft(tail_number="N500LT")
    # Drain the card to 1.00 hour so the fiscal guard also fails on the next trip.
    fly_trip(
        card["id"], member["id"], aircraft["id"], block_minutes=1428,
        trip_overrides={
            "departure_icao": "KTEB",
            "arrival_icao": "KDEN",
            "requested_departure_utc": "2026-06-05T15:00:00Z",
        },
    )
    trip = create_trip(card["id"], member["id"],
                       requested_departure_utc="2026-06-15T15:00:00Z")
    mh = make_member_headers(member["id"])
    resp = api.confirm_trip(trip["id"], mh)
    validate_error(resp, ApiErrorId.ERR_BLACKOUT_PERIOD, expected_status=422)


def test_confirm_blackout_denies_trip_with_reason(api):
    """PRD §3.5: "When any precondition fails, the trip does not simply error out — it
    transitions from `QUOTE` to `DENIED`, with `denial_reason` set to the class of the
    failed check: `INSUFFICIENT_HOURS`, `BLACKOUT`, `AVAILABILITY_WINDOW`, or
    `PEAK_RESTRICTED`. A denied trip is terminal."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_confirm
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "PRIO2B"})
    create_blackout_window(
        card["program_id"],
        window_start_utc="2026-06-10T00:00:00Z",
        window_end_utc="2026-06-20T00:00:00Z",
        applies_to_category="LIGHT",
        reason="Maintenance",
    )
    aircraft = create_aircraft(tail_number="N501LT")
    fly_trip(
        card["id"], member["id"], aircraft["id"], block_minutes=1428,
        trip_overrides={
            "departure_icao": "KTEB",
            "arrival_icao": "KDEN",
            "requested_departure_utc": "2026-06-05T15:00:00Z",
        },
    )
    trip = create_trip(card["id"], member["id"],
                       requested_departure_utc="2026-06-15T15:00:00Z")
    mh = make_member_headers(member["id"])
    api.confirm_trip(trip["id"], mh)
    after = get_trip(trip["id"])
    assert after["trip_status"] == "DENIED", (
        f"failed confirm must transition the trip to DENIED, got {after['trip_status']}"
    )
    assert after["denial_reason"] == "BLACKOUT", (
        f"denial_reason must be BLACKOUT (temporal guard surfaces before fiscal), "
        f"got {after['denial_reason']}"
    )


def test_confirm_on_suspended_card_rejected(api):
    """PRD §3.5: "the card must be `ACTIVE` (`ERR_CARD_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/trip_confirm_requires_card_active
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "XDEP1"})
    trip = create_trip(card["id"], member["id"])
    suspend_card(card["id"])
    mh = make_member_headers(member["id"])
    resp = api.confirm_trip(trip["id"], mh)
    validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE, expected_status=409)


def test_blackout_window_denies_intersecting_trip(api):
    """PRD §3.5: "the requested departure must not intersect any `BlackoutWindow` whose
    `applies_to_category` matches the trip's `requested_category` (`ERR_BLACKOUT_PERIOD`,
    HTTP 422)" and "it transitions from `QUOTE` to `DENIED`, with `denial_reason` set to
    the class of the failed check".
    PRD §3.1: "A `PeakCalendar` window is defined by `window_start_utc` (inclusive) and
    `window_end_utc` (exclusive)"; "A `BlackoutWindow` carries the same start and end
    fields plus `applies_to_category`".

    Design: Difficulty/resource_temporal_overlap/blackout_window_blocks_trip_departure
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "OVL1"})
    create_blackout_window(
        card["program_id"],
        window_start_utc="2026-07-01T00:00:00Z",
        window_end_utc="2026-07-10T00:00:00Z",
        applies_to_category="LIGHT",
        reason="Maintenance",
    )
    trip = create_trip(card["id"], member["id"],
                       requested_departure_utc="2026-07-05T15:00:00Z")
    mh = make_member_headers(member["id"])
    resp = api.confirm_trip(trip["id"], mh)
    validate_error(resp, ApiErrorId.ERR_BLACKOUT_PERIOD, expected_status=422)
    after = get_trip(trip["id"])
    assert after["trip_status"] == "DENIED"
    assert after["denial_reason"] == "BLACKOUT"


def test_blackout_window_end_boundary_allows_trip(api):
    """PRD §3.1: "A `PeakCalendar` window is defined by `window_start_utc` (inclusive) and
    `window_end_utc` (exclusive)"; "A `BlackoutWindow` carries the same start and end
    fields". A departure exactly at `window_end_utc` lies outside the half-open window.
    PRD §3.5: "When every precondition holds, the trip transitions to `CONFIRMED` and its
    `version` increments."

    Design: Difficulty/resource_temporal_overlap/blackout_window_blocks_trip_departure
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "OVL1B"})
    create_blackout_window(
        card["program_id"],
        window_start_utc="2026-07-01T00:00:00Z",
        window_end_utc="2026-07-10T00:00:00Z",
        applies_to_category="LIGHT",
        reason="Maintenance",
    )
    trip = create_trip(card["id"], member["id"],
                       requested_departure_utc="2026-07-10T00:00:00Z")
    mh = make_member_headers(member["id"])
    resp = api.confirm_trip(trip["id"], mh)
    data = validate_success(resp, expected_status=200)
    assert data["trip_status"] == "CONFIRMED", (
        f"departure at the exclusive window end must confirm, got {data['trip_status']}"
    )
