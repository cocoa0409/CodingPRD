"""Where each machine starts, which doors it refuses to open, and what one
approved transition drags along behind it.

Initial states, an invoicing cascade that is fenced by registration year, three
terminal or replayed transitions that answer 409, and the transfer that moves two
units and their paper at once.
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_AUDIT_SELECTION_NOT_SELECTED,
    ERR_INVALID_APPLICATION_STATE,
    ERR_INVALID_TRIP_STATE,
    ERR_TRANSFER_NOT_REVERSIBLE,
)
from test_helpers.assertions import (
    assert_application_totals,
    assert_audit_selection,
    assert_carrier_compliance,
    assert_change_request,
    assert_credential_state,
    assert_gallons,
    assert_miles,
    assert_money,
    assert_trip_state,
    assert_vehicle_dimensions,
    assert_version_is,
)
from test_helpers.constants import JURISDICTION_IL
from test_helpers.factories import fuel_purchase_payload, leg
from test_helpers.fixtures import (
    accept_trip,
    add_schedule_lines,
    capture_trip,
    create_carrier,
    create_vehicle,
    decide_fleet_change,
    invoiced_application,
    issued_application,
    open_application,
    open_return,
    prepare_return,
    read_application,
    read_carrier,
    read_fleet_change,
    read_purchase,
    read_return,
    read_trip,
    read_vehicle,
    record_purchase,
    reject_trip,
    request_fleet_change,
    score_audit_selection,
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


def _illinois_carrier_with_one_unit(client, unit_number="U-101", vin="1FUJA6CK21L101101"):
    """One Illinois carrier holding one still-pending power unit."""
    carrier = create_carrier(
        client,
        legal_name="Prairie Freight LLC",
        usdot_number="USDOT-2637001",
        base_jurisdiction_code="IL",
    )
    vehicle = create_vehicle(
        client,
        carrier["id"],
        unit_number=unit_number,
        vin=vin,
        factory_price_amount=145000.00,
        registration_year=2026,
    )
    return carrier, vehicle


class TestWhereTheMachinesStart:
    """A first trip, a receipt-less purchase and a rejected supplement all sit
    in the state their guard leaves them in."""

    def test_a_clean_first_trip_is_born_captured_with_no_predecessor_gap(
        self, client
    ):
        """"The predecessor is then selected **chronologically, never by id** ... If
        no such trip exists, `gap_miles_from_previous` is 0.0." And "Otherwise the
        trip is born `CAPTURED`, which is not the same thing as settled — a
        `CAPTURED` trip still requires an explicit review decision before its miles
        may enter any settlement."

        Design: Corner/state_machines/a_clean_first_trip_starts_in_captured_with_no_predecessor_gap
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier, vehicle = _illinois_carrier_with_one_unit(client)

        trip = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-04-05T06:00:00Z",
            "2026-04-05T18:00:00Z",
            4500.0,
            4900.0,
            [leg("IL", 400.0)],
        )
        assert_trip_state(
            trip,
            trip_status="CAPTURED",
            gap_miles_from_previous=0.0,
            odometer_delta_miles=400.0,
            accepted_leg_miles_total=400.0,
        )
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]),
            unsubstantiated_mileage_ratio=0.0000,
            audit_flag=False,
        )

        _, meta = validate_paginated(
            client.list_trip_records(
                OFFICER_1_HEADERS,
                params={"carrier_id": carrier["id"], "trip_status": "ACCEPTED"},
            )
        )
        assert meta["total_count"] == 0, meta

    def test_a_receipt_less_purchase_stays_recorded_and_adds_no_gallons(
        self, client
    ):
        """"A purchase moves `RECORDED → ACCEPTED` at creation time when **both**
        conditions hold: `receipt_reference` is present, and `tax_paid_flag` is
        true." And "A purchase missing its receipt, or one flagged as untaxed bulk
        fuel, stays `RECORDED` and contributes nothing to any figure — it is
        retained as a record, not as a credit."

        Design: Corner/state_machines/a_receipt_less_purchase_stays_recorded_and_contributes_no_gallons
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier, vehicle = _illinois_carrier_with_one_unit(client)

        no_receipt_payload = fuel_purchase_payload(
            carrier["id"],
            vehicle["id"],
            jurisdiction_code="IL",
            purchase_date="2026-05-02",
            gallons=25.000,
        )
        no_receipt_payload.pop("receipt_reference")
        without_receipt = validate_success(
            client.create_fuel_purchase(no_receipt_payload, ANALYST_1_HEADERS),
            expected_status=201,
        )
        assert without_receipt["purchase_status"] == "RECORDED", without_receipt
        assert without_receipt["receipt_reference"] is None, without_receipt
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]), tax_paid_gallons_ytd=0.000
        )

        with_receipt = record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            "IL",
            "2026-05-03",
            40.000,
            receipt_reference="RCPT-IL-4471",
        )
        assert with_receipt["purchase_status"] == "ACCEPTED", with_receipt
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]), tax_paid_gallons_ytd=40.000
        )
        assert read_purchase(client, without_receipt["id"])["purchase_status"] == (
            "RECORDED"
        )

        accepted, meta = validate_paginated(
            client.list_fuel_purchases(
                ANALYST_1_HEADERS,
                params={"carrier_id": carrier["id"], "purchase_status": "ACCEPTED"},
            )
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in accepted] == [with_receipt["id"]], accepted
        assert_gallons(accepted[0]["gallons"], 40.000, "gallons")

    def test_rejecting_a_supplement_stamps_the_decision_and_moves_nothing(
        self, client
    ):
        """"Rejection is the simple path: `change_status` becomes `REJECTED`,
        `decided_by_user_id` is stamped, `fee_delta` stays 0.00, no vehicle and no
        credential is touched, and the parent application's `version` increments by
        1." A newly filed supplement also opens with "`prorate_months` at 0".

        Design: Corner/state_machines/rejecting_a_fleet_change_leaves_every_vehicle_and_fee_untouched
        """
        seed_reference_data_il_in_only(client)
        carrier, first_unit = _illinois_carrier_with_one_unit(client)
        application = invoiced_application(
            client,
            carrier["id"],
            [("IL", 60000.0), ("IN", 40000.0)],
            preparer_headers=PREPARER_1_HEADERS,
            officer_headers=OFFICER_1_HEADERS,
        )
        assert_application_totals(
            application,
            application_status="INVOICED",
            apportioned_vehicle_count=1,
            base_fee_total=2350.80,
            total_apportioned_fee=2350.80,
        )
        second_unit = create_vehicle(
            client,
            carrier["id"],
            unit_number="U-102",
            vin="1FUJA6CK21L101102",
            factory_price_amount=152000.00,
            registration_year=2026,
        )
        supplement = request_fleet_change(
            client,
            application["id"],
            second_unit["id"],
            "ADDITION",
            "2026-07-15",
            headers=PREPARER_1_HEADERS,
        )

        decided = decide_fleet_change(
            client,
            supplement["id"],
            "REJECT",
            headers=OFFICER_1_HEADERS,
            decision_note="unit not delivered",
        )
        assert_change_request(
            decided,
            change_status="REJECTED",
            prorate_months=0,
            fee_delta=0.00,
            decided_by_user_id="officer-1",
            reversal_reason_code=None,
        )
        assert_vehicle_dimensions(
            read_vehicle(client, second_unit["id"]),
            vehicle_status="PENDING",
            activated_on_date=None,
        )
        assert_application_totals(
            read_application(client, application["id"]),
            application_status="INVOICED",
            apportioned_vehicle_count=1,
            base_fee_total=2350.80,
            total_apportioned_fee=2350.80,
        )
        assert_vehicle_dimensions(
            read_vehicle(client, first_unit["id"]), vehicle_status="ACTIVE"
        )


class TestTheInvoicingCascadeIsFencedByRegistrationYear:
    """Pricing one year's paper leaves the next year's unit where it stands."""

    def test_invoicing_activates_only_that_registration_years_units(self, client):
        """"And a cascade runs across the fleet: every power unit of the carrier for
        the application's `registration_year` whose `vehicle_status` is `PENDING`
        transitions `PENDING → ACTIVE`, with `activated_on_date` stamped from the
        logical-clock date." On submission "`apportioned_vehicle_count` is recomputed
        from the carrier's `PENDING` and `ACTIVE` units for the year", so the 2027
        unit is priced by nobody.

        Design: Corner/state_machines/invoicing_activates_only_the_vehicles_of_the_invoiced_registration_year
        """
        seed_reference_data_il_in_only(client)
        carrier, this_year = _illinois_carrier_with_one_unit(client)
        next_year = create_vehicle(
            client,
            carrier["id"],
            unit_number="U-901",
            vin="1FUJA6CK21L101901",
            factory_price_amount=158000.00,
            registration_year=2027,
        )

        application = invoiced_application(
            client,
            carrier["id"],
            [("IL", 60000.0), ("IN", 40000.0)],
            preparer_headers=PREPARER_1_HEADERS,
            officer_headers=OFFICER_1_HEADERS,
        )
        assert_application_totals(
            application,
            application_status="INVOICED",
            apportioned_vehicle_count=1,
            fleet_total_distance_miles=100000.0,
            base_fee_total=2350.80,
            total_apportioned_fee=2350.80,
        )
        assert application["apportion_frozen_at"] is not None, application

        assert_vehicle_dimensions(
            read_vehicle(client, this_year["id"]),
            vehicle_status="ACTIVE",
            activated_on_date="2026-08-01",
            credential_status="NONE",
        )
        assert_vehicle_dimensions(
            read_vehicle(client, next_year["id"]),
            vehicle_status="PENDING",
            activated_on_date=None,
            credential_status="NONE",
        )


class TestDoorsTheMachinesRefuseToOpen:
    """A transition that does not exist from the current state answers 409 and
    writes nothing."""

    def test_reconstructing_a_captured_trip_is_an_invalid_trip_state(self, client):
        """"Reconstruction is exclusive to the `MileageAnalyst` role and moves the
        trip `GAP_FLAGGED → RECONSTRUCTED`. Attempting it on a trip in any other
        status is refused with `ERR_INVALID_TRIP_STATE`." Nothing of the successful
        path — "`mileage_source` flips from `TELEMATICS` to `MANUAL_RECONSTRUCTION`
        and never flips back" — happens on the refusal.

        Design: Corner/state_machines/reconstruct_on_a_captured_trip_returns_invalid_trip_state
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier, vehicle = _illinois_carrier_with_one_unit(client)
        trip = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-04-05T06:00:00Z",
            "2026-04-05T18:00:00Z",
            1000.0,
            1400.0,
            [leg("IL", 400.0)],
        )
        assert_trip_state(trip, trip_status="CAPTURED")

        response = client.reconstruct_trip_record(
            trip["id"],
            ANALYST_1_HEADERS,
            reconstructed_legs=[leg("IL", 400.0)],
            supporting_document_reference="FUEL-LOG-88",
        )
        validate_error(response, ERR_INVALID_TRIP_STATE, expected_status=409)

        after = read_trip(client, trip["id"])
        assert_trip_state(
            after,
            trip_status="CAPTURED",
            mileage_source="TELEMATICS",
            reconstructed_by_user_id=None,
            supporting_document_reference=None,
        )
        active = trip_legs(client, trip["id"], leg_status="ACTIVE")
        assert len(active) == 1, active
        assert_miles(active[0]["leg_miles"], 400.0, "leg_miles")

    def test_a_rejected_trip_is_terminal_and_a_second_review_cannot_revive_it(
        self, client
    ):
        """"Rejecting a `GAP_FLAGGED` trip, and rejecting a `CAPTURED` trip, both
        move it to the terminal `REJECTED`. In both cases the trip's `ACTIVE` legs
        become `VOIDED`, `accepted_leg_miles_total` resets to 0.0, and the carrier's
        `unsubstantiated_mileage_ratio` and `audit_flag` are recomputed with the
        carrier's `version` incrementing by 1." A rejected trip "leaves the
        unsubstantiated numerator and the fleet-total denominator alike", and
        `ACCEPT` is offered only from `CAPTURED` or `RECONSTRUCTED`, so the replay is
        refused with `ERR_INVALID_TRIP_STATE`.

        Design: Corner/state_machines/a_rejected_trip_is_terminal_and_a_second_review_cannot_revive_it
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier, vehicle = _illinois_carrier_with_one_unit(client)
        trip = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-04-05T06:00:00Z",
            "2026-04-05T18:00:00Z",
            1000.0,
            1400.0,
            [leg("IL", 400.0)],
        )
        reject_trip(
            client,
            trip["id"],
            headers=OFFICER_1_HEADERS,
            review_note="telematics feed corrupt",
        )

        response = client.review_trip_record(
            trip["id"], OFFICER_1_HEADERS, decision="ACCEPT"
        )
        validate_error(response, ERR_INVALID_TRIP_STATE, expected_status=409)

        after = read_trip(client, trip["id"])
        assert_trip_state(
            after, trip_status="REJECTED", accepted_leg_miles_total=0.0
        )
        assert trip_legs(client, trip["id"], leg_status="ACTIVE") == []
        voided = trip_legs(client, trip["id"], leg_status="VOIDED")
        assert len(voided) == 1, voided
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]),
            unsubstantiated_mileage_ratio=0.0000,
            audit_flag=False,
        )

    def test_submitting_an_already_submitted_application_a_second_time_is_refused(
        self, client
    ):
        """"Submitting the application moves it `DRAFT → SUBMITTED`, or
        `RETURNED_FOR_CORRECTION → SUBMITTED` on a later round; from any other status
        the submission is refused with `ERR_INVALID_APPLICATION_STATE`." The fee
        totals wait for invoicing, at which point "`apportion_frozen_at` is stamped
        with the logical clock", so the refused replay leaves them at their opening
        values.

        Design: Corner/state_machines/submitting_an_already_submitted_application_a_second_time_is_rejected
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier, _vehicle = _illinois_carrier_with_one_unit(client)
        application = open_application(
            client,
            carrier["id"],
            registration_year=2026,
            distance_basis="ACTUAL_DISTANCE_BASIS",
            headers=PREPARER_1_HEADERS,
        )
        add_schedule_lines(
            client, application["id"], [("IL", 60000.0)], headers=PREPARER_1_HEADERS
        )
        submitted = submit_application(
            client, application["id"], headers=PREPARER_1_HEADERS
        )
        version_after_submit = submitted["version"]

        response = client.submit_registration_application(
            application["id"], PREPARER_1_HEADERS
        )
        validate_error(response, ERR_INVALID_APPLICATION_STATE, expected_status=409)

        after = read_application(client, application["id"])
        assert_version_is(after, version_after_submit)
        assert_application_totals(
            after,
            application_status="SUBMITTED",
            base_fee_total=0.00,
            total_apportioned_fee=0.00,
        )
        assert after["apportion_frozen_at"] is None, after

    def test_retention_review_of_a_not_selected_audit_is_refused(self, client):
        """"The selection must be in `SELECTED`; a review aimed at a record in any
        other status is refused with `ERR_AUDIT_SELECTION_NOT_SELECTED`." The state
        check is step 9 and the filed-return requirement is step 28, so the state
        complaint is the one that surfaces. And "Both outcomes leave
        `expected_records_count`, `records_missing_count`,
        `retention_deficiency_ratio` and `post_review_risk_score` null until a
        retention review runs, and `reviewed_by_user_id` null."

        Design: Corner/state_machines/retention_review_of_a_not_selected_audit_is_rejected
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier, vehicle = _illinois_carrier_with_one_unit(client)
        trip = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-04-05T06:00:00Z",
            "2026-04-05T18:00:00Z",
            1000.0,
            1650.0,
            [leg("IL", 650.0)],
        )
        accept_trip(client, trip["id"], headers=OFFICER_1_HEADERS)
        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            "IL",
            "2026-05-02",
            100.000,
            receipt_reference="RCPT-IL-4471",
        )
        quarter = open_return(
            client, carrier["id"], filing_year=2026, filing_quarter=2,
            headers=PREPARER_1_HEADERS,
        )
        prepared = prepare_return(
            client, quarter["id"], carrier["id"], headers=PREPARER_1_HEADERS
        )
        assert prepared["return_status"] == "PREPARED", prepared

        selection = score_audit_selection(
            client,
            carrier["id"],
            selection_year=2026,
            selection_quarter=2,
            late_filing_count=0,
            retention_deficiency_count=0,
            headers=OFFICER_1_HEADERS,
        )
        assert_audit_selection(
            selection,
            risk_score=0,
            selection_status="NOT_SELECTED",
            post_review_risk_score=None,
            retention_deficiency_ratio=None,
            expected_records_count=None,
            records_missing_count=None,
            reviewed_by_user_id=None,
        )

        response = client.retention_review_audit_selection(
            selection["id"],
            OFFICER_1_HEADERS,
            expected_records_count=20,
            records_missing_count=5,
        )
        validate_error(response, ERR_AUDIT_SELECTION_NOT_SELECTED, expected_status=409)

        selections = validate_success(
            client.list_carrier_audit_selections(
                carrier["id"], OFFICER_1_HEADERS, params={"selection_year": 2026}
            )
        )
        assert [row["id"] for row in selections] == [selection["id"]], selections
        assert_audit_selection(
            selections[0],
            risk_score=0,
            selection_status="NOT_SELECTED",
            post_review_risk_score=None,
            retention_deficiency_ratio=None,
        )
        assert read_return(client, quarter["id"])["return_status"] == "PREPARED"
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]),
            ifta_license_status="ACTIVE",
            suspension_count=0,
        )


@pytest.fixture
def requested_transfer_of_one_unit(client):
    """An ISSUED 2026 registration for U-101 with a TRANSFER supplement filed
    against it, bringing U-102 in and swapping U-101 out on 2026-07-15."""
    seed_reference_data_il_in_only(client)
    carrier, outgoing = _illinois_carrier_with_one_unit(client)
    application = issued_application(
        client,
        carrier["id"],
        [("IL", 60000.0), ("IN", 40000.0)],
        preparer_headers=PREPARER_1_HEADERS,
        officer_headers=OFFICER_1_HEADERS,
    )
    incoming = create_vehicle(
        client,
        carrier["id"],
        unit_number="U-102",
        vin="1FUJA6CK21L101102",
        factory_price_amount=152000.00,
        registration_year=2026,
    )
    supplement = request_fleet_change(
        client,
        application["id"],
        incoming["id"],
        "TRANSFER",
        "2026-07-15",
        headers=PREPARER_1_HEADERS,
        replaced_vehicle_id=outgoing["id"],
    )
    return {
        "carrier_id": carrier["id"],
        "application_id": application["id"],
        "outgoing_id": outgoing["id"],
        "incoming_id": incoming["id"],
        "supplement_id": supplement["id"],
    }


class TestATransferMovesTwoUnitsAtOnceAndCannotBeUndone:
    """One APPROVE swaps the units and replaces the outgoing paper; nothing
    walks that back."""

    def test_approval_activates_the_incoming_unit_and_replaces_the_outgoing_paper(
        self, client, requested_transfer_of_one_unit
    ):
        """"The incoming unit named by `vehicle_id` moves `PENDING → ACTIVE` with
        `activated_on_date` stamped from the supplement's `effective_date`, and its
        `replaced_vehicle_id` is set to the `id` of the outgoing unit ... The
        outgoing unit named by the supplement's `replaced_vehicle_id` moves
        `ACTIVE → TRANSFERRED`, which is terminal, and every `Credential` of that
        outgoing unit whose `credential_status` is `ISSUED` or `DISTRIBUTED` becomes
        `REPLACED` with `voided_reason_code` set to `TRANSFER_REPLACEMENT`." The
        addition leg is 2350.80 × 6 / 12 = 1175.40 and the credit leg is
        2350.80 × 5 / 12 = 979.50, so with "a flat transfer administration charge of
        15.00" the delta is 210.90, and "`apportioned_vehicle_count` is adjusted by
        ... zero for a `TRANSFER`, since a transfer swaps one unit for another."

        Design: Corner/state_machines/transfer_approval_freezes_the_outgoing_unit_and_replaces_its_credentials
        """
        ctx = requested_transfer_of_one_unit
        decided = decide_fleet_change(
            client,
            ctx["supplement_id"],
            "APPROVE",
            headers=OFFICER_1_HEADERS,
            decision_note="unit swap",
        )
        assert_change_request(
            decided,
            change_status="APPROVED",
            prorate_months=6,
            fee_delta=210.90,
            decided_by_user_id="officer-1",
        )
        assert_application_totals(
            read_application(client, ctx["application_id"]),
            apportioned_vehicle_count=1,
            base_fee_total=2350.80,
            total_apportioned_fee=2561.70,
        )

        incoming = read_vehicle(client, ctx["incoming_id"])
        assert_vehicle_dimensions(
            incoming,
            vehicle_status="ACTIVE",
            activated_on_date="2026-07-15",
            replaced_vehicle_id=ctx["outgoing_id"],
        )
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["outgoing_id"]),
            vehicle_status="TRANSFERRED",
            credential_status="NONE",
        )

        replaced, replaced_meta = validate_paginated(
            client.list_credentials(
                OFFICER_1_HEADERS,
                params={
                    "vehicle_id": ctx["outgoing_id"],
                    "credential_status": "REPLACED",
                },
            )
        )
        assert replaced_meta["total_count"] == 3, replaced_meta
        for credential in replaced:
            assert_credential_state(
                credential,
                credential_status="REPLACED",
                voided_reason_code="TRANSFER_REPLACEMENT",
            )
        _, incoming_paper = validate_paginated(
            client.list_credentials(
                OFFICER_1_HEADERS, params={"vehicle_id": ctx["incoming_id"]}
            )
        )
        assert incoming_paper["total_count"] == 0, incoming_paper

    def test_an_approved_transfer_cannot_be_reversed(
        self, client, requested_transfer_of_one_unit
    ):
        """"And it requires `change_type` to be `ADDITION` or `DELETION`: an approved
        `TRANSFER` is **not** reversible, because the outgoing unit has already
        reached the terminal `TRANSFERRED` state and its credentials have already
        been `REPLACED`, so an attempt is refused with
        `ERR_TRANSFER_NOT_REVERSIBLE`." The refusal leaves both units and the fee
        exactly where the approval put them.

        Design: Corner/state_machines/an_approved_transfer_cannot_be_reversed
        """
        ctx = requested_transfer_of_one_unit
        decide_fleet_change(
            client, ctx["supplement_id"], "APPROVE", headers=OFFICER_1_HEADERS
        )

        response = client.reverse_fleet_change_request(
            ctx["supplement_id"],
            OFFICER_1_HEADERS,
            reversal_reason_code="CLERICAL_ERROR",
        )
        validate_error(response, ERR_TRANSFER_NOT_REVERSIBLE, expected_status=409)

        assert_change_request(
            read_fleet_change(client, ctx["supplement_id"]),
            change_status="APPROVED",
            reversal_reason_code=None,
            fee_delta=210.90,
        )
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["outgoing_id"]), vehicle_status="TRANSFERRED"
        )
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["incoming_id"]), vehicle_status="ACTIVE"
        )
        assert_money(
            read_application(client, ctx["application_id"])["total_apportioned_fee"],
            2561.70,
            "total_apportioned_fee",
        )
