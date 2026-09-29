"""Formulas whose intermediate rounding and saturation are observable.

A quarterly settlement rounds three times on the way to one total, and an audit
risk score adds four independently capped factors before a single final round.
Both are wrong if the order of operations is rearranged.
"""
import pytest

from test_helpers.assertions import (
    assert_carrier_compliance,
    assert_gallons,
    assert_jurisdiction_line,
    assert_money,
    assert_audit_selection,
    assert_return_settlement,
    assert_trip_state,
    by_code,
    codes_of,
)
from test_helpers.constants import JURISDICTION_IL, WEIGHT_GROUP_FEES_W80
from test_helpers.factories import leg
from test_helpers.fixtures import (
    accept_trip,
    capture_trip,
    carrier_with_vehicle,
    create_carrier,
    create_vehicle,
    open_return,
    prepare_return,
    read_carrier,
    read_return,
    read_trip,
    record_purchase,
    return_lines,
    reconstruct_trip,
    score_audit_selection,
    seed_reference_data,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    PREPARER_1_HEADERS,
)


@pytest.fixture
def prepared_quarter_with_mixed_positions(client):
    """A Q2-2026 quarter whose three jurisdictions land in three different
    positions: Illinois in credit, Indiana in credit on base tax but owing a
    surcharge, and Kentucky owing outright.

    Mileage: 700.0 and 800.0 accepted telematics trips, a 500.0-mile trip behind
    a 100.0-mile odometer gap reconstructed to 600.0 and accepted, and a
    700.0-mile trip left gap-flagged outside the settlement. Fuel: 175.000 IL,
    80.000 IN, 30.000 KY, all receipted.
    """
    ctx = carrier_with_vehicle(
        client,
        unit_number="U-201",
        vin="1FUJA6CK21L300201",
        factory_price_amount=158000.00,
        carrier_overrides={
            "legal_name": "Rounding Order Transport LLC",
            "usdot_number": "USDOT-2637020",
            "base_jurisdiction_code": "IL",
            "bond_ceiling_amount": 5000.00,
        },
    )
    carrier_id, vehicle_id = ctx["carrier_id"], ctx["vehicle_id"]

    t1 = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        "2026-04-10T06:00:00Z",
        "2026-04-10T18:00:00Z",
        100000.0,
        100700.0,
        [leg("IL", 300.0), leg("IN", 200.0), leg("KY", 200.0)],
    )
    accept_trip(client, t1["id"], headers=OFFICER_1_HEADERS)

    t2 = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        "2026-05-05T06:00:00Z",
        "2026-05-05T20:00:00Z",
        100700.0,
        101500.0,
        [leg("IL", 400.0), leg("IN", 250.0), leg("KY", 150.0)],
    )
    accept_trip(client, t2["id"], headers=OFFICER_1_HEADERS)

    t3 = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        "2026-06-02T06:00:00Z",
        "2026-06-02T16:00:00Z",
        101600.0,
        102100.0,
        [leg("IL", 300.0), leg("KY", 200.0)],
    )
    reconstruct_trip(
        client,
        t3["id"],
        [leg("IL", 250.0), leg("KY", 350.0)],
        "RECON-2026-06-02-B",
        headers=ANALYST_1_HEADERS,
    )
    accept_trip(client, t3["id"], headers=OFFICER_1_HEADERS)

    capture_trip(
        client,
        carrier_id,
        vehicle_id,
        "2026-06-20T06:00:00Z",
        "2026-06-20T18:00:00Z",
        102200.0,
        102900.0,
        [leg("IL", 700.0)],
    )

    record_purchase(
        client,
        carrier_id,
        vehicle_id,
        "IL",
        "2026-04-11",
        175.000,
        receipt_reference="RCPT-IL-2-0411",
    )
    record_purchase(
        client,
        carrier_id,
        vehicle_id,
        "IN",
        "2026-05-06",
        80.000,
        receipt_reference="RCPT-IN-2-0506",
    )
    record_purchase(
        client,
        carrier_id,
        vehicle_id,
        "KY",
        "2026-06-03",
        30.000,
        receipt_reference="RCPT-KY-2-0603",
    )

    opened = open_return(client, carrier_id, 2026, 2, headers=PREPARER_1_HEADERS)
    prepared = prepare_return(
        client, opened["id"], carrier_id, headers=PREPARER_1_HEADERS
    )
    return {
        "carrier_id": carrier_id,
        "vehicle_id": vehicle_id,
        "return_id": opened["id"],
        "prepared": prepared,
    }


class TestRoundedFleetMpgDrivesEveryLine:
    """The quarter's MPG is rounded once and then used as a rounded figure by
    every jurisdiction line."""

    def test_fleet_mpg_is_rounded_to_two_places_before_any_line_divides_by_it(
        self, client, prepared_quarter_with_mixed_positions
    ):
        """"The return's `fleet_mpg` is `total_fleet_miles` divided by
        `total_tax_paid_gallons`, rounded to 2 decimal places. That rounded value
        — and not the raw quotient — is what every jurisdiction's taxable miles
        are subsequently divided by." 2100.0 over 285.000 is 7.368421..., which
        settles at 7.37, and every line's `taxable_gallons` follows from 7.37.

        Design: Difficulty/combinatorial_formula/net_tax_total_rounds_each_jurisdiction_line_before_summing
        """
        ctx = prepared_quarter_with_mixed_positions
        assert_return_settlement(
            ctx["prepared"],
            return_status="PREPARED",
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=2100.0,
            total_tax_paid_gallons=285.000,
            fleet_mpg=7.37,
        )

        lines = return_lines(client, ctx["return_id"], line_status="ACTIVE")
        assert_gallons(by_code(lines, "IL")["taxable_gallons"], 128.901, "IL gallons")
        assert_gallons(by_code(lines, "IN")["taxable_gallons"], 61.058, "IN gallons")
        assert_gallons(by_code(lines, "KY")["taxable_gallons"], 94.980, "KY gallons")

    def test_the_lines_are_written_one_per_jurisdiction_in_code_order(
        self, client, prepared_quarter_with_mixed_positions
    ):
        """"One `ReturnJurisdictionLine` is written for every jurisdiction that
        appears either in the quarter's mileage or in the quarter's accepted
        purchases, iterated in `jurisdiction_code` ascending order, each carrying
        the `fuel_tax_return_id` of its parent return, its `jurisdiction_code`,
        and `line_status` set to `ACTIVE`." The
        gap-flagged trip's 700.0 Illinois miles are not accepted mileage, so
        Illinois carries 950.0 rather than 1650.0.

        Design: Difficulty/combinatorial_formula/net_tax_total_rounds_each_jurisdiction_line_before_summing
        """
        lines = return_lines(
            client, prepared_quarter_with_mixed_positions["return_id"], line_status="ACTIVE"
        )
        assert codes_of(lines) == ["IL", "IN", "KY"], codes_of(lines)
        assert_jurisdiction_line(lines[0], taxable_miles=950.0, tax_paid_gallons=175.000)
        assert_jurisdiction_line(lines[1], taxable_miles=450.0, tax_paid_gallons=80.000)
        assert_jurisdiction_line(lines[2], taxable_miles=700.0, tax_paid_gallons=30.000)

    def test_the_surcharge_rides_full_taxable_gallons_while_base_tax_rides_the_net(
        self, client, prepared_quarter_with_mixed_positions
    ):
        """"The surcharge is assessed on full taxable gallons and is **never**
        offset by `tax_paid_gallons`, because surcharge fuel tax is not collected
        at the pump — the carrier owes it in full on every gallon it burned in
        that jurisdiction regardless of where it bought fuel." Indiana burned 61.058 gallons and bought 80.000, so its
        base tax is a 6.25 credit while its surcharge is the full 33.58, and
        "`net_tax_amount` is `base_tax_amount` plus `surcharge_amount`, rounded
        to 2 decimal places."

        Design: Difficulty/combinatorial_formula/net_tax_total_rounds_each_jurisdiction_line_before_summing
        """
        lines = return_lines(
            client, prepared_quarter_with_mixed_positions["return_id"], line_status="ACTIVE"
        )
        assert_jurisdiction_line(
            by_code(lines, "IL"),
            taxable_gallons=128.901,
            net_taxable_gallons=-46.099,
            base_tax_amount=-28.90,
            surcharge_amount=0.00,
            net_tax_amount=-28.90,
        )
        assert_jurisdiction_line(
            by_code(lines, "IN"),
            taxable_gallons=61.058,
            net_taxable_gallons=-18.942,
            base_tax_amount=-6.25,
            surcharge_amount=33.58,
            net_tax_amount=27.33,
        )
        assert_jurisdiction_line(
            by_code(lines, "KY"),
            taxable_gallons=94.980,
            net_taxable_gallons=64.980,
            base_tax_amount=15.99,
            surcharge_amount=4.18,
            net_tax_amount=20.17,
        )


class TestTotalSumsAlreadyRoundedLines:
    """Summing rounded lines and rounding a raw sum give different money here,
    and only one of them is the contract."""

    def test_total_net_tax_due_sums_the_rounded_lines_rather_than_re_deriving(
        self, client, prepared_quarter_with_mixed_positions
    ):
        """"`total_net_tax_due` is the sum of the `net_tax_amount` values of the
        return's `ACTIVE` lines — each already rounded to 2 decimal places,
        summed as-is, never re-derived from a full-precision aggregate."
        -28.90 + 27.33 + 20.17 is 18.60; re-deriving the same quarter from
        full-precision gallons and rounding once at the end yields 18.59.

        Design: Difficulty/combinatorial_formula/net_tax_total_rounds_each_jurisdiction_line_before_summing
        """
        ctx = prepared_quarter_with_mixed_positions
        settled = read_return(client, ctx["return_id"])
        assert_money(settled["total_net_tax_due"], 18.60, "total_net_tax_due")

        lines = return_lines(client, ctx["return_id"], line_status="ACTIVE")
        assert_money(
            sum(line["net_tax_amount"] for line in lines),
            settled["total_net_tax_due"],
            "sum of the ACTIVE line amounts",
        )

    def test_the_penalty_and_the_amount_due_stack_on_the_line_wise_total(
        self, client, prepared_quarter_with_mixed_positions
    ):
        """"If `total_fleet_miles` is 0.0 the return's
        `reconstructed_mileage_ratio` is 0.0000; otherwise it is the
        reconstructed miles divided by `total_fleet_miles`, rounded to 4 decimal
        places. When that ratio is **strictly greater** than one tenth — greater
        than 0.1000 — the `reconstruction_penalty_amount` is the larger of a
        hundred-dollar floor and one tenth of the quarter's net tax due:
        specifically, take `total_net_tax_due` or 0.00, whichever is larger,
        multiply by 0.10, round to 2 decimal places, and then take whichever is
        larger of that figure and 100.00." 600.0 of 2100.0 miles is
        0.2857, and one tenth of 18.60 is far under the floor, so the penalty is
        100.00 and "`total_amount_due` is `total_net_tax_due` plus
        `reconstruction_penalty_amount`, rounded to 2 decimal places."

        Design: Difficulty/combinatorial_formula/net_tax_total_rounds_each_jurisdiction_line_before_summing
        """
        settled = read_return(
            client, prepared_quarter_with_mixed_positions["return_id"]
        )
        assert_return_settlement(
            settled,
            reconstructed_mileage_ratio=0.2857,
            total_net_tax_due=18.60,
            reconstruction_penalty_amount=100.00,
            total_amount_due=118.60,
        )


@pytest.fixture
def carrier_at_thirty_percent_unsubstantiated(client):
    """One carrier operating only in Illinois whose two trips leave exactly
    three tenths of its distance unsubstantiated, and which has never had a
    return prepared.

    The second trip starts 60.0 miles past where the first ended, so it is born
    gap-flagged and its 300.0 miles are the unsubstantiated numerator against a
    1000.0-mile denominator.
    """
    seed_reference_data(
        client,
        jurisdictions=[JURISDICTION_IL],
        fees=[f for f in WEIGHT_GROUP_FEES_W80 if f["jurisdiction_code"] == "IL"],
    )
    carrier = create_carrier(
        client,
        legal_name="Threshold Edge Hauling Co",
        usdot_number="USDOT-2637030",
        base_jurisdiction_code="IL",
        bond_ceiling_amount=5000.00,
    )
    vehicle = create_vehicle(
        client,
        carrier["id"],
        unit_number="U-301",
        vin="1FUJA6CK21L300301",
        factory_price_amount=152000.00,
        registration_year=2026,
    )
    first = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-04-15T06:00:00Z",
        "2026-04-15T18:00:00Z",
        300000.0,
        300700.0,
        [leg("IL", 700.0)],
    )
    second = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-05-15T06:00:00Z",
        "2026-05-15T14:00:00Z",
        300760.0,
        301060.0,
        [leg("IL", 300.0)],
    )
    return {
        "carrier_id": carrier["id"],
        "vehicle_id": vehicle["id"],
        "first_trip_id": first["id"],
        "second_trip_id": second["id"],
    }


class TestRiskScoreFactorsSaturateIndependently:
    """Four capped factors are added at full precision and rounded once, and the
    sum lands on the inclusive selection threshold."""

    def test_the_gap_flagged_trip_sets_the_ratio_that_feeds_the_first_factor(
        self, client, carrier_at_thirty_percent_unsubstantiated
    ):
        """"the numerator is the sum of `odometer_delta_miles` over all of that
        carrier's trips whose `trip_status` is `GAP_FLAGGED` or
        `RECONSTRUCTED`; the denominator is the sum of `odometer_delta_miles`
        over all of that carrier's trips whose `trip_status` is anything other
        than `REJECTED`." 300.0 over 1000.0 is 0.3000, which is "**strictly
        greater** than fifteen hundredths — that is, greater than 0.1500", so the
        carrier already carries an audit flag.

        Design: Difficulty/combinatorial_formula/audit_risk_score_saturating_min_max_lands_on_inclusive_threshold
        """
        ctx = carrier_at_thirty_percent_unsubstantiated
        assert_trip_state(
            read_trip(client, ctx["first_trip_id"]),
            trip_status="CAPTURED",
            odometer_delta_miles=700.0,
        )
        assert_trip_state(
            read_trip(client, ctx["second_trip_id"]),
            trip_status="GAP_FLAGGED",
            gap_miles_from_previous=60.0,
            odometer_delta_miles=300.0,
        )
        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            unsubstantiated_mileage_ratio=0.3000,
            audit_flag=True,
            latest_prepared_fleet_mpg=None,
        )

    def test_the_four_factors_add_to_exactly_seventy_and_the_record_is_selected(
        self, client, carrier_at_thirty_percent_unsubstantiated
    ):
        """"take the carrier's `unsubstantiated_mileage_ratio`, divide it by a
        saturation ratio of 0.25, cap the quotient at 1, and multiply by 40",
        "if that field is null, because no return of the carrier has ever been
        prepared, this factor contributes exactly 0 rather than saturating",
        "The late-filing factor contributes 5 points per late filing" and
        "divide `retention_deficiency_count` by a saturation count of 4, cap the
        quotient at 1, and multiply by 20" give 40 + 0 + 10 + 20. "When
        `risk_score` reaches the selection threshold of 70 — the comparison is
        inclusive, so exactly 70 selects — the record is born `SELECTED` rather
        than `SCORED`, and the carrier's `audit_flag` is set to true with the
        carrier's `version` incrementing by 1."

        Design: Difficulty/combinatorial_formula/audit_risk_score_saturating_min_max_lands_on_inclusive_threshold
        """
        ctx = carrier_at_thirty_percent_unsubstantiated
        selection = score_audit_selection(
            client,
            ctx["carrier_id"],
            selection_year=2026,
            selection_quarter=2,
            late_filing_count=2,
            retention_deficiency_count=4,
            headers=OFFICER_2_HEADERS,
        )
        assert_audit_selection(
            selection,
            risk_score=70,
            selection_status="SELECTED",
            expected_records_count=None,
            records_missing_count=None,
            retention_deficiency_ratio=None,
            post_review_risk_score=None,
            reviewed_by_user_id=None,
        )

    def test_the_retention_factor_scales_below_its_saturation_count(
        self, client, carrier_at_thirty_percent_unsubstantiated
    ):
        """"The retention factor contributes up to 20 points: divide
        `retention_deficiency_count` by a saturation count of 4, cap the quotient
        at 1, and multiply by 20." Three deficiencies contribute 15 rather than
        20, dropping the same carrier to 65, and "When `risk_score` falls below
        70 the record is born `NOT_SELECTED` and nothing outside the record
        changes."

        Design: Difficulty/combinatorial_formula/audit_risk_score_saturating_min_max_lands_on_inclusive_threshold
        """
        ctx = carrier_at_thirty_percent_unsubstantiated
        selection = score_audit_selection(
            client,
            ctx["carrier_id"],
            selection_year=2026,
            selection_quarter=3,
            late_filing_count=2,
            retention_deficiency_count=3,
            headers=OFFICER_2_HEADERS,
        )
        assert_audit_selection(selection, risk_score=65, selection_status="NOT_SELECTED")

    def test_the_late_filing_factor_counts_at_most_three_filings(
        self, client, carrier_at_thirty_percent_unsubstantiated
    ):
        """"The late-filing factor contributes 5 points per late filing, counting
        at most three of them, for up to 15 points." Five late filings are worth
        the same 15 as three, so with the ratio factor saturated at 40 and no
        retention deficiencies the score is 55.

        Design: Difficulty/combinatorial_formula/audit_risk_score_saturating_min_max_lands_on_inclusive_threshold
        """
        ctx = carrier_at_thirty_percent_unsubstantiated
        selection = score_audit_selection(
            client,
            ctx["carrier_id"],
            selection_year=2026,
            selection_quarter=4,
            late_filing_count=5,
            retention_deficiency_count=0,
            headers=OFFICER_2_HEADERS,
        )
        assert_audit_selection(selection, risk_score=55, selection_status="NOT_SELECTED")
