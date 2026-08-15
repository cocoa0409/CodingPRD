"""Shipment routing, insurance coverage, crate location conservation (PRD §3.5, §3.6)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_and_open_booking,
    create_venue,
    book_stop,
    issue_certificate,
    plan_first_leg,
    setup_contracted_stop,
    setup_received_shipment,
    create_shipment_payload,
)

TM = TEST_USERS["tour_manager_headers"]
SHIP = TEST_USERS["shipper_headers"]


class TestRouteConsecutive:
    def _setup_three_stops(self, api):
        tour, _ = create_and_open_booking()
        va = create_venue(name="VA")
        vb = create_venue(name="VB")
        vc = create_venue(name="VC")
        s1 = book_stop(
            tour["id"],
            va["id"],
            install_start="2026-09-01T00:00:00Z",
            open_date="2026-09-03T00:00:00Z",
            close_date="2026-09-20T00:00:00Z",
            teardown_end="2026-09-23T00:00:00Z",
        )
        s2 = book_stop(
            tour["id"],
            vb["id"],
            install_start="2026-10-01T00:00:00Z",
            open_date="2026-10-03T00:00:00Z",
            close_date="2026-10-20T00:00:00Z",
            teardown_end="2026-10-23T00:00:00Z",
        )
        s3 = book_stop(
            tour["id"],
            vc["id"],
            install_start="2026-11-01T00:00:00Z",
            open_date="2026-11-03T00:00:00Z",
            close_date="2026-11-20T00:00:00Z",
            teardown_end="2026-11-23T00:00:00Z",
        )
        return tour, s1, s2, s3

    def test_shipment_skipping_a_stop_rejected(self, api):
        """PRD §3.6: "The destination must be a stop of the same tour, and
        whenever an origin is given, origin and destination must be consecutive
        stops by route `seq`; a plan violating either clause is rejected with
        `ERR_ROUTE_NOT_CONSECUTIVE`."

        Design: Corner/validations/shipment_non_consecutive_route_rejected
        """
        tour, s1, s2, s3 = self._setup_three_stops(api)
        crate_id = get_success_data(api.list_crates(tour["id"], TM))[0]["id"]
        res = api.create_shipment(
            tour["id"],
            create_shipment_payload(
                s3["id"],
                [crate_id],
                origin_stop_id=s1["id"],
                depart_at="2026-09-24T00:00:00Z",
                arrive_at="2026-10-30T00:00:00Z",
            ),
            TM,
        )
        validate_error(res, ApiErrorId.ERR_ROUTE_NOT_CONSECUTIVE)

    def test_shipment_between_consecutive_stops_accepted(self, api):
        """PRD §3.6: "The destination must be a stop of the same tour, and
        whenever an origin is given, origin and destination must be consecutive
        stops by route `seq`; a plan violating either clause is rejected with
        `ERR_ROUTE_NOT_CONSECUTIVE`."

        Design: Corner/validations/shipment_non_consecutive_route_rejected
        """
        tour, s1, s2, s3 = self._setup_three_stops(api)
        crate_id = get_success_data(api.list_crates(tour["id"], TM))[0]["id"]
        res = api.create_shipment(
            tour["id"],
            create_shipment_payload(
                s2["id"],
                [crate_id],
                origin_stop_id=s1["id"],
                depart_at="2026-09-24T00:00:00Z",
                arrive_at="2026-09-30T00:00:00Z",
            ),
            TM,
        )
        shipment = validate_success(res, 201)
        assert shipment["status"] == "PLANNED"


class TestInsuranceCoverageWindow:
    def test_arrival_exactly_at_effective_to_not_covered(self, api):
        """PRD §3.5: "the certificate's `status` is `ISSUED` or `ACTIVE`; its
        `coverage_cents` is at least the tour's `declared_value_cents`; its
        `effective_from` falls at or before the leg's `depart_at`; and its
        `effective_to` falls strictly after the leg's `arrive_at` — the window's
        end is exclusive. When no certificate satisfying all four clauses covers
        the destination stop, the dispatch or the installation start is rejected
        with `ERR_NO_INSURANCE_COVERAGE` (HTTP 409)."

        Design: Corner/calculations/insurance_coverage_check_window_boundary
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="Bead Hall")
        stop = book_stop(
            tour["id"],
            venue["id"],
            install_start="2026-08-20T00:00:00Z",
            open_date="2026-08-22T00:00:00Z",
            close_date="2026-08-30T00:00:00Z",
            teardown_end="2026-09-02T00:00:00Z",
        )
        issue_certificate(
            tour["id"],
            stop["id"],
            tour["declared_value_cents"],
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        )
        crate_id = get_success_data(api.list_crates(tour["id"], TM))[0]["id"]
        shipment = plan_first_leg(
            tour["id"],
            stop["id"],
            [crate_id],
            depart_at="2026-08-15T00:00:00Z",
            arrive_at="2026-09-01T00:00:00Z",
        )
        res = api.transition_shipment(
            tour["id"], shipment["id"], {"action": "DISPATCH"}, SHIP
        )
        validate_error(res, ApiErrorId.ERR_NO_INSURANCE_COVERAGE)

    def test_arrival_one_second_before_effective_to_covered(self, api):
        """PRD §3.5: "its `effective_to` falls strictly after the leg's
        `arrive_at` — the window's end is exclusive. When no certificate
        satisfying all four clauses covers the destination stop, the dispatch or
        the installation start is rejected with `ERR_NO_INSURANCE_COVERAGE`
        (HTTP 409)."

        Design: Corner/calculations/insurance_coverage_check_window_boundary
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="Bead Hall")
        stop = book_stop(
            tour["id"],
            venue["id"],
            install_start="2026-08-20T00:00:00Z",
            open_date="2026-08-22T00:00:00Z",
            close_date="2026-08-30T00:00:00Z",
            teardown_end="2026-09-02T00:00:00Z",
        )
        issue_certificate(
            tour["id"],
            stop["id"],
            tour["declared_value_cents"],
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        )
        crate_id = get_success_data(api.list_crates(tour["id"], TM))[0]["id"]
        shipment = plan_first_leg(
            tour["id"],
            stop["id"],
            [crate_id],
            depart_at="2026-08-15T00:00:00Z",
            arrive_at="2026-08-31T23:59:59Z",
        )
        res = api.transition_shipment(
            tour["id"], shipment["id"], {"action": "DISPATCH"}, SHIP
        )
        dispatched = validate_success(res, 200)
        assert dispatched["status"] == "DISPATCHED"


class TestBeginInstallInsuranceGate:
    def test_begin_install_without_certificate_rejected(self, api):
        """PRD §3.8: "Insurance comes first: a certificate covering this stop and
        satisfying the four-clause rule of §3.5 against the inbound leg must
        exist, or the attempt fails with `ERR_NO_INSURANCE_COVERAGE`."

        Design: Difficulty/cross_entity_state_dependency/begin_install_gated_by_insurance_certificate_state
        """
        # CONTRACTED stop with NO certificate issued.
        tour, crates, venue, stop, contract = setup_contracted_stop()
        res = api.transition_stop(tour["id"], stop["id"], {"action": "BEGIN_INSTALL"}, TM)
        validate_error(res, ApiErrorId.ERR_NO_INSURANCE_COVERAGE)
        stop_after = validate_success(api.get_stop(tour["id"], stop["id"], TM), 200)
        assert stop_after["status"] == "CONTRACTED"

    def test_begin_install_with_certificate_succeeds(self, api):
        """PRD §3.8: "a `TourManager` begins install (`action` `BEGIN_INSTALL`),
        taking the stop `CONTRACTED` → `INSTALLING`."
        PRD §3.8: "if the tour was `BOOKING` or `IN_REFURBISHMENT`, the system
        lifts it to `ON_TOUR`, the first installation anywhere on the route
        being exactly what ends the booking posture."

        Design: Difficulty/cross_entity_state_dependency/begin_install_gated_by_insurance_certificate_state
        """
        from test_helpers import setup_install_ready_stop

        tour, crates, venue, stop, contract, shipment = setup_install_ready_stop()
        res = api.transition_stop(tour["id"], stop["id"], {"action": "BEGIN_INSTALL"}, TM)
        stop_after = validate_success(res, 200)
        assert stop_after["status"] == "INSTALLING"
        tour_after = validate_success(api.get_tour(tour["id"], TM), 200)
        assert tour_after["status"] == "ON_TOUR"


class TestCrateLocationConservation:
    def test_dispatch_moves_all_manifest_crates_in_transit(self, api):
        """PRD §3.6: "Dispatch physically commits the crates: every crate on the
        manifest moves from `AT_VENUE` (or `AT_ORIGIN`) to `IN_TRANSIT`, with
        each crate's `current_stop_id` pointed at the destination stop."

        Design: Difficulty/compensating_invariant/crate_location_conservation_across_shipment_dispatch_and_hold
        """
        tour, crates, venue, stop, contract = setup_contracted_stop(
            crate_values=[1000000, 1000000], crate_count=2
        )
        issue_certificate(tour["id"], stop["id"], tour["declared_value_cents"])
        shipment = plan_first_leg(
            tour["id"], stop["id"], [c["id"] for c in crates]
        )
        res = api.transition_shipment(
            tour["id"], shipment["id"], {"action": "DISPATCH"}, SHIP
        )
        validate_success(res, 200)
        crates_after = get_success_data(api.list_crates(tour["id"], TM))
        in_transit = [c for c in crates_after if c["location_status"] == "IN_TRANSIT"]
        assert len(in_transit) == 2
        for c in in_transit:
            assert c["current_stop_id"] == stop["id"]

    def test_location_bucket_sum_invariant_after_dispatch(self, api):
        """PRD §3.6: "Dispatch physically commits the crates: every crate on the
        manifest moves from `AT_VENUE` (or `AT_ORIGIN`) to `IN_TRANSIT`, with
        each crate's `current_stop_id` pointed at the destination stop."
        PRD §3.1: "A crate is born with `location_status` `AT_ORIGIN`, a null
        `condition_score`, and an empty `current_stop_id`."

        Design: Difficulty/compensating_invariant/crate_location_conservation_across_shipment_dispatch_and_hold
        """
        tour, crates, venue, stop, contract = setup_contracted_stop(
            crate_values=[1000000, 1000000], crate_count=2
        )
        # Before dispatch: both AT_ORIGIN.
        before = get_success_data(api.list_crates(tour["id"], TM))
        counts_before = {}
        for c in before:
            counts_before[c["location_status"]] = counts_before.get(c["location_status"], 0) + 1
        assert sum(counts_before.values()) == 2
        assert counts_before.get("AT_ORIGIN", 0) == 2

        issue_certificate(tour["id"], stop["id"], tour["declared_value_cents"])
        shipment = plan_first_leg(
            tour["id"], stop["id"], [c["id"] for c in crates]
        )
        validate_success(
            api.transition_shipment(tour["id"], shipment["id"], {"action": "DISPATCH"}, SHIP),
            200,
        )
        after = get_success_data(api.list_crates(tour["id"], TM))
        counts_after = {}
        for c in after:
            counts_after[c["location_status"]] = counts_after.get(c["location_status"], 0) + 1
        # Conservation: total crates across buckets unchanged; dispatch only
        # re-buckets AT_ORIGIN -> IN_TRANSIT.
        assert sum(counts_after.values()) == 2
        assert counts_after.get("IN_TRANSIT", 0) == 2
        assert counts_after.get("AT_ORIGIN", 0) == 0
