"""Temporal-overlap semantics: buffered half-open booking intervals,
closed-interval downtime windows, half-open contract coverage dates
(PRD §3.2, §3.11)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    TEST_USERS, create_booking_payload, create_downtime_event_payload,
    create_maintenance_contract_payload,
    make_researcher_headers, make_external_client_headers,
    setup_canonical_stack, create_approved_booking, create_instrument,
    create_maintenance_contract, create_downtime_event_payload as _dt,
    enroll_and_certify, create_user, set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestBufferedHalfOpenBookingOverlap:
    def _setup(self, api):
        stack = setup_canonical_stack()
        u2 = create_user(affiliation="EXTERNAL", full_name="Eve Ext",
                         email="eve@acme.com")
        enroll_and_certify(u2["id"], stack["i1"]["id"])
        # APPROVED booking occupies [09:00, 11:00) with the 30-minute buffer.
        b1 = create_approved_booking(stack)
        return stack, u2, b1

    def test_start_inside_buffered_window_rejected(self, api):
        """PRD §3.2: "for booking-versus-booking conflict purposes, every
        booking occupies the **half-open interval** from its `start_at` up to
        but not including its `end_at` plus the instrument's
        `booking_buffer_minutes`. Two buffered intervals conflict if and only
        if they intersect". PRD §3.6: "the buffered half-open overlap check
        must pass (`ERR_BOOKING_OVERLAP`)".

        Design: Difficulty/resource_temporal_overlap/booking_overlap_buffered_half_open
        """
        stack, u2, b1 = self._setup(api)
        res = api.create_booking(
            create_booking_payload(
                u2["id"], stack["i1"]["id"],
                start_at="2026-09-01T10:30:00Z", end_at="2026-09-01T12:00:00Z",
            ),
            make_external_client_headers(u2["id"]),
        )
        # 10:30 < buffered end 11:00 -> intervals intersect.
        validate_error(res, "ERR_BOOKING_OVERLAP", expected_status=409)
        assert api.get_booking(b1["id"], STAFF).json()["data"]["status"] == "APPROVED"

    def test_adjacency_at_buffered_edge_allowed(self, api):
        """PRD §3.2: "Two buffered intervals conflict if and only if they
        intersect; exact adjacency — one booking's `start_at` equaling the
        other's buffered end — is allowed."

        Design: Difficulty/resource_temporal_overlap/booking_overlap_buffered_half_open
        """
        stack, u2, b1 = self._setup(api)
        adjacent = validate_success(
            api.create_booking(
                create_booking_payload(
                    u2["id"], stack["i1"]["id"],
                    start_at="2026-09-01T11:00:00Z", end_at="2026-09-01T12:00:00Z",
                ),
                make_external_client_headers(u2["id"]),
            ),
            201,
        )
        assert adjacent["status"] == "REQUESTED", (
            "a start exactly at the buffered end 11:00 is allowed"
        )


class TestDowntimeClosedInterval:
    def _setup(self, api):
        stack = setup_canonical_stack()
        dt1 = validate_success(
            api.create_downtime_event(
                create_downtime_event_payload(
                    stack["i1"]["id"],
                    start_at="2026-09-01T11:00:00Z",
                    end_at="2026-09-01T13:00:00Z",
                ),
                STAFF,
            ),
            201,
        )
        # Future window (clock still at the 2026-08-01 default): the confirm
        # leaves the instrument AVAILABLE but blocks overlapping bookings.
        confirmed = validate_success(api.confirm_downtime_event(dt1["id"], STAFF), 200)
        instrument = validate_success(api.get_instrument(stack["i1"]["id"], ADMIN), 200)
        return stack, dt1, confirmed, instrument

    def test_booking_ending_at_downtime_start_conflicts(self, api):
        """PRD §3.2: "Downtime windows behave differently: a `CONFIRMED`
        downtime event conflicts with bookings under **closed-interval**
        semantics, where touching endpoints collide." PRD §3.6: "no
        confirmed-downtime closed-interval conflict may exist
        (`ERR_DOWNTIME_CONFLICT`)".

        Design: Difficulty/resource_temporal_overlap/downtime_closed_interval_touch_conflicts
        """
        stack, dt1, confirmed, instrument = self._setup(api)
        assert instrument["status"] == "AVAILABLE", (
            "confirming a future-window event leaves the instrument AVAILABLE"
        )
        res = api.create_booking(
            create_booking_payload(
                stack["u1"]["id"], stack["i1"]["id"],
                grant_id=stack["g1"]["id"],
                start_at="2026-09-01T10:30:00Z", end_at="2026-09-01T11:00:00Z",
            ),
            make_researcher_headers(stack["u1"]["id"]),
        )
        # end 11:00 touches the downtime start 11:00; closed-interval touch.
        validate_error(res, "ERR_DOWNTIME_CONFLICT", expected_status=409)

    def test_booking_ending_one_minute_before_allowed(self, api):
        """PRD §3.2: "Downtime windows behave differently: a `CONFIRMED`
        downtime event conflicts with bookings under **closed-interval**
        semantics, where touching endpoints collide." PRD §3.2: "Confirming a
        future-window event leaves the instrument `AVAILABLE`, though the
        confirmed window still blocks overlapping bookings via
        `ERR_DOWNTIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/downtime_closed_interval_touch_conflicts
        """
        stack, dt1, confirmed, instrument = self._setup(api)
        assert instrument["status"] == "AVAILABLE"
        ok = validate_success(
            api.create_booking(
                create_booking_payload(
                    stack["u1"]["id"], stack["i1"]["id"],
                    grant_id=stack["g1"]["id"],
                    start_at="2026-09-01T10:00:00Z", end_at="2026-09-01T10:59:00Z",
                ),
                make_researcher_headers(stack["u1"]["id"]),
            ),
            201,
        )
        assert ok["status"] == "REQUESTED"


class TestContractCoverageDates:
    def _setup(self, api):
        i1 = create_instrument()
        c1 = create_maintenance_contract(i1["id"])  # 2026-01-01..2026-12-31
        return i1, c1

    def test_overlapping_coverage_rejected(self, api):
        """PRD §3.11: "an instrument may not hold two contracts whose status is
        anything other than `TERMINATED` and whose coverage windows overlap,
        but touching boundaries — one contract's `coverage_end` equaling
        another's `coverage_start` — are allowed; a violation is
        `ERR_CONTRACT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contract_coverage_date_adjacency
        """
        i1, c1 = self._setup(api)
        res = api.create_maintenance_contract(
            create_maintenance_contract_payload(
                i1["id"], vendor="OtherVendor", sla_response_hours=48,
                coverage_start="2026-06-01", coverage_end="2027-05-31",
                annual_cost_cents=30000,
            ),
            ADMIN,
        )
        validate_error(res, "ERR_CONTRACT_OVERLAP", expected_status=409)

    def test_adjacent_coverage_allowed(self, api):
        """PRD §3.11: "an instrument may not hold two contracts whose status is
        anything other than `TERMINATED` and whose coverage windows overlap,
        but touching boundaries — one contract's `coverage_end` equaling
        another's `coverage_start` — are allowed; a violation is
        `ERR_CONTRACT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contract_coverage_date_adjacency
        """
        i1, c1 = self._setup(api)
        adjacent = validate_success(
            api.create_maintenance_contract(
                create_maintenance_contract_payload(
                    i1["id"], vendor="OtherVendor", sla_response_hours=48,
                    coverage_start="2027-01-01", coverage_end="2027-12-31",
                    annual_cost_cents=30000,
                ),
                ADMIN,
            ),
            201,
        )
        assert adjacent["status"] == "ACTIVE", (
            "a window starting the day after the inclusive end does not overlap"
        )
        contracts = validate_success(api.list_maintenance_contracts(ADMIN), 200)
        mine = [c for c in contracts if c.get("instrument_id") == i1["id"]]
        assert len(mine) == 2, f"expected exactly two contracts, got {mine!r}"


class TestDowntimeCreationAndTerminalStates:
    def test_preventive_maintenance_requires_covering_contract(self, api):
        """PRD §3.11: "For `PREVENTIVE_MAINTENANCE` the
        `maintenance_contract_id` is required and must reference an `ACTIVE`
        contract whose coverage window contains the event window
        (`ERR_CONTRACT_REQUIRED`); for the other kinds it is optional."

        Design: Corner/validations/preventive_maintenance_requires_covering_contract
        """
        i1 = create_instrument()
        # Coverage spans the default logical clock date (2026-08-01, PRD §2.4)
        # so the contract resolves ACTIVE (PRD §3.11/§2.10).
        c1 = create_maintenance_contract(
            i1["id"], coverage_start="2026-08-01", coverage_end="2026-12-31"
        )
        no_contract = api.create_downtime_event(
            create_downtime_event_payload(
                i1["id"], kind="PREVENTIVE_MAINTENANCE",
                start_at="2026-09-05T09:00:00Z", end_at="2026-09-05T12:00:00Z",
            ),
            STAFF,
        )
        validate_error(no_contract, "ERR_CONTRACT_REQUIRED", expected_status=422)

        not_covering = api.create_downtime_event(
            create_downtime_event_payload(
                i1["id"], kind="PREVENTIVE_MAINTENANCE",
                start_at="2027-01-15T09:00:00Z", end_at="2027-01-15T12:00:00Z",
                maintenance_contract_id=c1["id"],
            ),
            STAFF,
        )
        validate_error(not_covering, "ERR_CONTRACT_REQUIRED", expected_status=422)

        covering = validate_success(
            api.create_downtime_event(
                create_downtime_event_payload(
                    i1["id"], kind="PREVENTIVE_MAINTENANCE",
                    start_at="2026-09-05T09:00:00Z", end_at="2026-09-05T12:00:00Z",
                    maintenance_contract_id=c1["id"],
                ),
                STAFF,
            ),
            201,
        )
        assert covering["status"] == "REPORTED"

    def test_downtime_cancelled_terminal_and_instrument_retired_terminal(self, api):
        """PRD §3.11: "Cancelling a `REPORTED` event (an erroneous report)
        moves it to `CANCELLED`, terminal like `RESOLVED`." PRD §3.2:
        "Instruments cycle through `AVAILABLE`, `DOWN`, `MAINTENANCE`, and the
        terminal `RETIRED`." PRD §2.9: "State-machine legality
        (`ERR_INVALID_STATE`): the target resource's current state must permit
        the requested transition".

        Design: Corner/state_machines/downtime_cancelled_terminal_and_instrument_retired_terminal
        """
        i1 = create_instrument()
        i2 = create_instrument(
            name="OldSpec", model="Varian 300", location="Lab 9",
            requires_training=False, booking_buffer_minutes=0,
            min_booking_minutes=15, max_booking_minutes=120,
            cancellation_free_notice_hours=0, late_cancel_penalty_pct=0.0,
            no_show_penalty_pct=0.0,
        )
        dt1 = validate_success(
            api.create_downtime_event(
                create_downtime_event_payload(
                    i1["id"], kind="CALIBRATION",
                    start_at="2026-09-05T09:00:00Z", end_at="2026-09-05T10:00:00Z",
                ),
                STAFF,
            ),
            201,
        )
        validate_success(api.cancel_downtime_event(dt1["id"], STAFF), 200)
        validate_success(api.retire_instrument(i2["id"], ADMIN), 200)

        res1 = api.confirm_downtime_event(dt1["id"], STAFF)
        validate_error(res1, "ERR_INVALID_STATE", expected_status=409)
        res2 = api.return_instrument_to_service(i2["id"], ADMIN)
        validate_error(res2, "ERR_INVALID_STATE", expected_status=409)
        instrument = validate_success(api.get_instrument(i1["id"], ADMIN), 200)
        assert instrument["status"] == "AVAILABLE", (
            "a cancelled report never touches the instrument"
        )
