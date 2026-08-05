"""Amenities and reservations: dual-variant settlement, half-open concurrent
capacity, slot conservation, and check-in validation ordering.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock, create_community, create_resident, create_amenity,
    book_reservation, transition_reservation, setup_community_and_resident,
    setup_reservation_checked_in,
    ADMIN,
)


class TestAmenitySettlementDualVariant:
    """Tests for the amenity_settlement_quoted_vs_settled rule (see per-test Design tags)."""

    def test_quoted_fee_at_booking(self, api):
        """PRD §3.5: "A successful booking sets `status` to `BOOKED`, commits the
        `party_size` to the amenity's load, and computes the provisional
        `quoted_fee_cents`: the planned span from `start_at` to `end_at` is
        converted to hours and rounded up to the next whole hour, multiplied by
        `hourly_fee_cents`, and then the `deposit_cents` is added as a held (not
        yet charged) deposit."

        Design: Difficulty/dual_variant_calc/amenity_settlement_quoted_vs_settled
        """
        set_clock("2026-06-02T08:00:00Z")
        community, resident = setup_community_and_resident()
        amenity = create_amenity(community["id"], amenity_type="POOL", capacity=10,
                                 hourly_fee_cents=1000, deposit_cents=5000,
                                 open_hour=6, close_hour=22)
        resv = book_reservation(amenity["id"], resident["id"],
                                start_at="2026-06-02T10:00:00Z",
                                end_at="2026-06-02T12:00:00Z", party_size=2)
        assert resv["quoted_fee_cents"] == 7000, "ceil(2h)*1000 + 5000 deposit"

    def test_settled_fee_at_checkout_differs_from_quoted(self, api):
        """PRD §3.5: "The settled fee takes the base hours as the span from
        `checkin_at` up to the earlier of `checkout_at` and `end_at`, converted
        to hours and rounded up to the next whole hour, multiplied by
        `hourly_fee_cents`; adds an overage term for the span by which
        `checkout_at` exceeds `end_at` (zero when not past), converted to hours
        rounded up and multiplied by twice the `hourly_fee_cents`; and releases
        the deposit (it is not charged)."

        Design: Difficulty/dual_variant_calc/amenity_settlement_quoted_vs_settled
        """
        _, _, _, resv = setup_reservation_checked_in(
            clock_iso="2026-06-02T08:00:00Z",
            amenity_overrides={"hourly_fee_cents": 1000, "deposit_cents": 5000},
            start_at="2026-06-02T10:00:00Z", end_at="2026-06-02T12:00:00Z",
            party_size=2, checkin_iso="2026-06-02T10:00:00Z",
        )
        set_clock("2026-06-02T13:00:00Z")
        data = validate_success(api.transition_reservation(resv["id"], {"to_status": "COMPLETED"}, ADMIN))
        # base = ceil(min(13:00,12:00)-10:00)=2h*1000=2000 ; overage=ceil(1)=1h*2*1000=2000
        assert data["settled_fee_cents"] == 4000
        assert data["quoted_fee_cents"] == 7000
        assert data["settled_fee_cents"] != data["quoted_fee_cents"]


class TestAmenityCapacityOverlap:
    """Tests for the amenity_reservation_capacity_overlap_half_open rule (see per-test Design tags)."""

    def _setup_two_adjacent(self):
        set_clock("2026-06-06T08:00:00Z")
        community, resident = setup_community_and_resident()
        amenity = create_amenity(community["id"], name="Court 1", amenity_type="TENNIS",
                                 capacity=2, hourly_fee_cents=500, deposit_cents=0,
                                 open_hour=6, close_hour=22)
        r1 = book_reservation(amenity["id"], resident["id"],
                              start_at="2026-06-06T10:00:00Z", end_at="2026-06-06T12:00:00Z",
                              party_size=2)
        r3 = book_reservation(amenity["id"], resident["id"],
                              start_at="2026-06-06T12:00:00Z", end_at="2026-06-06T14:00:00Z",
                              party_size=2)
        return community, resident, amenity, r1, r3

    def test_adjacent_reservations_both_booked(self, api):
        """PRD §3.5: "two reservation windows overlap when the first starts
        strictly before the second ends and the second starts strictly before the
        first ends, so windows that merely touch end-to-start do not overlap."

        Design: Difficulty/resource_temporal_overlap/amenity_reservation_capacity_overlap_half_open
        """
        _, _, _, r1, r3 = self._setup_two_adjacent()
        assert r1["status"] == "BOOKED"
        assert r3["status"] == "BOOKED"

    def test_overlapping_over_capacity_rejected(self, api):
        """PRD §3.5: "a booking is refused with `ERR_AMENITY_AT_CAPACITY` when, at
        the busiest overlapping instant, the existing load plus the new
        `party_size` would exceed the amenity's `capacity`."

        Design: Difficulty/resource_temporal_overlap/amenity_reservation_capacity_overlap_half_open
        """
        _, resident, amenity, _, _ = self._setup_two_adjacent()
        resp = api.create_reservation(
            {"amenity_id": amenity["id"], "resident_id": resident["id"],
             "start_at": "2026-06-06T11:00:00Z", "end_at": "2026-06-06T13:00:00Z",
             "party_size": 1}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_AMENITY_AT_CAPACITY.value)


class TestAmenitySlotConservation:
    """Tests for the amenity_slot_conservation_book_then_cancel rule (see per-test Design tags)."""

    def _book_full_then_cancel(self):
        set_clock("2026-06-07T08:00:00Z")
        community, resident = setup_community_and_resident()
        amenity = create_amenity(community["id"], name="Clubhouse", amenity_type="CLUBHOUSE",
                                 capacity=5, hourly_fee_cents=0, deposit_cents=0,
                                 open_hour=6, close_hour=22)
        r1 = book_reservation(amenity["id"], resident["id"],
                              start_at="2026-06-07T10:00:00Z", end_at="2026-06-07T12:00:00Z",
                              party_size=5)
        r1 = transition_reservation(r1["id"], "CANCELLED")
        return community, resident, amenity, r1

    def test_cancelled_reservation_is_terminal_cancelled(self, api):
        """PRD §3.5: "A resident may cancel a `BOOKED` reservation to
        `CANCELLED`, which releases the committed `party_size` back to the amenity
        load and releases the deposit without charge".

        Design: Difficulty/compensating_invariant/amenity_slot_conservation_book_then_cancel
        """
        _, _, _, r1 = self._book_full_then_cancel()
        assert r1["status"] == "CANCELLED"

    def test_cancel_releases_slots_for_full_rebook(self, api):
        """PRD §3.5: "A resident may cancel a `BOOKED` reservation to
        `CANCELLED`, which releases the committed `party_size` back to the amenity
        load and releases the deposit without charge".

        Design: Difficulty/compensating_invariant/amenity_slot_conservation_book_then_cancel
        """
        _, resident, amenity, _ = self._book_full_then_cancel()
        r2 = validate_success(api.create_reservation(
            {"amenity_id": amenity["id"], "resident_id": resident["id"],
             "start_at": "2026-06-07T10:00:00Z", "end_at": "2026-06-07T12:00:00Z",
             "party_size": 5}, ADMIN), expected_status=201)
        assert r2["status"] == "BOOKED"
        assert r2["party_size"] == 5


class TestReservationCheckinOrdering:
    """Tests for the state_beats_fiscal_on_reservation_checkin rule (see per-test Design tags)."""

    def _setup_cancelled_r2_full_r1(self):
        set_clock("2026-06-04T08:00:00Z")
        community, resident = setup_community_and_resident()
        amenity = create_amenity(community["id"], name="Sauna", amenity_type="CLUBHOUSE",
                                 capacity=2, hourly_fee_cents=500, deposit_cents=0,
                                 open_hour=6, close_hour=22)
        r2 = book_reservation(amenity["id"], resident["id"],
                              start_at="2026-06-04T10:00:00Z", end_at="2026-06-04T12:00:00Z",
                              party_size=1)
        r2 = transition_reservation(r2["id"], "CANCELLED")
        book_reservation(amenity["id"], resident["id"],
                         start_at="2026-06-04T10:00:00Z", end_at="2026-06-04T12:00:00Z",
                         party_size=2)  # fills capacity
        set_clock("2026-06-04T10:30:00Z")
        return community, resident, amenity, r2

    def test_checkin_cancelled_reservation_returns_invalid_state(self, api):
        """PRD §2.10: "whether the target resource's current state permits the
        requested transition (`ERR_INVALID_STATE`); cross-entity eligibility gates
        (`ERR_SPONSOR_NOT_ELIGIBLE`, `ERR_VEHICLE_INACTIVE`,
        `ERR_RESIDENT_NOT_ELIGIBLE`); temporal window and overlap gates
        (`ERR_PASS_WINDOW_INVALID`, `ERR_RESERVATION_WINDOW_INVALID`,
        `ERR_PATROL_OVERLAP`); amenity capacity (`ERR_AMENITY_AT_CAPACITY`)".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reservation_checkin
        """
        _, _, _, r2 = self._setup_cancelled_r2_full_r1()
        validate_error(api.transition_reservation(r2["id"], {"to_status": "CHECKED_IN"}, ADMIN),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_error_precedes_capacity_http_409(self, api):
        """PRD §2.10: "amenity capacity (`ERR_AMENITY_AT_CAPACITY`)" fires after
        "whether the target resource's current state permits the requested
        transition (`ERR_INVALID_STATE`)".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reservation_checkin
        """
        _, _, _, r2 = self._setup_cancelled_r2_full_r1()
        validate_error(api.transition_reservation(r2["id"], {"to_status": "CHECKED_IN"}, ADMIN),
                       ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_book_nonreservable_amenity_returns_not_reservable(api):
    """PRD §3.5: "Booking is refused with `ERR_AMENITY_NOT_RESERVABLE` when the
    amenity's `reservable` flag is false".

    Design: Corner/validations/book_nonreservable_amenity_returns_not_reservable
    """
    community, resident = setup_community_and_resident()
    amenity = create_amenity(community["id"], name="Gym", amenity_type="GYM",
                             capacity=20, hourly_fee_cents=0, deposit_cents=0,
                             open_hour=5, close_hour=23, reservable=False)
    resp = api.create_reservation(
        {"amenity_id": amenity["id"], "resident_id": resident["id"],
         "start_at": "2026-06-10T10:00:00Z", "end_at": "2026-06-10T11:00:00Z",
         "party_size": 1}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_AMENITY_NOT_RESERVABLE.value)


def test_checkin_before_window_returns_reservation_window_invalid(api):
    """PRD §3.5: "A resident checks in a `BOOKED` reservation, advancing it to
    `CHECKED_IN`, only when the current clock is at or after `start_at` and
    strictly before `end_at` — otherwise the check-in is refused with
    `ERR_RESERVATION_WINDOW_INVALID`".

    Design: Corner/errors/error_reservation_window_invalid_present
    """
    set_clock("2026-06-08T08:00:00Z")
    community, resident = setup_community_and_resident()
    amenity = create_amenity(community["id"], name="Court 2", amenity_type="TENNIS",
                             capacity=4, hourly_fee_cents=500, deposit_cents=0,
                             open_hour=6, close_hour=22)
    resv = book_reservation(amenity["id"], resident["id"],
                            start_at="2026-06-08T10:00:00Z", end_at="2026-06-08T12:00:00Z",
                            party_size=1)
    validate_error(api.transition_reservation(resv["id"], {"to_status": "CHECKED_IN"}, ADMIN),
                   ApiErrorId.ERR_RESERVATION_WINDOW_INVALID.value)
