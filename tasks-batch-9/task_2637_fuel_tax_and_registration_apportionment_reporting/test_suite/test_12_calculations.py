"""Arithmetic that only looks right until the inputs are chosen adversarially.

A quarter is settled from a filtered input set through a rounded intermediate,
its membership test is half-open at both ends of the calendar, a registration
fee is built from percentages that are deliberately left un-normalised, and an
odometer gap is measured against the trip that came before in time rather than
the one that arrived last.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_apportion_percent,
    assert_application_totals,
    assert_audit_selection,
    assert_carrier_compliance,
    assert_jurisdiction_line,
    assert_money,
    assert_return_settlement,
    assert_trip_state,
    by_code,
    codes_of,
)
from test_helpers.constants import JURISDICTION_IL
from test_helpers.factories import fuel_purchase_payload, leg
from test_helpers.fixtures import (
    accept_trip,
    add_schedule_lines,
    capture_trip,
    create_carrier,
    create_vehicle,
    invoice_application,
    open_application,
    open_return,
    prepare_return,
    read_application,
    read_carrier,
    read_purchase,
    read_trip,
    record_purchase,
    return_lines,
    schedule_lines,
    score_audit_selection,
    seed_reference_data,
    seed_reference_data_il_in_only,
    submit_application,
)
from test_helpers.test_users import ANALYST_1_HEADERS, OFFICER_1_HEADERS


def _carrier_with_one_unit(client):
    """One carrier and the single power unit that runs every trip below."""
    carrier = create_carrier(
        client,
        legal_name="Prairie Freight LLC",
        usdot_number="USDOT-2637001",
        base_jurisdiction_code="IL",
    )
    vehicle = create_vehicle(
        client,
        carrier["id"],
        unit_number="U-101",
        vin="1FUJA6CK21L101101",
        factory_price_amount=145000.00,
        registration_year=2026,
    )
    return carrier, vehicle


class TestTheSettlementReadsItsConstantsAsSignedDeviations:
    def test_a_fleet_at_exactly_the_industry_baseline_scores_zero(self, client):
        """"The return's `fleet_mpg` is `total_fleet_miles` divided by
        `total_tax_paid_gallons`, rounded to 2 decimal places."

        650.0 accepted miles over 100.000 accepted gallons is a fleet MPG of
        exactly 6.50 -- the industry baseline itself. The risk score reads that
        baseline as a signed deviation: "Where it is present, take the absolute
        difference between `latest_prepared_fleet_mpg` and an industry baseline
        of 6.50 miles per gallon, divide by that same 6.50 baseline to get a
        relative variance, divide the variance by a tolerated band of 0.20, cap
        the quotient at 1, and multiply by 25." A carrier sitting exactly on the
        baseline therefore contributes 0 points rather than being penalised for
        having been measured at all, and with no late filings and no retention
        deficiencies the whole score is 0. "When `risk_score` falls below 70 the
        record is born `NOT_SELECTED` and nothing outside the record changes."

        Design: Corner/calculations/fleet_mpg_exactly_at_the_industry_baseline_contributes_zero_to_the_risk_score
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier, vehicle = _carrier_with_one_unit(client)

        trip = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-04-05T06:00:00Z",
            trip_end_utc="2026-04-05T18:00:00Z",
            start_odometer=1000.0,
            end_odometer=1650.0,
            legs=[leg("IL", 650.0)],
        )
        accept_trip(client, trip["id"])
        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            "IL",
            "2026-05-02",
            100.000,
            receipt_reference="RCPT-IL-4471",
        )

        tax_return = open_return(client, carrier["id"], 2026, 2)
        prepared = prepare_return(client, tax_return["id"], carrier["id"])

        # 650.0 / 100.000 divides out exactly, with no rounding residue to hide
        # behind.
        assert_return_settlement(
            prepared,
            return_status="PREPARED",
            total_fleet_miles=650.0,
            total_tax_paid_gallons=100.000,
            fleet_mpg=6.50,
            total_net_tax_due=0.00,
            reconstruction_penalty_amount=0.00,
            total_amount_due=0.00,
        )

        # Every gallon burned in Illinois was bought there, so the line nets to
        # zero in gallons and therefore in dollars.
        lines = return_lines(client, tax_return["id"], line_status="ACTIVE")
        assert codes_of(lines) == ["IL"]
        assert_jurisdiction_line(
            by_code(lines, "IL"),
            taxable_miles=650.0,
            taxable_gallons=100.000,
            tax_paid_gallons=100.000,
            net_taxable_gallons=0.000,
            base_tax_amount=0.00,
            surcharge_amount=0.00,
            net_tax_amount=0.00,
        )

        assert_carrier_compliance(
            read_carrier(client, carrier["id"]),
            unsubstantiated_mileage_ratio=0.0000,
            audit_flag=False,
            latest_prepared_fleet_mpg=6.50,
        )

        selection = score_audit_selection(
            client,
            carrier["id"],
            selection_year=2026,
            selection_quarter=2,
            late_filing_count=0,
            retention_deficiency_count=0,
        )
        assert_audit_selection(
            selection, risk_score=0, selection_status="NOT_SELECTED"
        )


class TestOnlyAcceptedEvidenceEntersTheSettlement:
    def test_a_gap_flagged_trip_and_a_receipt_less_purchase_are_both_ignored(
        self, client
    ):
        """"The trips that count are those of the return's carrier whose
        `trip_status` is `ACCEPTED` and whose `trip_start_utc` falls inside the
        quarter window. `GAP_FLAGGED`, `RECONSTRUCTED`, `CAPTURED` and
        `REJECTED` trips contribute nothing."

        The fuel side filters just as hard: "For each jurisdiction,
        `tax_paid_gallons` on the line is the sum of `gallons` over the
        carrier's purchases whose `jurisdiction_code` is that jurisdiction,
        whose `purchase_status` is `ACCEPTED`, and whose `purchase_date` falls
        inside the quarter window, rounded to 3 decimal places. `RECORDED` and
        `DISALLOWED` purchases contribute zero." And a purchase never reaches
        `ACCEPTED` without its receipt: "A purchase missing its receipt, or one
        flagged as untaxed bulk fuel, stays `RECORDED` and contributes nothing
        to any figure — it is retained as a record, not as a credit."

        So a quarter holding 1300.0 miles of trips and 100.000 gallons of
        receipts settles on 400.0 miles and 40.000 gallons. Indiana then shows
        why the surcharge is not a second copy of the base tax: "`surcharge_amount`
        is, for a jurisdiction whose `is_surcharge_jurisdiction` is true, the
        line's **full** `taxable_gallons` multiplied by that jurisdiction's
        `surcharge_rate_per_gallon`, rounded to 2 decimal places."

        Design: Corner/calculations/settlement_excludes_gap_flagged_trips_and_receipt_less_purchases
        """
        seed_reference_data_il_in_only(client)
        carrier, vehicle = _carrier_with_one_unit(client)

        counted = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-04-05T06:00:00Z",
            trip_end_utc="2026-04-05T18:00:00Z",
            start_odometer=1000.0,
            end_odometer=1400.0,
            legs=[leg("IL", 300.0), leg("IN", 100.0)],
        )
        accept_trip(client, counted["id"])

        # 200.0 unaccounted miles between 1400.0 and 1600.0 flag this one, and
        # nobody reconstructs it.
        ignored_trip = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-05-10T06:00:00Z",
            trip_end_utc="2026-05-10T20:00:00Z",
            start_odometer=1600.0,
            end_odometer=2500.0,
            legs=[leg("IL", 900.0)],
        )
        assert_trip_state(
            ignored_trip,
            trip_status="GAP_FLAGGED",
            gap_miles_from_previous=200.0,
            odometer_delta_miles=900.0,
        )

        accepted_purchase = record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            "IL",
            "2026-05-02",
            40.000,
            receipt_reference="RCPT-IL-4471",
        )
        assert accepted_purchase["purchase_status"] == "ACCEPTED"

        no_receipt_payload = fuel_purchase_payload(
            carrier["id"],
            vehicle["id"],
            jurisdiction_code="IL",
            purchase_date="2026-05-04",
            gallons=60.000,
        )
        no_receipt_payload.pop("receipt_reference")
        ignored_purchase = validate_success(
            client.create_fuel_purchase(no_receipt_payload, ANALYST_1_HEADERS),
            expected_status=201,
        )
        assert ignored_purchase["purchase_status"] == "RECORDED"

        tax_return = open_return(client, carrier["id"], 2026, 2)
        prepared = prepare_return(client, tax_return["id"], carrier["id"])

        # 400.0 / 40.000 = 10.00, not 1300.0 / 100.000 = 13.00.
        assert_return_settlement(
            prepared,
            return_status="PREPARED",
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=400.0,
            total_tax_paid_gallons=40.000,
            fleet_mpg=10.00,
            total_net_tax_due=2.53,
            reconstruction_penalty_amount=0.00,
            total_amount_due=2.53,
        )

        lines = return_lines(client, tax_return["id"], line_status="ACTIVE")
        assert codes_of(lines) == ["IL", "IN"]
        # Illinois is a credit position: 30.000 gallons burned against 40.000
        # bought, and no surcharge to offset it.
        assert_jurisdiction_line(
            by_code(lines, "IL"),
            taxable_miles=300.0,
            taxable_gallons=30.000,
            tax_paid_gallons=40.000,
            net_taxable_gallons=-10.000,
            base_tax_amount=-6.27,
            surcharge_amount=0.00,
            net_tax_amount=-6.27,
        )
        # Indiana is owed base tax on 10.000 net gallons and surcharge on all
        # 10.000 taxable gallons.
        assert_jurisdiction_line(
            by_code(lines, "IN"),
            taxable_miles=100.0,
            taxable_gallons=10.000,
            tax_paid_gallons=0.000,
            net_taxable_gallons=10.000,
            base_tax_amount=3.30,
            surcharge_amount=5.50,
            net_tax_amount=8.80,
        )

        # The excluded rows are still on file, unchanged by the settlement.
        assert_trip_state(read_trip(client, ignored_trip["id"]), trip_status="GAP_FLAGGED")
        assert read_purchase(client, ignored_purchase["id"])["purchase_status"] == "RECORDED"
        assert read_purchase(client, ignored_purchase["id"])["receipt_reference"] is None
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]), tax_paid_gallons_ytd=40.000
        )


class TestTheQuarterWindowIsHalfOpen:
    def test_july_first_falls_into_the_next_quarter_for_trips_and_purchases_alike(
        self, client
    ):
        """"First quarter runs from January 1 up to but excluding April 1;
        second quarter from April 1 up to but excluding July 1; third quarter
        from July 1 up to but excluding October 1; and fourth quarter from
        October 1 of `filing_year` up to but excluding January 1 of the
        following year."

        Membership is decided by the opening instant on both sides of the
        ledger: "A trip belongs to the quarter when its `trip_start_utc` falls
        inside that window — the trip's end instant is irrelevant, so a trip
        that straddles a quarter boundary settles entirely in the quarter it
        began. A purchase belongs to the quarter when its `purchase_date` falls
        inside the same window on the same half-open basis."

        A trip running 2026-06-30T22:00:00Z to 23:00:00Z is inside Q2; the
        chronologically adjacent trip starting at exactly 2026-07-01T00:00:00Z
        is outside it, as is the purchase dated 2026-07-01. Both excluded rows
        are `ACCEPTED`, so only the boundary decides. Q2 therefore settles on
        100.0 miles and 8.000 gallons, not 300.0 and 13.000, and no third
        jurisdiction line appears.

        Design: Corner/calculations/the_quarter_window_is_half_open_so_july_first_falls_into_the_next_quarter
        """
        seed_reference_data_il_in_only(client)
        carrier, vehicle = _carrier_with_one_unit(client)

        inside_q2 = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-06-30T22:00:00Z",
            trip_end_utc="2026-06-30T23:00:00Z",
            start_odometer=1000.0,
            end_odometer=1100.0,
            legs=[leg("IL", 60.0), leg("IN", 40.0)],
        )
        accept_trip(client, inside_q2["id"])

        # Starts on the instant the window closes: adjacent to the Q2 trip, so
        # no odometer gap, but it belongs to Q3.
        starts_on_the_boundary = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-07-01T00:00:00Z",
            trip_end_utc="2026-07-01T01:00:00Z",
            start_odometer=1100.0,
            end_odometer=1300.0,
            legs=[leg("IL", 200.0)],
        )
        assert_trip_state(
            starts_on_the_boundary,
            trip_status="CAPTURED",
            gap_miles_from_previous=0.0,
        )
        accept_trip(client, starts_on_the_boundary["id"])

        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            "IL",
            "2026-06-30",
            8.000,
            receipt_reference="RCPT-IL-6630",
        )
        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            "IL",
            "2026-07-01",
            5.000,
            receipt_reference="RCPT-IL-7701",
        )

        tax_return = open_return(client, carrier["id"], 2026, 2)
        prepared = prepare_return(client, tax_return["id"], carrier["id"])

        # 100.0 / 8.000 = 12.50. Had the boundary row been swept in it would
        # have been 300.0 / 13.000 = 23.08.
        assert_return_settlement(
            prepared,
            return_status="PREPARED",
            total_fleet_miles=100.0,
            total_tax_paid_gallons=8.000,
            fleet_mpg=12.50,
            total_net_tax_due=0.81,
            total_amount_due=0.81,
        )

        lines, meta = validate_paginated(
            client.list_return_jurisdiction_lines(
                tax_return["id"], OFFICER_1_HEADERS, params={"line_status": "ACTIVE"}
            )
        )
        # The Q3 trip's Illinois leg contributed no third line, and its miles
        # did not swell the Illinois one.
        assert meta["total_count"] == 2
        assert codes_of(lines) == ["IL", "IN"]
        assert_jurisdiction_line(
            by_code(lines, "IL"),
            taxable_miles=60.0,
            taxable_gallons=4.800,
            tax_paid_gallons=8.000,
            net_taxable_gallons=-3.200,
            base_tax_amount=-2.01,
            surcharge_amount=0.00,
            net_tax_amount=-2.01,
        )
        assert_jurisdiction_line(
            by_code(lines, "IN"),
            taxable_miles=40.0,
            taxable_gallons=3.200,
            tax_paid_gallons=0.000,
            net_taxable_gallons=3.200,
            base_tax_amount=1.06,
            surcharge_amount=1.76,
            net_tax_amount=2.82,
        )

        # Both excluded rows are accepted evidence; only the window kept them
        # out.
        assert read_trip(client, starts_on_the_boundary["id"])["trip_status"] == "ACCEPTED"
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]), tax_paid_gallons_ytd=13.000
        )


class TestThePercentageMixIsStoredAsRounded:
    def test_apportion_percent_is_rounded_to_six_decimals_and_never_renormalised(
        self, client
    ):
        """"For each line, `apportion_percent` is that line's
        `effective_distance_miles` divided by `fleet_total_distance_miles`,
        rounded to 6 decimal places; the percentages are deliberately not
        re-normalised, so their sum may differ from exactly 1.000000 by the
        residue of that rounding."

        10000.0 and 20000.0 miles over a 30000.0-mile fleet total are a third
        and two thirds, which round to 0.333333 and 0.666667 -- values that only
        happen to add back to 1.000000 because the two rounding directions
        cancel. What matters is that each stored figure is the rounded quotient
        of its own line and nothing else: no scaling pass adjusts either one to
        force the sum, and 0.333333 is not silently held at full precision.

        The fee is then built from those stored percentages: "Each line's
        `jurisdiction_fee_amount` is its `apportion_percent` multiplied by the
        `annual_fee_amount` of the `WeightGroupFee` cell for that line's
        `jurisdiction_code` paired with the application's `weight_group_code`,
        multiplied again by the application's `apportioned_vehicle_count`,
        rounded to 2 decimal places. The application's `base_fee_total` is the
        sum of those already-rounded per-line fees, and at invoicing time —
        before any supplement exists — `total_apportioned_fee` equals
        `base_fee_total`." Illinois at 2790.00 gives 930.00, Indiana at 1692.00
        gives 1128.00, and the total is the sum of those two cents figures.

        Design: Corner/calculations/apportion_percent_is_rounded_to_six_decimals_and_never_renormalised
        """
        seed_reference_data_il_in_only(client)
        carrier, _vehicle = _carrier_with_one_unit(client)

        application = open_application(
            client,
            carrier["id"],
            registration_year=2026,
            distance_basis="ACTUAL_DISTANCE_BASIS",
            weight_group_code="W80",
        )
        add_schedule_lines(
            client, application["id"], [("IL", 10000.0), ("IN", 20000.0)]
        )
        submit_application(client, application["id"])

        invoiced = invoice_application(client, application["id"])
        assert_application_totals(
            invoiced,
            application_status="INVOICED",
            apportioned_vehicle_count=1,
            fleet_total_distance_miles=30000.0,
            base_fee_total=2058.00,
            total_apportioned_fee=2058.00,
        )

        lines = schedule_lines(client, application["id"], line_status="ACTIVE")
        assert codes_of(lines) == ["IL", "IN"]
        illinois = by_code(lines, "IL")
        indiana = by_code(lines, "IN")

        assert_apportion_percent(illinois["apportion_percent"], 0.333333)
        assert_money(illinois["jurisdiction_fee_amount"], 930.00)
        assert_apportion_percent(indiana["apportion_percent"], 0.666667)
        assert_money(indiana["jurisdiction_fee_amount"], 1128.00)

        # Each percentage is exactly the rounded quotient of its own line, and
        # the pair was left alone afterwards.
        assert round(illinois["apportion_percent"], 6) == illinois["apportion_percent"]
        assert round(indiana["apportion_percent"], 6) == indiana["apportion_percent"]

        # The total is the sum of the two rounded line fees, not a fresh
        # multiplication against the un-rounded mix.
        assert_money(
            read_application(client, application["id"])["base_fee_total"],
            illinois["jurisdiction_fee_amount"] + indiana["jurisdiction_fee_amount"],
        )


class TestTheGapIsMeasuredAgainstTheChronologicalPredecessor:
    def test_a_back_filled_trip_is_compared_against_the_trip_before_it_in_time(
        self, client
    ):
        """"The predecessor is then selected **chronologically, never by id**:
        among all trips of the same `vehicle_id` whose `trip_status` is not
        `REJECTED` and whose `trip_start_utc` is strictly earlier than the new
        trip's `trip_start_utc`, sort by `trip_start_utc` ascending with
        `created_at` ascending as tiebreaker and take the last element. If no
        such trip exists, `gap_miles_from_previous` is 0.0. Otherwise
        `gap_miles_from_previous` is the new trip's `start_odometer` minus the
        predecessor's `end_odometer`, rounded to 1 decimal place."

        Telematics arrives out of order. April's trip lands first (1000.0 ->
        1300.0), then June's (1400.0 -> 1900.0), which gaps 100.0 miles against
        April and is flagged. May's trip is then back-filled starting at
        1300.0 -- exactly where April left off. Its predecessor is April, not
        the most recently created row, so its measured gap is 0.0 and it is born
        `CAPTURED`. "If `gap_miles_from_previous` is **strictly greater** than
        the five-mile gap tolerance, the trip is born `GAP_FLAGGED`:
        unaccounted distance exists between the vehicle's last known position
        and this trip's start, and someone must account for it." Measuring
        against June's 1900.0 would have produced -600.0 instead. June's own
        stamped gap is not re-derived when May appears underneath it.

        Design: Corner/calculations/the_gap_is_measured_against_the_chronological_predecessor_not_the_last_created_trip
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier, vehicle = _carrier_with_one_unit(client)

        april = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-04-05T06:00:00Z",
            trip_end_utc="2026-04-05T18:00:00Z",
            start_odometer=1000.0,
            end_odometer=1300.0,
            legs=[leg("IL", 300.0)],
        )
        # First trip of the unit: no predecessor exists, so the gap is 0.0 by
        # definition rather than by measurement.
        assert_trip_state(
            april,
            trip_status="CAPTURED",
            gap_miles_from_previous=0.0,
            odometer_delta_miles=300.0,
        )

        june = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-06-10T06:00:00Z",
            trip_end_utc="2026-06-10T18:00:00Z",
            start_odometer=1400.0,
            end_odometer=1900.0,
            legs=[leg("IL", 500.0)],
        )
        assert_trip_state(
            june,
            trip_status="GAP_FLAGGED",
            gap_miles_from_previous=100.0,
            odometer_delta_miles=500.0,
        )

        may = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-05-10T06:00:00Z",
            trip_end_utc="2026-05-10T12:00:00Z",
            start_odometer=1300.0,
            end_odometer=1350.0,
            legs=[leg("IL", 50.0)],
        )
        assert_trip_state(
            may,
            trip_status="CAPTURED",
            gap_miles_from_previous=0.0,
            odometer_delta_miles=50.0,
        )

        # The stamp on June is historical, not a live derivation.
        assert_trip_state(
            read_trip(client, june["id"]),
            trip_status="GAP_FLAGGED",
            gap_miles_from_previous=100.0,
        )
        assert_trip_state(
            read_trip(client, may["id"]),
            trip_status="CAPTURED",
            gap_miles_from_previous=0.0,
        )

        flagged, meta = validate_paginated(
            client.list_trip_records(
                OFFICER_1_HEADERS,
                params={"vehicle_id": vehicle["id"], "trip_status": "GAP_FLAGGED"},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in flagged] == [june["id"]]
