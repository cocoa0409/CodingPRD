"""The exact values either side of a threshold.

Both thresholds below are strict, so landing on the number is a different
outcome from landing one representable step past it — once on a one-decimal
mileage scale, once on a four-decimal ratio that gates a flat penalty.
"""
import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_INVALID_TRIP_STATE
from test_helpers.assertions import (
    assert_carrier_compliance,
    assert_jurisdiction_line,
    assert_money,
    assert_return_settlement,
    assert_trip_state,
    by_code,
    codes_of,
)
from test_helpers.constants import JURISDICTION_IL
from test_helpers.factories import leg
from test_helpers.fixtures import (
    accept_trip,
    capture_trip,
    create_carrier,
    create_vehicle,
    open_return,
    prepare_return,
    read_carrier,
    read_trip,
    reconstruct_trip,
    record_purchase,
    return_lines,
    seed_reference_data,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    PREPARER_1_HEADERS,
)


@pytest.fixture
def three_trips_straddling_the_gap_tolerance(client):
    """One unit's odometer chain: a baseline trip, then a trip opening a gap of
    exactly 5.0 miles, then a trip opening a gap of 5.1 miles.

    All three cover 600.0 miles of their own, so the only difference between the
    second and third outcomes is the tenth of a mile in the gap.
    """
    seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
    carrier = create_carrier(
        client,
        legal_name="Tolerance Edge Trucking LLC",
        usdot_number="USDOT-2637100",
        base_jurisdiction_code="IL",
        bond_ceiling_amount=5000.00,
    )
    vehicle = create_vehicle(
        client,
        carrier["id"],
        unit_number="U-1001",
        vin="1FUJA6CK21L701001",
        factory_price_amount=148000.00,
        registration_year=2026,
    )
    baseline = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-04-02T06:00:00Z",
        "2026-04-02T18:00:00Z",
        810000.0,
        810600.0,
        [leg("IL", 600.0)],
    )
    at_tolerance = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-04-09T06:00:00Z",
        "2026-04-09T18:00:00Z",
        810605.0,
        811205.0,
        [leg("IL", 600.0)],
    )
    carrier_after_tolerance = read_carrier(client, carrier["id"])
    over_tolerance = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-04-16T06:00:00Z",
        "2026-04-16T18:00:00Z",
        811210.1,
        811810.1,
        [leg("IL", 600.0)],
    )
    return {
        "carrier_id": carrier["id"],
        "vehicle_id": vehicle["id"],
        "baseline": baseline,
        "at_tolerance": at_tolerance,
        "over_tolerance": over_tolerance,
        "carrier_after_tolerance": carrier_after_tolerance,
    }


class TestGapToleranceIsStrictlyGreaterThan:
    """Exactly five miles of unexplained distance is tolerated; five and a tenth
    is not."""

    def test_a_gap_of_exactly_five_miles_leaves_the_trip_captured(
        self, client, three_trips_straddling_the_gap_tolerance
    ):
        """"If `gap_miles_from_previous` is **strictly greater** than the
        five-mile gap tolerance, the trip is born `GAP_FLAGGED` ... A gap of
        exactly 5.0 miles is tolerated; 5.1 is flagged." The baseline trip is the
        vehicle's first, so "If no such trip exists, `gap_miles_from_previous` is
        0.0."

        Design: Difficulty/boundary_precision_check/gap_of_exactly_five_miles_stays_captured_and_five_point_one_flags
        """
        ctx = three_trips_straddling_the_gap_tolerance
        assert_trip_state(
            ctx["baseline"],
            trip_status="CAPTURED",
            mileage_source="TELEMATICS",
            gap_miles_from_previous=0.0,
            odometer_delta_miles=600.0,
        )
        assert_trip_state(
            ctx["at_tolerance"],
            trip_status="CAPTURED",
            mileage_source="TELEMATICS",
            gap_miles_from_previous=5.0,
            odometer_delta_miles=600.0,
            accepted_leg_miles_total=600.0,
        )

    def test_a_gap_of_five_point_one_miles_flags_the_trip(
        self, client, three_trips_straddling_the_gap_tolerance
    ):
        """"`gap_miles_from_previous` is the new trip's `start_odometer` minus the
        predecessor's `end_odometer`, rounded to 1 decimal place." 811210.1 less
        811205.0 is 5.1, which is strictly greater than the tolerance.

        Design: Difficulty/boundary_precision_check/gap_of_exactly_five_miles_stays_captured_and_five_point_one_flags
        """
        ctx = three_trips_straddling_the_gap_tolerance
        assert_trip_state(
            ctx["over_tolerance"],
            trip_status="GAP_FLAGGED",
            mileage_source="TELEMATICS",
            gap_miles_from_previous=5.1,
            odometer_delta_miles=600.0,
        )

    def test_only_the_tenth_of_a_mile_moves_the_carrier_s_exposure(
        self, client, three_trips_straddling_the_gap_tolerance
    ):
        """"the numerator is the sum of `odometer_delta_miles` over all of that
        carrier's trips whose `trip_status` is `GAP_FLAGGED` or `RECONSTRUCTED`;
        the denominator is the sum of `odometer_delta_miles` over all of that
        carrier's trips whose `trip_status` is anything other than `REJECTED`."
        Both trips contributed the same 600.0 miles, yet only the flagged one
        enters the numerator, at which point 600.0 of 1800.0 is "**strictly
        greater** than fifteen hundredths".

        Design: Difficulty/boundary_precision_check/gap_of_exactly_five_miles_stays_captured_and_five_point_one_flags
        """
        ctx = three_trips_straddling_the_gap_tolerance
        assert_carrier_compliance(
            ctx["carrier_after_tolerance"],
            unsubstantiated_mileage_ratio=0.0000,
            audit_flag=False,
        )
        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            unsubstantiated_mileage_ratio=0.3333,
            audit_flag=True,
        )

    def test_the_tolerated_trip_may_be_accepted_and_the_flagged_one_may_not(
        self, client, three_trips_straddling_the_gap_tolerance
    ):
        """"Accepting a `CAPTURED` trip moves it `CAPTURED → ACCEPTED`. This is
        permitted only while `gap_miles_from_previous` is no greater than the
        five-mile tolerance, and only while the trip's vehicle has a
        `vehicle_status` other than the terminal `TRANSFERRED` — a unit that has
        left the fleet on a transfer cannot have new distance admitted against
        it, and an attempt to do so is refused with `ERR_INVALID_TRIP_STATE`."
        The flagged trip has no accept outcome at all, so the same decision is
        refused on it.

        Design: Difficulty/boundary_precision_check/gap_of_exactly_five_miles_stays_captured_and_five_point_one_flags
        """
        ctx = three_trips_straddling_the_gap_tolerance
        accepted = validate_success(
            client.review_trip_record(
                ctx["at_tolerance"]["id"], OFFICER_1_HEADERS, decision="ACCEPT"
            )
        )
        assert_trip_state(accepted, trip_status="ACCEPTED")

        refused = client.review_trip_record(
            ctx["over_tolerance"]["id"], OFFICER_1_HEADERS, decision="ACCEPT"
        )
        validate_error(refused, ERR_INVALID_TRIP_STATE)
        assert_trip_state(
            read_trip(client, ctx["over_tolerance"]["id"]), trip_status="GAP_FLAGGED"
        )

        flagged = client.list_trip_records(
            OFFICER_1_HEADERS,
            params={"vehicle_id": ctx["vehicle_id"], "trip_status": "GAP_FLAGGED"},
        ).json()["data"]
        assert [row["id"] for row in flagged] == [ctx["over_tolerance"]["id"]], flagged


def _prepare_ten_percent_quarter(
    client,
    usdot_number,
    unit_number,
    vin,
    gap_miles,
    reconstructed_il_miles,
    receipt_suffix,
):
    """A Q2-2026 quarter whose only reconstruction is sized to land the
    reconstructed-mileage ratio on or just past one tenth.

    An accepted 1800.0-mile telematics trip is followed by a 140.0-mile trip that
    starts `gap_miles` past where the first ended, so it is born gap-flagged and
    is reconstructed to `odometer_delta_miles` plus the gap before being accepted.
    The quarter's fuel is fixed at 250.000 tax-paid gallons.
    """
    carrier = create_carrier(
        client,
        legal_name="Ten Percent Haulage Inc",
        usdot_number=usdot_number,
        base_jurisdiction_code="IL",
        bond_ceiling_amount=5000.00,
    )
    vehicle = create_vehicle(
        client,
        carrier["id"],
        unit_number=unit_number,
        vin=vin,
        factory_price_amount=147000.00,
        registration_year=2026,
    )
    long_haul = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-04-05T05:00:00Z",
        "2026-04-06T05:00:00Z",
        200000.0,
        201800.0,
        [leg("IL", 900.0), leg("IN", 500.0), leg("KY", 400.0)],
    )
    accept_trip(client, long_haul["id"], headers=OFFICER_1_HEADERS)

    short_haul = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-05-20T06:00:00Z",
        "2026-05-20T12:00:00Z",
        201800.0 + gap_miles,
        201940.0 + gap_miles,
        [leg("IL", 90.0), leg("KY", 50.0)],
    )
    flagged = read_trip(client, short_haul["id"])
    reconstruct_trip(
        client,
        short_haul["id"],
        [leg("IL", reconstructed_il_miles), leg("KY", 80.0)],
        "RECON-D2" + receipt_suffix,
        headers=ANALYST_1_HEADERS,
    )
    accept_trip(client, short_haul["id"], headers=OFFICER_1_HEADERS)

    for code, date, gallons in (
        ("IL", "2026-04-06", 150.000),
        ("IN", "2026-04-07", 70.000),
        ("KY", "2026-05-21", 30.000),
    ):
        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            code,
            date,
            gallons,
            receipt_reference="RCPT-%s-A2-%s%s" % (code, date.replace("-", "")[4:], receipt_suffix),
        )

    opened = open_return(client, carrier["id"], 2026, 2, headers=PREPARER_1_HEADERS)
    prepared = prepare_return(
        client, opened["id"], carrier["id"], headers=PREPARER_1_HEADERS
    )
    return {
        "carrier_id": carrier["id"],
        "vehicle_id": vehicle["id"],
        "trip_id": short_haul["id"],
        "flagged": flagged,
        "return_id": opened["id"],
        "prepared": prepared,
    }


@pytest.fixture
def quarter_reconstructed_to_exactly_one_tenth(client):
    """A prepared Q2-2026 quarter in which 200.0 of 2000.0 fleet miles came from
    an accepted reconstruction."""
    seed_reference_data(client)
    return _prepare_ten_percent_quarter(
        client,
        usdot_number="USDOT-2637110",
        unit_number="U-1101",
        vin="1FUJA6CK21L701101",
        gap_miles=60.0,
        reconstructed_il_miles=120.0,
        receipt_suffix="",
    )


class TestReconstructionPenaltyThresholdIsStrictlyGreaterThan:
    """A ratio of exactly 0.1000 is free; the next representable ratio costs the
    whole hundred-dollar floor."""

    def test_a_ratio_of_exactly_one_tenth_attracts_no_penalty(
        self, client, quarter_reconstructed_to_exactly_one_tenth
    ):
        """"When the ratio is 0.1000 or below there is no penalty and
        `reconstruction_penalty_amount` is 0.00. Because the comparison is strict,
        a ratio of exactly 0.1000 attracts nothing while 0.1001 attracts at least
        the full floor." 200.0 reconstructed miles over 2000.0 fleet miles is
        0.1000, so "`total_amount_due` is `total_net_tax_due` plus
        `reconstruction_penalty_amount`" adds nothing.

        Design: Difficulty/boundary_precision_check/reconstructed_mileage_ratio_exactly_ten_percent_attracts_no_penalty
        """
        ctx = quarter_reconstructed_to_exactly_one_tenth
        assert_return_settlement(
            ctx["prepared"],
            return_status="PREPARED",
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=2000.0,
            reconstructed_mileage_ratio=0.1000,
            total_net_tax_due=27.81,
            reconstruction_penalty_amount=0.00,
            total_amount_due=27.81,
        )

    def test_the_quarter_behind_the_boundary_settles_as_an_ordinary_quarter(
        self, client, quarter_reconstructed_to_exactly_one_tenth
    ):
        """"The trips that count are those of the return's carrier whose
        `trip_status` is `ACCEPTED` and whose `trip_start_utc` falls inside the
        quarter window." An accepted reconstruction is one of them, and on this
        basis it is not uplifted at all -- "on the preparer basis every trip's
        factor is 1.000" -- so its legs are settled miles like any other:
        1020.0 Illinois miles at a `fleet_mpg` of 8.00 against 250.000 tax-paid
        gallons.

        Design: Difficulty/boundary_precision_check/reconstructed_mileage_ratio_exactly_ten_percent_attracts_no_penalty
        """
        ctx = quarter_reconstructed_to_exactly_one_tenth
        assert_trip_state(
            ctx["flagged"],
            trip_status="GAP_FLAGGED",
            gap_miles_from_previous=60.0,
            odometer_delta_miles=140.0,
        )
        assert_trip_state(
            read_trip(client, ctx["trip_id"]),
            trip_status="ACCEPTED",
            mileage_source="MANUAL_RECONSTRUCTION",
            accepted_leg_miles_total=200.0,
            supporting_document_reference="RECON-D2",
        )
        assert_return_settlement(
            ctx["prepared"],
            total_fleet_miles=2000.0,
            total_tax_paid_gallons=250.000,
            fleet_mpg=8.00,
        )

        lines = return_lines(client, ctx["return_id"], line_status="ACTIVE")
        assert codes_of(lines) == ["IL", "IN", "KY"], codes_of(lines)
        assert_jurisdiction_line(
            by_code(lines, "IL"),
            taxable_miles=1020.0,
            taxable_gallons=127.500,
            tax_paid_gallons=150.000,
            net_tax_amount=-14.11,
        )
        assert_jurisdiction_line(
            by_code(lines, "IN"),
            taxable_miles=500.0,
            taxable_gallons=62.500,
            tax_paid_gallons=70.000,
            net_tax_amount=31.90,
        )
        assert_jurisdiction_line(
            by_code(lines, "KY"),
            taxable_miles=480.0,
            taxable_gallons=60.000,
            tax_paid_gallons=30.000,
            net_tax_amount=10.02,
        )
        assert_money(
            sum(line["net_tax_amount"] for line in lines),
            27.81,
            "sum of the ACTIVE line amounts",
        )

    def test_five_more_reconstructed_miles_add_the_entire_hundred_dollar_floor(
        self, client
    ):
        """"When that ratio is **strictly greater** than one tenth — greater than
        0.1000 — the `reconstruction_penalty_amount` is the larger of a
        hundred-dollar floor and one tenth of the quarter's net tax due:
        specifically, take `total_net_tax_due` or 0.00, whichever is larger,
        multiply by 0.10, round to 2 decimal places, and then take whichever is
        larger of that figure and 100.00." A gap of
        65.0 miles forces a 205.0-mile reconstruction, and 205.0 over 2005.0 is
        0.1022. The net tax due happens to settle at the same 27.81 on the
        rearranged mileage, so the 100.00 comes purely from crossing the line.

        Design: Difficulty/boundary_precision_check/reconstructed_mileage_ratio_exactly_ten_percent_attracts_no_penalty
        """
        seed_reference_data(client)
        ctx = _prepare_ten_percent_quarter(
            client,
            usdot_number="USDOT-2637111",
            unit_number="U-1102",
            vin="1FUJA6CK21L701102",
            gap_miles=65.0,
            reconstructed_il_miles=125.0,
            receipt_suffix="-B",
        )
        assert_return_settlement(
            ctx["prepared"],
            total_fleet_miles=2005.0,
            total_tax_paid_gallons=250.000,
            fleet_mpg=8.02,
            reconstructed_mileage_ratio=0.1022,
            total_net_tax_due=27.81,
            reconstruction_penalty_amount=100.00,
            total_amount_due=127.81,
        )

        lines = return_lines(client, ctx["return_id"], line_status="ACTIVE")
        assert_jurisdiction_line(by_code(lines, "IL"), taxable_miles=1025.0, net_tax_amount=-13.92)
        assert_jurisdiction_line(by_code(lines, "IN"), taxable_miles=500.0, net_tax_amount=31.76)
        assert_jurisdiction_line(by_code(lines, "KY"), taxable_miles=480.0, net_tax_amount=9.97)
