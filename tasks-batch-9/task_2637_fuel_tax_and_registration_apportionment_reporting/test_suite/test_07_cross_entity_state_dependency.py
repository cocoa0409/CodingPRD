"""Operations blocked by state that lives on another entity entirely.

In both cases the request targets a legal record in a legal state, and the
refusal comes from a field one or two hops away that an audit outcome moved.
"""
import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CARRIER_LICENSE_INACTIVE,
    ERR_CREDENTIAL_NOT_ISSUED,
    ERR_DRIVER_CARRIER_MISMATCH,
)
from test_helpers.assertions import (
    assert_application_totals,
    assert_audit_selection,
    assert_carrier_compliance,
    assert_credential_state,
    assert_return_settlement,
    assert_vehicle_dimensions,
)
from test_helpers.factories import leg
from test_helpers.fixtures import (
    accept_trip,
    add_schedule_lines,
    capture_trip,
    carrier_version,
    carrier_with_vehicle,
    create_carrier,
    create_driver,
    create_vehicle,
    credentials_for_vehicle,
    distribute_credential,
    file_return,
    invoice_application,
    issue_credentials,
    open_application,
    open_return,
    prepare_return,
    read_application,
    read_carrier,
    read_return,
    read_vehicle,
    reconstruct_trip,
    record_purchase,
    retention_review,
    return_lines,
    score_audit_selection,
    seed_reference_data_il_in_only,
    submit_application,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    PREPARER_1_HEADERS,
)


@pytest.fixture
def licence_suspended_by_a_retention_review(client):
    """A carrier whose IFTA licence was suspended by an audit finding, holding a
    brand-new and entirely legal Q1-2026 DRAFT return.

    The Q2-2026 quarter carried 700.0 and 800.0 accepted telematics trips, a
    500.0-mile trip behind a 100.0-mile gap reconstructed to 600.0 and accepted,
    and a 700.0-mile trip left gap-flagged; it was prepared by preparer-1, filed
    by officer-1, selected for audit at 77 and then reviewed at 14 of 20 records
    missing.
    """
    ctx = carrier_with_vehicle(
        client,
        unit_number="U-1201",
        vin="1FUJA6CK21L801201",
        factory_price_amount=154000.00,
        carrier_overrides={
            "legal_name": "Suspended Licence Lines LLC",
            "usdot_number": "USDOT-2637120",
            "base_jurisdiction_code": "IL",
            "bond_ceiling_amount": 5000.00,
        },
    )
    carrier_id, vehicle_id = ctx["carrier_id"], ctx["vehicle_id"]

    b1 = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        "2026-04-10T06:00:00Z",
        "2026-04-10T18:00:00Z",
        900000.0,
        900700.0,
        [leg("IL", 300.0), leg("IN", 200.0), leg("KY", 200.0)],
    )
    accept_trip(client, b1["id"], headers=OFFICER_1_HEADERS)

    b2 = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        "2026-05-05T06:00:00Z",
        "2026-05-05T20:00:00Z",
        900700.0,
        901500.0,
        [leg("IL", 400.0), leg("IN", 250.0), leg("KY", 150.0)],
    )
    accept_trip(client, b2["id"], headers=OFFICER_1_HEADERS)

    b3 = capture_trip(
        client,
        carrier_id,
        vehicle_id,
        "2026-06-02T06:00:00Z",
        "2026-06-02T16:00:00Z",
        901600.0,
        902100.0,
        [leg("IL", 300.0), leg("KY", 200.0)],
    )
    reconstruct_trip(
        client,
        b3["id"],
        [leg("IL", 250.0), leg("KY", 350.0)],
        "RECON-B3",
        headers=ANALYST_1_HEADERS,
    )
    accept_trip(client, b3["id"], headers=OFFICER_1_HEADERS)

    capture_trip(
        client,
        carrier_id,
        vehicle_id,
        "2026-06-20T06:00:00Z",
        "2026-06-20T18:00:00Z",
        902200.0,
        902900.0,
        [leg("IL", 700.0)],
    )

    for code, date, gallons, receipt in (
        ("IL", "2026-04-11", 175.000, "RCPT-IL-B-0411"),
        ("IN", "2026-05-06", 80.000, "RCPT-IN-B-0506"),
        ("KY", "2026-06-03", 30.000, "RCPT-KY-B-0603"),
    ):
        record_purchase(
            client, carrier_id, vehicle_id, code, date, gallons, receipt_reference=receipt
        )

    second_quarter = open_return(
        client, carrier_id, 2026, 2, headers=PREPARER_1_HEADERS
    )
    prepare_return(client, second_quarter["id"], carrier_id, headers=PREPARER_1_HEADERS)
    file_return(client, second_quarter["id"], headers=OFFICER_1_HEADERS)
    selection = score_audit_selection(
        client,
        carrier_id,
        selection_year=2026,
        selection_quarter=2,
        late_filing_count=0,
        retention_deficiency_count=4,
        headers=OFFICER_2_HEADERS,
    )
    reviewed = retention_review(
        client,
        selection["id"],
        expected_records_count=20,
        records_missing_count=14,
        headers=OFFICER_2_HEADERS,
    )

    first_quarter = open_return(client, carrier_id, 2026, 1, headers=PREPARER_1_HEADERS)
    return {
        "carrier_id": carrier_id,
        "vehicle_id": vehicle_id,
        "second_quarter_id": second_quarter["id"],
        "first_quarter_id": first_quarter["id"],
        "first_quarter": first_quarter,
        "selection": selection,
        "reviewed": reviewed,
    }


class TestReturnPreparationDependsOnTheCarrierLicence:
    """The operation is on a return; the state that forbids it is on the
    carrier."""

    def test_the_retention_review_suspends_the_licence_without_touching_the_irp_side(
        self, client, licence_suspended_by_a_retention_review
    ):
        """"multiply `retention_deficiency_ratio` by 30, round that product to a
        whole number, add it to `risk_score`, and cap the total at 100" puts 14 of
        20 missing records at 77 + 21 == 98, at or above the threshold of 90. "An
        `ACTIVE` licence with `retention_deficiency_ratio` below 1.0000 moves
        `ACTIVE → SUSPENDED`. `suspension_count` increments by 1 ... Critically,
        `irp_account_status` stays `ACTIVE`: apportioned registration work
        continues while quarterly filing is frozen."

        Design: Difficulty/cross_entity_state_dependency/return_prepare_blocked_while_carrier_ifta_license_suspended
        """
        ctx = licence_suspended_by_a_retention_review
        assert_audit_selection(ctx["selection"], risk_score=77, selection_status="SELECTED")
        assert_audit_selection(
            ctx["reviewed"],
            risk_score=77,
            selection_status="RETENTION_REVIEWED",
            retention_deficiency_ratio=0.7000,
            post_review_risk_score=98,
            expected_records_count=20,
            records_missing_count=14,
            reviewed_by_user_id="officer-2",
        )
        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            ifta_license_status="SUSPENDED",
            irp_account_status="ACTIVE",
            suspension_count=1,
        )

    def test_a_clean_draft_return_cannot_be_prepared_once_the_licence_is_suspended(
        self, client, licence_suspended_by_a_retention_review
    ):
        """"The carrier's `ifta_license_status` must be `ACTIVE`, or the attempt is
        refused with `ERR_CARRIER_LICENSE_INACTIVE`." The Q1 return is in `DRAFT`,
        which is one of the three statuses preparation is reachable from, and the
        `expected_carrier_version` supplied is the carrier's current one, so the
        only thing standing in the way lives on the other entity.

        Design: Difficulty/cross_entity_state_dependency/return_prepare_blocked_while_carrier_ifta_license_suspended
        """
        ctx = licence_suspended_by_a_retention_review
        current_version = carrier_version(client, ctx["carrier_id"])
        response = client.prepare_fuel_tax_return(
            ctx["first_quarter_id"],
            PREPARER_1_HEADERS,
            expected_carrier_version=current_version,
        )
        validate_error(response, ERR_CARRIER_LICENSE_INACTIVE)
        assert current_version == read_carrier(client, ctx["carrier_id"])["version"]

    def test_the_refused_preparation_writes_nothing_to_the_draft_return(
        self, client, licence_suspended_by_a_retention_review
    ):
        """"The new return opens in `DRAFT` with every computed figure at its zero
        value — `total_fleet_miles` at 0.0, `total_tax_paid_gallons` at 0.000 ...
        with `settlement_basis` at `PREPARER_BASIS`, `fleet_mpg` at null, and
        `prepared_by_user_id`, `filed_by_user_id` and `filed_at` all null." A
        refused preparation leaves every one of those untouched and inserts no
        jurisdiction lines.

        Design: Difficulty/cross_entity_state_dependency/return_prepare_blocked_while_carrier_ifta_license_suspended
        """
        ctx = licence_suspended_by_a_retention_review
        client.prepare_fuel_tax_return(
            ctx["first_quarter_id"],
            PREPARER_1_HEADERS,
            expected_carrier_version=carrier_version(client, ctx["carrier_id"]),
        )

        draft = read_return(client, ctx["first_quarter_id"])
        assert_return_settlement(
            draft,
            return_status="DRAFT",
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=0.0,
            total_tax_paid_gallons=0.000,
            fleet_mpg=None,
            reconstructed_mileage_ratio=0.0000,
            total_net_tax_due=0.00,
            reconstruction_penalty_amount=0.00,
            total_amount_due=0.00,
        )
        assert draft["prepared_by_user_id"] is None, draft["prepared_by_user_id"]
        assert return_lines(client, ctx["first_quarter_id"]) == []

    def test_registration_work_continues_because_only_the_ifta_dimension_moved(
        self, client, licence_suspended_by_a_retention_review
    ):
        """"apportioned registration work continues while quarterly filing is
        frozen", and submission is guarded by the other dimension: "the carrier's
        `irp_account_status` must be `ACTIVE`, or the submission is refused with
        `ERR_CARRIER_IRP_INACTIVE`." The suspension left that dimension `ACTIVE`,
        so the very same carrier that cannot prepare a return can still submit an
        application.

        Design: Difficulty/cross_entity_state_dependency/return_prepare_blocked_while_carrier_ifta_license_suspended
        """
        ctx = licence_suspended_by_a_retention_review
        application = open_application(
            client,
            ctx["carrier_id"],
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
        submitted = submit_application(
            client, application["id"], headers=PREPARER_1_HEADERS
        )
        assert_application_totals(
            submitted, application_status="SUBMITTED", apportioned_vehicle_count=1
        )


@pytest.fixture
def licence_revoked_by_a_total_retention_failure(client):
    """A carrier whose licence was revoked outright, leaving one deactivated
    driver and three credentials in three different conditions.

    An Illinois-and-Indiana carrier plated one unit on the actual basis
    (IL 80000.0 / IN 20000.0) and issued its three credentials while the licence
    was still `ACTIVE`; the driver received the cab card only. Its Q2-2026 return
    settled at 20.24 on 1000.0 accepted miles against a 400.0-mile gap-flagged
    trip, was filed, scored 100, and was then reviewed at 20 of 20 records
    missing.
    """
    seed_reference_data_il_in_only(client)
    carrier = create_carrier(
        client,
        legal_name="Revoked Licence Carriage LLC",
        usdot_number="USDOT-2637130",
        base_jurisdiction_code="IL",
        bond_ceiling_amount=5000.00,
    )
    driver = create_driver(
        client, carrier["id"], full_name="Ines Ortega", cdl_number="CDL-IL-130001"
    )
    vehicle = create_vehicle(
        client,
        carrier["id"],
        unit_number="U-1301",
        vin="1FUJA6CK21L801301",
        factory_price_amount=153000.00,
        registration_year=2026,
    )

    application = open_application(
        client,
        carrier["id"],
        registration_year=2026,
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
    issue_credentials(
        client,
        application["id"],
        headers=OFFICER_1_HEADERS,
        valid_from_date="2026-01-01",
        valid_to_date="2026-12-31",
    )
    credentials = credentials_for_vehicle(client, vehicle["id"])
    distribute_credential(client, credentials["CAB_CARD"]["id"], driver["id"])

    e1 = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-04-20T06:00:00Z",
        "2026-04-20T22:00:00Z",
        950000.0,
        951000.0,
        [leg("IL", 200.0), leg("IN", 800.0)],
    )
    accept_trip(client, e1["id"], headers=OFFICER_1_HEADERS)
    capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-05-10T06:00:00Z",
        "2026-05-10T16:00:00Z",
        951060.0,
        951460.0,
        [leg("IL", 400.0)],
    )
    record_purchase(
        client,
        carrier["id"],
        vehicle["id"],
        "IL",
        "2026-04-21",
        100.000,
        receipt_reference="RCPT-IL-B2-0421",
    )

    quarter = open_return(client, carrier["id"], 2026, 2, headers=PREPARER_1_HEADERS)
    prepared = prepare_return(
        client, quarter["id"], carrier["id"], headers=PREPARER_1_HEADERS
    )
    file_return(client, quarter["id"], headers=OFFICER_1_HEADERS)
    selection = score_audit_selection(
        client,
        carrier["id"],
        selection_year=2026,
        selection_quarter=2,
        late_filing_count=3,
        retention_deficiency_count=4,
        headers=OFFICER_2_HEADERS,
    )
    reviewed = retention_review(
        client,
        selection["id"],
        expected_records_count=20,
        records_missing_count=20,
        headers=OFFICER_2_HEADERS,
    )
    return {
        "carrier_id": carrier["id"],
        "vehicle_id": vehicle["id"],
        "driver_id": driver["id"],
        "application_id": application["id"],
        "return_id": quarter["id"],
        "prepared": prepared,
        "selection": selection,
        "reviewed": reviewed,
        "cab_card_id": credentials["CAB_CARD"]["id"],
        "decal_set_id": credentials["DECAL_SET"]["id"],
        "ifta_copy_id": credentials["IFTA_LICENSE_COPY"]["id"],
    }


class TestCredentialDistributionDependsOnADriverTheCarrierMoved:
    """The operation is on a credential, the blocking state is on a driver, and
    what moved the driver was a carrier revocation two hops away."""

    def test_a_total_records_failure_revokes_the_licence_and_deactivates_the_driver(
        self, client, licence_revoked_by_a_total_retention_failure
    ):
        """"An `ACTIVE` licence with `retention_deficiency_ratio` exactly 1.0000 —
        no record of the period survived retention at all — skips suspension and
        moves `ACTIVE → REVOKED` ... and then revocation couples the second
        dimension: `irp_account_status` moves `ACTIVE → SUSPENDED`." From there,
        "Whenever `irp_account_status` moves `ACTIVE → SUSPENDED`, every driver of
        that carrier whose `driver_status` is `ACTIVE` moves `ACTIVE → INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/credential_distribution_blocked_when_driver_deactivated_by_revocation
        """
        ctx = licence_revoked_by_a_total_retention_failure
        assert_audit_selection(
            ctx["selection"], risk_score=100, selection_status="SELECTED"
        )
        assert_audit_selection(
            ctx["reviewed"],
            risk_score=100,
            selection_status="RETENTION_REVIEWED",
            retention_deficiency_ratio=1.0000,
            post_review_risk_score=100,
        )
        assert_carrier_compliance(
            read_carrier(client, ctx["carrier_id"]),
            ifta_license_status="REVOKED",
            irp_account_status="SUSPENDED",
            suspension_count=1,
        )

        drivers = validate_success(
            client.list_carrier_drivers(ctx["carrier_id"], OFFICER_1_HEADERS)
        )
        assert len(drivers) == 1, drivers
        assert drivers[0]["id"] == ctx["driver_id"]
        assert drivers[0]["driver_status"] == "INACTIVE", drivers[0]["driver_status"]

    def test_only_the_fuel_licence_copy_is_withdrawn_from_the_three_credentials(
        self, client, licence_revoked_by_a_total_retention_failure
    ):
        """"every `Credential` belonging to that carrier's vehicles whose
        `credential_type` is `IFTA_LICENSE_COPY` and whose `credential_status` is
        `ISSUED` or `DISTRIBUTED` becomes `VOIDED` with `voided_reason_code` set to
        `LICENSE_SUSPENSION` ... Decal sets and cab cards are untouched — the
        suspension withdraws the fuel licence, not the plate." The unit's derived
        dimension is re-derived over what is left, and the registration side keeps
        its frozen pricing.

        Design: Difficulty/cross_entity_state_dependency/credential_distribution_blocked_when_driver_deactivated_by_revocation
        """
        ctx = licence_revoked_by_a_total_retention_failure
        credentials = credentials_for_vehicle(client, ctx["vehicle_id"])
        assert_credential_state(
            credentials["IFTA_LICENSE_COPY"],
            credential_status="VOIDED",
            voided_reason_code="LICENSE_SUSPENSION",
        )
        assert_credential_state(
            credentials["CAB_CARD"],
            credential_status="DISTRIBUTED",
            distributed_to_driver_id=ctx["driver_id"],
        )
        assert_credential_state(
            credentials["DECAL_SET"],
            credential_status="ISSUED",
            distributed_to_driver_id=None,
        )
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["vehicle_id"]),
            vehicle_status="ACTIVE",
            credential_status="ISSUED",
        )
        assert_application_totals(
            read_application(client, ctx["application_id"]),
            application_status="ISSUED",
            apportioned_vehicle_count=1,
            fleet_total_distance_miles=100000.0,
            base_fee_total=2570.40,
        )

    def test_the_still_issued_decal_set_can_no_longer_reach_the_deactivated_driver(
        self, client, licence_revoked_by_a_total_retention_failure
    ):
        """"The receiving driver must belong to the same carrier as the credential's
        vehicle and must have `driver_status` `ACTIVE`; a driver of another carrier,
        or an `INACTIVE` driver, is refused with `ERR_DRIVER_CARRIER_MISMATCH`."
        The decal set itself is in exactly the status distribution requires, so the
        refusal is attributable entirely to the driver.

        Design: Difficulty/cross_entity_state_dependency/credential_distribution_blocked_when_driver_deactivated_by_revocation
        """
        ctx = licence_revoked_by_a_total_retention_failure
        response = client.distribute_credential(
            ctx["decal_set_id"],
            OFFICER_1_HEADERS,
            distributed_to_driver_id=ctx["driver_id"],
        )
        validate_error(response, ERR_DRIVER_CARRIER_MISMATCH)

        credentials = credentials_for_vehicle(client, ctx["vehicle_id"])
        assert_credential_state(
            credentials["DECAL_SET"],
            credential_status="ISSUED",
            distributed_to_driver_id=None,
            distributed_at=None,
        )
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["vehicle_id"]), credential_status="ISSUED"
        )

    def test_the_voided_credential_reports_its_own_state_before_the_driver_check(
        self, client, licence_revoked_by_a_total_retention_failure
    ):
        """"The credential's `credential_status` must be `ISSUED`; a credential that
        is already `DISTRIBUTED`, or that has been `VOIDED` or `REPLACED`, cannot be
        handed over and the attempt is refused with `ERR_CREDENTIAL_NOT_ISSUED`."
        The same deactivated driver on the withdrawn fuel licence copy therefore
        reports the credential's state rather than the driver's.

        Design: Difficulty/cross_entity_state_dependency/credential_distribution_blocked_when_driver_deactivated_by_revocation
        """
        ctx = licence_revoked_by_a_total_retention_failure
        response = client.distribute_credential(
            ctx["ifta_copy_id"],
            OFFICER_1_HEADERS,
            distributed_to_driver_id=ctx["driver_id"],
        )
        validate_error(response, ERR_CREDENTIAL_NOT_ISSUED)

    def test_the_quarter_re_settles_on_the_audit_basis_with_nothing_to_uplift(
        self, client, licence_revoked_by_a_total_retention_failure
    ):
        """"legs belonging to trips whose `mileage_source` is
        `MANUAL_RECONSTRUCTION` are uplifted by the factor of 1.100 before
        aggregation, while telematics legs are unchanged", and
        "`audit_assessment_delta` is written as the audit-basis `total_amount_due`
        minus the preparer-basis `total_amount_due` that was actually filed,
        rounded to 2 decimal places." This
        quarter's only settled trip is telematics, so the same 20.24 comes back
        and the delta is 0.00 — the revocation came from the records failure alone.

        Design: Difficulty/cross_entity_state_dependency/credential_distribution_blocked_when_driver_deactivated_by_revocation
        """
        ctx = licence_revoked_by_a_total_retention_failure
        assert_return_settlement(
            ctx["prepared"],
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=1000.0,
            fleet_mpg=10.00,
            total_amount_due=20.24,
        )
        assert_return_settlement(
            read_return(client, ctx["return_id"]),
            return_status="AUDIT_ADJUSTED",
            settlement_basis="AUDIT_BASIS",
            total_fleet_miles=1000.0,
            fleet_mpg=10.00,
            reconstructed_mileage_ratio=0.0000,
            total_net_tax_due=20.24,
            reconstruction_penalty_amount=0.00,
            total_amount_due=20.24,
            audit_assessment_delta=0.00,
        )
