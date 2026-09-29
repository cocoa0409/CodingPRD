"""What a refusal looks like, and which refusal arrives when several are true.

Every test in this file drives an operation to a documented failure and then
reads the affected records back. A refusal is only correct if it is also inert:
the ledgers it touched must be exactly where they were, the replayed decision
must not be applied twice, and the record that failed must still be sitting in
the status it failed from.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CHANGE_REQUEST_NOT_PENDING,
    ERR_DUPLICATE_APPLICATION_YEAR,
    ERR_DUPLICATE_AUDIT_PERIOD,
    ERR_DUPLICATE_JURISDICTION,
    ERR_DUPLICATE_UNIT_NUMBER,
    ERR_DUPLICATE_USDOT_NUMBER,
    ERR_DUPLICATE_WEIGHT_GROUP_FEE,
    ERR_INVALID_PURCHASE_STATE,
    ERR_INVALID_RETURN_STATE,
    ERR_NO_ACCEPTED_MILEAGE,
    ERR_NO_FILED_RETURN_FOR_PERIOD,
    ERR_RECONSTRUCTION_SUPPORT_MISSING,
    ERR_VEHICLE_NOT_FOUND,
    ERR_VEHICLE_STATE_INCOMPATIBLE,
)
from test_helpers.assertions import (
    assert_application_totals,
    assert_audit_selection,
    assert_carrier_compliance,
    assert_change_request,
    assert_error_envelope,
    assert_return_settlement,
    assert_trip_state,
    assert_vehicle_dimensions,
)
from test_helpers.constants import JURISDICTION_IL, JURISDICTION_IN
from test_helpers.factories import (
    audit_selection_payload,
    carrier_payload,
    jurisdiction_payload_for,
    leg,
    registration_application_payload,
    vehicle_payload,
    weight_group_fee_payload,
)
from test_helpers.fixtures import (
    accept_trip,
    capture_trip,
    carrier_version,
    create_carrier,
    create_vehicle,
    disallowed_purchase,
    invoiced_application,
    open_application,
    open_return,
    read_application,
    read_carrier,
    read_fleet_change,
    read_purchase,
    read_return,
    read_trip,
    read_vehicle,
    record_purchase,
    request_fleet_change,
    score_audit_selection,
    seed_jurisdictions,
    seed_reference_data_il_in_only,
    set_clock,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    PREPARER_1_HEADERS,
)


def _prairie(client):
    """The Illinois licensee that every scenario below registers."""
    return create_carrier(
        client,
        legal_name="Prairie Freight LLC",
        usdot_number="USDOT-2637001",
        base_jurisdiction_code="IL",
    )


def _unit(client, carrier_id, unit_number, vin, price, registration_year=2026):
    return create_vehicle(
        client,
        carrier_id,
        unit_number=unit_number,
        vin=vin,
        factory_price_amount=price,
        registration_year=registration_year,
    )


def _illinois_only(client):
    """Clock plus a single declared jurisdiction -- enough to register a carrier
    whose base jurisdiction must already exist, and nothing more."""
    set_clock(client)
    seed_jurisdictions(client, [JURISDICTION_IL])


class TestTheErrorEnvelopeIsTheOrdinaryEnvelope:
    def test_a_missing_vehicle_answers_in_the_standard_shape(self, client):
        """"The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        The error body is not a framework default. It carries the same meta
        block a success carries, minus the pagination fields, and its payload
        is a two-field object: "The `error_id` is a unique, machine-readable
        string that identifies the specific error." and "The `message` provides
        a human-readable explanation of what went wrong." The request id obeys
        the same rule it obeys on the success path -- "The `api_request_id` is
        a server-generated unique identifier for the request that starts with
        `req_`." A failed read is also inert: the carrier that does exist still
        reads back unharmed.

        Design: Corner/errors/the_error_envelope_carries_the_same_meta_block_as_a_success
        """
        _illinois_only(client)
        carrier = _prairie(client)

        response = client.get_vehicle(NON_EXISTENT_UUID, PREPARER_1_HEADERS)
        validate_error(response, ERR_VEHICLE_NOT_FOUND, 404)
        data = assert_error_envelope(response, ERR_VEHICLE_NOT_FOUND)
        assert data["message"].strip(), "the message must not be blank"
        assert set(data.keys()) == {"error_id", "message"}, (
            f"the error payload carries error_id and message only, got {sorted(data)}"
        )

        body = response.json()
        assert set(body.keys()) == {"meta", "response_type", "data"}, (
            f"unexpected top-level keys on the error envelope: {sorted(body)}"
        )
        assert "detail" not in body, "a bare framework detail body is not the contract"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        survivor = validate_success(
            client.get_carrier(carrier["id"], PREPARER_1_HEADERS)
        )
        assert survivor["id"] == carrier["id"]
        assert_carrier_compliance(
            survivor, ifta_license_status="ACTIVE", irp_account_status="ACTIVE"
        )


class TestTheAuditDeskNeedsAFiledReturnToMeasureAgainst:
    def test_a_carrier_can_be_selected_and_still_have_nothing_to_audit(self, client):
        """"And exactly one quarterly return of the carrier with `filing_year`
        equal to `selection_year` and `filing_quarter` equal to
        `selection_quarter` must be in `FILED` status; if none is, the review is
        refused with `ERR_NO_FILED_RETURN_FOR_PERIOD`, because there is no filed
        basis to audit against."

        Selection and reviewability are independent. This carrier has never
        prepared a return, so the efficiency factor stands down rather than
        maxing out -- "The fuel-efficiency factor contributes up to 25 points
        and is computed only where the carrier has a `latest_prepared_fleet_mpg`;
        if that field is null, because no return of the carrier has ever been
        prepared, this factor contributes exactly 0 rather than saturating." --
        and the remaining three factors saturate the ratio weight at 40, add 10
        for two late filings and 20 for four deficiencies. That is exactly 70,
        and "When `risk_score` reaches the selection threshold of 70 — the
        comparison is inclusive, so exactly 70 selects — the record is born
        `SELECTED` rather than `SCORED`, and the carrier's `audit_flag` is set
        to true with the carrier's `version` incrementing by 1."

        The refused review writes nothing at all, which is visible in the four
        fields the scoring step deliberately left empty: "Both outcomes leave
        `expected_records_count`, `records_missing_count`,
        `retention_deficiency_ratio` and `post_review_risk_score` null until a
        retention review runs, and `reviewed_by_user_id` null." A review that
        was refused is not a review that ran.

        Design: Corner/errors/retention_review_without_a_filed_return_for_the_period_is_rejected
        """
        _illinois_only(client)
        carrier = _prairie(client)
        vehicle = _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)

        substantiated = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-04-05T06:00:00Z",
            "2026-04-05T18:00:00Z",
            1000.0,
            1700.0,
            [leg("IL", 700.0)],
        )
        assert_trip_state(
            substantiated, trip_status="CAPTURED", odometer_delta_miles=700.0
        )
        flagged = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-05-10T06:00:00Z",
            "2026-05-10T18:00:00Z",
            1800.0,
            2100.0,
            [leg("IL", 300.0)],
        )
        assert_trip_state(
            flagged,
            trip_status="GAP_FLAGGED",
            gap_miles_from_previous=100.0,
            odometer_delta_miles=300.0,
        )
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]),
            unsubstantiated_mileage_ratio=0.3000,
            audit_flag=True,
            latest_prepared_fleet_mpg=None,
        )

        selection = score_audit_selection(
            client,
            carrier["id"],
            selection_year=2026,
            selection_quarter=2,
            late_filing_count=2,
            retention_deficiency_count=4,
        )
        assert_audit_selection(
            selection,
            risk_score=70,
            selection_status="SELECTED",
            post_review_risk_score=None,
            retention_deficiency_ratio=None,
            expected_records_count=None,
            records_missing_count=None,
            reviewed_by_user_id=None,
        )

        validate_error(
            client.retention_review_audit_selection(
                selection["id"],
                OFFICER_1_HEADERS,
                expected_records_count=10,
                records_missing_count=3,
            ),
            ERR_NO_FILED_RETURN_FOR_PERIOD,
            409,
        )

        rows, meta = validate_paginated(
            client.list_carrier_audit_selections(carrier["id"], OFFICER_1_HEADERS)
        )
        assert meta["total_count"] == 1
        assert_audit_selection(
            rows[0],
            risk_score=70,
            selection_status="SELECTED",
            post_review_risk_score=None,
            retention_deficiency_ratio=None,
            expected_records_count=None,
            records_missing_count=None,
            reviewed_by_user_id=None,
        )
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]),
            ifta_license_status="ACTIVE",
            suspension_count=0,
            audit_flag=True,
        )


class TestEachNaturalKeyAnswersWithItsOwnDuplicateError:
    def test_the_reference_and_fleet_keys_are_four_distinct_refusals(self, client):
        """"A `Jurisdiction` row is keyed for business purposes by
        `jurisdiction_code`, exactly two uppercase letters, unique across all
        declared jurisdictions; a collision is rejected with
        `ERR_DUPLICATE_JURISDICTION` (HTTP 409)."

        One uniqueness rule, four tables, four different error ids. The fee
        chart is keyed on a pair, not on a jurisdiction -- "The pair of
        `jurisdiction_code` and `weight_group_code` is unique across the chart;
        republishing an existing pair is refused with
        `ERR_DUPLICATE_WEIGHT_GROUP_FEE`." -- so an Indiana cell for the same
        weight group is a fresh row rather than a collision. The carrier key is
        single-column: "A `usdot_number` already on file is refused with
        `ERR_DUPLICATE_USDOT_NUMBER`." The fleet key is a triple: "The
        combination of `carrier_id`, `unit_number` and `registration_year` must
        be unique; a collision is refused with `ERR_DUPLICATE_UNIT_NUMBER`." --
        which is why the same unit number is admitted again for the following
        registration year, and admitted in the same unplated state a first
        enrolment gets: "A newly enrolled unit is not yet plated:
        `vehicle_status` starts at `PENDING`, the derived `credential_status`
        reads `NONE`, `replaced_vehicle_id` is null, and `activated_on_date` is
        null."

        Design: Corner/errors/reference_natural_key_collisions_each_raise_their_own_duplicate_error
        """
        set_clock(client)
        declared = seed_jurisdictions(client, [JURISDICTION_IL, JURISDICTION_IN])
        validate_success(
            client.create_weight_group_fee(
                weight_group_fee_payload(
                    jurisdiction_code="IL", annual_fee_amount=2790.00
                ),
                OFFICER_1_HEADERS,
            ),
            201,
        )
        carrier = _prairie(client)
        _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)

        validate_error(
            client.create_jurisdiction(
                jurisdiction_payload_for(
                    "IL", name="Illinois duplicate", fuel_tax_rate_per_gallon=0.7000
                ),
                OFFICER_1_HEADERS,
            ),
            ERR_DUPLICATE_JURISDICTION,
            409,
        )
        illinois = validate_success(
            client.get_jurisdiction(declared["IL"]["id"], OFFICER_1_HEADERS)
        )
        assert illinois["name"] == "Illinois"
        assert illinois["fuel_tax_rate_per_gallon"] == 0.6270

        validate_error(
            client.create_weight_group_fee(
                weight_group_fee_payload(
                    jurisdiction_code="IL", annual_fee_amount=3000.00
                ),
                OFFICER_1_HEADERS,
            ),
            ERR_DUPLICATE_WEIGHT_GROUP_FEE,
            409,
        )
        indiana_cell = validate_success(
            client.create_weight_group_fee(
                weight_group_fee_payload(
                    jurisdiction_code="IN", annual_fee_amount=1692.00
                ),
                OFFICER_1_HEADERS,
            ),
            201,
        )
        assert indiana_cell["jurisdiction_code"] == "IN"
        assert indiana_cell["weight_group_code"] == "W80"

        validate_error(
            client.create_carrier(
                carrier_payload(
                    legal_name="Copycat Freight LLC",
                    usdot_number="USDOT-2637001",
                    base_jurisdiction_code="IN",
                ),
                OFFICER_1_HEADERS,
            ),
            ERR_DUPLICATE_USDOT_NUMBER,
            409,
        )

        validate_error(
            client.create_vehicle(
                vehicle_payload(
                    carrier["id"],
                    unit_number="U-101",
                    vin="1FUJA6CK21L101999",
                    factory_price_amount=145000.00,
                    registration_year=2026,
                ),
                OFFICER_1_HEADERS,
            ),
            ERR_DUPLICATE_UNIT_NUMBER,
            409,
        )
        next_year = validate_success(
            client.create_vehicle(
                vehicle_payload(
                    carrier["id"],
                    unit_number="U-101",
                    vin="1FUJA6CK21L101998",
                    factory_price_amount=145000.00,
                    registration_year=2027,
                ),
                OFFICER_1_HEADERS,
            ),
            201,
        )
        assert next_year["registration_year"] == 2027
        assert_vehicle_dimensions(
            next_year,
            vehicle_status="PENDING",
            credential_status="NONE",
            replaced_vehicle_id=None,
            activated_on_date=None,
        )

        rows, meta = validate_paginated(
            client.list_vehicles(OFFICER_1_HEADERS, params={"carrier_id": carrier["id"]})
        )
        assert meta["total_count"] == 2
        assert sorted(row["registration_year"] for row in rows) == [2026, 2027]

    def test_the_application_year_and_the_audit_period_are_scoped_differently(
        self, client
    ):
        """"A carrier may hold only one live application per year: if it already
        has an application for the same `registration_year` whose
        `application_status` is anything other than `RETURNED_FOR_CORRECTION`,
        the new application is refused with `ERR_DUPLICATE_APPLICATION_YEAR`."

        The registration key is (carrier, year); the audit key carries the
        quarter as well -- "A carrier may be scored only once per period: a
        repeat of the same `carrier_id`, `selection_year` and
        `selection_quarter` is refused with `ERR_DUPLICATE_AUDIT_PERIOD`." So a
        second 2026 application is refused while a 2027 one opens, and a second
        2026 Q2 selection is refused while a 2026 Q3 one scores. The refused
        application also leaves the incumbent's own basis alone rather than
        overwriting it with the rejected payload's. The Q3 record has no
        evidence of anything against it, and "When `risk_score` falls below 70
        the record is born `NOT_SELECTED` and nothing outside the record
        changes."

        Design: Corner/errors/application_year_and_audit_period_collisions_raise_their_own_duplicate_errors
        """
        _illinois_only(client)
        carrier = _prairie(client)
        _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)
        application = open_application(client, carrier["id"], registration_year=2026)
        assert_application_totals(application, application_status="DRAFT")
        first_selection = score_audit_selection(
            client, carrier["id"], selection_year=2026, selection_quarter=2
        )
        assert_audit_selection(
            first_selection, risk_score=0, selection_status="NOT_SELECTED"
        )

        validate_error(
            client.create_registration_application(
                registration_application_payload(
                    carrier["id"],
                    registration_year=2026,
                    distance_basis="ESTIMATED_DISTANCE_BASIS",
                ),
                PREPARER_1_HEADERS,
            ),
            ERR_DUPLICATE_APPLICATION_YEAR,
            409,
        )
        incumbent = read_application(client, application["id"])
        assert incumbent["distance_basis"] == "ACTUAL_DISTANCE_BASIS"
        assert_application_totals(incumbent, application_status="DRAFT")

        following_year = validate_success(
            client.create_registration_application(
                registration_application_payload(
                    carrier["id"],
                    registration_year=2027,
                    distance_basis="ESTIMATED_DISTANCE_BASIS",
                ),
                PREPARER_1_HEADERS,
            ),
            201,
        )
        assert following_year["registration_year"] == 2027
        assert_application_totals(following_year, application_status="DRAFT")

        validate_error(
            client.create_audit_selection(
                audit_selection_payload(
                    carrier["id"], selection_year=2026, selection_quarter=2
                ),
                OFFICER_1_HEADERS,
            ),
            ERR_DUPLICATE_AUDIT_PERIOD,
            409,
        )
        third_quarter = validate_success(
            client.create_audit_selection(
                audit_selection_payload(
                    carrier["id"], selection_year=2026, selection_quarter=3
                ),
                OFFICER_1_HEADERS,
            ),
            201,
        )
        assert third_quarter["late_filing_count"] == 0
        assert third_quarter["retention_deficiency_count"] == 0
        assert_audit_selection(
            third_quarter, risk_score=0, selection_status="NOT_SELECTED"
        )

        rows, meta = validate_paginated(
            client.list_carrier_audit_selections(
                carrier["id"], OFFICER_1_HEADERS, params={"selection_year": 2026}
            )
        )
        assert meta["total_count"] == 2
        assert [row["selection_quarter"] for row in rows] == [2, 3]


class TestASupplementIsPricedOnceAndOnlyOnUnitsInTheRightState:
    def _invoiced_with_a_spare_unit(self, client):
        """An invoiced 2026 fleet of one unit, plus a second unit enrolled after
        invoicing and therefore still unplated."""
        seed_reference_data_il_in_only(client)
        carrier = _prairie(client)
        first = _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)
        application = invoiced_application(
            client, carrier["id"], [("IL", 60000.0), ("IN", 40000.0)]
        )
        assert_application_totals(
            application,
            application_status="INVOICED",
            apportioned_vehicle_count=1,
            base_fee_total=2350.80,
            total_apportioned_fee=2350.80,
        )
        second = _unit(client, carrier["id"], "U-102", "1FUJA6CK21L101102", 152000.00)
        assert_vehicle_dimensions(second, vehicle_status="PENDING")
        return carrier, first, second, application

    def test_a_deletion_aimed_at_a_pending_unit_is_refused_at_the_decision(
        self, client
    ):
        """"And the referenced units must be in the states their `change_type`
        requires: for `ADDITION`, the target unit's `vehicle_status` must be
        `PENDING`; for `DELETION`, it must be `ACTIVE`; for `TRANSFER`, the
        incoming unit named by `vehicle_id` must be `PENDING` **and** the
        outgoing unit named by `replaced_vehicle_id` must be `ACTIVE`. Any
        mismatch is refused with `ERR_VEHICLE_STATE_INCOMPATIBLE`."

        U-102 was enrolled after invoicing, so it never reached `ACTIVE` and
        cannot be deleted. Filing the supplement is nonetheless permitted --
        the state of the unit is examined at the decision, not at the request --
        so the record is born in the shape the specification prescribes: "A
        newly filed supplement opens with `change_status` `REQUESTED`,
        `fee_delta` at 0.00, `prorate_months` at 0, `decided_by_user_id` and
        `reversal_reason_code` null, and `requested_by_user_id` stamped from the
        caller's `X-User-ID` — which, for a `CarrierAdmin`, is the requesting
        carrier's own `id`." The refused approval leaves it there: an
        unpriceable deletion is not silently skipped and the fee does not move.

        Design: Corner/errors/deleting_a_pending_unit_is_rejected_as_vehicle_state_incompatible
        """
        carrier, first, second, application = self._invoiced_with_a_spare_unit(client)

        change = request_fleet_change(
            client, application["id"], second["id"], "DELETION", "2026-07-15"
        )
        assert_change_request(
            change,
            change_status="REQUESTED",
            fee_delta=0.00,
            prorate_months=0,
            decided_by_user_id=None,
            reversal_reason_code=None,
        )

        validate_error(
            client.decide_fleet_change_request(
                change["id"], OFFICER_1_HEADERS, decision="APPROVE"
            ),
            ERR_VEHICLE_STATE_INCOMPATIBLE,
            409,
        )

        assert_change_request(
            read_fleet_change(client, change["id"]),
            change_status="REQUESTED",
            fee_delta=0.00,
            prorate_months=0,
            decided_by_user_id=None,
        )
        assert_vehicle_dimensions(
            read_vehicle(client, second["id"]), vehicle_status="PENDING"
        )
        assert_vehicle_dimensions(
            read_vehicle(client, first["id"]), vehicle_status="ACTIVE"
        )
        assert_application_totals(
            read_application(client, application["id"]),
            application_status="INVOICED",
            apportioned_vehicle_count=1,
            base_fee_total=2350.80,
            total_apportioned_fee=2350.80,
        )
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]), irp_account_status="ACTIVE"
        )

    def test_replaying_approve_on_an_approved_addition_does_not_charge_twice(
        self, client
    ):
        """"Either decision requires `change_status` to be `REQUESTED`; a
        decision against a request in any other status is refused with
        `ERR_CHANGE_REQUEST_NOT_PENDING`."

        The July addition is priced once. "For an `ADDITION`, the month of entry
        is charged, so `prorate_months` is thirteen minus the month number — a
        January addition is charged all twelve months and a December addition is
        charged one — and `fee_delta` is the per-vehicle full-year fee
        multiplied by `prorate_months`, divided by twelve, rounded to 2 decimal
        places." Six months of the frozen 2350.80 is 1175.40, and the unit joins
        the fleet: "An approved `ADDITION` moves the target unit `PENDING →
        ACTIVE` and stamps `activated_on_date` with the supplement's
        `effective_date` — not with the logical clock, which is the rule that
        applies to activation at invoicing instead."

        The replay is where the conservation property is visible. Because
        "The application's `total_apportioned_fee` becomes its `base_fee_total`
        plus the sum of `fee_delta` over all of that application's supplements
        whose `change_status` is `APPROVED`, rounded to 2 decimal places — a
        conserved quantity recomputed from the whole approved set rather than
        nudged incrementally.", a second successful approval of the same
        supplement could not double the charge anyway -- but the state gate
        refuses it first, and the count stays where one approval left it:
        "`apportioned_vehicle_count` is adjusted by plus one for an `ADDITION`,
        minus one for a `DELETION`, and zero for a `TRANSFER`, since a transfer
        swaps one unit for another."

        Design: Corner/errors/deciding_an_already_approved_change_request_is_rejected
        """
        carrier, first, second, application = self._invoiced_with_a_spare_unit(client)

        change = request_fleet_change(
            client, application["id"], second["id"], "ADDITION", "2026-07-15"
        )
        approved = validate_success(
            client.decide_fleet_change_request(
                change["id"], OFFICER_1_HEADERS, decision="APPROVE"
            )
        )
        assert_change_request(
            approved,
            change_status="APPROVED",
            prorate_months=6,
            fee_delta=1175.40,
        )
        assert_application_totals(
            read_application(client, application["id"]),
            application_status="INVOICED",
            apportioned_vehicle_count=2,
            base_fee_total=2350.80,
            total_apportioned_fee=3526.20,
        )
        assert_vehicle_dimensions(
            read_vehicle(client, second["id"]),
            vehicle_status="ACTIVE",
            activated_on_date="2026-07-15",
        )

        validate_error(
            client.decide_fleet_change_request(
                change["id"], OFFICER_1_HEADERS, decision="APPROVE"
            ),
            ERR_CHANGE_REQUEST_NOT_PENDING,
            409,
        )

        assert_change_request(
            read_fleet_change(client, change["id"]),
            change_status="APPROVED",
            prorate_months=6,
            fee_delta=1175.40,
        )
        assert_application_totals(
            read_application(client, application["id"]),
            application_status="INVOICED",
            apportioned_vehicle_count=2,
            base_fee_total=2350.80,
            total_apportioned_fee=3526.20,
        )
        assert_vehicle_dimensions(
            read_vehicle(client, first["id"]), vehicle_status="ACTIVE"
        )
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]), irp_account_status="ACTIVE"
        )


class TestAReconstructionWithoutPaperIsNotAReconstruction:
    def test_a_blank_document_reference_is_not_a_supplied_document_reference(
        self, client
    ):
        """"If `supporting_document_reference` is absent or empty, or if
        `reconstructed_legs` is empty, the attempt is refused with
        `ERR_RECONSTRUCTION_SUPPORT_MISSING`. A reconstruction without a paper
        trail is not a reconstruction."

        The empty string is the interesting case, because a present-but-blank
        field satisfies a naive required-field check and must still be refused
        here. Nothing about the trip moves: it keeps the basis and the totals it
        was born with -- "In both cases `mileage_source` starts at `TELEMATICS`,
        `accepted_leg_miles_total` is set to the sum of `leg_miles` over the
        trip's `ACTIVE` legs rounded to 1 decimal place, and
        `reconstructed_by_user_id` and `supporting_document_reference` are
        null." -- so the three hundred telematics miles it reported are still
        the miles on the record, and no analyst is stamped against it.

        Design: Corner/errors/a_reconstruction_with_a_blank_document_reference_is_rejected
        """
        _illinois_only(client)
        carrier = _prairie(client)
        vehicle = _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)

        capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-04-05T06:00:00Z",
            "2026-04-05T18:00:00Z",
            700.0,
            1000.0,
            [leg("IL", 300.0)],
        )
        flagged = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-05-10T06:00:00Z",
            "2026-05-10T18:00:00Z",
            1100.0,
            1400.0,
            [leg("IL", 300.0)],
        )
        assert_trip_state(
            flagged, trip_status="GAP_FLAGGED", gap_miles_from_previous=100.0
        )

        validate_error(
            client.reconstruct_trip_record(
                flagged["id"],
                ANALYST_1_HEADERS,
                reconstructed_legs=[leg("IL", 400.0)],
                supporting_document_reference="",
            ),
            ERR_RECONSTRUCTION_SUPPORT_MISSING,
            422,
        )

        assert_trip_state(
            read_trip(client, flagged["id"]),
            trip_status="GAP_FLAGGED",
            mileage_source="TELEMATICS",
            accepted_leg_miles_total=300.0,
            supporting_document_reference=None,
            reconstructed_by_user_id=None,
        )


class TestAReplayedDisallowanceDoesNotSubtractTwice:
    def test_the_gallons_ledger_stays_at_zero_rather_than_going_negative(self, client):
        """"Disallowance is reachable from `ACCEPTED` and from `RECORDED` alike
        and lands on the terminal `DISALLOWED`; a purchase that is already
        `DISALLOWED` cannot be disallowed again, and the attempt is refused with
        `ERR_INVALID_PURCHASE_STATE`."

        The purchase arrives receipted and tax-paid, so it is credited without a
        separate approval -- "A purchase moves `RECORDED → ACCEPTED` at creation
        time when **both** conditions hold: `receipt_reference` is present, and
        `tax_paid_flag` is true." -- and the first disallowance takes the credit
        back exactly: "Disallowing an `ACCEPTED` purchase stamps
        `disallow_reason_code` and reduces the carrier's `tax_paid_gallons_ytd`
        to its prior value minus the purchase's `gallons`, rounded to 3 decimal
        places — restoring, when that purchase was the only change, exactly the
        value the field held before the purchase existed."

        A replay is the test of the invariant rather than of the transition,
        because the ledger's definition admits no second subtraction: "That
        running total is a **conserved quantity**, maintained incrementally and
        exactly reversible, and its definition is the sum of `gallons` over the
        carrier's purchases whose `purchase_status` is `ACCEPTED` and whose
        `tax_paid_flag` is true, held to 3 decimal places." The replay is
        refused, the stored reason is not overwritten by the second attempt's,
        and the ledger reads zero rather than minus forty.

        Design: Corner/errors/disallowing_an_already_disallowed_purchase_is_rejected
        """
        _illinois_only(client)
        carrier = _prairie(client)
        vehicle = _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)

        purchase = record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            "IL",
            "2026-05-02",
            40.000,
            receipt_reference="RCPT-IL-4471",
        )
        assert purchase["purchase_status"] == "ACCEPTED"
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]), tax_paid_gallons_ytd=40.000
        )

        disallowed = disallowed_purchase(client, purchase["id"], "DUPLICATE")
        assert disallowed["purchase_status"] == "DISALLOWED"
        assert disallowed["disallow_reason_code"] == "DUPLICATE"
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]), tax_paid_gallons_ytd=0.000
        )

        validate_error(
            client.disallow_fuel_purchase(
                purchase["id"],
                ANALYST_1_HEADERS,
                disallow_reason_code="AUDIT_ADJUSTMENT",
            ),
            ERR_INVALID_PURCHASE_STATE,
            409,
        )

        replayed = read_purchase(client, purchase["id"])
        assert replayed["purchase_status"] == "DISALLOWED"
        assert replayed["disallow_reason_code"] == "DUPLICATE"
        settled = read_carrier(client, carrier["id"])
        assert_carrier_compliance(settled, tax_paid_gallons_ytd=0.000)
        assert settled["tax_paid_gallons_ytd"] >= 0.000

        rows, meta = validate_paginated(
            client.list_fuel_purchases(
                OFFICER_1_HEADERS,
                params={"carrier_id": carrier["id"], "purchase_status": "ACCEPTED"},
            )
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestTheReturnStateGateAnswersBeforeTheDeeperGuards:
    def test_filing_a_draft_return_never_reaches_segregation_of_duties(self, client):
        """"Either decision requires that the return be in `PREPARED`; from any
        other status the review is refused with `ERR_INVALID_RETURN_STATE`."

        This quarter has everything a settlement needs -- an accepted trip and a
        receipted tax-paid purchase -- but nobody has computed it, so the return
        is still `DRAFT` and the reviewer has nothing to sign off. The state gate
        is what answers, and it has to answer first, because the next guard along
        cannot even be evaluated: "Both decisions require that the reviewer's
        `X-User-ID` differ from the return's `prepared_by_user_id`, failing which
        the review is refused with `ERR_SEGREGATION_OF_DUTIES`." -- and
        `prepared_by_user_id` is null on a return nobody has prepared.

        Afterwards the return is still standing exactly where it was opened:
        "The new return opens in `DRAFT` with every computed figure at its zero
        value — `total_fleet_miles` at 0.0, `total_tax_paid_gallons` at 0.000,
        `reconstructed_mileage_ratio` at 0.0000, `total_net_tax_due`,
        `reconstruction_penalty_amount`, `total_amount_due` and
        `audit_assessment_delta` all at 0.00 — with `settlement_basis` at
        `PREPARER_BASIS`, `fleet_mpg` at null, and `prepared_by_user_id`,
        `filed_by_user_id` and `filed_at` all null."

        Design: Corner/errors/filing_a_draft_return_is_rejected_as_an_invalid_return_state
        """
        _illinois_only(client)
        carrier = _prairie(client)
        vehicle = _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)

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
        accepted = accept_trip(client, trip["id"])
        assert_trip_state(
            accepted, trip_status="ACCEPTED", accepted_leg_miles_total=650.0
        )
        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            "IL",
            "2026-05-02",
            100.000,
            receipt_reference="RCPT-IL-4471",
        )
        opened = open_return(client, carrier["id"], filing_year=2026, filing_quarter=2)
        assert_return_settlement(opened, return_status="DRAFT")

        validate_error(
            client.review_fuel_tax_return(
                opened["id"],
                OFFICER_1_HEADERS,
                decision="FILE",
                review_note="premature",
            ),
            ERR_INVALID_RETURN_STATE,
            409,
        )

        untouched = read_return(client, opened["id"])
        assert_return_settlement(
            untouched,
            return_status="DRAFT",
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=0.0,
            total_tax_paid_gallons=0.000,
            fleet_mpg=None,
            reconstructed_mileage_ratio=0.0000,
            total_net_tax_due=0.00,
            reconstruction_penalty_amount=0.00,
            total_amount_due=0.00,
            audit_assessment_delta=0.00,
        )
        assert untouched["prepared_by_user_id"] is None
        assert untouched["filed_by_user_id"] is None
        assert untouched["filed_at"] is None

        rows, meta = validate_paginated(
            client.list_return_jurisdiction_lines(opened["id"], OFFICER_1_HEADERS)
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]), latest_prepared_fleet_mpg=None
        )


class TestTheQuarterMustHaveSubstanceInBothBases:
    def test_gallons_without_accepted_mileage_fails_one_step_later(self, client):
        """"Finally the quarter must have substance in both bases: if the
        quarter's accepted tax-paid gallons total is not strictly greater than
        0.000, fleet MPG would be undefined and the attempt is refused with
        `ERR_NO_TAX_PAID_GALLONS`; and if the quarter's total effective mileage
        is not strictly greater than 0.0, the attempt is refused with
        `ERR_NO_ACCEPTED_MILEAGE`. The gallons check is evaluated before the
        mileage check."

        Here the first of the pair is satisfied and the second is not, which is
        the only way to observe the second one at all. A hundred receipted
        tax-paid gallons sit inside the quarter, and no trip has ever been
        captured for this carrier -- so the numerator of the fleet-MPG quotient
        is empty for the reason the settlement's first step describes: "The trips
        that count are those of the return's carrier whose `trip_status` is
        `ACCEPTED` and whose `trip_start_utc` falls inside the quarter window."
        The refusal leaves the carrier's version exactly where the preparer read
        it, which is the proof that no partial settlement was written.

        Design: Corner/errors/prepare_with_gallons_but_no_accepted_mileage_is_rejected
        """
        _illinois_only(client)
        carrier = _prairie(client)
        vehicle = _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)

        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            "IL",
            "2026-05-02",
            100.000,
            receipt_reference="RCPT-IL-4471",
        )
        opened = open_return(client, carrier["id"], filing_year=2026, filing_quarter=2)
        version_before = carrier_version(client, carrier["id"])

        validate_error(
            client.prepare_fuel_tax_return(
                opened["id"],
                PREPARER_1_HEADERS,
                expected_carrier_version=version_before,
            ),
            ERR_NO_ACCEPTED_MILEAGE,
            422,
        )

        settled = read_carrier(client, carrier["id"])
        assert_carrier_compliance(
            settled,
            tax_paid_gallons_ytd=100.000,
            latest_prepared_fleet_mpg=None,
        )
        assert settled["version"] == version_before

        untouched = read_return(client, opened["id"])
        assert_return_settlement(
            untouched,
            return_status="DRAFT",
            fleet_mpg=None,
            total_fleet_miles=0.0,
            total_tax_paid_gallons=0.000,
            total_amount_due=0.00,
        )
        assert untouched["prepared_by_user_id"] is None
