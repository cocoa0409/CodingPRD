"""The two settlement bases and the two distance bases.

Identical underlying evidence settles to different money depending on which
basis the computation runs on, and the divergence is observable in the stored
figures rather than only in the totals.
"""
import pytest

from test_helpers.assertions import (
    assert_application_totals,
    assert_apportion_percent,
    assert_audit_selection,
    assert_carrier_compliance,
    assert_jurisdiction_line,
    assert_miles,
    assert_money,
    assert_return_settlement,
    by_code,
)
from test_helpers.factories import leg
from test_helpers.fixtures import (
    accept_trip,
    capture_trip,
    carrier_with_vehicle,
    create_carrier,
    create_vehicle,
    file_return,
    open_application,
    open_return,
    prepare_return,
    read_carrier,
    read_return,
    reconstruct_trip,
    record_purchase,
    return_lines,
    schedule_lines,
    score_audit_selection,
    seed_reference_data,
    add_schedule_lines,
    submit_application,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    PREPARER_1_HEADERS,
)


@pytest.fixture
def filed_quarter_under_audit(client):
    """One carrier, one unit, a Q2-2026 quarter of mixed telematics and
    reconstructed mileage, filed on the preparer basis and then selected for
    audit.

    Q2 mileage: 700.0 accepted telematics, 800.0 accepted telematics, a
    500.0-mile trip behind a 100.0-mile gap reconstructed to 600.0 and
    accepted, and a 700.0-mile trip left gap-flagged. Q2 fuel: 175.000 IL,
    80.000 IN, 30.000 KY, all receipted.
    """
    ctx = carrier_with_vehicle(
        client,
        unit_number="U-101",
        vin="1FUJA6CK21L100101",
        factory_price_amount=165000.00,
        carrier_overrides={
            "legal_name": "Prairie Line Freight LLC",
            "usdot_number": "USDOT-2637001",
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
        "RECON-2026-06-02-A",
        headers=ANALYST_1_HEADERS,
    )
    accept_trip(client, t3["id"], headers=OFFICER_1_HEADERS)

    t4 = capture_trip(
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
        receipt_reference="RCPT-IL-0411",
    )
    record_purchase(
        client,
        carrier_id,
        vehicle_id,
        "IN",
        "2026-05-06",
        80.000,
        receipt_reference="RCPT-IN-0506",
    )
    record_purchase(
        client,
        carrier_id,
        vehicle_id,
        "KY",
        "2026-06-03",
        30.000,
        receipt_reference="RCPT-KY-0603",
    )

    opened = open_return(client, carrier_id, 2026, 2, headers=PREPARER_1_HEADERS)
    prepared = prepare_return(
        client, opened["id"], carrier_id, headers=PREPARER_1_HEADERS
    )
    file_return(client, opened["id"], headers=OFFICER_1_HEADERS)
    selection = score_audit_selection(
        client,
        carrier_id,
        selection_year=2026,
        selection_quarter=2,
        late_filing_count=0,
        retention_deficiency_count=4,
        headers=OFFICER_2_HEADERS,
    )
    return {
        "carrier_id": carrier_id,
        "vehicle_id": vehicle_id,
        "trip_ids": [t1["id"], t2["id"], t3["id"], t4["id"]],
        "return_id": opened["id"],
        "prepared": prepared,
        "selection": selection,
    }


class TestPreparerVersusAuditBasis:
    """The audit basis uplifts reconstructed legs, and the uplift does not
    cancel out against the fleet MPG it raises."""

    def test_retention_review_re_settles_the_filed_quarter_on_the_audit_basis(
        self, client, filed_quarter_under_audit
    ):
        """"The matching `FILED` return is recomputed by exactly the settlement
        machinery of §3.5, but on the audit basis: legs belonging to trips whose
        `mileage_source` is `MANUAL_RECONSTRUCTION` are uplifted by the factor
        of 1.100 before aggregation, while telematics legs are unchanged." The
        reconstructed trip contributed 600.0 miles on the preparer basis, so the
        audit basis carries 660.0 and the fleet total moves 2100.0 to 2160.0.

        Design: Difficulty/dual_variant_calc/preparer_versus_audit_basis_quarterly_settlement_divergence
        """
        ctx = filed_quarter_under_audit
        response = client.retention_review_audit_selection(
            ctx["selection"]["id"],
            OFFICER_2_HEADERS,
            expected_records_count=20,
            records_missing_count=5,
        )
        assert response.status_code == 200, response.text

        settled = read_return(client, ctx["return_id"])
        assert_return_settlement(
            settled,
            return_status="AUDIT_ADJUSTED",
            settlement_basis="AUDIT_BASIS",
            total_fleet_miles=2160.0,
            fleet_mpg=7.58,
            total_net_tax_due=17.50,
            reconstruction_penalty_amount=100.00,
            total_amount_due=117.50,
            audit_assessment_delta=-1.10,
        )

    def test_preparer_basis_totals_are_what_the_audit_delta_is_measured_against(
        self, client, filed_quarter_under_audit
    ):
        """"`audit_assessment_delta` is written as the audit-basis
        `total_amount_due` minus the preparer-basis `total_amount_due` that was
        actually filed, rounded to 2 decimal places." The quarter was filed at
        118.60 and re-settles at 117.50, so the delta is -1.10.

        Design: Difficulty/dual_variant_calc/preparer_versus_audit_basis_quarterly_settlement_divergence
        """
        ctx = filed_quarter_under_audit
        assert_return_settlement(
            ctx["prepared"],
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=2100.0,
            fleet_mpg=7.37,
            total_amount_due=118.60,
        )

        client.retention_review_audit_selection(
            ctx["selection"]["id"],
            OFFICER_2_HEADERS,
            expected_records_count=20,
            records_missing_count=5,
        )
        settled = read_return(client, ctx["return_id"])
        assert_money(
            settled["total_amount_due"] - ctx["prepared"]["total_amount_due"],
            -1.10,
            "audit basis less preparer basis",
        )
        assert_money(settled["audit_assessment_delta"], -1.10, "audit_assessment_delta")

    def test_the_two_line_sets_are_both_readable_and_disagree_per_jurisdiction(
        self, client, filed_quarter_under_audit
    ):
        """"All of the return's `ACTIVE` jurisdiction lines become `VOIDED` and a
        freshly computed set is inserted as `ACTIVE`." And the two sets disagree
        unevenly: "The two effects apply to different jurisdictions in different
        proportions, so each line's `net_tax_amount`, and therefore
        `total_net_tax_due` and `total_amount_due`, diverge from the
        preparer-basis result on identical underlying data." So the voided
        preparer-basis line set and the fresh audit-basis set differ line by
        line rather than by a single uniform shift.

        Design: Difficulty/dual_variant_calc/preparer_versus_audit_basis_quarterly_settlement_divergence
        """
        ctx = filed_quarter_under_audit
        client.retention_review_audit_selection(
            ctx["selection"]["id"],
            OFFICER_2_HEADERS,
            expected_records_count=20,
            records_missing_count=5,
        )

        active = return_lines(client, ctx["return_id"], line_status="ACTIVE")
        assert len(active) == 3, [row["jurisdiction_code"] for row in active]
        assert_jurisdiction_line(by_code(active, "IL"), net_tax_amount=-29.08)
        assert_jurisdiction_line(by_code(active, "IN"), net_tax_amount=25.84)
        assert_jurisdiction_line(by_code(active, "KY"), net_tax_amount=20.74)

        voided = return_lines(client, ctx["return_id"], line_status="VOIDED")
        assert len(voided) == 3, [row["jurisdiction_code"] for row in voided]
        assert_jurisdiction_line(by_code(voided, "IL"), net_tax_amount=-28.90)
        assert_jurisdiction_line(by_code(voided, "IN"), net_tax_amount=27.33)
        assert_jurisdiction_line(by_code(voided, "KY"), net_tax_amount=20.17)

    def test_the_review_scores_eighty_five_and_leaves_the_licence_active(
        self, client, filed_quarter_under_audit
    ):
        """"`post_review_risk_score` is then the record's existing `risk_score`
        plus a retention penalty of thirty points scaled by the measured
        deficiency — multiply `retention_deficiency_ratio` by 30, round that
        product to a whole number, add it to `risk_score`, and cap the total at
        100." Five of twenty records missing is a deficiency ratio of
        0.2500, worth 8 points on top of a risk score of 77, and 85 stays below
        the suspension threshold: "The reaction is evaluated on
        `post_review_risk_score` against a suspension threshold of 90,
        inclusive, so exactly 90 triggers it. Below 90 the licence is
        untouched."

        Design: Difficulty/dual_variant_calc/preparer_versus_audit_basis_quarterly_settlement_divergence
        """
        ctx = filed_quarter_under_audit
        assert_audit_selection(ctx["selection"], risk_score=77, selection_status="SELECTED")

        reviewed = client.retention_review_audit_selection(
            ctx["selection"]["id"],
            OFFICER_2_HEADERS,
            expected_records_count=20,
            records_missing_count=5,
        ).json()["data"]
        assert_audit_selection(
            reviewed,
            risk_score=77,
            selection_status="RETENTION_REVIEWED",
            retention_deficiency_ratio=0.2500,
            post_review_risk_score=85,
        )
        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]), ifta_license_status="ACTIVE"
        )


@pytest.fixture
def two_applications_on_opposing_bases(client):
    """Two carriers with two W80 units each, both applications carrying the
    identical reported schedule IL 60000.0 / IN 25000.0 / KY 15000.0 and both
    submitted — one on the actual basis, one on the estimated basis."""
    seed_reference_data(client)
    carrier_a = create_carrier(
        client,
        legal_name="Actual Basis Carriage Inc",
        usdot_number="USDOT-2637010",
        base_jurisdiction_code="IL",
        bond_ceiling_amount=5000.00,
    )
    carrier_b = create_carrier(
        client,
        legal_name="Estimated Basis Carriage Inc",
        usdot_number="USDOT-2637011",
        base_jurisdiction_code="IL",
        bond_ceiling_amount=5000.00,
    )
    for unit_number, vin in (("A-1", "1FUJA6CK21L200001"), ("A-2", "1FUJA6CK21L200002")):
        create_vehicle(
            client,
            carrier_a["id"],
            unit_number=unit_number,
            vin=vin,
            factory_price_amount=160000.00,
            registration_year=2026,
        )
    for unit_number, vin in (("B-1", "1FUJA6CK21L200011"), ("B-2", "1FUJA6CK21L200012")):
        create_vehicle(
            client,
            carrier_b["id"],
            unit_number=unit_number,
            vin=vin,
            factory_price_amount=160000.00,
            registration_year=2026,
        )

    schedule = [("IL", 60000.0), ("IN", 25000.0), ("KY", 15000.0)]
    app_a = open_application(
        client,
        carrier_a["id"],
        registration_year=2026,
        distance_basis="ACTUAL_DISTANCE_BASIS",
        headers=PREPARER_1_HEADERS,
    )
    app_b = open_application(
        client,
        carrier_b["id"],
        registration_year=2026,
        distance_basis="ESTIMATED_DISTANCE_BASIS",
        headers=PREPARER_1_HEADERS,
    )
    add_schedule_lines(client, app_a["id"], schedule, headers=PREPARER_1_HEADERS)
    add_schedule_lines(client, app_b["id"], schedule, headers=PREPARER_1_HEADERS)
    submit_application(client, app_a["id"], headers=PREPARER_1_HEADERS)
    submit_application(client, app_b["id"], headers=PREPARER_1_HEADERS)
    return {"app_a_id": app_a["id"], "app_b_id": app_b["id"]}


class TestActualVersusEstimatedDistanceBasis:
    """The chart floor lifts only the below-floor jurisdictions, which re-mixes
    every other jurisdiction's share of the fee."""

    def test_actual_basis_invoices_the_reported_mix_verbatim(
        self, client, two_applications_on_opposing_bases
    ):
        """"Under `ACTUAL_DISTANCE_BASIS` — the basis for a carrier that
        genuinely operated in every listed jurisdiction during the reporting
        period — `effective_distance_miles` is `reported_distance_miles`
        verbatim, and the resulting percentage mix is the carrier's true
        operational mix."

        Design: Difficulty/dual_variant_calc/actual_versus_estimated_distance_basis_registration_fee_divergence
        """
        app_a_id = two_applications_on_opposing_bases["app_a_id"]
        response = client.review_registration_application(
            app_a_id, OFFICER_1_HEADERS, decision="INVOICE"
        )
        assert response.status_code == 200, response.text

        invoiced = response.json()["data"]
        assert_application_totals(
            invoiced,
            application_status="INVOICED",
            apportioned_vehicle_count=2,
            fleet_total_distance_miles=100000.0,
            base_fee_total=4617.00,
            total_apportioned_fee=4617.00,
        )

        lines = schedule_lines(client, app_a_id, line_status="ACTIVE")
        expected = {
            "IL": (60000.0, 0.600000, 3348.00),
            "IN": (25000.0, 0.250000, 846.00),
            "KY": (15000.0, 0.150000, 423.00),
        }
        assert len(lines) == 3
        for code, (miles, percent, fee) in expected.items():
            line = by_code(lines, code)
            assert_miles(line["effective_distance_miles"], miles, f"{code} effective")
            assert_apportion_percent(line["apportion_percent"], percent, f"{code} percent")
            assert_money(line["jurisdiction_fee_amount"], fee, f"{code} fee")

    def test_estimated_basis_lifts_only_the_below_floor_jurisdiction(
        self, client, two_applications_on_opposing_bases
    ):
        """"Under `ESTIMATED_DISTANCE_BASIS` ... `effective_distance_miles` is
        whichever is larger of `reported_distance_miles` and a
        twenty-thousand-mile chart floor, that is 20000.0 miles." And the lift is
        not confined to the jurisdiction it touches: "Because the floor lifts only
        the below-floor jurisdictions, it changes the denominator *and*
        redistributes the mix: on identical reported distances, every line's
        `apportion_percent` and `jurisdiction_fee_amount` differ from the
        actual-basis result, and so does `base_fee_total`." Kentucky's reported 15000.0
        is lifted to 20000.0; Illinois and Indiana are already above the floor
        yet both of their shares still move.

        Design: Difficulty/dual_variant_calc/actual_versus_estimated_distance_basis_registration_fee_divergence
        """
        app_b_id = two_applications_on_opposing_bases["app_b_id"]
        response = client.review_registration_application(
            app_b_id, OFFICER_1_HEADERS, decision="INVOICE"
        )
        assert response.status_code == 200, response.text

        invoiced = response.json()["data"]
        assert_application_totals(
            invoiced,
            application_status="INVOICED",
            apportioned_vehicle_count=2,
            fleet_total_distance_miles=105000.0,
            base_fee_total=4531.42,
            total_apportioned_fee=4531.42,
        )

        lines = schedule_lines(client, app_b_id, line_status="ACTIVE")
        expected = {
            "IL": (60000.0, 0.571429, 3188.57),
            "IN": (25000.0, 0.238095, 805.71),
            "KY": (20000.0, 0.190476, 537.14),
        }
        assert len(lines) == 3
        for code, (miles, percent, fee) in expected.items():
            line = by_code(lines, code)
            assert_miles(line["effective_distance_miles"], miles, f"{code} effective")
            assert_apportion_percent(line["apportion_percent"], percent, f"{code} percent")
            assert_money(line["jurisdiction_fee_amount"], fee, f"{code} fee")

    def test_identical_reported_schedules_produce_different_base_fee_totals(
        self, client, two_applications_on_opposing_bases
    ):
        """"on identical reported distances, every line's `apportion_percent`
        and `jurisdiction_fee_amount` differ from the actual-basis result, and
        so does `base_fee_total`." Both applications reported IL 60000.0 /
        IN 25000.0 / KY 15000.0, and the two base fee totals differ by 85.58.

        Design: Difficulty/dual_variant_calc/actual_versus_estimated_distance_basis_registration_fee_divergence
        """
        ctx = two_applications_on_opposing_bases
        actual = client.review_registration_application(
            ctx["app_a_id"], OFFICER_1_HEADERS, decision="INVOICE"
        ).json()["data"]
        estimated = client.review_registration_application(
            ctx["app_b_id"], OFFICER_1_HEADERS, decision="INVOICE"
        ).json()["data"]

        assert_money(actual["base_fee_total"], 4617.00, "actual basis base_fee_total")
        assert_money(
            estimated["base_fee_total"], 4531.42, "estimated basis base_fee_total"
        )
        assert_money(
            actual["base_fee_total"] - estimated["base_fee_total"],
            85.58,
            "difference between the two bases",
        )
