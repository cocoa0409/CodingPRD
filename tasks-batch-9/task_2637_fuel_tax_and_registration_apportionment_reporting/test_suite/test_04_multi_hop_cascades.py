"""Single calls that unwind several levels of dependent state.

Returning a quarter for correction travels up the compliance chain from a child
ledger to a grandparent's audit posture; approving a deletion travels down the
registration chain from an application to a driver's paperwork.
"""
import pytest

from test_helpers.assertions import (
    assert_application_totals,
    assert_apportion_percent,
    assert_audit_selection,
    assert_carrier_compliance,
    assert_change_request,
    assert_credential_state,
    assert_return_settlement,
    assert_trip_state,
    assert_vehicle_dimensions,
    by_code,
    codes_of,
)
from test_helpers.factories import leg
from test_helpers.fixtures import (
    accept_trip,
    add_schedule_lines,
    capture_trip,
    carrier_with_fleet,
    carrier_with_vehicle,
    credentials_for_vehicle,
    decide_fleet_change,
    distribute_credential,
    invoice_application,
    issue_credentials,
    list_credentials,
    open_application,
    open_return,
    prepare_return,
    read_application,
    read_carrier,
    read_fleet_change,
    read_return,
    read_trip,
    read_vehicle,
    reconstruct_trip,
    record_purchase,
    request_fleet_change,
    return_lines,
    schedule_lines,
    score_audit_selection,
    submit_application,
    trip_legs,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    PREPARER_1_HEADERS,
)


@pytest.fixture
def prepared_quarter_with_an_escaped_audit_period(client):
    """A fully substantiated Q2-2026 quarter, prepared, whose 2026 Q2 audit
    selection scored just under the threshold and sits in NOT_SELECTED.

    All three trips are accepted, including the reconstructed one, so the carrier
    carries no unsubstantiated mileage at all and the ratio factor contributes
    nothing to the score.
    """
    ctx = carrier_with_vehicle(
        client,
        unit_number="U-601",
        vin="1FUJA6CK21L500601",
        factory_price_amount=157000.00,
        carrier_overrides={
            "legal_name": "Cascade Compliance Carriers LLC",
            "usdot_number": "USDOT-2637060",
            "base_jurisdiction_code": "IL",
            "bond_ceiling_amount": 5000.00,
        },
    )
    carrier_id, vehicle_id = ctx["carrier_id"], ctx["vehicle_id"]

    z1 = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        "2026-04-10T06:00:00Z",
        "2026-04-10T18:00:00Z",
        500000.0,
        500700.0,
        [leg("IL", 300.0), leg("IN", 200.0), leg("KY", 200.0)],
    )
    accept_trip(client, z1["id"], headers=OFFICER_1_HEADERS)

    z2 = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        "2026-05-05T06:00:00Z",
        "2026-05-05T20:00:00Z",
        500700.0,
        501500.0,
        [leg("IL", 400.0), leg("IN", 250.0), leg("KY", 150.0)],
    )
    accept_trip(client, z2["id"], headers=OFFICER_1_HEADERS)

    z3 = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        "2026-06-02T06:00:00Z",
        "2026-06-02T16:00:00Z",
        501600.0,
        502100.0,
        [leg("IL", 300.0), leg("KY", 200.0)],
    )
    reconstruct_trip(
        client,
        z3["id"],
        [leg("IL", 250.0), leg("KY", 350.0)],
        "RECON-Z3-A",
        headers=ANALYST_1_HEADERS,
    )
    accept_trip(client, z3["id"], headers=OFFICER_1_HEADERS)

    for code, date, gallons, receipt in (
        ("IL", "2026-04-11", 175.000, "RCPT-IL-6-0411"),
        ("IN", "2026-05-06", 80.000, "RCPT-IN-6-0506"),
        ("KY", "2026-06-03", 30.000, "RCPT-KY-6-0603"),
    ):
        record_purchase(
            client,
            carrier_id,
            vehicle_id,
            code,
            date,
            gallons,
            receipt_reference=receipt,
        )

    opened = open_return(client, carrier_id, 2026, 2, headers=PREPARER_1_HEADERS)
    prepared = prepare_return(
        client, opened["id"], carrier_id, headers=PREPARER_1_HEADERS
    )
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
        "z1_id": z1["id"],
        "z2_id": z2["id"],
        "z3_id": z3["id"],
        "return_id": opened["id"],
        "prepared": prepared,
        "selection": selection,
    }


class TestReturnForCorrectionCascade:
    """One review call unwinds four levels: the return's ledger, the trips it
    settled, the carrier's exposure, and an audit period already escaped."""

    def test_the_starting_position_has_no_unsubstantiated_mileage_and_no_selection(
        self, client, prepared_quarter_with_an_escaped_audit_period
    ):
        """"because an accepted reconstruction has now been substantiated, its
        miles leave the unsubstantiated numerator", so the ratio factor
        contributes nothing and, with the 7.37 MPG variance and the saturated
        retention factor alone, "When `risk_score` falls below 70 the record is
        born `NOT_SELECTED` and nothing outside the record changes."

        Design: Difficulty/transitive_cascade/return_for_correction_cascades_through_trips_carrier_and_audit_selection
        """
        ctx = prepared_quarter_with_an_escaped_audit_period
        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            unsubstantiated_mileage_ratio=0.0000,
            audit_flag=False,
            latest_prepared_fleet_mpg=7.37,
        )
        assert_audit_selection(
            ctx["selection"], risk_score=37, selection_status="NOT_SELECTED"
        )

    def test_first_hop_voids_the_line_set_and_zeroes_the_return(
        self, client, prepared_quarter_with_an_escaped_audit_period
    ):
        """"All `ACTIVE` `ReturnJurisdictionLine` rows of the return become
        `VOIDED`. `total_net_tax_due`, `reconstruction_penalty_amount` and
        `total_amount_due` reset to 0.00; `total_fleet_miles` resets to 0.0;
        `fleet_mpg` resets to null; `reconstructed_mileage_ratio` resets to
        0.0000." The voided set stays readable.

        Design: Difficulty/transitive_cascade/return_for_correction_cascades_through_trips_carrier_and_audit_selection
        """
        ctx = prepared_quarter_with_an_escaped_audit_period
        response = client.review_fuel_tax_return(
            ctx["return_id"],
            OFFICER_1_HEADERS,
            decision="RETURN_FOR_CORRECTION",
            review_note="Reconstruction support insufficient for the June trip.",
        )
        assert response.status_code == 200, response.text

        corrected = read_return(client, ctx["return_id"])
        assert_return_settlement(
            corrected,
            return_status="RETURNED_FOR_CORRECTION",
            total_fleet_miles=0.0,
            fleet_mpg=None,
            reconstructed_mileage_ratio=0.0000,
            total_net_tax_due=0.00,
            reconstruction_penalty_amount=0.00,
            total_amount_due=0.00,
        )
        assert return_lines(client, ctx["return_id"], line_status="ACTIVE") == []
        voided = return_lines(client, ctx["return_id"], line_status="VOIDED")
        assert codes_of(voided) == ["IL", "IN", "KY"], codes_of(voided)
        assert all(row["line_status"] == "VOIDED" for row in voided)

    def test_second_hop_reopens_only_the_manual_reconstruction(
        self, client, prepared_quarter_with_an_escaped_audit_period
    ):
        """"Every trip of the return's carrier whose `trip_status` is `ACCEPTED`,
        whose `mileage_source` is `MANUAL_RECONSTRUCTION`, and whose
        `trip_start_utc` falls inside the return's quarter window transitions
        `ACCEPTED → GAP_FLAGGED`. ... Telematics-sourced accepted trips are
        untouched — only manual reconstructions are reopened."

        Design: Difficulty/transitive_cascade/return_for_correction_cascades_through_trips_carrier_and_audit_selection
        """
        ctx = prepared_quarter_with_an_escaped_audit_period
        client.review_fuel_tax_return(
            ctx["return_id"],
            OFFICER_1_HEADERS,
            decision="RETURN_FOR_CORRECTION",
            review_note="Reconstruction support insufficient for the June trip.",
        )

        assert_trip_state(
            read_trip(client, ctx["z3_id"]),
            trip_status="GAP_FLAGGED",
            mileage_source="MANUAL_RECONSTRUCTION",
            accepted_leg_miles_total=0.0,
            supporting_document_reference=None,
        )
        assert trip_legs(client, ctx["z3_id"], leg_status="ACTIVE") == []
        for telematics_id in (ctx["z1_id"], ctx["z2_id"]):
            assert_trip_state(
                read_trip(client, telematics_id),
                trip_status="ACCEPTED",
                mileage_source="TELEMATICS",
            )

    def test_third_and_fourth_hops_raise_the_exposure_and_pull_the_period_back(
        self, client, prepared_quarter_with_an_escaped_audit_period
    ):
        """"the carrier's `unsubstantiated_mileage_ratio` is recomputed and its
        `audit_flag` is re-derived against the fifteen-hundredths threshold ...
        every `AuditSelection` of that carrier whose `selection_year` equals the
        return's `filing_year` and whose `selection_status` is `NOT_SELECTED` is
        re-scored from the carrier's freshly recomputed
        `unsubstantiated_mileage_ratio`; where the recomputed `risk_score`
        reaches the selection threshold of 70, the selection transitions
        `NOT_SELECTED → SELECTED` and the carrier's `audit_flag` remains true."
        500.0 of 2000.0 miles saturates the ratio factor and 37 becomes 77.

        Design: Difficulty/transitive_cascade/return_for_correction_cascades_through_trips_carrier_and_audit_selection
        """
        ctx = prepared_quarter_with_an_escaped_audit_period
        client.review_fuel_tax_return(
            ctx["return_id"],
            OFFICER_1_HEADERS,
            decision="RETURN_FOR_CORRECTION",
            review_note="Reconstruction support insufficient for the June trip.",
        )

        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            unsubstantiated_mileage_ratio=0.2500,
            audit_flag=True,
        )
        selections = client.list_carrier_audit_selections(
            ctx["carrier_id"], OFFICER_1_HEADERS, params={"selection_year": 2026}
        ).json()["data"]
        assert len(selections) == 1, selections
        assert_audit_selection(
            selections[0], risk_score=77, selection_status="SELECTED"
        )

    def test_the_cascade_stops_at_the_compliance_chain(
        self, client, prepared_quarter_with_an_escaped_audit_period
    ):
        """"Critically, `irp_account_status` stays `ACTIVE`: apportioned
        registration work continues while quarterly filing is frozen." The
        correction cascade's four hops touch the return, its trips, the carrier's
        exposure and its audit periods; a licence standing is only ever moved by
        the retention-review reaction of §3.9.

        Design: Difficulty/transitive_cascade/return_for_correction_cascades_through_trips_carrier_and_audit_selection
        """
        ctx = prepared_quarter_with_an_escaped_audit_period
        client.review_fuel_tax_return(
            ctx["return_id"],
            OFFICER_1_HEADERS,
            decision="RETURN_FOR_CORRECTION",
            review_note="Reconstruction support insufficient for the June trip.",
        )

        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            ifta_license_status="ACTIVE",
            irp_account_status="ACTIVE",
            suspension_count=0,
        )
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["vehicle_id"]),
            vehicle_status="PENDING",
            credential_status="NONE",
        )
        assert list_credentials(client, vehicle_id=ctx["vehicle_id"]) == []

    def test_the_reopened_quarter_can_be_prepared_again_on_the_surviving_mileage(
        self, client, prepared_quarter_with_an_escaped_audit_period
    ):
        """"A corrected return is not dead. A `TaxPreparer` may prepare it again,
        moving it `RETURNED_FOR_CORRECTION → PREPARED`, but only once the
        reopened reconstructions have been re-reconstructed and re-accepted —
        until then the quarter contains no `ACCEPTED` mileage and the attempt
        fails on the accepted-mileage condition, and while any of them sits in
        `RECONSTRUCTED` awaiting review the attempt fails on the in-flight
        condition instead." Two telematics
        trips survived the cascade, so 1500.0 miles remain to settle against the
        same 285.000 gallons.

        Design: Difficulty/transitive_cascade/return_for_correction_cascades_through_trips_carrier_and_audit_selection
        """
        ctx = prepared_quarter_with_an_escaped_audit_period
        client.review_fuel_tax_return(
            ctx["return_id"],
            OFFICER_1_HEADERS,
            decision="RETURN_FOR_CORRECTION",
            review_note="Reconstruction support insufficient for the June trip.",
        )

        reprepared = prepare_return(
            client, ctx["return_id"], ctx["carrier_id"], headers=PREPARER_1_HEADERS
        )
        assert_return_settlement(
            reprepared,
            return_status="PREPARED",
            total_fleet_miles=1500.0,
            total_tax_paid_gallons=285.000,
            fleet_mpg=5.26,
            reconstructed_mileage_ratio=0.0000,
            reconstruction_penalty_amount=0.00,
        )


@pytest.fixture
def invoiced_fleet_with_a_pending_deletion(client):
    """Two plated 2026 units, the second one's whole credential set already in a
    driver's hands, behind a filed DELETION effective 2026-07-15.

    The actual-basis application reported IL 60000.0 / IN 25000.0 / KY 15000.0,
    so its base fee total is 4617.00 across two units — 2308.50 each.
    """
    ctx = carrier_with_fleet(
        client,
        unit_numbers=["U-71", "U-72"],
        factory_price_amount=163000.00,
        carrier_overrides={
            "legal_name": "Fleet Deletion Freightways Inc",
            "usdot_number": "USDOT-2637070",
            "base_jurisdiction_code": "IL",
            "bond_ceiling_amount": 9000.00,
        },
        driver_names=[("Marco Villa", "CDL-IL-770001")],
    )
    carrier_id = ctx["carrier_id"]
    v71, v72 = ctx["vehicles"][0]["id"], ctx["vehicles"][1]["id"]
    driver_id = ctx["drivers"][0]["id"]

    application = open_application(
        client,
        carrier_id,
        registration_year=2026,
        distance_basis="ACTUAL_DISTANCE_BASIS",
        headers=PREPARER_1_HEADERS,
    )
    add_schedule_lines(
        client,
        application["id"],
        [("IL", 60000.0), ("IN", 25000.0), ("KY", 15000.0)],
        headers=PREPARER_1_HEADERS,
    )
    submit_application(client, application["id"], headers=PREPARER_1_HEADERS)
    invoiced = invoice_application(client, application["id"], headers=OFFICER_1_HEADERS)
    issue_credentials(
        client,
        application["id"],
        headers=OFFICER_1_HEADERS,
        valid_from_date="2026-01-01",
        valid_to_date="2026-12-31",
    )

    credentials = credentials_for_vehicle(client, v72)
    for credential_type in ("DECAL_SET", "CAB_CARD", "IFTA_LICENSE_COPY"):
        distribute_credential(client, credentials[credential_type]["id"], driver_id)

    change = request_fleet_change(
        client,
        application["id"],
        v72,
        "DELETION",
        "2026-07-15",
        headers=PREPARER_1_HEADERS,
    )
    return {
        "carrier_id": carrier_id,
        "application_id": application["id"],
        "invoiced": invoiced,
        "v71_id": v71,
        "v72_id": v72,
        "driver_id": driver_id,
        "change_id": change["id"],
    }


class TestDeletionApprovalCascade:
    """Approving one supplement reprices the application, retires the unit and
    kills its paper, in that order."""

    def test_the_deletion_is_priced_without_crediting_the_month_of_exit(
        self, client, invoiced_fleet_with_a_pending_deletion
    ):
        """"For a `DELETION`, the month of exit is **not** credited, so
        `prorate_months` is twelve minus the month number ... and `fee_delta` is
        the negative of the per-vehicle full-year fee multiplied by
        `prorate_months`, divided by twelve, rounded to 2 decimal places.
        `fee_delta` is signed, and it is negative for a `DELETION`." July is
        month 7, so five months of the 2308.50 per-unit fee come back.

        Design: Difficulty/transitive_cascade/deletion_approval_cascades_through_vehicle_and_credentials
        """
        ctx = invoiced_fleet_with_a_pending_deletion
        assert_application_totals(ctx["invoiced"], base_fee_total=4617.00)

        decided = decide_fleet_change(
            client, ctx["change_id"], "APPROVE", headers=OFFICER_2_HEADERS
        )
        assert_change_request(
            decided,
            change_status="APPROVED",
            prorate_months=5,
            fee_delta=-961.88,
            decided_by_user_id="officer-2",
        )
        assert_change_request(
            read_fleet_change(client, ctx["change_id"]),
            change_status="APPROVED",
            fee_delta=-961.88,
        )

    def test_first_hop_reprices_the_application_without_disturbing_the_base_fee(
        self, client, invoiced_fleet_with_a_pending_deletion
    ):
        """"The application's `total_apportioned_fee` becomes its `base_fee_total`
        plus the sum of `fee_delta` over all of that application's supplements
        whose `change_status` is `APPROVED` ... `apportioned_vehicle_count` is
        adjusted by plus one for an `ADDITION`, minus one for a `DELETION` ...
        Note that the frozen `apportion_percent` values and `base_fee_total` are
        untouched — only `total_apportioned_fee` and the vehicle count move."

        Design: Difficulty/transitive_cascade/deletion_approval_cascades_through_vehicle_and_credentials
        """
        ctx = invoiced_fleet_with_a_pending_deletion
        decide_fleet_change(client, ctx["change_id"], "APPROVE", headers=OFFICER_2_HEADERS)

        assert_application_totals(
            read_application(client, ctx["application_id"]),
            base_fee_total=4617.00,
            total_apportioned_fee=3655.12,
            apportioned_vehicle_count=1,
        )

        lines = schedule_lines(client, ctx["application_id"], line_status="ACTIVE")
        assert codes_of(lines) == ["IL", "IN", "KY"], codes_of(lines)
        for code, percent in (("IL", 0.600000), ("IN", 0.250000), ("KY", 0.150000)):
            assert_apportion_percent(
                by_code(lines, code)["apportion_percent"], percent, f"{code} percent"
            )

    def test_second_and_third_hops_retire_the_unit_and_void_its_paper(
        self, client, invoiced_fleet_with_a_pending_deletion
    ):
        """"An approved `DELETION` moves the target unit `ACTIVE → DELETED`, and
        then a further hop reaches its paper: every `Credential` of that unit
        whose `credential_status` is `ISSUED` or `DISTRIBUTED` becomes `VOIDED`
        with `voided_reason_code` set to `FLEET_DELETION`. Where such a credential
        had already been handed out, its `distributed_to_driver_id` is
        deliberately retained so that the driver handover trail survives the
        void. Because no credential of the unit remains in `ISSUED` or
        `DISTRIBUTED`, the unit's derived `credential_status` falls to `NONE`."

        Design: Difficulty/transitive_cascade/deletion_approval_cascades_through_vehicle_and_credentials
        """
        ctx = invoiced_fleet_with_a_pending_deletion
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["v72_id"]),
            vehicle_status="ACTIVE",
            credential_status="DISTRIBUTED",
        )

        decide_fleet_change(client, ctx["change_id"], "APPROVE", headers=OFFICER_2_HEADERS)

        assert_vehicle_dimensions(
            read_vehicle(client, ctx["v72_id"]),
            vehicle_status="DELETED",
            credential_status="NONE",
        )
        rows = list_credentials(client, vehicle_id=ctx["v72_id"])
        assert len(rows) == 3, [row["credential_type"] for row in rows]
        for row in rows:
            assert_credential_state(
                row,
                credential_status="VOIDED",
                voided_reason_code="FLEET_DELETION",
                distributed_to_driver_id=ctx["driver_id"],
            )

    def test_the_sibling_unit_and_its_credentials_are_left_alone(
        self, client, invoiced_fleet_with_a_pending_deletion
    ):
        """"every `Credential` of that unit whose `credential_status` is `ISSUED`
        or `DISTRIBUTED` becomes `VOIDED`" — of *that* unit. The supplement named
        one `vehicle_id`, so the other plated unit keeps its plate and its three
        printed credentials.

        Design: Difficulty/transitive_cascade/deletion_approval_cascades_through_vehicle_and_credentials
        """
        ctx = invoiced_fleet_with_a_pending_deletion
        decide_fleet_change(client, ctx["change_id"], "APPROVE", headers=OFFICER_2_HEADERS)

        assert_vehicle_dimensions(
            read_vehicle(client, ctx["v71_id"]),
            vehicle_status="ACTIVE",
            credential_status="ISSUED",
        )
        issued = list_credentials(
            client, vehicle_id=ctx["v71_id"], credential_status="ISSUED"
        )
        assert len(issued) == 3, [row["credential_type"] for row in issued]
        for row in issued:
            assert_credential_state(
                row,
                credential_status="ISSUED",
                distributed_to_driver_id=None,
                voided_reason_code=None,
            )
