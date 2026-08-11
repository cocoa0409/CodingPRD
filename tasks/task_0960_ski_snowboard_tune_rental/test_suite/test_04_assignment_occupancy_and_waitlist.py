"""Assignment eligibility, the one-free-day occupancy rule, waitlist promotion,
and fleet retirement gating."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_item,
    assign_item,
    confirm,
    make_customer,
    make_customer_headers,
    make_equipment_item,
    make_reservation,
    set_clock,
    setup_picked_up_reservation,
    validate_error,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]


class TestOccupancyGapRule:
    def _setup_unit_with_window(self, api):
        customer = make_customer()
        unit = make_equipment_item()
        r1 = make_reservation(customer, start_date="2026-12-10", end_date="2026-12-12")
        i1 = add_item(r1)
        assigned = validate_success(api.assign_reservation_item(
            i1["id"], {"preferred_equipment_item_id": unit["id"]}, FD))
        assert assigned["status"] == "ASSIGNED"
        return customer, unit

    def test_start_on_mandatory_gap_day_rejected(self, api):
        """PRD Fleet Occupancy: "Between any two windows on the same unit there must be
        at least one full calendar day that belongs to neither window: the first day of
        a new rental window must fall at least two calendar dates after the last day of
        any existing window on that unit. A request that would collide with an existing
        window, or leave no free day between windows, is rejected with
        `ERR_EQUIPMENT_OCCUPANCY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/equipment_window_gap_overlap_rule
        """
        customer, unit = self._setup_unit_with_window(api)
        r2 = make_reservation(customer, start_date="2026-12-13", end_date="2026-12-15")
        i2 = add_item(r2)
        # 2026-12-13 is only one calendar date after 2026-12-12 — the gap day.
        resp = api.assign_reservation_item(
            i2["id"], {"preferred_equipment_item_id": unit["id"]}, FD)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_OCCUPANCY_CONFLICT)

    def test_start_two_dates_after_window_accepted(self, api):
        """PRD Fleet Occupancy: "the first day of a new rental window must fall at
        least two calendar dates after the last day of any existing window on that
        unit."

        Design: Difficulty/resource_temporal_overlap/equipment_window_gap_overlap_rule
        """
        customer, unit = self._setup_unit_with_window(api)
        r3 = make_reservation(customer, start_date="2026-12-14", end_date="2026-12-16")
        i3 = add_item(r3)
        assigned = validate_success(api.assign_reservation_item(
            i3["id"], {"preferred_equipment_item_id": unit["id"]}, FD))
        assert assigned["status"] == "ASSIGNED"
        assert assigned["equipment_item_id"] == unit["id"]
        unit_after = validate_success(api.get_equipment_item(unit["id"], FD))
        assert unit_after["status"] == "RESERVED"


class TestPreferredUnitEligibility:
    def test_preferred_unit_din_range_must_cover_fitment(self, api):
        """PRD Booking a Rental: "a unit whose DIN range does not cover the customer's
        computed fitment DIN is rejected with `ERR_DIN_MISMATCH`"

        Design: Corner/validations/din_mismatch_preferred_unit_rejected
        """
        # Standard profile computes DIN 5.75; the unit caps at din_max 5.
        customer = make_customer()
        unit = make_equipment_item(din_min=2, din_max=5, size_label="150cm")
        reservation = make_reservation(customer)
        item = add_item(reservation)
        resp = api.assign_reservation_item(
            item["id"], {"preferred_equipment_item_id": unit["id"]}, FD)
        validate_error(resp, ApiErrorId.ERR_DIN_MISMATCH)
        after = validate_success(api.get_reservation_item(item["id"], FD))
        assert after["status"] == "QUEUED"

    def test_preferred_unit_in_service_rejected(self, api):
        """PRD Fleet Occupancy: "A unit that is `IN_SERVICE`, `AWAITING_INSPECTION`,
        `RETIRED`, `LOST`, or `SOLD` cannot be newly committed to a customer; attempts
        to force such a unit into a rental or lease are rejected with
        `ERR_EQUIPMENT_NOT_AVAILABLE`."

        Design: Corner/validations/assign_preferred_in_service_unit_rejected
        """
        ctx = setup_picked_up_reservation(start_date="2026-12-01", end_date="2026-12-02",
                                          deposit_authorized_cents=1600,
                                          pickup_instant="2026-12-01T09:00:00Z")
        customer, unit = ctx["customer"], ctx["units"][0]
        set_clock("2026-12-02T17:00:00Z")
        validate_success(api.return_reservation(ctx["reservation"]["id"], FD))
        serviced = validate_success(api.inspect_equipment_item(
            unit["id"], {"outcome": "NEEDS_TUNE"}, TEST_USERS["technician_headers"]))
        assert serviced["status"] == "IN_SERVICE"

        r2 = make_reservation(customer, start_date="2027-01-05", end_date="2027-01-06")
        i2 = add_item(r2)
        resp = api.assign_reservation_item(
            i2["id"], {"preferred_equipment_item_id": unit["id"]}, FD)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_NOT_AVAILABLE)
        after = validate_success(api.get_reservation_item(i2["id"], FD))
        assert after["status"] == "QUEUED"


class TestWaitlistPromotion:
    def _setup_queued_waiter(self, api):
        ca = make_customer(email="fq@example.com", full_name="First Q")
        cb = make_customer(email="sq@example.com", full_name="Second Q")
        unit = make_equipment_item()
        r1 = make_reservation(ca, start_date="2026-12-10", end_date="2026-12-12")
        i1 = add_item(r1)
        assign_item(i1)
        r2 = make_reservation(cb, start_date="2026-12-14", end_date="2026-12-16")
        i2 = add_item(r2)
        queued = validate_success(api.assign_reservation_item(i2["id"], {}, FD))
        assert queued["status"] == "QUEUED"  # empty-pool fallback, not an error
        return ca, cb, unit, r1, i1, r2, i2

    def test_release_promotes_oldest_queued_item(self, api):
        """PRD Booking a Rental: "Release is contagious in a useful way: the moment a
        unit comes free, the system runs waitlist promotion, scanning for the
        oldest-created compatible `QUEUED` line anywhere in the system and assigning
        it to the freed unit, which flips right back to `RESERVED` with fresh rate,
        DIN, and timestamp snapshots"

        Design: Difficulty/transitive_cascade/release_promotes_oldest_queued_item
        """
        _, _, unit, _, i1, _, i2 = self._setup_queued_waiter(api)
        released = validate_success(api.release_reservation_item(i1["id"], FD))
        assert released["status"] == "RELEASED"

        promoted = validate_success(api.get_reservation_item(i2["id"], FD))
        assert promoted["status"] == "ASSIGNED"
        assert promoted["equipment_item_id"] == unit["id"]

    def test_promotion_reearmarks_unit_as_reserved(self, api):
        """PRD Booking a Rental: "the moment a unit comes free, the system runs
        waitlist promotion, scanning for the oldest-created compatible `QUEUED` line
        anywhere in the system and assigning it to the freed unit, which flips right
        back to `RESERVED`"

        Design: Difficulty/transitive_cascade/release_promotes_oldest_queued_item
        """
        _, _, unit, _, i1, _, _ = self._setup_queued_waiter(api)
        validate_success(api.release_reservation_item(i1["id"], FD))
        unit_after = validate_success(api.get_equipment_item(unit["id"], FD))
        # Freed then immediately re-earmarked by the promotion cascade.
        assert unit_after["status"] == "RESERVED"


class TestCancelCascadePromotion:
    def test_cancel_releases_unit_and_promotes_waiter(self, api):
        """PRD From Confirm to Close: "Every assigned line is released and each freed
        unit returns to `AVAILABLE` — and each such release itself triggers waitlist
        promotion, so a cancellation can transitively assign waiting lines onto the
        freed units."

        Design: Corner/cross_cutting_layers/cascade_cancel_releases_and_promotes
        """
        ca = make_customer(email="cc@example.com", full_name="Can Cel")
        cb = make_customer(email="wl@example.com", full_name="Wait Listed")
        unit = make_equipment_item()
        r1 = make_reservation(ca, start_date="2026-12-10", end_date="2026-12-12")
        i1 = add_item(r1)
        assign_item(i1)
        confirm(r1, 2400)

        r2 = make_reservation(cb, start_date="2026-12-14", end_date="2026-12-16")
        i2 = add_item(r2)
        queued = validate_success(api.assign_reservation_item(i2["id"], {}, FD))
        assert queued["status"] == "QUEUED"

        cancelled = validate_success(
            api.cancel_reservation(r1["id"], make_customer_headers(ca["id"])))
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "VOIDED"
        assert cancelled["deposit_released_cents"] == 2400

        released = validate_success(api.get_reservation_item(i1["id"], FD))
        assert released["status"] == "RELEASED"
        promoted = validate_success(api.get_reservation_item(i2["id"], FD))
        assert promoted["status"] == "ASSIGNED"
        assert promoted["equipment_item_id"] == unit["id"]


class TestRetirementGating:
    def test_retire_out_unit_rejected(self, api):
        """PRD Building and Maintaining the Fleet: "A `Manager` may retire a unit,
        moving it from `AVAILABLE` to `RETIRED`, but only while no assigned reservation
        line still references it."
        PRD Request Validation Precedence: "Sixth, the target resource's state is
        checked against the requested transition — including terminal-state lockdown —
        yielding `ERR_INVALID_STATE`."

        Design: Corner/state_machines/equipment_retire_from_out_returns_invalid_state
        """
        ctx = setup_picked_up_reservation()
        unit = ctx["units"][0]
        resp = api.retire_equipment_item(unit["id"], TEST_USERS["manager_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_equipment_item(unit["id"], FD))
        assert after["status"] == "OUT"
