"""State that does not move in a straight line.

A trip can be reconstructed, rejected back to where it started, and
reconstructed again from a different field state; a vehicle carries two status
dimensions that advance on unrelated triggers, one of them backwards.
"""
import pytest

from test_helpers.assertions import (
    assert_carrier_compliance,
    assert_change_request,
    assert_credential_state,
    assert_trip_state,
    assert_vehicle_dimensions,
    by_code,
    codes_of,
)
from test_helpers.constants import JURISDICTION_IL, JURISDICTION_KY
from test_helpers.factories import leg
from test_helpers.fixtures import (
    accept_trip,
    add_schedule_lines,
    capture_trip,
    carrier_with_fleet,
    create_carrier,
    create_vehicle,
    credentials_for_vehicle,
    decide_fleet_change,
    distribute_credential,
    invoice_application,
    issue_credentials,
    list_credentials,
    open_application,
    read_carrier,
    read_fleet_change,
    read_trip,
    read_vehicle,
    reconstruct_trip,
    reject_trip,
    request_fleet_change,
    reverse_fleet_change,
    seed_reference_data,
    submit_application,
    trip_legs,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    ANALYST_2_HEADERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    PREPARER_1_HEADERS,
)


@pytest.fixture
def trip_rejected_back_to_gap_flagged(client):
    """A gap-flagged trip whose first reconstruction has already been rejected,
    so it sits in the loop for a second pass.

    The carrier has one accepted 700.0-mile trip and one 500.0-mile trip that
    opened a 100.0-mile odometer gap. The rejected first pass claimed
    IL 400.0 / KY 200.0 against document RECON-Y2-PASS1.
    """
    seed_reference_data(client, jurisdictions=[JURISDICTION_IL, JURISDICTION_KY])
    carrier = create_carrier(
        client,
        legal_name="Revision Loop Logistics LLC",
        usdot_number="USDOT-2637040",
        base_jurisdiction_code="IL",
        bond_ceiling_amount=5000.00,
    )
    vehicle = create_vehicle(
        client,
        carrier["id"],
        unit_number="U-401",
        vin="1FUJA6CK21L300401",
        factory_price_amount=149000.00,
        registration_year=2026,
    )
    y1 = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-05-02T06:00:00Z",
        "2026-05-02T18:00:00Z",
        400000.0,
        400700.0,
        [leg("IL", 700.0)],
    )
    accept_trip(client, y1["id"], headers=OFFICER_1_HEADERS)

    y2 = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-06-10T06:00:00Z",
        "2026-06-10T16:00:00Z",
        400800.0,
        401300.0,
        [leg("IL", 300.0), leg("KY", 200.0)],
    )
    flagged = read_trip(client, y2["id"])
    reconstruct_trip(
        client,
        y2["id"],
        [leg("IL", 400.0), leg("KY", 200.0)],
        "RECON-Y2-PASS1",
        headers=ANALYST_1_HEADERS,
    )
    first_pass = read_trip(client, y2["id"])
    reject_trip(client, y2["id"], headers=OFFICER_1_HEADERS)
    return {
        "carrier_id": carrier["id"],
        "vehicle_id": vehicle["id"],
        "y1_id": y1["id"],
        "y2_id": y2["id"],
        "flagged": flagged,
        "first_pass": first_pass,
    }


class TestTripReconstructionRevisionLoop:
    """The rejection hop is not a no-op: the second pass through the loop starts
    from a different field state than the first."""

    def test_rejecting_the_reconstruction_returns_the_trip_to_gap_flagged_with_a_cleared_trail(
        self, client, trip_rejected_back_to_gap_flagged
    ):
        """"The trip moves `RECONSTRUCTED → GAP_FLAGGED` — back to precisely the
        state it came from, so the analyst may try again. The trip's `ACTIVE`
        legs become `VOIDED`, `accepted_leg_miles_total` resets to 0.0, and both
        `supporting_document_reference` and `reconstructed_by_user_id` are
        cleared to null so that the next attempt starts from a clean paper trail
        and any analyst, including the original one, may make it." But
        "`mileage_source` deliberately **stays** `MANUAL_RECONSTRUCTION`: the
        trip's history is not rewritten by a rejection." So the returned state
        differs from the state first entered.

        Design: Difficulty/non_linear_state_machine/trip_reconstruction_rejection_cycles_back_to_gap_flagged
        """
        ctx = trip_rejected_back_to_gap_flagged
        assert_trip_state(
            ctx["flagged"],
            trip_status="GAP_FLAGGED",
            mileage_source="TELEMATICS",
            gap_miles_from_previous=100.0,
            odometer_delta_miles=500.0,
            supporting_document_reference=None,
            reconstructed_by_user_id=None,
        )
        assert_trip_state(
            ctx["first_pass"],
            trip_status="RECONSTRUCTED",
            mileage_source="MANUAL_RECONSTRUCTION",
            accepted_leg_miles_total=600.0,
            supporting_document_reference="RECON-Y2-PASS1",
            reconstructed_by_user_id="analyst-1",
        )
        assert_trip_state(
            read_trip(client, ctx["y2_id"]),
            trip_status="GAP_FLAGGED",
            mileage_source="MANUAL_RECONSTRUCTION",
            accepted_leg_miles_total=0.0,
            gap_miles_from_previous=100.0,
            supporting_document_reference=None,
            reconstructed_by_user_id=None,
        )

    def test_the_backward_hop_voids_the_first_pass_legs_alongside_the_telematics_legs(
        self, client, trip_rejected_back_to_gap_flagged
    ):
        """"Every one of the trip's `ACTIVE` legs becomes `VOIDED`, and the
        submitted legs are inserted as `ACTIVE`" on reconstruction, and on
        rejection "The trip's `ACTIVE` legs become `VOIDED`". Two telematics legs
        plus two first-pass reconstruction legs therefore leave four voided rows
        and nothing active.

        Design: Difficulty/non_linear_state_machine/trip_reconstruction_rejection_cycles_back_to_gap_flagged
        """
        y2_id = trip_rejected_back_to_gap_flagged["y2_id"]
        assert trip_legs(client, y2_id, leg_status="ACTIVE") == []
        voided = trip_legs(client, y2_id, leg_status="VOIDED")
        assert len(voided) == 4, codes_of(voided)

    def test_the_second_pass_stamps_a_different_analyst_and_a_different_document(
        self, client, trip_rejected_back_to_gap_flagged
    ):
        """"both `supporting_document_reference` and `reconstructed_by_user_id`
        are cleared to null so that the next attempt starts from a clean paper
        trail and any analyst, including the original one, may make it." The
        second pass reconciles a different leg split to the same
        "`odometer_delta_miles` plus its `gap_miles_from_previous`" evidence.

        Design: Difficulty/non_linear_state_machine/trip_reconstruction_rejection_cycles_back_to_gap_flagged
        """
        ctx = trip_rejected_back_to_gap_flagged
        reconstructed = reconstruct_trip(
            client,
            ctx["y2_id"],
            [leg("IL", 250.0), leg("KY", 350.0)],
            "RECON-Y2-PASS2",
            headers=ANALYST_2_HEADERS,
        )
        assert_trip_state(
            reconstructed,
            trip_status="RECONSTRUCTED",
            mileage_source="MANUAL_RECONSTRUCTION",
            accepted_leg_miles_total=600.0,
            supporting_document_reference="RECON-Y2-PASS2",
            reconstructed_by_user_id="analyst-2",
        )

        active = trip_legs(client, ctx["y2_id"], leg_status="ACTIVE")
        assert codes_of(active) == ["IL", "KY"], codes_of(active)
        assert by_code(active, "IL")["leg_miles"] == pytest.approx(250.0, abs=0.05)
        assert by_code(active, "KY")["leg_miles"] == pytest.approx(350.0, abs=0.05)

    def test_the_miles_stay_unsubstantiated_for_the_whole_loop_and_leave_only_on_accept(
        self, client, trip_rejected_back_to_gap_flagged
    ):
        """"the numerator is the sum of `odometer_delta_miles` over all of that
        carrier's trips whose `trip_status` is `GAP_FLAGGED` or `RECONSTRUCTED`",
        so 500.0 of 1200.0 miles — 0.4167 — is unsubstantiated at every stop in
        the loop. On the final accept, "because an accepted reconstruction has
        now been substantiated, its miles leave the unsubstantiated numerator."

        Design: Difficulty/non_linear_state_machine/trip_reconstruction_rejection_cycles_back_to_gap_flagged
        """
        ctx = trip_rejected_back_to_gap_flagged
        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            unsubstantiated_mileage_ratio=0.4167,
            audit_flag=True,
        )

        reconstruct_trip(
            client,
            ctx["y2_id"],
            [leg("IL", 250.0), leg("KY", 350.0)],
            "RECON-Y2-PASS2",
            headers=ANALYST_2_HEADERS,
        )
        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            unsubstantiated_mileage_ratio=0.4167,
            audit_flag=True,
        )

        accept_trip(client, ctx["y2_id"], headers=OFFICER_1_HEADERS)
        assert_trip_state(
            read_trip(client, ctx["y2_id"]),
            trip_status="ACCEPTED",
            gap_miles_from_previous=100.0,
        )
        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            unsubstantiated_mileage_ratio=0.0000,
            audit_flag=False,
        )


@pytest.fixture
def invoiced_fleet_with_a_pending_addition(client):
    """Two plated units carrying six issued credentials, plus a third unit that
    is still pending behind an unapproved mid-year addition.

    The 2026 actual-basis application reported IL 60000.0 / IN 25000.0 /
    KY 15000.0 and was invoiced, activating U-51 and U-52; credentials were then
    printed for both. U-53 was enrolled afterwards and an ADDITION effective
    2026-07-15 sits in REQUESTED.
    """
    ctx = carrier_with_fleet(
        client,
        unit_numbers=["U-51", "U-52"],
        factory_price_amount=161000.00,
        carrier_overrides={
            "legal_name": "Two Dimension Fleet Services Inc",
            "usdot_number": "USDOT-2637050",
            "base_jurisdiction_code": "IL",
            "bond_ceiling_amount": 9000.00,
        },
        driver_names=[("Dana Reyes", "CDL-IL-550001")],
    )
    carrier_id = ctx["carrier_id"]
    v51, v52 = ctx["vehicles"][0]["id"], ctx["vehicles"][1]["id"]
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
    after_invoice = read_vehicle(client, v51)
    issue_credentials(
        client,
        application["id"],
        headers=OFFICER_1_HEADERS,
        valid_from_date="2026-01-01",
        valid_to_date="2026-12-31",
    )

    v53 = create_vehicle(
        client,
        carrier_id,
        unit_number="U-53",
        vin="1FUJA6CK21L400053",
        factory_price_amount=161000.00,
        registration_year=2026,
    )
    change = request_fleet_change(
        client,
        application["id"],
        v53["id"],
        "ADDITION",
        "2026-07-15",
        headers=PREPARER_1_HEADERS,
    )
    return {
        "carrier_id": carrier_id,
        "application_id": application["id"],
        "invoiced": invoiced,
        "after_invoice": after_invoice,
        "v51_id": v51,
        "v52_id": v52,
        "v53_id": v53["id"],
        "driver_id": driver_id,
        "change_id": change["id"],
    }


class TestVehicleStatusAndCredentialStatusMoveIndependently:
    """One row, two dimensions: plating a unit prints no paper and handing out
    paper plates no unit."""

    def test_invoicing_plates_the_unit_while_the_credential_dimension_waits(
        self, client, invoiced_fleet_with_a_pending_addition
    ):
        """"A `Vehicle` carries `vehicle_status`, its fleet dimension, and
        `credential_status`, its credential dimension; they move on entirely
        different triggers and neither is derivable from the other." Invoicing
        activates the unit yet leaves it with no paper, and only issuance moves
        the second dimension: "As a consequence of the credentials appearing,
        each of those vehicles' derived `credential_status` moves `NONE →
        ISSUED`."

        Design: Difficulty/non_linear_state_machine/vehicle_status_and_credential_status_dimensions_move_independently
        """
        ctx = invoiced_fleet_with_a_pending_addition
        assert_vehicle_dimensions(
            ctx["after_invoice"], vehicle_status="ACTIVE", credential_status="NONE"
        )
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["v51_id"]),
            vehicle_status="ACTIVE",
            credential_status="ISSUED",
        )
        assert len(list_credentials(client, vehicle_id=ctx["v51_id"])) == 3
        assert len(list_credentials(client, registration_application_id=ctx["application_id"])) == 6

    def test_the_credential_dimension_reaches_distributed_only_on_the_last_handover(
        self, client, invoiced_fleet_with_a_pending_addition
    ):
        """"it moves `ISSUED → DISTRIBUTED` once every one of that unit's
        credentials in `ISSUED` or `DISTRIBUTED` has reached `DISTRIBUTED`, and
        it stays at `ISSUED` while any of them is still outstanding.
        ... Distribution moves only the credential dimension; it never touches
        `vehicle_status`."

        Design: Difficulty/non_linear_state_machine/vehicle_status_and_credential_status_dimensions_move_independently
        """
        ctx = invoiced_fleet_with_a_pending_addition
        credentials = credentials_for_vehicle(client, ctx["v51_id"])
        ordered = ["DECAL_SET", "CAB_CARD", "IFTA_LICENSE_COPY"]
        for index, credential_type in enumerate(ordered, start=1):
            distribute_credential(
                client, credentials[credential_type]["id"], ctx["driver_id"]
            )
            expected = "DISTRIBUTED" if index == len(ordered) else "ISSUED"
            assert_vehicle_dimensions(
                read_vehicle(client, ctx["v51_id"]),
                vehicle_status="ACTIVE",
                credential_status=expected,
            )

        assert_vehicle_dimensions(
            read_vehicle(client, ctx["v52_id"]),
            vehicle_status="ACTIVE",
            credential_status="ISSUED",
        )

    def test_the_driver_ends_up_holding_one_distributed_credential_of_each_type(
        self, client, invoiced_fleet_with_a_pending_addition
    ):
        """"a credential of a different `credential_type` never conflicts, so the
        same driver may hold a decal set and a cab card covering the same dates."
        All three of the unit's credentials cover 2026-01-01 to 2026-12-31 and all
        three reach the same driver.

        Design: Difficulty/non_linear_state_machine/vehicle_status_and_credential_status_dimensions_move_independently
        """
        ctx = invoiced_fleet_with_a_pending_addition
        credentials = credentials_for_vehicle(client, ctx["v51_id"])
        for credential_type in ("DECAL_SET", "CAB_CARD", "IFTA_LICENSE_COPY"):
            distribute_credential(
                client, credentials[credential_type]["id"], ctx["driver_id"]
            )

        held = list_credentials(client, distributed_to_driver_id=ctx["driver_id"])
        assert len(held) == 3, [row["credential_type"] for row in held]
        assert sorted(row["credential_type"] for row in held) == [
            "CAB_CARD",
            "DECAL_SET",
            "IFTA_LICENSE_COPY",
        ]
        for row in held:
            assert_credential_state(
                row,
                credential_status="DISTRIBUTED",
                distributed_to_driver_id=ctx["driver_id"],
                valid_from_date="2026-01-01",
                valid_to_date="2026-12-31",
            )

    def test_approving_the_addition_plates_the_new_unit_without_minting_paper(
        self, client, invoiced_fleet_with_a_pending_addition
    ):
        """"An approved `ADDITION` moves the target unit `PENDING → ACTIVE` and
        stamps `activated_on_date` with the supplement's `effective_date` — not
        with the logical clock, which is the rule that applies to activation at
        invoicing instead." Credentials are printed only by the issuance
        endpoint, so the newly plated unit's credential dimension stays at
        `NONE`.

        Design: Difficulty/non_linear_state_machine/vehicle_status_and_credential_status_dimensions_move_independently
        """
        ctx = invoiced_fleet_with_a_pending_addition
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["v53_id"]),
            vehicle_status="PENDING",
            credential_status="NONE",
            activated_on_date=None,
        )
        assert list_credentials(client, vehicle_id=ctx["v53_id"]) == []

        decide_fleet_change(client, ctx["change_id"], "APPROVE", headers=OFFICER_2_HEADERS)
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["v53_id"]),
            vehicle_status="ACTIVE",
            credential_status="NONE",
            activated_on_date="2026-07-15",
        )
        assert list_credentials(client, vehicle_id=ctx["v53_id"]) == []

    def test_reversing_the_addition_walks_the_fleet_dimension_backwards_alone(
        self, client, invoiced_fleet_with_a_pending_addition
    ):
        """"a reversed `ADDITION` moves its unit `ACTIVE → PENDING` and clears
        `activated_on_date` back to null", while "The row's `fee_delta` is
        **retained** as an audit trail but stops counting as approved". The
        credential dimension never participated in either direction.

        Design: Difficulty/non_linear_state_machine/vehicle_status_and_credential_status_dimensions_move_independently
        """
        ctx = invoiced_fleet_with_a_pending_addition
        decide_fleet_change(client, ctx["change_id"], "APPROVE", headers=OFFICER_2_HEADERS)
        reverse_fleet_change(
            client,
            ctx["change_id"],
            "VEHICLE_NOT_DELIVERED",
            headers=OFFICER_2_HEADERS,
        )

        assert_vehicle_dimensions(
            read_vehicle(client, ctx["v53_id"]),
            vehicle_status="PENDING",
            credential_status="NONE",
            activated_on_date=None,
        )
        assert_change_request(
            read_fleet_change(client, ctx["change_id"]),
            change_status="REVERSED",
            prorate_months=6,
            fee_delta=1154.25,
            reversal_reason_code="VEHICLE_NOT_DELIVERED",
        )
        assert list_credentials(client, vehicle_id=ctx["v53_id"]) == []
