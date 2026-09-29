"""Two contended timelines with deliberately opposite interval geometry.

A vehicle's timeline is half-open and unbuffered, so back-to-back trips are
legal. A driver's hands hold closed windows expanded by a two-day buffer on
each side, so windows that look disjoint on the paperwork still collide.
"""
import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_DRIVER_CREDENTIAL_WINDOW_CONFLICT,
    ERR_TRIP_INTERVAL_OVERLAP,
)
from test_helpers.assertions import (
    assert_carrier_compliance,
    assert_credential_state,
    assert_trip_state,
    assert_vehicle_dimensions,
)
from test_helpers.constants import JURISDICTION_IL
from test_helpers.factories import leg, trip_record_payload
from test_helpers.fixtures import (
    add_schedule_lines,
    capture_trip,
    create_carrier,
    create_driver,
    create_vehicle,
    credentials_for_vehicle,
    distribute_credential,
    invoice_application,
    issue_credentials,
    open_application,
    read_carrier,
    read_trip,
    read_vehicle,
    reject_trip,
    seed_reference_data,
    seed_reference_data_il_in_only,
    submit_application,
    trip_legs,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    PREPARER_1_HEADERS,
)


@pytest.fixture
def vehicle_with_one_occupied_interval(client):
    """One Illinois unit whose timeline is occupied from 06:00 to 18:00 on
    2026-04-10, covering 600.0 miles from odometer 100000.0 to 100600.0."""
    seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
    carrier = create_carrier(
        client,
        legal_name="Half Open Interval Trucking LLC",
        usdot_number="USDOT-2637140",
        base_jurisdiction_code="IL",
        bond_ceiling_amount=5000.00,
    )
    vehicle = create_vehicle(
        client,
        carrier["id"],
        unit_number="U-1401",
        vin="1FUJA6CK21L901401",
        factory_price_amount=146000.00,
        registration_year=2026,
    )
    occupied = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-04-10T06:00:00Z",
        "2026-04-10T18:00:00Z",
        100000.0,
        100600.0,
        [leg("IL", 600.0)],
    )
    return {
        "carrier_id": carrier["id"],
        "vehicle_id": vehicle["id"],
        "occupied_id": occupied["id"],
    }


class TestVehicleTripIntervalsAreHalfOpenAndUnbuffered:
    """Adjacency is free on a vehicle's timeline, and rejection hands the
    interval back."""

    def test_a_trip_starting_at_the_instant_the_previous_one_ended_is_adjacent(
        self, client, vehicle_with_one_occupied_interval
    ):
        """"The new trip's interval runs from `trip_start_utc` inclusive to
        `trip_end_utc` exclusive ... There is no buffer: a trip that starts at
        exactly the instant the previous one ended is adjacent, not overlapping,
        and is accepted." Its odometer also continues from exactly where the
        previous trip stopped, so "If no such trip exists,
        `gap_miles_from_previous` is 0.0" is not the only way to reach 0.0.

        Design: Difficulty/resource_temporal_overlap/vehicle_trip_intervals_are_half_open_so_adjacency_is_allowed
        """
        ctx = vehicle_with_one_occupied_interval
        adjacent = capture_trip(
            client,
            ctx["carrier_id"],
            ctx["vehicle_id"],
            "2026-04-10T18:00:00Z",
            "2026-04-11T02:00:00Z",
            100600.0,
            100900.0,
            [leg("IL", 300.0)],
        )
        assert_trip_state(
            adjacent,
            trip_status="CAPTURED",
            mileage_source="TELEMATICS",
            gap_miles_from_previous=0.0,
            odometer_delta_miles=300.0,
        )
        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            unsubstantiated_mileage_ratio=0.0000,
            audit_flag=False,
        )

    def test_one_second_of_overlap_is_refused_and_writes_no_trip_row(
        self, client, vehicle_with_one_occupied_interval
    ):
        """"it may not overlap the interval of any existing trip of the same
        `vehicle_id` whose `trip_status` is anything other than `REJECTED` ... Any
        true overlap is refused with `ERR_TRIP_INTERVAL_OVERLAP`." Starting one
        second before the occupied interval closes is a true overlap, and the
        refusal happens before any odometer arithmetic, so no row appears.

        Design: Difficulty/resource_temporal_overlap/vehicle_trip_intervals_are_half_open_so_adjacency_is_allowed
        """
        ctx = vehicle_with_one_occupied_interval
        capture_trip(
            client,
            ctx["carrier_id"],
            ctx["vehicle_id"],
            "2026-04-10T18:00:00Z",
            "2026-04-11T02:00:00Z",
            100600.0,
            100900.0,
            [leg("IL", 300.0)],
        )

        response = client.create_trip_record(
            trip_record_payload(
                ctx["carrier_id"],
                ctx["vehicle_id"],
                trip_start_utc="2026-04-10T17:59:59Z",
                trip_end_utc="2026-04-11T03:00:00Z",
                start_odometer=100900.0,
                end_odometer=101200.0,
                legs=[leg("IL", 300.0)],
            ),
            ANALYST_1_HEADERS,
        )
        validate_error(response, ERR_TRIP_INTERVAL_OVERLAP)

        rows = validate_success(
            client.list_trip_records(
                ANALYST_1_HEADERS, params={"vehicle_id": ctx["vehicle_id"]}
            )
        )
        assert len(rows) == 2, [row["trip_start_utc"] for row in rows]

    def test_rejecting_the_adjacent_trip_frees_its_interval_for_a_replacement(
        self, client, vehicle_with_one_occupied_interval
    ):
        """"it may not overlap the interval of any existing trip of the same
        `vehicle_id` whose `trip_status` is anything other than `REJECTED`", and
        "A rejected trip is gone from the mileage picture in both directions — it
        leaves the unsubstantiated numerator and the fleet-total denominator
        alike, and it is invisible to gap detection, so the odometer chain closes
        over it." The replacement therefore takes the freed window and measures
        its gap against the trip before the rejected one.

        Design: Difficulty/resource_temporal_overlap/vehicle_trip_intervals_are_half_open_so_adjacency_is_allowed
        """
        ctx = vehicle_with_one_occupied_interval
        adjacent = capture_trip(
            client,
            ctx["carrier_id"],
            ctx["vehicle_id"],
            "2026-04-10T18:00:00Z",
            "2026-04-11T02:00:00Z",
            100600.0,
            100900.0,
            [leg("IL", 300.0)],
        )
        reject_trip(client, adjacent["id"], headers=OFFICER_1_HEADERS)
        assert_trip_state(
            read_trip(client, adjacent["id"]), trip_status="REJECTED"
        )
        assert trip_legs(client, adjacent["id"], leg_status="ACTIVE") == []

        replacement = capture_trip(
            client,
            ctx["carrier_id"],
            ctx["vehicle_id"],
            "2026-04-10T18:00:00Z",
            "2026-04-11T02:00:00Z",
            100600.0,
            100900.0,
            [leg("IL", 300.0)],
        )
        assert_trip_state(
            replacement,
            trip_status="CAPTURED",
            gap_miles_from_previous=0.0,
            odometer_delta_miles=300.0,
        )
        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            unsubstantiated_mileage_ratio=0.0000,
            audit_flag=False,
        )
        rows = validate_success(
            client.list_trip_records(
                ANALYST_1_HEADERS, params={"vehicle_id": ctx["vehicle_id"]}
            )
        )
        assert len(rows) == 3, [row["trip_status"] for row in rows]


def _carrier_with_two_credential_windows(
    client,
    usdot_number,
    cdl_number,
    units,
    second_window_from,
):
    """A carrier holding two years of paper for one driver.

    The 2026 unit's credentials cover 2026-01-01 to 2026-06-29 and its decal set
    is already in the driver's hands; the second unit is registered for 2027 and
    its credentials open on ``second_window_from`` and run to 2027-06-30.
    """
    carrier = create_carrier(
        client,
        legal_name="Handover Buffer Haulers LLC",
        usdot_number=usdot_number,
        base_jurisdiction_code="IL",
        bond_ceiling_amount=9000.00,
    )
    driver = create_driver(
        client, carrier["id"], full_name="Otto Lindqvist", cdl_number=cdl_number
    )
    vehicles = {}
    for (unit_number, vin), year in zip(units, (2026, 2027)):
        vehicles[year] = create_vehicle(
            client,
            carrier["id"],
            unit_number=unit_number,
            vin=vin,
            factory_price_amount=145000.00,
            registration_year=year,
        )

    windows = {2026: ("2026-01-01", "2026-06-29"), 2027: (second_window_from, "2027-06-30")}
    applications = {}
    for year in (2026, 2027):
        application = open_application(
            client,
            carrier["id"],
            registration_year=year,
            distance_basis="ACTUAL_DISTANCE_BASIS",
            headers=PREPARER_1_HEADERS,
        )
        add_schedule_lines(
            client,
            application["id"],
            [("IL", 80000.0), ("IN", 20000.0)],
            headers=PREPARER_1_HEADERS,
        )
        submit_application(client, application["id"], headers=PREPARER_1_HEADERS)
        invoice_application(client, application["id"], headers=OFFICER_1_HEADERS)
        valid_from, valid_to = windows[year]
        issue_credentials(
            client,
            application["id"],
            headers=OFFICER_1_HEADERS,
            valid_from_date=valid_from,
            valid_to_date=valid_to,
        )
        applications[year] = application["id"]

    first_year_paper = credentials_for_vehicle(client, vehicles[2026]["id"])
    second_year_paper = credentials_for_vehicle(client, vehicles[2027]["id"])
    distribute_credential(client, first_year_paper["DECAL_SET"]["id"], driver["id"])
    return {
        "carrier_id": carrier["id"],
        "driver_id": driver["id"],
        "first_vehicle_id": vehicles[2026]["id"],
        "second_vehicle_id": vehicles[2027]["id"],
        "first_decal_id": first_year_paper["DECAL_SET"]["id"],
        "second_decal_id": second_year_paper["DECAL_SET"]["id"],
        "second_cab_card_id": second_year_paper["CAB_CARD"]["id"],
    }


@pytest.fixture
def driver_holding_paper_that_ends_two_clear_days_early(client):
    """A driver holding a decal set whose window closes 2026-06-29, offered a
    second decal set whose window opens 2026-07-02."""
    seed_reference_data_il_in_only(client)
    return _carrier_with_two_credential_windows(
        client,
        usdot_number="USDOT-2637150",
        cdl_number="CDL-IL-150001",
        units=[("U-1501", "1FUJA6CK21L901501"), ("U-1502", "1FUJA6CK21L901502")],
        second_window_from="2026-07-02",
    )


class TestDriverCredentialWindowsAreClosedAndBuffered:
    """Two clear days between two windows is not enough, and the whole test is
    scoped to one credential type."""

    def test_the_two_windows_are_disjoint_on_their_own_terms(
        self, client, driver_holding_paper_that_ends_two_clear_days_early
    ):
        """"Each credential's validity interval is a **closed** interval of whole
        calendar days: `valid_from_date` is the supplied value or, when omitted,
        the logical-clock date at issuance, and `valid_to_date` is the supplied
        value or, when omitted, December 31 of the credential's
        `registration_year`." Raw, the two windows do not touch: one ends
        2026-06-29 and the next opens 2026-07-02.

        Design: Difficulty/resource_temporal_overlap/driver_credential_windows_are_closed_and_buffered_by_two_days
        """
        ctx = driver_holding_paper_that_ends_two_clear_days_early
        first = credentials_for_vehicle(client, ctx["first_vehicle_id"])["DECAL_SET"]
        assert_credential_state(
            first,
            credential_type="DECAL_SET",
            credential_status="DISTRIBUTED",
            distributed_to_driver_id=ctx["driver_id"],
            valid_from_date="2026-01-01",
            valid_to_date="2026-06-29",
        )
        second = credentials_for_vehicle(client, ctx["second_vehicle_id"])["DECAL_SET"]
        assert_credential_state(
            second,
            credential_type="DECAL_SET",
            credential_status="ISSUED",
            distributed_to_driver_id=None,
            valid_from_date="2026-07-02",
            valid_to_date="2027-06-30",
        )

    def test_two_clear_days_still_conflicts_because_both_windows_are_expanded(
        self, client, driver_holding_paper_that_ends_two_clear_days_early
    ):
        """"The distribution is refused when, for any other `Credential` of the
        **same** `credential_type` already `DISTRIBUTED` to that same driver, the
        new credential's `valid_from_date` minus two days is on or before the other
        credential's `valid_to_date` plus two days, **and** the new credential's
        `valid_to_date` plus two days is on or after the other credential's
        `valid_from_date` minus two days ... a handover gap of exactly two clear
        days, or of exactly four, still conflicts."

        Design: Difficulty/resource_temporal_overlap/driver_credential_windows_are_closed_and_buffered_by_two_days
        """
        ctx = driver_holding_paper_that_ends_two_clear_days_early
        response = client.distribute_credential(
            ctx["second_decal_id"],
            OFFICER_1_HEADERS,
            distributed_to_driver_id=ctx["driver_id"],
        )
        validate_error(response, ERR_DRIVER_CREDENTIAL_WINDOW_CONFLICT)

        untouched = credentials_for_vehicle(client, ctx["second_vehicle_id"])["DECAL_SET"]
        assert_credential_state(
            untouched,
            credential_status="ISSUED",
            distributed_to_driver_id=None,
            distributed_at=None,
        )
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["second_vehicle_id"]), credential_status="ISSUED"
        )

    def test_the_buffer_test_is_scoped_to_one_credential_type(
        self, client, driver_holding_paper_that_ends_two_clear_days_early
    ):
        """"a credential of a different `credential_type` never conflicts, so the
        same driver may hold a decal set and a cab card covering the same dates."
        The cab card carries the very window the decal set was refused for and is
        handed over without complaint.

        Design: Difficulty/resource_temporal_overlap/driver_credential_windows_are_closed_and_buffered_by_two_days
        """
        ctx = driver_holding_paper_that_ends_two_clear_days_early
        handed_over = distribute_credential(
            client, ctx["second_cab_card_id"], ctx["driver_id"]
        )
        assert_credential_state(
            handed_over,
            credential_type="CAB_CARD",
            credential_status="DISTRIBUTED",
            distributed_to_driver_id=ctx["driver_id"],
            valid_from_date="2026-07-02",
            valid_to_date="2027-06-30",
        )

        held = validate_success(
            client.list_credentials(
                OFFICER_1_HEADERS, params={"distributed_to_driver_id": ctx["driver_id"]}
            )
        )
        assert sorted(row["credential_type"] for row in held) == [
            "CAB_CARD",
            "DECAL_SET",
        ], [row["credential_type"] for row in held]

    def test_five_clear_days_is_more_than_the_four_the_buffers_consume(
        self, client
    ):
        """"Because both windows are expanded and both endpoints are inclusive, two
        windows handed to one driver for one credential type need **more than four
        clear days** between them; a handover gap of exactly two clear days, or of
        exactly four, still conflicts." Opening the second window on 2026-07-05 leaves
        five clear days, so 2026-07-03 falls after 2026-07-01 and the same handover
        that was refused above goes through.

        Design: Difficulty/resource_temporal_overlap/driver_credential_windows_are_closed_and_buffered_by_two_days
        """
        seed_reference_data_il_in_only(client)
        ctx = _carrier_with_two_credential_windows(
            client,
            usdot_number="USDOT-2637151",
            cdl_number="CDL-IL-150002",
            units=[("U-1511", "1FUJA6CK21L901511"), ("U-1512", "1FUJA6CK21L901512")],
            second_window_from="2026-07-05",
        )
        handed_over = distribute_credential(
            client, ctx["second_decal_id"], ctx["driver_id"]
        )
        assert_credential_state(
            handed_over,
            credential_type="DECAL_SET",
            credential_status="DISTRIBUTED",
            distributed_to_driver_id=ctx["driver_id"],
            valid_from_date="2026-07-05",
            valid_to_date="2027-06-30",
        )
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["second_vehicle_id"]), credential_status="ISSUED"
        )
