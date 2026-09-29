"""What the entity surface itself guarantees.

Declared defaults, derived fields, the light rows that carry no version, the
shape of a listing window, and the order in which a malformed or dangling
reference is reported.
"""
import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_AUDIT_SELECTION_NOT_FOUND,
    ERR_CARRIER_NOT_FOUND,
    ERR_CREDENTIAL_NOT_FOUND,
    ERR_FLEET_CHANGE_REQUEST_NOT_FOUND,
    ERR_FUEL_PURCHASE_NOT_FOUND,
    ERR_FUEL_TAX_RETURN_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_TRIP_RECORD_NOT_FOUND,
    ERR_VEHICLE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_carrier_compliance,
    assert_error_envelope,
    assert_miles,
    assert_money,
    assert_object_envelope,
    assert_reference_entity,
    assert_success_meta,
    assert_trip_state,
    assert_version_is,
    assert_versioned_entity,
    assert_vehicle_dimensions,
)
from test_helpers.constants import (
    DECLARED_WEIGHT_W80_LBS,
    JURISDICTION_IL,
    JURISDICTION_IN,
    WEIGHT_GROUP_W80,
)
from test_helpers.factories import (
    carrier_payload,
    fleet_change_request_payload,
    fuel_purchase_payload,
    jurisdiction_payload_for,
    leg,
    trip_record_payload,
)
from test_helpers.fixtures import (
    application_version,
    capture_trip,
    create_carrier,
    create_vehicle,
    open_application,
    read_application,
    seed_reference_data,
    trip_legs,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    PREPARER_1_HEADERS,
)


class TestDeclaredDefaultsAndDerivedFields:
    """What the server owns on creation, and what it recomputes whatever the
    client says."""

    def test_a_minimal_carrier_create_returns_the_envelope_and_every_default(
        self, client
    ):
        """"The registration may also declare a `bond_ceiling_amount` ... it is
        carried to 2 decimal places, may not be negative, and defaults to 5000.00
        when omitted. Every other carrier attribute is system-owned and starts at a
        known value: `ifta_license_status` at `ACTIVE`, `irp_account_status` at
        `ACTIVE`, `tax_paid_gallons_ytd` at 0.000, `unsubstantiated_mileage_ratio`
        at 0.0000, `audit_flag` at false, `suspension_count` at 0,
        `latest_prepared_fleet_mpg` at null until the first return of that carrier
        is successfully prepared, and `version` at 1."

        Design: Corner/entities/carrier_creation_returns_the_envelope_plus_every_declared_default
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        payload = carrier_payload(
            legal_name="Prairie Freight LLC", usdot_number="USDOT-2637001"
        )
        payload.pop("bond_ceiling_amount")

        response = client.create_carrier(payload, OFFICER_1_HEADERS)
        carrier = validate_success(response, expected_status=201)
        assert_object_envelope(response)
        assert_success_meta(response)

        assert_versioned_entity(carrier)
        assert_version_is(carrier, 1)
        assert_money(carrier["bond_ceiling_amount"], 5000.00, "bond_ceiling_amount")
        assert_carrier_compliance(
            carrier,
            ifta_license_status="ACTIVE",
            irp_account_status="ACTIVE",
            tax_paid_gallons_ytd=0.000,
            unsubstantiated_mileage_ratio=0.0000,
            audit_flag=False,
            suspension_count=0,
            latest_prepared_fleet_mpg=None,
        )
        assert carrier["created_at"] == carrier["updated_at"], (
            carrier["created_at"],
            carrier["updated_at"],
        )

    def test_the_surcharge_flag_is_derived_and_a_supplied_value_is_ignored(
        self, client
    ):
        """"Whether a jurisdiction is a surcharge jurisdiction is not a matter of
        operator opinion: `is_surcharge_jurisdiction` is derived, and it is true
        exactly when `surcharge_rate_per_gallon` is greater than 0.0000. A client
        may include `is_surcharge_jurisdiction` in the declaration payload, but the
        derived rule governs the stored value." Illinois omits the surcharge, and
        "for those the declaration carries a `surcharge_rate_per_gallon`, likewise 4
        decimal places and never negative, defaulting to 0.0000 when omitted."

        Design: Corner/entities/surcharge_flag_is_computed_from_the_rate_and_the_client_supplied_flag_is_ignored
        """
        illinois_without_a_surcharge = dict(JURISDICTION_IL)
        illinois_without_a_surcharge.pop("surcharge_rate_per_gallon")
        reference = seed_reference_data(
            client,
            jurisdictions=[illinois_without_a_surcharge, JURISDICTION_IN],
            fees=[],
        )
        kentucky = validate_success(
            client.create_jurisdiction(
                jurisdiction_payload_for("KY", is_surcharge_jurisdiction=False),
                OFFICER_1_HEADERS,
            ),
            expected_status=201,
        )

        assert kentucky["is_surcharge_jurisdiction"] is True, kentucky
        assert kentucky["surcharge_rate_per_gallon"] == pytest.approx(
            0.0440, abs=0.00005
        ), kentucky["surcharge_rate_per_gallon"]

        illinois = reference["jurisdictions"]["IL"]
        assert illinois["surcharge_rate_per_gallon"] == pytest.approx(
            0.0000, abs=0.00005
        ), illinois["surcharge_rate_per_gallon"]
        assert illinois["is_surcharge_jurisdiction"] is False, illinois
        assert reference["jurisdictions"]["IN"]["is_surcharge_jurisdiction"] is True

    def test_the_two_reference_tables_carry_no_version_and_no_updated_at(
        self, client
    ):
        """"`Jurisdiction`, `WeightGroupFee`, `JurisdictionMileageLeg`,
        `ReturnJurisdictionLine`, and `DistanceScheduleLine` carry only `id` and
        `created_at`. Neither `updated_at` nor `version` exists on them, and
        neither field appears in their serialised representation." Both rows read
        back through their own path with their published figures intact.

        Design: Corner/entities/reference_rows_expose_no_version_and_have_no_write_surface_after_creation
        """
        reference = seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        jurisdiction_id = reference["jurisdictions"]["IL"]["id"]
        fee_id = reference["weight_group_fees"]["IL"]["id"]

        jurisdiction = validate_success(
            client.get_jurisdiction(jurisdiction_id, PREPARER_1_HEADERS)
        )
        assert_reference_entity(jurisdiction)
        assert jurisdiction["fuel_tax_rate_per_gallon"] == pytest.approx(
            0.6270, abs=0.00005
        ), jurisdiction["fuel_tax_rate_per_gallon"]

        fee = validate_success(client.get_weight_group_fee(fee_id, PREPARER_1_HEADERS))
        assert_reference_entity(fee)
        assert_money(fee["annual_fee_amount"], 2790.00, "annual_fee_amount")
        assert fee["weight_group_code"] == WEIGHT_GROUP_W80, fee
        assert fee["declared_weight_lbs"] == DECLARED_WEIGHT_W80_LBS, fee

    def test_a_new_power_unit_reads_back_unplated_with_its_inputs_intact(
        self, client
    ):
        """"A newly enrolled unit is not yet plated: `vehicle_status` starts at
        `PENDING`, the derived `credential_status` reads `NONE`,
        `replaced_vehicle_id` is null, and `activated_on_date` is null." The six
        supplied attributes — `carrier_id`, `unit_number`, `vin`,
        `weight_group_code`, `factory_price_amount` and `registration_year` — come
        back exactly as enrolled.

        Design: Corner/entities/vehicle_retrieval_returns_the_stored_row_with_its_system_dimensions
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier = create_carrier(
            client,
            legal_name="Prairie Freight LLC",
            usdot_number="USDOT-2637001",
            base_jurisdiction_code="IL",
        )
        created = create_vehicle(
            client,
            carrier["id"],
            unit_number="U-101",
            vin="1FUJA6CK21L101101",
            factory_price_amount=145000.00,
            registration_year=2026,
        )

        vehicle = validate_success(
            client.get_vehicle(created["id"], ANALYST_1_HEADERS)
        )
        assert vehicle["carrier_id"] == carrier["id"], vehicle
        assert vehicle["unit_number"] == "U-101", vehicle
        assert vehicle["vin"] == "1FUJA6CK21L101101", vehicle
        assert vehicle["weight_group_code"] == WEIGHT_GROUP_W80, vehicle
        assert_money(vehicle["factory_price_amount"], 145000.00, "factory_price_amount")
        assert vehicle["registration_year"] == 2026, vehicle
        assert_vehicle_dimensions(
            vehicle,
            vehicle_status="PENDING",
            credential_status="NONE",
            replaced_vehicle_id=None,
            activated_on_date=None,
        )

    def test_a_trip_mints_its_own_system_fields_and_sequences_its_legs(
        self, client
    ):
        """"Each element becomes one `JurisdictionMileageLeg` row whose
        `trip_record_id` points back at the trip, whose `leg_status` starts at
        `ACTIVE`, and whose `leg_sequence` is assigned by the server from the
        element's 1-based position in the submitted array." And "`leg_sequence` is
        never supplied by the client, is at least 1, is unique among the trip's
        `ACTIVE` legs, and is the sort key whenever legs are processed in order."
        And "In both cases `mileage_source` starts at
        `TELEMATICS`, `accepted_leg_miles_total` is set to the sum of `leg_miles`
        over the trip's `ACTIVE` legs rounded to 1 decimal place, and
        `reconstructed_by_user_id` and `supporting_document_reference` are null."

        Design: Corner/entities/trip_system_fields_are_server_minted_and_legs_are_sequenced_by_submission_order
        """
        seed_reference_data(client)
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

        response = client.create_trip_record(
            trip_record_payload(
                carrier["id"],
                vehicle["id"],
                trip_start_utc="2026-04-05T06:00:00Z",
                trip_end_utc="2026-04-05T18:00:00Z",
                start_odometer=1000.0,
                end_odometer=1700.0,
                legs=[leg("KY", 200.0), leg("IL", 300.0), leg("IN", 200.0)],
            ),
            ANALYST_1_HEADERS,
        )
        trip = validate_success(response, expected_status=201)
        assert_versioned_entity(trip)
        assert_version_is(trip, 1)
        assert_trip_state(
            trip,
            trip_status="CAPTURED",
            mileage_source="TELEMATICS",
            odometer_delta_miles=700.0,
            gap_miles_from_previous=0.0,
            accepted_leg_miles_total=700.0,
            reconstructed_by_user_id=None,
            supporting_document_reference=None,
        )

        legs = trip_legs(client, trip["id"])
        assert [(row["leg_sequence"], row["jurisdiction_code"]) for row in legs] == [
            (1, "KY"),
            (2, "IL"),
            (3, "IN"),
        ], legs
        assert all(row["leg_status"] == "ACTIVE" for row in legs), legs
        assert all(row["trip_record_id"] == trip["id"] for row in legs), legs

    def test_one_jurisdiction_row_serves_the_legs_of_many_trips(self, client):
        """"Each element becomes one `JurisdictionMileageLeg` row whose
        `trip_record_id` points back at the trip, whose `leg_status` starts at
        `ACTIVE`, and whose `leg_sequence` is assigned by the server from the
        element's 1-based position in the submitted array", and "Legs are the child of a
        trip; the leg-listing read is the only channel through which
        reconstruction-replaced and cascade-voided legs become observable, and it
        accepts a `leg_status` filter for exactly that purpose." Two units' trips
        both name Illinois without sharing a leg row.

        Design: Corner/entities/mileage_legs_form_a_many_to_many_junction_between_trips_and_jurisdictions
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL, JURISDICTION_IN])
        carrier = create_carrier(
            client,
            legal_name="Prairie Freight LLC",
            usdot_number="USDOT-2637001",
            base_jurisdiction_code="IL",
        )
        first_unit = create_vehicle(
            client,
            carrier["id"],
            unit_number="U-101",
            vin="1FUJA6CK21L101101",
            factory_price_amount=145000.00,
        )
        second_unit = create_vehicle(
            client,
            carrier["id"],
            unit_number="U-102",
            vin="1FUJA6CK21L101102",
            factory_price_amount=152000.00,
        )
        first_trip = capture_trip(
            client,
            carrier["id"],
            first_unit["id"],
            "2026-04-05T06:00:00Z",
            "2026-04-05T18:00:00Z",
            1000.0,
            1400.0,
            [leg("IL", 300.0), leg("IN", 100.0)],
        )
        second_trip = capture_trip(
            client,
            carrier["id"],
            second_unit["id"],
            "2026-04-06T06:00:00Z",
            "2026-04-06T18:00:00Z",
            500.0,
            750.0,
            [leg("IL", 250.0)],
        )

        first_legs = trip_legs(client, first_trip["id"], leg_status="ACTIVE")
        second_legs = trip_legs(client, second_trip["id"], leg_status="ACTIVE")
        assert [row["jurisdiction_code"] for row in first_legs] == ["IL", "IN"], first_legs
        assert all(row["trip_record_id"] == first_trip["id"] for row in first_legs)
        assert [row["jurisdiction_code"] for row in second_legs] == ["IL"], second_legs
        assert second_legs[0]["trip_record_id"] == second_trip["id"], second_legs
        assert not {row["id"] for row in first_legs} & {
            row["id"] for row in second_legs
        }, "a leg row may not be shared between two trips"


@pytest.fixture
def carrier_with_one_illinois_unit(client):
    """The smallest useful fleet: one Illinois carrier holding unit U-101."""
    seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
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
    return {"carrier_id": carrier["id"], "vehicle_id": vehicle["id"]}


class TestListingWindowsAndFilters:
    """A collection read reports the window it applied and the size of the set
    it applied it to."""

    def test_the_trip_listing_windows_by_limit_and_offset_and_reports_total_count(
        self, client, carrier_with_one_illinois_unit
    ):
        """"Both are reported back in `meta` alongside `total_count` — the number of
        rows matching the filters before the window is applied — and `has_more`, a
        boolean that is true exactly when rows remain beyond the returned window."
        Trips "sort by `trip_start_utc` ascending", and "Filters offered on a
        collection narrow the row set before ordering and windowing."

        Design: Corner/entities/trip_record_listing_paginates_with_total_count_and_has_more
        """
        ctx = carrier_with_one_illinois_unit
        first = capture_trip(
            client,
            ctx["carrier_id"],
            ctx["vehicle_id"],
            "2026-04-05T06:00:00Z",
            "2026-04-05T18:00:00Z",
            1000.0,
            1400.0,
            [leg("IL", 400.0)],
        )
        second = capture_trip(
            client,
            ctx["carrier_id"],
            ctx["vehicle_id"],
            "2026-05-10T06:00:00Z",
            "2026-05-10T18:00:00Z",
            1400.0,
            1700.0,
            [leg("IL", 300.0)],
        )
        gapped = capture_trip(
            client,
            ctx["carrier_id"],
            ctx["vehicle_id"],
            "2026-06-10T06:00:00Z",
            "2026-06-10T18:00:00Z",
            1800.0,
            2000.0,
            [leg("IL", 200.0)],
        )

        page, meta = validate_paginated(
            client.list_trip_records(
                PREPARER_1_HEADERS,
                params={"carrier_id": ctx["carrier_id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page) == 2, [row["trip_start_utc"] for row in page]
        assert meta["total_count"] == 3, meta
        assert meta["has_more"] is True, meta
        assert (meta["limit"], meta["offset"]) == (2, 0), meta
        assert [row["id"] for row in page] == [first["id"], second["id"]], page

        tail, tail_meta = validate_paginated(
            client.list_trip_records(
                PREPARER_1_HEADERS,
                params={"carrier_id": ctx["carrier_id"], "limit": 2, "offset": 2},
            )
        )
        assert [row["id"] for row in tail] == [gapped["id"]], tail
        assert tail_meta["total_count"] == 3, tail_meta
        assert tail_meta["has_more"] is False, tail_meta

        flagged, flagged_meta = validate_paginated(
            client.list_trip_records(
                PREPARER_1_HEADERS,
                params={
                    "carrier_id": ctx["carrier_id"],
                    "trip_status": "GAP_FLAGGED",
                },
            )
        )
        assert [row["id"] for row in flagged] == [gapped["id"]], flagged
        assert flagged_meta["total_count"] == 1, flagged_meta
        assert_miles(
            flagged[0]["gap_miles_from_previous"], 100.0, "gap_miles_from_previous"
        )
        assert_trip_state(first, trip_status="CAPTURED")
        assert_trip_state(second, trip_status="CAPTURED")


class TestRequestShapeIsCheckedBeforeAnythingIsWritten:
    """A malformed body earns `ERR_INVALID_REQUEST` and leaves the database
    exactly as it was."""

    def test_a_carrier_create_without_a_usdot_number_is_a_shape_error(self, client):
        """"Request-shape validation at step 5 covers: presence of every required
        field, correct types, membership of every enum value in its declared set,
        rejection of unknown fields ... and `retention_deficiency_count` no
        smaller than 0." And step 5 answers
        "Request shape — `ERR_INVALID_REQUEST`." For a carrier, "A
        `ComplianceOfficer` supplies the `legal_name` exactly as it appears on the
        IFTA licence, the carrier's `usdot_number`, and the `base_jurisdiction_code`".

        Design: Corner/entities/carrier_create_missing_usdot_number_returns_invalid_request
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        payload = carrier_payload(legal_name="Prairie Freight LLC")
        payload.pop("usdot_number")
        payload.pop("bond_ceiling_amount")

        response = client.create_carrier(payload, OFFICER_1_HEADERS)
        validate_error(response, ERR_INVALID_REQUEST, expected_status=400)
        assert_error_envelope(response, ERR_INVALID_REQUEST)

        rows, meta = validate_paginated(client.list_carriers(OFFICER_1_HEADERS))
        assert meta["total_count"] == 0, meta
        assert rows == [], rows

    def test_zero_gallons_and_a_backward_odometer_are_both_shape_errors(
        self, client, carrier_with_one_illinois_unit
    ):
        """"Request-shape validation at step 5 covers: ... `gallons` strictly
        greater than 0.000, `end_odometer` strictly greater than `start_odometer`",
        and step 5 answers "Request shape — `ERR_INVALID_REQUEST`." Neither refused
        write leaves a row behind, and the carrier's gallon ledger — of which
        "Every other carrier attribute is system-owned and starts at a known value:
        ... `tax_paid_gallons_ytd` at 0.000" — never moves.

        Design: Corner/entities/shape_violations_on_gallons_and_odometer_are_rejected_as_invalid_request
        """
        ctx = carrier_with_one_illinois_unit
        empty_purchase = client.create_fuel_purchase(
            fuel_purchase_payload(
                ctx["carrier_id"],
                ctx["vehicle_id"],
                jurisdiction_code="IL",
                purchase_date="2026-05-02",
                gallons=0.000,
            ),
            ANALYST_1_HEADERS,
        )
        validate_error(empty_purchase, ERR_INVALID_REQUEST, expected_status=400)

        backward = client.create_trip_record(
            trip_record_payload(
                ctx["carrier_id"],
                ctx["vehicle_id"],
                trip_start_utc="2026-04-05T06:00:00Z",
                trip_end_utc="2026-04-05T18:00:00Z",
                start_odometer=1000.0,
                end_odometer=900.0,
                legs=[leg("IL", 100.0)],
            ),
            ANALYST_1_HEADERS,
        )
        validate_error(backward, ERR_INVALID_REQUEST, expected_status=400)

        _, purchase_meta = validate_paginated(
            client.list_fuel_purchases(
                ANALYST_1_HEADERS, params={"carrier_id": ctx["carrier_id"]}
            )
        )
        assert purchase_meta["total_count"] == 0, purchase_meta
        _, trip_meta = validate_paginated(
            client.list_trip_records(
                ANALYST_1_HEADERS, params={"carrier_id": ctx["carrier_id"]}
            )
        )
        assert trip_meta["total_count"] == 0, trip_meta
        assert_carrier_compliance(
            validate_success(
                client.get_carrier(ctx["carrier_id"], ANALYST_1_HEADERS)
            ),
            tax_paid_gallons_ytd=0.000,
        )

    def test_an_unknown_change_type_is_rejected_before_the_version_and_state_checks(
        self, client, carrier_with_one_illinois_unit
    ):
        """"Request-shape validation at step 5 covers: ... membership of every enum
        value in its declared set", and step 5 outranks both step 8
        "Optimistic-concurrency version match" and step 9 "State compatibility of
        the target resource with the requested transition", so a `DRAFT` parent and
        a correct `expected_registration_application_version` cannot rescue a
        `change_type` outside its declared set. And since "`version` is an integer
        that starts at 1 when the row is created and increments by exactly 1 on every
        mutation of that row", a refused create leaves the parent's version alone.

        Design: Corner/entities/unknown_change_type_enum_member_is_rejected_as_invalid_request
        """
        ctx = carrier_with_one_illinois_unit
        application = open_application(
            client,
            ctx["carrier_id"],
            registration_year=2026,
            distance_basis="ACTUAL_DISTANCE_BASIS",
            headers=PREPARER_1_HEADERS,
        )
        version_before = application_version(client, application["id"])

        payload = fleet_change_request_payload(
            application["id"],
            ctx["vehicle_id"],
            change_type="SWAP",
            effective_date="2026-07-15",
            expected_registration_application_version=version_before,
        )
        payload.pop("replaced_vehicle_id")
        response = client.create_fleet_change_request(payload, PREPARER_1_HEADERS)
        validate_error(response, ERR_INVALID_REQUEST, expected_status=400)

        _, meta = validate_paginated(
            client.list_fleet_change_requests(
                PREPARER_1_HEADERS,
                params={"registration_application_id": application["id"]},
            )
        )
        assert meta["total_count"] == 0, meta
        after = read_application(client, application["id"])
        assert_version_is(after, version_before)
        assert after["application_status"] == "DRAFT", after


class TestDanglingReferencesAreReportedInAFixedOrder:
    """Which missing thing you are told about is not a matter of taste."""

    def test_body_foreign_keys_are_reported_in_declaration_order(
        self, client, carrier_with_one_illinois_unit
    ):
        """"Existence of every foreign key supplied in the request body, evaluated
        in this body-field order: `carrier_id`, `vehicle_id`, `replaced_vehicle_id`,
        `registration_application_id`, `distributed_to_driver_id` — answering with
        `ERR_CARRIER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`,
        `ERR_REGISTRATION_APPLICATION_NOT_FOUND` or `ERR_DRIVER_NOT_FOUND` as
        appropriate, all HTTP 404."

        Design: Corner/entities/trip_create_foreign_keys_are_checked_in_body_declaration_order
        """
        ctx = carrier_with_one_illinois_unit
        both_absent = client.create_trip_record(
            trip_record_payload(
                NON_EXISTENT_UUID,
                NON_EXISTENT_UUID,
                trip_start_utc="2026-04-05T06:00:00Z",
                trip_end_utc="2026-04-05T18:00:00Z",
                start_odometer=1000.0,
                end_odometer=1400.0,
                legs=[leg("IL", 400.0)],
            ),
            ANALYST_1_HEADERS,
        )
        validate_error(both_absent, ERR_CARRIER_NOT_FOUND, expected_status=404)

        unit_absent = client.create_trip_record(
            trip_record_payload(
                ctx["carrier_id"],
                NON_EXISTENT_UUID,
                trip_start_utc="2026-04-05T06:00:00Z",
                trip_end_utc="2026-04-05T18:00:00Z",
                start_odometer=1000.0,
                end_odometer=1400.0,
                legs=[leg("IL", 400.0)],
            ),
            ANALYST_1_HEADERS,
        )
        validate_error(unit_absent, ERR_VEHICLE_NOT_FOUND, expected_status=404)

        _, meta = validate_paginated(
            client.list_trip_records(
                ANALYST_1_HEADERS, params={"carrier_id": ctx["carrier_id"]}
            )
        )
        assert meta["total_count"] == 0, meta

    def test_each_absent_path_id_answers_with_its_own_not_found_code(self, client):
        """"Existence of the path resource, in this sequence by resource kind:
        carrier (`ERR_CARRIER_NOT_FOUND`), vehicle (`ERR_VEHICLE_NOT_FOUND`), trip
        record (`ERR_TRIP_RECORD_NOT_FOUND`), fuel purchase
        (`ERR_FUEL_PURCHASE_NOT_FOUND`), fuel tax return
        (`ERR_FUEL_TAX_RETURN_NOT_FOUND`), registration application
        (`ERR_REGISTRATION_APPLICATION_NOT_FOUND`), fleet change request
        (`ERR_FLEET_CHANGE_REQUEST_NOT_FOUND`), credential
        (`ERR_CREDENTIAL_NOT_FOUND`), audit selection
        (`ERR_AUDIT_SELECTION_NOT_FOUND`)." The path check is step 3 and body
        foreign keys are step 4, so the distribute call names the absent credential
        rather than the absent driver.

        Design: Corner/entities/unknown_path_ids_return_the_entity_specific_not_found_error
        """
        validate_error(
            client.get_trip_record(NON_EXISTENT_UUID, ANALYST_1_HEADERS),
            ERR_TRIP_RECORD_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            client.disallow_fuel_purchase(
                NON_EXISTENT_UUID,
                ANALYST_1_HEADERS,
                disallow_reason_code="MISSING_RECEIPT",
            ),
            ERR_FUEL_PURCHASE_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            client.list_return_jurisdiction_lines(
                NON_EXISTENT_UUID, PREPARER_1_HEADERS
            ),
            ERR_FUEL_TAX_RETURN_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            client.decide_fleet_change_request(
                NON_EXISTENT_UUID, OFFICER_1_HEADERS, decision="APPROVE"
            ),
            ERR_FLEET_CHANGE_REQUEST_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            client.distribute_credential(
                NON_EXISTENT_UUID,
                OFFICER_1_HEADERS,
                distributed_to_driver_id=NON_EXISTENT_UUID,
            ),
            ERR_CREDENTIAL_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            client.retention_review_audit_selection(
                NON_EXISTENT_UUID,
                OFFICER_1_HEADERS,
                expected_records_count=20,
                records_missing_count=5,
            ),
            ERR_AUDIT_SELECTION_NOT_FOUND,
            expected_status=404,
        )
