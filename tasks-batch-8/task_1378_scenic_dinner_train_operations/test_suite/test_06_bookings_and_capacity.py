"""Booking sales: publish gate, conservative capacity vs committed read, seat
conservation, party-size and dining_service shape rules, FK integrity, check-in gate
(PRD §3.4, §3.5, §3.6)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_booking,
    confirm_booking,
    create_booking_payload,
    create_confirmed_booking,
    create_held_booking,
    get_booking,
    get_excursion,
    is_iso8601_timestamp,
    publish_excursion,
    set_clock,
    setup_draft_excursion,
    setup_published_excursion,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import COACH_SPEC, DINING_SPEC, LOCO_SPEC


class TestCommittedVsConservativeSeats:
    """The excursion read exposes the committed variant (excludes HELD); the
    booking-create gate uses the conservative variant (includes unexpired HELD)."""

    def _setup(self):
        scenario = setup_published_excursion(
            car_specs=[LOCO_SPEC, ("COACH-S", "COACH_CAR", 3, 0, "COACH")])
        return scenario["excursion"]

    def test_committed_read_excludes_held_booking(self, api, station_agent_headers):
        """PRD §3.4: "Each is the sum of `effective_capacity` over the consist's
        assignments of that class minus the party sizes of that class's bookings in
        `CONFIRMED` or `CHECKED_IN` status. `HELD` bookings are deliberately excluded
        from this read view — a shopper browsing the excursion sees seats that held
        bookings may still consume, which is why the stricter gate of §3.5 exists at
        sale time."

        Design: Difficulty/dual_variant_calc/seats_availability_committed_vs_conservative_gate
        """
        excursion = self._setup()
        held = create_held_booking(excursion["id"], "held@x.com", "COACH", 2)

        read = get_excursion(excursion["id"])
        assert read["coach_seats_available"] == 3, (
            "committed variant excludes the unexpired HELD party of 2")

        held_after = get_booking(held["id"])
        assert held_after["status"] == "HELD", "the read itself changes nothing"

    def test_conservative_gate_rejects_when_read_shows_open_seats(self, api, station_agent_headers):
        """PRD §3.5: "Before a hold is even written, the conservative capacity gate runs:
        the class's capacity — summed `effective_capacity` of the consist's assignments
        in that class — must cover not only the `CONFIRMED` and `CHECKED_IN` bookings but
        also every unexpired `HELD` booking of that class, plus the new party. If the
        party does not fit, the sale is rejected with `ERR_CLASS_FULL` — and because the
        read fields of §3.4 exclude holds, this gate can reject even while the excursion
        still shows open seats."

        Design: Difficulty/dual_variant_calc/seats_availability_committed_vs_conservative_gate
        """
        excursion = self._setup()
        held = create_held_booking(excursion["id"], "held@x.com", "COACH", 2)

        # The committed read still shows 3 open seats at the exact moment the
        # conservative gate (3 - 2 held = 1 free < 2 requested) rejects the sale.
        read = get_excursion(excursion["id"])
        assert read["coach_seats_available"] == 3

        res = api.create_booking(
            create_booking_payload(excursion["id"], "late@x.com", "COACH", 2),
            station_agent_headers)
        validate_error(res, ApiErrorId.ERR_CLASS_FULL.value, expected_status=409)

        held_after = get_booking(held["id"])
        assert held_after["status"] == "HELD"

    def test_conservative_gate_counts_only_unexpired_holds(self, api, station_agent_headers):
        """PRD §3.5: "Before a hold is even written, the conservative capacity gate runs:
        the class's capacity — summed `effective_capacity` of the consist's assignments
        in that class — must cover not only the `CONFIRMED` and `CHECKED_IN` bookings but
        also every unexpired `HELD` booking of that class, plus the new party."
        PRD §2.5: "First, bookings still in `HELD` whose `expires_at` is at or before the
        new clock instant are swept to `CANCELLED` with no refund, processed earliest
        `expires_at` first."

        Design: Difficulty/dual_variant_calc/seats_availability_committed_vs_conservative_gate
        """
        excursion = self._setup()
        held = create_held_booking(excursion["id"], "held@x.com", "COACH", 2)

        # Once the clock sweeps the expired hold, the same party-of-2 sale fits (2 <= 3).
        set_clock("2026-08-01T00:46:00Z")
        swept = get_booking(held["id"])
        assert swept["status"] == "CANCELLED"

        res = api.create_booking(
            create_booking_payload(excursion["id"], "late@x.com", "COACH", 2),
            station_agent_headers)
        booking = validate_success(res, 201)
        assert booking["status"] == "HELD"


class TestBookingRequiresPublishedExcursion:
    """Booking -> Excursion state dependency."""

    def test_booking_create_on_draft_rejected(self, api, station_agent_headers):
        """PRD §3.5: "A `StationAgent` sells against a `PUBLISHED` excursion — any other
        excursion state is `ERR_EXCURSION_NOT_BOOKABLE`."

        Design: Difficulty/cross_entity_state_dependency/booking_create_requires_published_excursion
        """
        scenario = setup_draft_excursion()
        excursion = scenario["excursion"]
        assert excursion["status"] == "DRAFT"

        res = api.create_booking(
            create_booking_payload(excursion["id"], "e1@x.com", "COACH", 1),
            station_agent_headers)
        validate_error(res, ApiErrorId.ERR_EXCURSION_NOT_BOOKABLE.value, expected_status=409)
        after = get_excursion(excursion["id"])
        assert after["status"] == "DRAFT"

    def test_booking_create_succeeds_once_published(self, api, station_agent_headers):
        """PRD §3.5: "A `StationAgent` sells against a `PUBLISHED` excursion — any other
        excursion state is `ERR_EXCURSION_NOT_BOOKABLE`."
        PRD §2.5: "A freshly created booking's hold lasts 45 minutes: its `expires_at` is
        its `created_at` plus 45 minutes."

        Design: Difficulty/cross_entity_state_dependency/booking_create_requires_published_excursion
        """
        scenario = setup_draft_excursion()
        published = publish_excursion(scenario["excursion"]["id"])
        assert published["status"] == "PUBLISHED"

        res = api.create_booking(
            create_booking_payload(published["id"], "e1@x.com", "COACH", 1),
            station_agent_headers)
        booking = validate_success(res, 201)
        assert_booking(booking)
        assert booking["status"] == "HELD"
        assert is_iso8601_timestamp(booking["expires_at"]), "45-minute hold expiry stamped"


class TestSeatCountConservation:
    """Confirm paired with its compensating cancel conserves committed seat counts."""

    def _setup(self):
        scenario = setup_published_excursion(
            car_specs=[LOCO_SPEC, ("COACH-5", "COACH_CAR", 5, 0, "COACH")])
        return scenario["excursion"]

    def test_confirm_consumes_committed_seats(self, api, station_agent_headers):
        """PRD §3.4: "Each is the sum of `effective_capacity` over the consist's
        assignments of that class minus the party sizes of that class's bookings in
        `CONFIRMED` or `CHECKED_IN` status."
        PRD §3.5: "After any confirm, the excursion's availability fields are recomputed,
        and the excursion's still-`DRAFT` manifest recomputes its galley numbers with its
        `version` incrementing; the booking's own `version` increments as well."

        Design: Difficulty/compensating_invariant/seat_count_confirm_cancel_conservation
        """
        excursion = self._setup()
        before = get_excursion(excursion["id"])
        assert before["coach_seats_available"] == 5

        held = create_held_booking(excursion["id"], "inv@x.com", "COACH", 2)
        confirmed = confirm_booking(held["id"])
        assert confirmed["status"] == "CONFIRMED"

        after = get_excursion(excursion["id"])
        assert after["coach_seats_available"] == 3, "5 - party of 2 confirmed = 3"

    def test_cancel_restores_committed_seats_zero_drift(self, api, station_agent_headers):
        """PRD §3.6: "A cancelled `DINING` booking also frees its table, clearing
        `dining_table_number` and `dining_car_assignment_id` so the selector can hand the
        seats to someone else. Either cancel path recomputes the excursion's availability
        and the still-`DRAFT` manifest (bumping its `version`), and increments the
        booking's `version`."
        PRD §3.4: "Each is the sum of `effective_capacity` over the consist's assignments
        of that class minus the party sizes of that class's bookings in `CONFIRMED` or
        `CHECKED_IN` status."

        Design: Difficulty/compensating_invariant/seat_count_confirm_cancel_conservation
        """
        excursion = self._setup()
        assert get_excursion(excursion["id"])["coach_seats_available"] == 5

        confirmed = create_confirmed_booking(excursion["id"], "inv@x.com", "COACH", 2)
        assert get_excursion(excursion["id"])["coach_seats_available"] == 3

        cancelled = validate_success(
            api.booking_event(confirmed["id"], {"event_type": "CANCEL"}, station_agent_headers), 200)
        assert cancelled["status"] == "CANCELLED"

        restored = get_excursion(excursion["id"])
        assert restored["coach_seats_available"] == 5, (
            "confirm + cancel pair leaves the seat count exactly where it started")


def test_dining_party_over_four_rejected(api, station_agent_headers):
    """PRD §3.5: "Party size runs from 1 to 8, but a dining table seats four, so a
    `DINING` party above 4 is `ERR_PARTY_TOO_LARGE_FOR_DINING`."

    Design: Corner/calculations/dining_party_over_four_rejected
    """
    scenario = setup_published_excursion(car_specs=[LOCO_SPEC, DINING_SPEC, COACH_SPEC])
    excursion = scenario["excursion"]

    res = api.create_booking(
        create_booking_payload(excursion["id"], "big@x.com", "DINING", 5, "EARLY"),
        station_agent_headers)
    validate_error(res, ApiErrorId.ERR_PARTY_TOO_LARGE_FOR_DINING.value, expected_status=422)

    ok = api.create_booking(
        create_booking_payload(excursion["id"], "ok@x.com", "COACH", 5),
        station_agent_headers)
    booking = validate_success(ok, 201)
    assert booking["status"] == "HELD", "the same party size is legal in COACH"


def test_dining_service_required_for_dining_class(api, station_agent_headers):
    """PRD §3.5: "The `dining_service` field is required exactly when the class is
    `DINING` and forbidden otherwise; getting that conditional wrong is `ERR_VALIDATION`,
    as is any malformed body, missing required field, invalid enum value, or unknown
    `event_type`."

    Design: Corner/validations/dining_service_required_for_dining_class
    """
    scenario = setup_published_excursion(car_specs=[LOCO_SPEC, DINING_SPEC, COACH_SPEC])
    excursion = scenario["excursion"]

    res = api.create_booking(
        create_booking_payload(excursion["id"], "nodate@x.com", "DINING", 2),
        station_agent_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value, expected_status=400)

    res2 = api.create_booking(
        create_booking_payload(excursion["id"], "extra@x.com", "COACH", 2, "EARLY"),
        station_agent_headers)
    validate_error(res2, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_booking_with_unknown_excursion_reference_rejected(api, station_agent_headers):
    """PRD §2.9: "foreign keys carried in request bodies — `agreement_id`, `slot_id`,
    `stock_id`, `excursion_id`, `crew_member_id`, `redeemed_rain_check_id` — must resolve
    to existing resources, otherwise `ERR_INVALID_REFERENCE` (HTTP 422)."

    Design: Corner/validations/booking_with_unknown_excursion_reference_rejected
    """
    res = api.create_booking(
        create_booking_payload(NON_EXISTENT_UUID, "x@x.com", "COACH", 1),
        station_agent_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REFERENCE.value, expected_status=422)


def test_check_in_requires_boarding_excursion(api, station_agent_headers):
    """PRD §3.6: "Check-in is the `StationAgent`'s day-of action: `CONFIRMED →
    CHECKED_IN`, permitted only while the excursion is `BOARDING` — attempting it against
    any other excursion state is `ERR_INVALID_STATE`."

    Design: Corner/endpoints/check_in_requires_boarding_excursion
    """
    scenario = setup_published_excursion()
    confirmed = create_confirmed_booking(scenario["excursion"]["id"], "ci@x.com", "COACH", 1)

    # Excursion is PUBLISHED, not yet BOARDING.
    res = api.booking_event(confirmed["id"], {"event_type": "CHECK_IN"}, station_agent_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = get_booking(confirmed["id"])
    assert after["status"] == "CONFIRMED", "rejected check-in leaves the booking CONFIRMED"
