"""Intake and filing validations at the exact edge the PRD draws them.

Eight rules are exercised here, each on both sides of its boundary where the PRD
draws one: the global uniqueness of `zone_code`, the three ways a stop pairing can
be invalid and the reference check that outranks them, the ordering of a subsidy
reporting period, the `(zone_id, variant)` key of the reporting-period overlap
check, the inclusive walking-distance standard enforced at approval rather than at
create, the accessible-path requirement keyed off the effective `wav_required`
flag, the half-open block window a manually dispatched pickup must land inside,
and the inclusive guaranteed-transfer buffer on both sides of a fixed-route
departure.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    DISPATCHER_HEADERS,
    FINANCE_ANALYST_HEADERS,
    ZONE_ADMIN_HEADERS,
    make_rider_headers,
)

# A second zone policy that differs from the fixture default in every configurable
# field, so nothing but `zone_code` can explain a uniqueness rejection.
NORTH_ZONE_POLICY = {
    "name": "Riverbend North",
    "max_walk_meters": 800,
    "detour_tolerance_pct": 0.30,
    "detour_tolerance_floor_minutes": 8,
    "base_fare_cents": 300,
    "fare_cap_cents_daily": 900,
    "fare_cap_cents_weekly": 3000,
    "on_time_window_minutes": 5,
    "curb_capacity_per_bucket": 3,
}


# ---------------------------------------------------------------------------
# Service-zone code uniqueness
# ---------------------------------------------------------------------------


class TestZoneCodeUniqueness:
    def test_second_zone_reusing_an_existing_zone_code_is_rejected(self) -> None:
        """A different name cannot rescue a zone_code already taken by another zone.

        PRD: "A duplicate `zone_code` is rejected with `ERR_DUPLICATE_ZONE_CODE`."

        Design: Corner/validations/duplicate_zone_code_is_rejected_across_the_whole_fleet
        """
        fixtures.set_clock(constants.CLOCK_STARTUP_UTC, headers=ZONE_ADMIN_HEADERS)
        first = fixtures.create_zone()
        assert first["zone_code"] == "RBM"

        response = api_client.create_service_zone(
            factories.service_zone_payload(zone_code="RBM", **NORTH_ZONE_POLICY),
            ZONE_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_ZONE_CODE.value, 409)

        rows, meta = validate_paginated(
            api_client.list_service_zones(ZONE_ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1
        assertions.assert_contains_ids(rows, first["id"])

    def test_free_zone_code_is_accepted_under_an_unrelated_policy(self) -> None:
        """A zone code nobody holds yet is accepted even though the rest of the
        definition is unrelated to the zone that already exists.

        PRD: "The definition is as much a policy document as a geography: alongside a human-readable `name` of between 1 and 120 characters and an operator-assigned `zone_code` of between 2 and 12 characters that must be unique across every zone in the system, the planner fixes the walking-distance standard, the shared-ride detour tolerance, the fare policy and the curb-congestion ceiling in a single act."

        Design: Corner/validations/duplicate_zone_code_is_rejected_across_the_whole_fleet
        """
        fixtures.set_clock(constants.CLOCK_STARTUP_UTC, headers=ZONE_ADMIN_HEADERS)
        first = fixtures.create_zone()

        response = api_client.create_service_zone(
            factories.service_zone_payload(zone_code="RBM2", **NORTH_ZONE_POLICY),
            ZONE_ADMIN_HEADERS,
        )
        second = validate_success(response, 201)
        assertions.assert_fields(
            second,
            zone_code="RBM2",
            name="Riverbend North",
            status="DRAFT",
            version=1,
        )
        assert second["detour_tolerance_pct"] == pytest.approx(0.30, abs=0.01)
        assert second["id"] != first["id"]

        rows, meta = validate_paginated(
            api_client.list_service_zones(ZONE_ADMIN_HEADERS)
        )
        assert meta["total_count"] == 2
        assertions.assert_contains_ids(rows, first["id"], second["id"])
        assert {row["zone_code"] for row in rows} == {"RBM", "RBM2"}


# ---------------------------------------------------------------------------
# Virtual-stop pairing validity
# ---------------------------------------------------------------------------


def _two_zones_with_a_retired_and_a_cross_zone_stop() -> dict:
    """Zones RBM-A and RBM-B, both ACTIVE. Zone A holds an APPROVED stop A1 and a
    RETIRED stop A9; zone B holds an APPROVED stop B1."""
    fixtures.set_clock(constants.CLOCK_STARTUP_UTC, headers=ZONE_ADMIN_HEADERS)
    zone_a = fixtures.create_active_zone(name="Riverbend A", zone_code="RBM-A")
    zone_b = fixtures.create_active_zone(name="Riverbend B", zone_code="RBM-B")
    stop_a1 = fixtures.create_approved_stop(zone_a["id"], "A1", 1)
    stop_a9 = fixtures.create_stop(zone_a["id"], "A9", 9)
    stop_a9 = fixtures.retire_stop(stop_a9["id"])
    stop_b1 = fixtures.create_approved_stop(zone_b["id"], "B1", 1)
    return {
        "zone_a": zone_a,
        "zone_b": zone_b,
        "a1": stop_a1,
        "a9": stop_a9,
        "b1": stop_b1,
    }


class TestVirtualStopPairing:
    @pytest.mark.parametrize("partner", ["a9", "b1"])
    def test_paired_stop_that_is_retired_or_lives_in_another_zone_is_rejected(
        self, partner: str
    ) -> None:
        """A retired partner and a partner belonging to a different zone both fail
        the pairing check.

        PRD: "A stop may optionally name its opposite-direction twin across the street through `paired_stop_id`, which defaults to null; when supplied it must reference a virtual stop in the same zone whose `status` is not `RETIRED`, and it may not name the stop being created, with any of those three violations rejected as `ERR_PAIRED_STOP_INVALID`."

        Design: Corner/validations/paired_stop_must_be_a_live_stop_in_the_same_zone
        """
        state = _two_zones_with_a_retired_and_a_cross_zone_stop()
        assert state["a9"]["status"] == "RETIRED"
        assert state["b1"]["zone_id"] == state["zone_b"]["id"]

        response = api_client.create_virtual_stop(
            factories.virtual_stop_payload(
                state["zone_a"]["id"],
                "A2",
                2,
                paired_stop_id=state[partner]["id"],
            ),
            ZONE_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_PAIRED_STOP_INVALID.value, 422)

        rows, meta = validate_paginated(
            api_client.list_virtual_stops(
                ZONE_ADMIN_HEADERS, params={"zone_id": state["zone_a"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assertions.assert_excludes_ids(rows, state["b1"]["id"])

    def test_paired_stop_reference_that_resolves_to_nothing_is_a_not_found(
        self,
    ) -> None:
        """An unresolvable `paired_stop_id` is answered by the reference check, not
        by the pairing check.

        PRD: "The same twelve codes are reused when a foreign key supplied in a request body fails to resolve; in that case the fields are checked in the order the endpoint declares its inputs, so the first unresolvable reference in declared order decides the code."

        Design: Corner/validations/paired_stop_must_be_a_live_stop_in_the_same_zone
        """
        state = _two_zones_with_a_retired_and_a_cross_zone_stop()

        response = api_client.create_virtual_stop(
            factories.virtual_stop_payload(
                state["zone_a"]["id"],
                "A2",
                2,
                paired_stop_id=constants.ABSENT_UUID,
            ),
            ZONE_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_VIRTUAL_STOP_NOT_FOUND.value, 404)

    def test_paired_stop_that_is_live_and_in_the_same_zone_is_accepted(self) -> None:
        """Pairing to an approved stop of the same zone is stored as given.

        PRD: "A stop may optionally name its opposite-direction twin across the street through `paired_stop_id`, which defaults to null; when supplied it must reference a virtual stop in the same zone whose `status` is not `RETIRED`, and it may not name the stop being created, with any of those three violations rejected as `ERR_PAIRED_STOP_INVALID`."

        Design: Corner/validations/paired_stop_must_be_a_live_stop_in_the_same_zone
        """
        state = _two_zones_with_a_retired_and_a_cross_zone_stop()

        response = api_client.create_virtual_stop(
            factories.virtual_stop_payload(
                state["zone_a"]["id"],
                "A2",
                2,
                paired_stop_id=state["a1"]["id"],
            ),
            ZONE_ADMIN_HEADERS,
        )
        created = validate_success(response, 201)
        assertions.assert_fields(
            created,
            zone_id=state["zone_a"]["id"],
            stop_code="A2",
            corridor_index=2,
            paired_stop_id=state["a1"]["id"],
            status="PROPOSED",
            version=1,
        )

        rows, meta = validate_paginated(
            api_client.list_virtual_stops(
                ZONE_ADMIN_HEADERS, params={"zone_id": state["zone_a"]["id"]}
            )
        )
        assert meta["total_count"] == 3
        assertions.assert_contains_ids(
            rows, state["a1"]["id"], state["a9"]["id"], created["id"]
        )


# ---------------------------------------------------------------------------
# Subsidy reporting period ordering
# ---------------------------------------------------------------------------


def _active_zone_with_no_operations() -> dict:
    """An ACTIVE zone with no blocks and no trips, so every report total is 0."""
    fixtures.set_clock("2026-08-10T00:00:00Z", headers=ZONE_ADMIN_HEADERS)
    return fixtures.create_active_zone()


class TestReportPeriodOrdering:
    def test_report_period_ending_before_it_starts_is_rejected(self) -> None:
        """A reversed reporting period never opens a report.

        PRD: "An end date earlier than the start date is rejected with `ERR_REPORT_PERIOD_INVALID`."

        Design: Corner/validations/report_period_end_before_start_is_rejected
        """
        zone = _active_zone_with_no_operations()

        response = api_client.create_subsidy_report(
            factories.subsidy_report_payload(
                zone["id"],
                period_start_date="2026-08-05",
                period_end_date="2026-08-04",
                variant="PROVISIONAL",
            ),
            FINANCE_ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_REPORT_PERIOD_INVALID.value, 422)

        _rows, meta = validate_paginated(
            api_client.list_subsidy_reports(
                FINANCE_ANALYST_HEADERS, params={"zone_id": zone["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_single_day_report_period_is_accepted(self) -> None:
        """A period whose end equals its start is a legal one-day report.

        PRD: "An end date earlier than the start date is rejected with `ERR_REPORT_PERIOD_INVALID`."

        Design: Corner/validations/report_period_end_before_start_is_rejected
        """
        zone = _active_zone_with_no_operations()

        response = api_client.create_subsidy_report(
            factories.subsidy_report_payload(
                zone["id"],
                period_start_date="2026-08-05",
                period_end_date="2026-08-05",
                variant="PROVISIONAL",
            ),
            FINANCE_ANALYST_HEADERS,
        )
        report = validate_success(response, 201)
        assertions.assert_report_state(report, "DRAFT")
        assertions.assert_fields(
            report,
            zone_id=zone["id"],
            period_start_date="2026-08-05",
            period_end_date="2026-08-05",
            variant="PROVISIONAL",
            amendment_count=0,
            total_trips=0,
            total_fare_revenue_cents=0,
            total_operating_cost_cents=0,
            subsidy_per_trip_cents=0,
            version=1,
        )
        assertions.assert_null_fields(
            report, "submitted_by_user_id", "certified_by_user_id", "rejection_reason"
        )

        _rows, meta = validate_paginated(
            api_client.list_subsidy_reports(
                FINANCE_ANALYST_HEADERS, params={"zone_id": zone["id"]}
            )
        )
        assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Reporting-period overlap keys on (zone_id, variant)
# ---------------------------------------------------------------------------


class TestReportPeriodOverlapKey:
    def test_final_report_may_cover_the_same_days_as_a_live_provisional_report(
        self,
    ) -> None:
        """The other variant's identical period, and a disjoint period of the same
        variant, are both accepted.

        PRD: "A period that overlaps the inclusive date range of another report for the same `zone_id` and the same `variant` whose `state` is `DRAFT`, `SUBMITTED`, `CERTIFIED` or `AMENDED` is rejected with `ERR_REPORT_PERIOD_OVERLAP` — a report already superseded or rejected does not block a new filing, and the two variants are tracked independently, so a provisional and a final report may cover the same days."

        Design: Corner/validations/reports_of_different_variants_may_share_a_period_but_same_variant_may_not
        """
        zone = _active_zone_with_no_operations()
        provisional = fixtures.create_report(
            zone["id"],
            period_start_date="2026-08-03",
            period_end_date="2026-08-05",
            variant="PROVISIONAL",
        )

        final_response = api_client.create_subsidy_report(
            factories.subsidy_report_payload(
                zone["id"],
                period_start_date="2026-08-03",
                period_end_date="2026-08-05",
                variant="FINAL",
            ),
            FINANCE_ANALYST_HEADERS,
        )
        final = validate_success(final_response, 201)
        assertions.assert_fields(final, variant="FINAL", state="DRAFT")
        assert provisional["variant"] == "PROVISIONAL"

        disjoint_response = api_client.create_subsidy_report(
            factories.subsidy_report_payload(
                zone["id"],
                period_start_date="2026-08-06",
                period_end_date="2026-08-07",
                variant="PROVISIONAL",
            ),
            FINANCE_ANALYST_HEADERS,
        )
        disjoint = validate_success(disjoint_response, 201)
        assertions.assert_report_state(disjoint, "DRAFT")

        _rows, meta = validate_paginated(
            api_client.list_subsidy_reports(
                FINANCE_ANALYST_HEADERS,
                params={"zone_id": zone["id"], "variant": "PROVISIONAL"},
            )
        )
        assert meta["total_count"] == 2

    def test_second_provisional_report_touching_the_period_by_one_day_is_rejected(
        self,
    ) -> None:
        """Sharing a single inclusive day with a DRAFT report of the same variant is
        an overlap.

        PRD: "A period that overlaps the inclusive date range of another report for the same `zone_id` and the same `variant` whose `state` is `DRAFT`, `SUBMITTED`, `CERTIFIED` or `AMENDED` is rejected with `ERR_REPORT_PERIOD_OVERLAP` — a report already superseded or rejected does not block a new filing, and the two variants are tracked independently, so a provisional and a final report may cover the same days."

        Design: Corner/validations/reports_of_different_variants_may_share_a_period_but_same_variant_may_not
        """
        zone = _active_zone_with_no_operations()
        provisional = fixtures.create_report(
            zone["id"],
            period_start_date="2026-08-03",
            period_end_date="2026-08-05",
            variant="PROVISIONAL",
        )
        assertions.assert_report_state(provisional, "DRAFT")

        response = api_client.create_subsidy_report(
            factories.subsidy_report_payload(
                zone["id"],
                period_start_date="2026-08-05",
                period_end_date="2026-08-07",
                variant="PROVISIONAL",
            ),
            FINANCE_ANALYST_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP.value, 409)

        _rows, meta = validate_paginated(
            api_client.list_subsidy_reports(
                FINANCE_ANALYST_HEADERS,
                params={"zone_id": zone["id"], "variant": "PROVISIONAL"},
            )
        )
        assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# The walking-distance standard, enforced at approval
# ---------------------------------------------------------------------------


def _zone_with_edge_and_over_walk_sheds() -> dict:
    """An ACTIVE zone whose standard is 600 metres, holding one PROPOSED stop that
    advertises exactly 600 metres and one that advertises 601."""
    fixtures.set_clock(constants.CLOCK_STARTUP_UTC, headers=ZONE_ADMIN_HEADERS)
    zone = fixtures.create_active_zone()
    assert zone["max_walk_meters"] == 600
    edge = fixtures.create_stop(zone["id"], "SEDGE", 3, walk_shed_meters=600)
    over = fixtures.create_stop(zone["id"], "SOVER", 5, walk_shed_meters=601)
    return {"zone": zone, "edge": edge, "over": over}


class TestWalkShedStandard:
    def test_walk_shed_one_metre_over_the_standard_cannot_be_approved(self) -> None:
        """A 601-metre walk shed is stored at create and refused at approval.

        PRD: "A stop advertising more is rejected with `ERR_WALK_DISTANCE_EXCEEDED`."

        Design: Corner/validations/walk_shed_at_the_zone_standard_is_approved_and_one_meter_over_is_not
        """
        state = _zone_with_edge_and_over_walk_sheds()
        assertions.assert_fields(
            state["over"], walk_shed_meters=601, status="PROPOSED", version=1
        )

        response = api_client.approve_virtual_stop(
            state["over"]["id"], ZONE_ADMIN_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_WALK_DISTANCE_EXCEEDED.value, 422)

        after = fixtures.refresh_stop(state["over"]["id"])
        assertions.assert_fields(after, status="PROPOSED")
        assertions.assert_version_unchanged(state["over"], after)

    def test_walk_shed_exactly_at_the_standard_is_approved(self) -> None:
        """A walk shed equal to the zone standard clears the inclusive comparison.

        PRD: "A `ZoneAdmin` moves a stop `PROPOSED → APPROVED` only while the stop is still `PROPOSED`, only while its zone is in `DRAFT` or `ACTIVE`, and only when the stop's `walk_shed_meters` is less than or equal to the zone's `max_walk_meters` — the comparison is inclusive, so a stop advertising exactly the standard is approvable."

        Design: Corner/validations/walk_shed_at_the_zone_standard_is_approved_and_one_meter_over_is_not
        """
        state = _zone_with_edge_and_over_walk_sheds()

        response = api_client.approve_virtual_stop(
            state["edge"]["id"], ZONE_ADMIN_HEADERS
        )
        approved = validate_success(response, 200)
        assertions.assert_fields(approved, walk_shed_meters=600, status="APPROVED")
        assertions.assert_version_advanced(state["edge"], approved)


# ---------------------------------------------------------------------------
# Accessible path at both ends of a wheelchair-accessible trip
# ---------------------------------------------------------------------------


def _zone_with_a_stairs_only_destination() -> dict:
    """An ACTIVE zone whose S0 has an accessible path and whose S4 is stairs only;
    both stops are APPROVED. One rider declares a wheelchair, the other does not."""
    fixtures.set_clock("2026-08-03T06:00:00Z", headers=ZONE_ADMIN_HEADERS)
    zone = fixtures.create_active_zone()
    origin = fixtures.create_approved_stop(
        zone["id"], "S0", 0, accessibility="ACCESSIBLE_PATH"
    )
    destination = fixtures.create_approved_stop(
        zone["id"], "S4", 4, accessibility="STAIRS_ONLY"
    )
    wheelchair_rider = fixtures.create_rider(
        zone["id"], "RW", fare_category="FULL", mobility_device="WHEELCHAIR"
    )
    ambulatory_rider = fixtures.create_rider(
        zone["id"], "RN", fare_category="FULL", mobility_device="NONE"
    )
    return {
        "zone": zone,
        "origin": origin,
        "destination": destination,
        "wheelchair_rider": wheelchair_rider,
        "ambulatory_rider": ambulatory_rider,
    }


class TestAccessiblePathAtBothEnds:
    @pytest.mark.parametrize("source_of_the_flag", ["rider_declaration", "request_body"])
    def test_wav_trip_into_a_stairs_only_stop_is_rejected(
        self, source_of_the_flag: str
    ) -> None:
        """Whether the accessible handling comes from the rider's declared device or
        from the request body, a stairs-only end blocks intake.

        PRD: "When the effective `wav_required` is true, both the origin and the destination stop must have `accessibility` equal to `ACCESSIBLE_PATH`; a stop that is `STAIRS_ONLY` or `UNKNOWN` is rejected with `ERR_STOP_NOT_ACCESSIBLE`."

        Design: Corner/validations/wav_trip_requires_accessible_path_at_both_ends
        """
        state = _zone_with_a_stairs_only_destination()
        assert state["destination"]["accessibility"] == "STAIRS_ONLY"
        assert state["destination"]["status"] == "APPROVED"

        if source_of_the_flag == "rider_declaration":
            rider = state["wheelchair_rider"]
            extra = {}
        else:
            rider = state["ambulatory_rider"]
            extra = {"wav_required": True}

        response = api_client.create_trip_request(
            factories.trip_request_payload(
                state["zone"]["id"],
                rider["id"],
                state["origin"]["id"],
                state["destination"]["id"],
                requested_pickup_utc="2026-08-03T07:00:00Z",
                party_size=1,
                **extra,
            ),
            make_rider_headers(rider["id"]),
        )
        validate_error(response, ApiErrorId.ERR_STOP_NOT_ACCESSIBLE.value, 409)

        _rows, meta = validate_paginated(
            api_client.list_trip_requests(
                DISPATCHER_HEADERS, params={"zone_id": state["zone"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_ambulatory_rider_may_use_the_same_stairs_only_stop_pair(self) -> None:
        """With the effective flag false, the accessibility of the stops is not
        examined at all.

        PRD: "The effective wheelchair-accessible flag is then resolved and stored on the trip as `wav_required`: it is true when the request body supplied `wav_required` as true **or** when the rider's `mobility_device` is `WHEELCHAIR`."

        Design: Corner/validations/wav_trip_requires_accessible_path_at_both_ends
        """
        state = _zone_with_a_stairs_only_destination()
        rider = state["ambulatory_rider"]

        response = api_client.create_trip_request(
            factories.trip_request_payload(
                state["zone"]["id"],
                rider["id"],
                state["origin"]["id"],
                state["destination"]["id"],
                requested_pickup_utc="2026-08-03T07:00:00Z",
                party_size=1,
            ),
            make_rider_headers(rider["id"]),
        )
        trip = validate_success(response, 201)
        assertions.assert_trip_state(trip, "RECEIVED", "UNPRICED")
        assertions.assert_fields(
            trip,
            rider_id=rider["id"],
            wav_required=False,
            party_size=1,
            match_attempt_count=0,
            baseline_direct_minutes=12,
            version=1,
        )

        _rows, meta = validate_paginated(
            api_client.list_trip_requests(
                DISPATCHER_HEADERS, params={"zone_id": state["zone"]["id"]}
            )
        )
        assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# The half-open block window on manual dispatch
# ---------------------------------------------------------------------------


def _open_block_with_three_pickup_instants() -> dict:
    """An ACTIVE zone with stops S0 and S2 approved, one block OPEN over
    06:00Z-10:00Z, and three trips wanting pickups at 10:00Z, 06:00Z and 09:59Z."""
    fixtures.set_clock("2026-08-03T06:00:00Z", headers=ZONE_ADMIN_HEADERS)
    zone = fixtures.create_active_zone()
    origin = fixtures.create_approved_stop(zone["id"], "S0", 0)
    destination = fixtures.create_approved_stop(zone["id"], "S2", 2)
    vehicle = fixtures.create_vehicle(zone["id"], "V1", seat_capacity=6, wav_positions=2)
    driver = fixtures.create_driver(zone["id"], "D1", wav_certified=True)
    rider = fixtures.create_rider(
        zone["id"], "R1", fare_category="FULL", mobility_device="NONE"
    )
    block = fixtures.create_block(
        zone["id"],
        vehicle["id"],
        driver["id"],
        block_type="BASE",
        start_utc="2026-08-03T06:00:00Z",
        end_utc="2026-08-03T10:00:00Z",
    )
    block = fixtures.open_block(block["id"])

    def trip_at(instant: str) -> dict:
        return fixtures.create_trip(
            zone["id"],
            rider["id"],
            origin["id"],
            destination["id"],
            requested_pickup_utc=instant,
            party_size=1,
        )

    return {
        "zone": zone,
        "block": block,
        "at_end": trip_at("2026-08-03T10:00:00Z"),
        "at_start": trip_at("2026-08-03T06:00:00Z"),
        "one_minute_before_end": trip_at("2026-08-03T09:59:00Z"),
    }


class TestPickupInsideTheBlockWindow:
    def test_pickup_exactly_at_the_block_end_cannot_be_dispatched(self) -> None:
        """The exclusive end of the window rejects a pickup that lands on it.

        PRD: "The trip's `requested_pickup_utc` must fall inside the block's half-open window, at or after its start and strictly before its end, with a violation reported as `ERR_PICKUP_OUTSIDE_BLOCK_WINDOW`."

        Design: Corner/validations/requested_pickup_must_fall_inside_the_half_open_block_window
        """
        state = _open_block_with_three_pickup_instants()
        block = state["block"]

        response = api_client.create_pool_assignment(
            factories.pool_assignment_payload(
                state["at_end"]["id"], block["id"], block["version"]
            ),
            DISPATCHER_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_PICKUP_OUTSIDE_BLOCK_WINDOW.value, 422)

        # A rejected offer writes nothing, so the dispatcher's block version is
        # still the current one and the trip is untouched.
        after_block = fixtures.refresh_block(block["id"])
        assertions.assert_version_unchanged(block, after_block)
        assertions.assert_block_commitments(
            after_block,
            seats_committed=0,
            wav_positions_committed=0,
            committed_index_min=None,
            committed_index_max=None,
        )

        trip = fixtures.refresh_trip(state["at_end"]["id"])
        assertions.assert_trip_state(trip, "RECEIVED", "UNPRICED")
        assertions.assert_null_fields(
            trip, "assigned_block_id", "projected_detour_minutes", "promised_pickup_utc"
        )

        _rows, meta = validate_paginated(
            api_client.list_pool_assignments(
                DISPATCHER_HEADERS, params={"block_id": block["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_pickup_at_the_block_start_and_one_minute_before_its_end_are_dispatched(
        self,
    ) -> None:
        """The inclusive start and the last minute inside the window are both
        offerable onto the block.

        PRD: "The trip's `requested_pickup_utc` must fall inside the block's half-open window, at or after its start and strictly before its end, with a violation reported as `ERR_PICKUP_OUTSIDE_BLOCK_WINDOW`."

        Design: Corner/validations/requested_pickup_must_fall_inside_the_half_open_block_window
        """
        state = _open_block_with_three_pickup_instants()
        block = state["block"]

        at_start_response = api_client.create_pool_assignment(
            factories.pool_assignment_payload(
                state["at_start"]["id"], block["id"], block["version"]
            ),
            DISPATCHER_HEADERS,
        )
        at_start_assignment = validate_success(at_start_response, 201)
        assertions.assert_assignment_state(at_start_assignment, "OFFERED")
        assertions.assert_fields(
            at_start_assignment,
            block_id=block["id"],
            trip_request_id=state["at_start"]["id"],
            seats_held=1,
            offer_origin="MANUAL_DISPATCH",
            match_score=None,
        )
        assertions.assert_instant_equals(
            fixtures.refresh_trip(state["at_start"]["id"])["promised_pickup_utc"],
            "2026-08-03T06:00:00Z",
        )

        refreshed_block = fixtures.refresh_block(block["id"])
        assertions.assert_version_advanced(block, refreshed_block)

        last_minute_response = api_client.create_pool_assignment(
            factories.pool_assignment_payload(
                state["one_minute_before_end"]["id"],
                block["id"],
                refreshed_block["version"],
            ),
            DISPATCHER_HEADERS,
        )
        last_minute_assignment = validate_success(last_minute_response, 201)
        assertions.assert_assignment_state(last_minute_assignment, "OFFERED")

        settled_block = fixtures.refresh_block(block["id"])
        assertions.assert_block_commitments(
            settled_block,
            seats_committed=2,
            wav_positions_committed=0,
            committed_index_min=0,
            committed_index_max=2,
        )


# ---------------------------------------------------------------------------
# The guaranteed transfer buffer at intake
# ---------------------------------------------------------------------------


def _zone_with_a_rail_departure_at_seven() -> dict:
    """An ACTIVE zone with stops S0 and S2 approved and a RAIL departure at 07:00Z
    from S0 carrying a ten-minute guaranteed transfer buffer."""
    fixtures.set_clock("2026-08-03T06:00:00Z", headers=ZONE_ADMIN_HEADERS)
    zone = fixtures.create_active_zone()
    origin = fixtures.create_approved_stop(zone["id"], "S0", 0)
    destination = fixtures.create_approved_stop(zone["id"], "S2", 2)
    connection = fixtures.create_connection(
        zone["id"],
        origin["id"],
        mode="RAIL",
        route_code="ORANGE-IB",
        scheduled_departure_utc="2026-08-03T07:00:00Z",
        guaranteed_transfer_buffer_minutes=10,
        transfer_credit_cents=80,
    )
    rider = fixtures.create_rider(
        zone["id"], "R1", fare_category="FULL", mobility_device="NONE"
    )
    return {
        "zone": zone,
        "origin": origin,
        "destination": destination,
        "connection": connection,
        "rider": rider,
    }


def _request_trip(state: dict, instant: str, **extra):
    return api_client.create_trip_request(
        factories.trip_request_payload(
            state["zone"]["id"],
            state["rider"]["id"],
            state["origin"]["id"],
            state["destination"]["id"],
            requested_pickup_utc=instant,
            party_size=1,
            **extra,
        ),
        make_rider_headers(state["rider"]["id"]),
    )


class TestGuaranteedTransferBuffer:
    def test_pickup_one_minute_past_the_buffer_edge_is_rejected(self) -> None:
        """Eleven minutes after a departure with a ten-minute buffer misses the
        guaranteed transfer.

        PRD: "Finally, when a `connection_id` is supplied, the requested pickup must actually be able to make that departure: the absolute difference between `requested_pickup_utc` and the connection's `scheduled_departure_utc` must be less than or equal to that connection's `guaranteed_transfer_buffer_minutes`, inclusively, and a pickup further away than the buffer is rejected with `ERR_TRANSFER_WINDOW_MISSED`."

        Design: Corner/validations/guaranteed_transfer_window_is_inclusive_at_the_buffer_edge
        """
        state = _zone_with_a_rail_departure_at_seven()
        assertions.assert_fields(
            state["connection"],
            guaranteed_transfer_buffer_minutes=10,
            transfer_credit_cents=80,
            mode="RAIL",
        )

        response = _request_trip(
            state, "2026-08-03T07:11:00Z", connection_id=state["connection"]["id"]
        )
        validate_error(response, ApiErrorId.ERR_TRANSFER_WINDOW_MISSED.value, 422)

        _rows, meta = validate_paginated(
            api_client.list_trip_requests(
                DISPATCHER_HEADERS, params={"zone_id": state["zone"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    @pytest.mark.parametrize(
        "instant", ["2026-08-03T07:10:00Z", "2026-08-03T06:50:00Z"]
    )
    def test_pickup_exactly_at_the_buffer_edge_on_either_side_is_accepted(
        self, instant: str
    ) -> None:
        """Ten minutes after and ten minutes before the departure both sit inside
        the inclusive buffer.

        PRD: "Finally, when a `connection_id` is supplied, the requested pickup must actually be able to make that departure: the absolute difference between `requested_pickup_utc` and the connection's `scheduled_departure_utc` must be less than or equal to that connection's `guaranteed_transfer_buffer_minutes`, inclusively, and a pickup further away than the buffer is rejected with `ERR_TRANSFER_WINDOW_MISSED`."

        Design: Corner/validations/guaranteed_transfer_window_is_inclusive_at_the_buffer_edge
        """
        state = _zone_with_a_rail_departure_at_seven()

        response = _request_trip(
            state, instant, connection_id=state["connection"]["id"]
        )
        trip = validate_success(response, 201)
        assertions.assert_trip_state(trip, "RECEIVED", "UNPRICED")
        assertions.assert_fields(
            trip, connection_id=state["connection"]["id"], baseline_direct_minutes=6
        )
        assertions.assert_instant_equals(trip["requested_pickup_utc"], instant)

    def test_unlinked_trip_beyond_the_buffer_is_accepted(self) -> None:
        """With no `connection_id` supplied there is no departure to make, so the
        buffer rule never runs.

        PRD: "Finally, when a `connection_id` is supplied, the requested pickup must actually be able to make that departure: the absolute difference between `requested_pickup_utc` and the connection's `scheduled_departure_utc` must be less than or equal to that connection's `guaranteed_transfer_buffer_minutes`, inclusively, and a pickup further away than the buffer is rejected with `ERR_TRANSFER_WINDOW_MISSED`."

        Design: Corner/validations/guaranteed_transfer_window_is_inclusive_at_the_buffer_edge
        """
        state = _zone_with_a_rail_departure_at_seven()

        response = _request_trip(state, "2026-08-03T07:11:00Z")
        trip = validate_success(response, 201)
        assertions.assert_trip_state(trip, "RECEIVED", "UNPRICED")
        assertions.assert_null_fields(trip, "connection_id")

        _rows, meta = validate_paginated(
            api_client.list_trip_requests(
                DISPATCHER_HEADERS, params={"zone_id": state["zone"]["id"]}
            )
        )
        assert meta["total_count"] == 1
