"""Refusals, and the order in which the desk hands them out.

Each test here drives one guard to its refusal, then proves two further things:
that the refusal named the right rule when a lower-priority rule was also
broken, and that nothing was written on the way out.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CARRIER_IRP_INACTIVE,
    ERR_CARRIER_SCOPE_VIOLATION,
    ERR_DRIVER_CARRIER_MISMATCH,
    ERR_DRIVER_NOT_FOUND,
    ERR_DUPLICATE_JURISDICTION_LINE,
    ERR_DUPLICATE_RETURN_PERIOD,
    ERR_EFFECTIVE_DATE_OUT_OF_YEAR,
    ERR_JURISDICTION_NOT_DECLARED,
    ERR_LEG_MILEAGE_MISMATCH,
    ERR_NO_TAX_PAID_GALLONS,
    ERR_PURCHASE_LOCKED_BY_FILED_RETURN,
    ERR_RECONSTRUCTION_WINDOW_CLOSED,
    ERR_RETENTION_PERIOD_EXPIRED,
    ERR_TRIP_GAP_UNRESOLVED,
    ERR_UNAUTHENTICATED,
    ERR_WEIGHT_GROUP_FEE_MISSING,
)
from test_helpers.assertions import (
    assert_apportion_percent,
    assert_application_totals,
    assert_audit_selection,
    assert_carrier_compliance,
    assert_change_request,
    assert_credential_state,
    assert_error_envelope,
    assert_jurisdiction_line,
    assert_miles,
    assert_money,
    assert_return_settlement,
    assert_trip_state,
    by_code,
    codes_of,
)
from test_helpers.constants import (
    JURISDICTION_IL,
    JURISDICTION_IN,
    WEIGHT_GROUP_FEES_W80,
)
from test_helpers.factories import (
    fuel_tax_return_payload,
    leg,
    trip_record_payload,
)
from test_helpers.fixtures import (
    accept_trip,
    add_schedule_lines,
    capture_trip,
    carrier_version,
    create_carrier,
    create_driver,
    create_vehicle,
    credentials_for_vehicle,
    file_return,
    invoiced_application,
    issue_credentials,
    open_application,
    open_return,
    prepare_return,
    read_application,
    read_carrier,
    read_credential,
    read_fleet_change,
    read_purchase,
    read_return,
    read_trip,
    read_vehicle,
    record_purchase,
    request_fleet_change,
    retention_review,
    return_lines,
    schedule_lines,
    score_audit_selection,
    seed_reference_data,
    seed_reference_data_il_in_only,
    set_clock,
    submit_application,
    trip_legs,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    PREPARER_1_HEADERS,
    make_carrier_admin_headers,
    make_headers,
)


def _carrier_with_one_unit(client, unit_number="U-101", vin="1FUJA6CK21L101101"):
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


class TestIdentityIsSettledBeforeAnythingElse:
    def test_an_empty_user_id_header_is_unauthenticated_not_forbidden(self, client):
        """"If either header is absent or empty, or if `X-User-Role` carries any
        string other than one of those four, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        The role in the second header is a perfectly good one for capturing a
        trip, and the body is a perfectly good trip. Only the identity is
        missing, and an empty `X-User-ID` counts as absent. The refusal is
        therefore priority 1's, not priority 2's. "If both headers are
        well-formed but the declared role is not among the roles authorised for
        the endpoint being called, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)" -- which is a different rule about a
        different problem, and it does not get to answer here.

        Design: Corner/validations/an_empty_x_user_id_header_is_unauthenticated_before_any_role_check
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier, vehicle = _carrier_with_one_unit(client)

        anonymous = make_headers("", "MileageAnalyst")
        response = client.create_trip_record(
            trip_record_payload(
                carrier["id"],
                vehicle["id"],
                trip_start_utc="2026-04-05T06:00:00Z",
                trip_end_utc="2026-04-05T18:00:00Z",
                start_odometer=1000.0,
                end_odometer=1400.0,
                legs=[leg("IL", 400.0)],
            ),
            anonymous,
        )
        validate_error(response, ERR_UNAUTHENTICATED)
        assert_error_envelope(response, ERR_UNAUTHENTICATED)

        _rows, meta = validate_paginated(
            client.list_trip_records(
                OFFICER_1_HEADERS, params={"carrier_id": carrier["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestReferencedDataMustBeDeclaredAndInScope:
    def test_a_leg_in_an_undeclared_jurisdiction_rolls_the_whole_trip_back(
        self, client
    ):
        """"Each element of `legs` names a `jurisdiction_code` and a `leg_miles`
        figure strictly greater than 0.0 and carried to 1 decimal place; the
        array may not be empty, and every code in it must be a declared
        jurisdiction."

        Only Illinois is on file, so the second leg's `ZZ` is a syntactically
        fine code for a jurisdiction that was never declared. That is priority
        6's business -- "Jurisdiction declaration for every referenced
        `jurisdiction_code` — `ERR_JURISDICTION_NOT_DECLARED`" -- and not a
        missing path resource nor a malformed body. The valid Illinois leg
        travelled in the same array and is not half-committed: no trip exists
        afterwards at all.

        Design: Corner/validations/a_leg_in_an_undeclared_jurisdiction_is_rejected
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier, vehicle = _carrier_with_one_unit(client)

        response = client.create_trip_record(
            trip_record_payload(
                carrier["id"],
                vehicle["id"],
                trip_start_utc="2026-04-05T06:00:00Z",
                trip_end_utc="2026-04-05T18:00:00Z",
                start_odometer=1000.0,
                end_odometer=1400.0,
                legs=[leg("IL", 300.0), leg("ZZ", 100.0)],
            ),
            ANALYST_1_HEADERS,
        )
        validate_error(response, ERR_JURISDICTION_NOT_DECLARED)

        _rows, meta = validate_paginated(
            client.list_trip_records(
                OFFICER_1_HEADERS, params={"carrier_id": carrier["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_a_carrier_admin_cannot_capture_a_trip_for_another_carrier(self, client):
        """"Concretely, a `CarrierAdmin` request is confined to its own fleet:
        the target vehicle's `carrier_id`, the parent application's
        `carrier_id`, or, for a credential handover, the `carrier_id` of the
        vehicle the credential was printed for, must all equal `X-User-ID`."

        "When `X-User-Role` is `CarrierAdmin`, `X-User-ID` is the `id` of the
        acting `Carrier`", so the scope test compares the body against the
        caller's own identity rather than consulting a role table: the same
        role, the same endpoint and an existing carrier and vehicle are refused
        with `ERR_CARRIER_SCOPE_VIOLATION` when the body names someone else's
        fleet, and accepted when it names the caller's own.

        Design: Corner/validations/a_carrier_admin_cannot_post_a_trip_for_another_carrier
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        prairie, prairie_unit = _carrier_with_one_unit(client)
        lakeshore = create_carrier(
            client,
            legal_name="Lakeshore Haulage Inc",
            usdot_number="USDOT-2637002",
            base_jurisdiction_code="IL",
        )
        lakeshore_unit = create_vehicle(
            client,
            lakeshore["id"],
            unit_number="L-201",
            vin="1FUJA6CK21L102201",
            factory_price_amount=139000.00,
            registration_year=2026,
        )

        lakeshore_admin = make_carrier_admin_headers(lakeshore["id"])
        response = client.create_trip_record(
            trip_record_payload(
                prairie["id"],
                prairie_unit["id"],
                trip_start_utc="2026-04-05T06:00:00Z",
                trip_end_utc="2026-04-05T18:00:00Z",
                start_odometer=1000.0,
                end_odometer=1400.0,
                legs=[leg("IL", 400.0)],
            ),
            lakeshore_admin,
        )
        validate_error(response, ERR_CARRIER_SCOPE_VIOLATION)

        # The identical call inside its own fleet is fine.
        own = validate_success(
            client.create_trip_record(
                trip_record_payload(
                    lakeshore["id"],
                    lakeshore_unit["id"],
                    trip_start_utc="2026-04-05T06:00:00Z",
                    trip_end_utc="2026-04-05T18:00:00Z",
                    start_odometer=500.0,
                    end_odometer=900.0,
                    legs=[leg("IL", 400.0)],
                ),
                lakeshore_admin,
            ),
            expected_status=201,
        )
        assert own["carrier_id"] == lakeshore["id"]
        assert_trip_state(own, trip_status="CAPTURED", odometer_delta_miles=400.0)

        _rows, meta = validate_paginated(
            client.list_trip_records(
                OFFICER_1_HEADERS, params={"carrier_id": prairie["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestReconstructionIsFencedByArithmeticAndByTheClock:
    def _flagged_trip(self, client):
        """A gap-flagged trip: 300.0 of its own miles and 100.0 unexplained."""
        carrier, vehicle = _carrier_with_one_unit(client)
        capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-04-05T06:00:00Z",
            trip_end_utc="2026-04-05T18:00:00Z",
            start_odometer=700.0,
            end_odometer=1000.0,
            legs=[leg("IL", 300.0)],
        )
        flagged = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-06-10T06:00:00Z",
            trip_end_utc="2026-06-10T18:00:00Z",
            start_odometer=1100.0,
            end_odometer=1400.0,
            legs=[leg("IL", 300.0)],
        )
        return carrier, vehicle, flagged

    def test_the_leg_sum_passes_at_exactly_half_a_mile_and_fails_at_six_tenths(
        self, client
    ):
        """"The sum of `leg_miles` across the submitted `reconstructed_legs` is
        compared against the trip's `odometer_delta_miles` plus its
        `gap_miles_from_previous` — the analyst is accounting for the trip's own
        distance *and* the unexplained distance that preceded it, which is the
        whole reason the trip was flagged. The absolute difference between those
        two figures may be at most half a mile: a deviation of exactly 0.5 miles
        is accepted and 0.6 miles is refused with `ERR_LEG_MILEAGE_MISMATCH`."

        The target here is 300.0 plus 100.0, so 400.0. Legs of 300.3 and 100.3
        sum to 400.6 and are refused; legs of 300.5 and 100.0 sum to 400.5, are
        accepted, and become the trip's whole mileage basis. "Note that this
        reconciliation tolerance is **inclusive**, in deliberate contrast to the
        strictly-greater-than comparison that decides gap flagging."

        Design: Corner/validations/reconstruction_leg_sums_pass_at_exactly_half_a_mile_and_fail_at_six_tenths
        """
        seed_reference_data_il_in_only(client)
        _carrier, _vehicle, flagged = self._flagged_trip(client)
        assert_trip_state(
            flagged,
            trip_status="GAP_FLAGGED",
            gap_miles_from_previous=100.0,
            odometer_delta_miles=300.0,
        )

        too_far = client.reconstruct_trip_record(
            flagged["id"],
            ANALYST_1_HEADERS,
            reconstructed_legs=[leg("IL", 300.3), leg("IN", 100.3)],
            supporting_document_reference="FUEL-LOG-88",
        )
        validate_error(too_far, ERR_LEG_MILEAGE_MISMATCH)
        assert_trip_state(
            read_trip(client, flagged["id"]),
            trip_status="GAP_FLAGGED",
            mileage_source="TELEMATICS",
            supporting_document_reference=None,
            reconstructed_by_user_id=None,
        )

        on_the_line = validate_success(
            client.reconstruct_trip_record(
                flagged["id"],
                ANALYST_1_HEADERS,
                reconstructed_legs=[leg("IL", 300.5), leg("IN", 100.0)],
                supporting_document_reference="FUEL-LOG-88",
            )
        )
        assert_trip_state(
            on_the_line,
            trip_status="RECONSTRUCTED",
            mileage_source="MANUAL_RECONSTRUCTION",
            accepted_leg_miles_total=400.5,
            supporting_document_reference="FUEL-LOG-88",
            reconstructed_by_user_id="analyst-1",
        )

        # The refused attempt left no legs behind, so the active set is the
        # accepted pair and nothing else.
        active, meta = validate_paginated(
            client.list_trip_mileage_legs(
                flagged["id"], OFFICER_1_HEADERS, params={"leg_status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 2
        assert codes_of(active) == ["IL", "IN"]
        assert [row["leg_sequence"] for row in active] == [1, 2]
        assert_miles(by_code(active, "IL")["leg_miles"], 300.5, "IL leg_miles")
        assert_miles(by_code(active, "IN")["leg_miles"], 100.0, "IN leg_miles")

    def test_retention_expiry_outranks_the_reconstruction_window(self, client):
        """"The outer gate is record retention: if more than 1460 days — four
        years of retained records — have elapsed since `trip_end_utc`, the source
        documents are no longer required to exist at all, so the trip cannot be
        reconstructed under any circumstance and the attempt is refused with
        `ERR_RETENTION_PERIOD_EXPIRED`."

        The nearer gate is the other one: "The inner gate is the reconstruction
        window itself: if more than 120 days have elapsed since `trip_end_utc`,
        the window has closed and the attempt is refused with
        `ERR_RECONSTRUCTION_WINDOW_CLOSED`; a trip exactly 120 days old is still
        reconstructible." At 2026-11-01 the trip is 143 days past its end
        instant, so only the inner gate is shut and it is the one that answers.
        At 2031-01-01 both gates are shut. "Because retention is checked first, a
        very old trip reports expiry rather than a closed window even though both
        conditions hold."

        Design: Corner/validations/retention_expiry_outranks_the_reconstruction_window
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        _carrier, _vehicle, flagged = self._flagged_trip(client)

        set_clock(client, "2026-11-01T00:00:00Z")
        window_closed = client.reconstruct_trip_record(
            flagged["id"],
            ANALYST_1_HEADERS,
            reconstructed_legs=[leg("IL", 400.0)],
            supporting_document_reference="FUEL-LOG-88",
        )
        validate_error(window_closed, ERR_RECONSTRUCTION_WINDOW_CLOSED)

        set_clock(client, "2031-01-01T00:00:00Z")
        retention_expired = client.reconstruct_trip_record(
            flagged["id"],
            ANALYST_1_HEADERS,
            reconstructed_legs=[leg("IL", 400.0)],
            supporting_document_reference="FUEL-LOG-88",
        )
        validate_error(retention_expired, ERR_RETENTION_PERIOD_EXPIRED)

        # Neither attempt touched the mileage basis; the trip still carries the
        # 300.0 telematics miles it was captured with.
        assert_trip_state(
            read_trip(client, flagged["id"]),
            trip_status="GAP_FLAGGED",
            mileage_source="TELEMATICS",
            accepted_leg_miles_total=300.0,
            supporting_document_reference=None,
            reconstructed_by_user_id=None,
        )
        assert len(trip_legs(client, flagged["id"], leg_status="ACTIVE")) == 1


class TestNaturalKeysAndUniqueLines:
    def test_a_second_return_for_the_same_quarter_is_rejected(self, client):
        """"A carrier may hold only one return per period: a second attempt at
        the same combination of `carrier_id`, `filing_year` and `filing_quarter`
        is refused with `ERR_DUPLICATE_RETURN_PERIOD`."

        The key is the triple, not any one part of it, so the same carrier may
        open a different quarter and a different carrier may open the same
        quarter. Both of those succeed here, which is what makes the refusal a
        statement about the composite key rather than about the carrier or the
        period alone.

        Design: Corner/validations/a_second_return_for_the_same_quarter_is_rejected
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        prairie = create_carrier(
            client,
            legal_name="Prairie Freight LLC",
            usdot_number="USDOT-2637001",
            base_jurisdiction_code="IL",
        )
        lakeshore = create_carrier(
            client,
            legal_name="Lakeshore Haulage Inc",
            usdot_number="USDOT-2637002",
            base_jurisdiction_code="IL",
        )
        first = open_return(client, prairie["id"], filing_year=2026, filing_quarter=2)

        collision = client.create_fuel_tax_return(
            fuel_tax_return_payload(prairie["id"], 2026, 2), PREPARER_1_HEADERS
        )
        validate_error(collision, ERR_DUPLICATE_RETURN_PERIOD)

        # The same carrier, a different quarter.
        third_quarter = validate_success(
            client.create_fuel_tax_return(
                fuel_tax_return_payload(prairie["id"], 2026, 3), PREPARER_1_HEADERS
            ),
            expected_status=201,
        )
        assert third_quarter["filing_quarter"] == 3
        # A different carrier, the same quarter.
        neighbour = validate_success(
            client.create_fuel_tax_return(
                fuel_tax_return_payload(lakeshore["id"], 2026, 2), PREPARER_1_HEADERS
            ),
            expected_status=201,
        )
        assert neighbour["carrier_id"] == lakeshore["id"]

        rows, meta = validate_paginated(
            client.list_fuel_tax_returns(
                OFFICER_1_HEADERS, params={"carrier_id": prairie["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["filing_quarter"] for row in rows) == [2, 3]
        assert first["id"] in {row["id"] for row in rows}

    def test_a_second_active_line_for_the_same_jurisdiction_is_rejected(self, client):
        """"An application may hold at most one `ACTIVE` line per jurisdiction,
        and a second `ACTIVE` line for the same `jurisdiction_code` is refused
        with `ERR_DUPLICATE_JURISDICTION_LINE` — note that a `VOIDED` line from
        an earlier correction round does not block a fresh one for the same
        jurisdiction."

        The refused figure differs from the line already on file, so a permissive
        implementation would silently overwrite the schedule rather than refuse
        it. Illinois keeps the mileage it was given, and Indiana -- a different
        jurisdiction under the same application -- is still accepted afterwards.

        Design: Corner/validations/a_second_active_line_for_the_same_jurisdiction_is_rejected
        """
        seed_reference_data_il_in_only(client)
        carrier, _vehicle = _carrier_with_one_unit(client)
        application = open_application(client, carrier["id"])
        add_schedule_lines(client, application["id"], [("IL", 60000.0)])

        collision = client.add_distance_schedule_line(
            application["id"],
            {"jurisdiction_code": "IL", "reported_distance_miles": 12345.0},
            PREPARER_1_HEADERS,
        )
        validate_error(collision, ERR_DUPLICATE_JURISDICTION_LINE)

        lines = schedule_lines(client, application["id"], line_status="ACTIVE")
        assert codes_of(lines) == ["IL"]
        assert_miles(
            by_code(lines, "IL")["reported_distance_miles"],
            60000.0,
            "IL reported_distance_miles",
        )

        indiana = validate_success(
            client.add_distance_schedule_line(
                application["id"],
                {"jurisdiction_code": "IN", "reported_distance_miles": 40000.0},
                PREPARER_1_HEADERS,
            ),
            expected_status=201,
        )
        assert indiana["jurisdiction_code"] == "IN"

        rows, meta = validate_paginated(
            client.list_distance_schedule_lines(
                application["id"], OFFICER_1_HEADERS, params={"line_status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 2
        assert codes_of(rows) == ["IL", "IN"]


class TestSupplementAndInvoiceGuards:
    def test_an_effective_date_outside_the_registration_year_is_caught_at_decide_time(
        self, client
    ):
        """"The `effective_date` must fall inside the application's
        `registration_year` — January 1 through December 31 of that year, both
        inclusive — and a date outside it is refused with
        `ERR_EFFECTIVE_DATE_OUT_OF_YEAR`."

        The date is checked when the officer approves, not when the carrier
        files: "A newly filed supplement opens with `change_status` `REQUESTED`,
        `fee_delta` at 0.00, `prorate_months` at 0, `decided_by_user_id` and
        `reversal_reason_code` null, and `requested_by_user_id` stamped from the
        caller's `X-User-ID` — which, for a `CarrierAdmin`, is the requesting
        carrier's own `id`." So a February 2027 supplement against the 2026 book
        is accepted onto the desk and refused at the decision, leaving the
        request pending rather than rejected, and leaving the unit unpriced.

        Design: Corner/validations/an_effective_date_outside_the_registration_year_is_caught_at_decide_time
        """
        seed_reference_data_il_in_only(client)
        carrier, _unit = _carrier_with_one_unit(client)
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

        # A unit enrolled after invoicing is still PENDING, so the addition
        # clears the vehicle-state gate and the date gate is the one left.
        late_unit = create_vehicle(
            client,
            carrier["id"],
            unit_number="U-102",
            vin="1FUJA6CK21L101102",
            factory_price_amount=152000.00,
            registration_year=2026,
        )
        change = request_fleet_change(
            client,
            application["id"],
            late_unit["id"],
            "ADDITION",
            "2027-02-01",
        )
        assert_change_request(
            change,
            change_status="REQUESTED",
            prorate_months=0,
            fee_delta=0.00,
            decided_by_user_id=None,
        )

        decision = client.decide_fleet_change_request(
            change["id"], OFFICER_2_HEADERS, decision="APPROVE"
        )
        validate_error(decision, ERR_EFFECTIVE_DATE_OUT_OF_YEAR)

        # The refused approval is not a rejection: the request is still open.
        assert_change_request(
            read_fleet_change(client, change["id"]),
            change_status="REQUESTED",
            prorate_months=0,
            fee_delta=0.00,
            decided_by_user_id=None,
        )
        assert read_vehicle(client, late_unit["id"])["vehicle_status"] == "PENDING"
        assert_application_totals(
            read_application(client, application["id"]),
            application_status="INVOICED",
            apportioned_vehicle_count=1,
            total_apportioned_fee=2350.80,
        )

    def test_a_scheduled_jurisdiction_with_no_weight_group_fee_row_is_rejected_at_invoice(
        self, client
    ):
        """"Invoicing additionally requires the fee chart to be complete: for
        every `ACTIVE` line's `jurisdiction_code`, a `WeightGroupFee` cell must
        exist paired with the application's `weight_group_code`. A missing cell
        is refused with `ERR_WEIGHT_GROUP_FEE_MISSING` — the jurisdiction cannot
        be billed for a weight group it has not published a price for."

        Indiana is a properly declared jurisdiction here, so the schedule line
        was accepted; only its price cell is missing. The refusal therefore
        cannot happen until invoicing, and when it does the whole invoicing step
        is abandoned: nothing is frozen, no percentage is written onto the
        Illinois line whose price *is* published, and the pending unit is not
        activated.

        Design: Corner/validations/a_scheduled_jurisdiction_with_no_weight_group_fee_row_is_rejected_at_invoice
        """
        seed_reference_data(
            client,
            jurisdictions=[JURISDICTION_IL, JURISDICTION_IN],
            fees=[
                row
                for row in WEIGHT_GROUP_FEES_W80
                if row["jurisdiction_code"] == "IL"
            ],
        )
        carrier, vehicle = _carrier_with_one_unit(client)
        application = open_application(client, carrier["id"])
        add_schedule_lines(
            client, application["id"], [("IL", 60000.0), ("IN", 40000.0)]
        )
        submit_application(client, application["id"])

        response = client.review_registration_application(
            application["id"], OFFICER_1_HEADERS, decision="INVOICE"
        )
        validate_error(response, ERR_WEIGHT_GROUP_FEE_MISSING)

        after = read_application(client, application["id"])
        assert_application_totals(
            after,
            application_status="SUBMITTED",
            apportioned_vehicle_count=1,
            fleet_total_distance_miles=0.0,
            base_fee_total=0.00,
            total_apportioned_fee=0.00,
        )
        assert after["apportion_frozen_at"] is None

        lines = schedule_lines(client, application["id"], line_status="ACTIVE")
        assert codes_of(lines) == ["IL", "IN"]
        illinois = by_code(lines, "IL")
        assert_apportion_percent(illinois["apportion_percent"], 0.000000)
        assert_miles(illinois["effective_distance_miles"], 0.0, "IL effective miles")
        assert_money(illinois["jurisdiction_fee_amount"], 0.00, "IL fee")

        assert read_vehicle(client, vehicle["id"])["vehicle_status"] == "PENDING"


class TestPreparationRefusesAnUnsettleableQuarter:
    def test_the_gallons_check_answers_before_the_mileage_check(self, client):
        """"Finally the quarter must have substance in both bases: if the
        quarter's accepted tax-paid gallons total is not strictly greater than
        0.000, fleet MPG would be undefined and the attempt is refused with
        `ERR_NO_TAX_PAID_GALLONS`; and if the quarter's total effective mileage
        is not strictly greater than 0.0, the attempt is refused with
        `ERR_NO_ACCEPTED_MILEAGE`."

        An empty quarter breaks both conditions at once, so the answer is
        decided by the tie-break the specification states outright: "The gallons
        check is evaluated before the mileage check." The refused attempt also
        leaves the carrier's `version` where it was, so the token the preparer
        supplied is not consumed by a failure.

        Design: Corner/validations/prepare_with_no_tax_paid_gallons_reports_the_gallons_error_before_the_mileage_error
        """
        seed_reference_data(client, jurisdictions=[JURISDICTION_IL])
        carrier, _vehicle = _carrier_with_one_unit(client)
        quarter = open_return(client, carrier["id"], filing_year=2026, filing_quarter=2)
        version_before = carrier_version(client, carrier["id"])

        response = client.prepare_fuel_tax_return(
            quarter["id"],
            PREPARER_1_HEADERS,
            expected_carrier_version=version_before,
        )
        validate_error(response, ERR_NO_TAX_PAID_GALLONS)

        after = read_return(client, quarter["id"])
        assert_return_settlement(
            after,
            return_status="DRAFT",
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=0.0,
            total_tax_paid_gallons=0.000,
            fleet_mpg=None,
            total_net_tax_due=0.00,
            total_amount_due=0.00,
        )
        assert after["prepared_by_user_id"] is None
        assert return_lines(client, quarter["id"]) == []
        assert carrier_version(client, carrier["id"]) == version_before

    def test_prepare_is_blocked_while_a_captured_trip_still_awaits_review(self, client):
        """"No trip of the carrier whose `trip_start_utc` falls inside the
        quarter window may still be sitting in `CAPTURED` or `RECONSTRUCTED` —
        either is review work still in flight, and its presence is refused with
        `ERR_TRIP_GAP_UNRESOLVED`."

        The quarter is otherwise perfectly settleable: one accepted trip, one
        accepted purchase, an active licence and a fresh version token. The only
        obstacle is a second trip nobody has looked at yet, and the analyst
        clearing it -- not the preparer retrying harder -- is what unblocks the
        quarter. Once accepted, its miles join the settlement rather than being
        quietly dropped.

        Design: Corner/validations/prepare_is_blocked_while_a_captured_trip_still_awaits_review
        """
        seed_reference_data_il_in_only(client)
        carrier, vehicle = _carrier_with_one_unit(client)
        first = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-04-05T06:00:00Z",
            trip_end_utc="2026-04-05T18:00:00Z",
            start_odometer=1000.0,
            end_odometer=1400.0,
            legs=[leg("IL", 300.0), leg("IN", 100.0)],
        )
        accept_trip(client, first["id"])
        pending_review = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-05-10T06:00:00Z",
            trip_end_utc="2026-05-10T12:00:00Z",
            start_odometer=1400.0,
            end_odometer=1500.0,
            legs=[leg("IL", 100.0)],
        )
        assert_trip_state(pending_review, trip_status="CAPTURED")
        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            jurisdiction_code="IL",
            purchase_date="2026-05-02",
            gallons=40.000,
        )
        quarter = open_return(client, carrier["id"], filing_year=2026, filing_quarter=2)

        blocked = client.prepare_fuel_tax_return(
            quarter["id"],
            PREPARER_1_HEADERS,
            expected_carrier_version=carrier_version(client, carrier["id"]),
        )
        validate_error(blocked, ERR_TRIP_GAP_UNRESOLVED)
        assert_return_settlement(
            read_return(client, quarter["id"]),
            return_status="DRAFT",
            total_fleet_miles=0.0,
            fleet_mpg=None,
        )

        accept_trip(client, pending_review["id"])
        prepared = prepare_return(client, quarter["id"], carrier["id"])
        assert_return_settlement(
            prepared,
            return_status="PREPARED",
            total_fleet_miles=500.0,
            total_tax_paid_gallons=40.000,
            fleet_mpg=12.50,
            total_net_tax_due=2.02,
            reconstruction_penalty_amount=0.00,
            total_amount_due=2.02,
        )
        lines = return_lines(client, quarter["id"], line_status="ACTIVE")
        assert codes_of(lines) == ["IL", "IN"]
        assert_jurisdiction_line(
            by_code(lines, "IL"),
            taxable_miles=400.0,
            taxable_gallons=32.000,
            tax_paid_gallons=40.000,
            net_taxable_gallons=-8.000,
            base_tax_amount=-5.02,
            surcharge_amount=0.00,
            net_tax_amount=-5.02,
        )
        assert_jurisdiction_line(
            by_code(lines, "IN"),
            taxable_miles=100.0,
            taxable_gallons=8.000,
            tax_paid_gallons=0.000,
            net_taxable_gallons=8.000,
            base_tax_amount=2.64,
            surcharge_amount=4.40,
            net_tax_amount=7.04,
        )


class TestFilingFreezesTheQuartersEvidence:
    def test_disallowing_a_purchase_locked_by_a_filed_return_is_rejected(self, client):
        """"Filing also locks the quarter's evidence: the accepted trips and
        accepted purchases the return settled become frozen, and any later
        attempt to disallow a purchase whose `purchase_date` falls inside the
        filed quarter's window is refused with
        `ERR_PURCHASE_LOCKED_BY_FILED_RETURN`."

        Disallowance is otherwise wide open from this status -- "Disallowance is
        reachable from `ACCEPTED` and from `RECORDED` alike and lands on the
        terminal `DISALLOWED`" -- so the refusal is the filed quarter's doing and
        not the purchase's own state. Nothing is written on the way out: the
        gallons stay in the carrier's year-to-date credit and the reason code the
        analyst offered is not recorded anywhere.

        Design: Corner/validations/disallowing_a_purchase_locked_by_a_filed_return_is_rejected
        """
        seed_reference_data_il_in_only(client)
        carrier, vehicle = _carrier_with_one_unit(client)
        trip = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-04-05T06:00:00Z",
            trip_end_utc="2026-04-05T18:00:00Z",
            start_odometer=1000.0,
            end_odometer=1400.0,
            legs=[leg("IL", 300.0), leg("IN", 100.0)],
        )
        accept_trip(client, trip["id"])
        purchase = record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            jurisdiction_code="IL",
            purchase_date="2026-05-02",
            gallons=40.000,
        )
        assert purchase["purchase_status"] == "ACCEPTED"

        quarter = open_return(client, carrier["id"], filing_year=2026, filing_quarter=2)
        prepare_return(client, quarter["id"], carrier["id"])
        filed = file_return(client, quarter["id"])
        assert_return_settlement(
            filed,
            return_status="FILED",
            total_fleet_miles=400.0,
            total_tax_paid_gallons=40.000,
            fleet_mpg=10.00,
            total_net_tax_due=2.53,
            total_amount_due=2.53,
        )

        response = client.disallow_fuel_purchase(
            purchase["id"], ANALYST_1_HEADERS, disallow_reason_code="MISSING_RECEIPT"
        )
        validate_error(response, ERR_PURCHASE_LOCKED_BY_FILED_RETURN)

        after = read_purchase(client, purchase["id"])
        assert after["purchase_status"] == "ACCEPTED"
        assert after["disallow_reason_code"] is None
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]), tax_paid_gallons_ytd=40.000
        )


class TestTheHandoverChecksTheReceivingDriver:
    def test_distributing_a_credential_to_an_unknown_or_foreign_driver_is_rejected(
        self, client
    ):
        """"The receiving driver must belong to the same carrier as the
        credential's vehicle and must have `driver_status` `ACTIVE`; a driver of
        another carrier, or an `INACTIVE` driver, is refused with
        `ERR_DRIVER_CARRIER_MISMATCH`."

        A driver id that names nobody at all is a different failure and is caught
        earlier, by the referenced-existence rule: "Existence of every foreign
        key supplied in the request body, evaluated in this body-field order:
        `carrier_id`, `vehicle_id`, `replaced_vehicle_id`,
        `registration_application_id`, `distributed_to_driver_id` — answering
        with `ERR_CARRIER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`,
        `ERR_REGISTRATION_APPLICATION_NOT_FOUND` or `ERR_DRIVER_NOT_FOUND` as
        appropriate, all HTTP 404." Neither refusal hands the paper over, so the
        credential stays `ISSUED` with an empty handover trail and its unit's
        derived `credential_status` is unmoved.

        Design: Corner/validations/distributing_a_credential_to_an_unknown_or_foreign_driver_is_rejected
        """
        seed_reference_data_il_in_only(client)
        prairie, prairie_unit = _carrier_with_one_unit(client)
        application = invoiced_application(
            client, prairie["id"], [("IL", 60000.0), ("IN", 40000.0)]
        )
        issue_credentials(client, application["id"])
        cab_card = credentials_for_vehicle(client, prairie_unit["id"])["CAB_CARD"]
        assert_credential_state(
            cab_card,
            credential_status="ISSUED",
            distributed_to_driver_id=None,
            distributed_at=None,
        )

        lakeshore = create_carrier(
            client,
            legal_name="Lakeshore Haulage Inc",
            usdot_number="USDOT-2637002",
            base_jurisdiction_code="IL",
        )
        foreign_driver = create_driver(
            client, lakeshore["id"], full_name="Dana Reyes", cdl_number="IL-D-88231"
        )

        unknown = client.distribute_credential(
            cab_card["id"],
            OFFICER_1_HEADERS,
            distributed_to_driver_id=NON_EXISTENT_UUID,
        )
        validate_error(unknown, ERR_DRIVER_NOT_FOUND)

        mismatched = client.distribute_credential(
            cab_card["id"],
            OFFICER_1_HEADERS,
            distributed_to_driver_id=foreign_driver["id"],
        )
        validate_error(mismatched, ERR_DRIVER_CARRIER_MISMATCH)

        assert_credential_state(
            read_credential(client, cab_card["id"]),
            credential_status="ISSUED",
            credential_type="CAB_CARD",
            distributed_to_driver_id=None,
            distributed_at=None,
            voided_reason_code=None,
        )
        assert read_vehicle(client, prairie_unit["id"])["credential_status"] == "ISSUED"


class TestTheTwoLicenceDimensionsAreEnforcedByDifferentGuards:
    def test_irp_suspension_from_a_revocation_blocks_the_next_application_submit(
        self, client
    ):
        """"An `ACTIVE` licence with `retention_deficiency_ratio` exactly 1.0000
        — no record of the period survived retention at all — skips suspension
        and moves `ACTIVE → REVOKED`, which is terminal. `suspension_count`
        increments by 1 and the carrier's `version` increments by 1. The
        `IFTA_LICENSE_COPY` credentials are `VOIDED` with `LICENSE_SUSPENSION`
        exactly as above, and then revocation couples the second dimension:
        `irp_account_status` moves `ACTIVE → SUSPENDED`."

        The two dimensions are then read by two different guards: "application
        submission and fleet-change approval are refused with
        `ERR_CARRIER_IRP_INACTIVE` once `irp_account_status` is `SUSPENDED`.
        Reads are never blocked by licence standing." So next year's registration
        book cannot be submitted, while the audited quarter is still perfectly
        legible. Enrolling the 2027 unit before the application is opened is what
        gets the submission past the substantive `DRAFT` conditions so that the
        licence guard is the one left to answer.

        Design: Corner/validations/irp_suspension_from_a_revocation_blocks_the_next_application_submit
        """
        seed_reference_data_il_in_only(client)
        carrier, vehicle = _carrier_with_one_unit(client)
        clean = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-04-05T06:00:00Z",
            trip_end_utc="2026-04-05T20:00:00Z",
            start_odometer=1000.0,
            end_odometer=2000.0,
            legs=[leg("IL", 200.0), leg("IN", 800.0)],
        )
        accept_trip(client, clean["id"])
        gapped = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-05-10T06:00:00Z",
            trip_end_utc="2026-05-10T18:00:00Z",
            start_odometer=2100.0,
            end_odometer=2500.0,
            legs=[leg("IL", 400.0)],
        )
        assert_trip_state(gapped, trip_status="GAP_FLAGGED", gap_miles_from_previous=100.0)
        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            jurisdiction_code="IL",
            purchase_date="2026-05-02",
            gallons=100.000,
        )
        quarter = open_return(client, carrier["id"], filing_year=2026, filing_quarter=2)
        prepare_return(client, quarter["id"], carrier["id"])
        file_return(client, quarter["id"])

        selection = score_audit_selection(
            client,
            carrier["id"],
            selection_year=2026,
            selection_quarter=2,
            late_filing_count=3,
            retention_deficiency_count=4,
        )
        assert_audit_selection(selection, risk_score=100, selection_status="SELECTED")
        reviewed = retention_review(
            client, selection["id"], expected_records_count=20, records_missing_count=20
        )
        assert_audit_selection(
            reviewed,
            risk_score=100,
            selection_status="RETENTION_REVIEWED",
            retention_deficiency_ratio=1.0000,
            post_review_risk_score=100,
        )
        assert_carrier_compliance(
            read_carrier(client, carrier["id"]),
            ifta_license_status="REVOKED",
            irp_account_status="SUSPENDED",
            suspension_count=1,
        )

        next_year_unit = create_vehicle(
            client,
            carrier["id"],
            unit_number="U-201",
            vin="1FUJA6CK21L102201",
            factory_price_amount=151000.00,
            registration_year=2027,
        )
        next_book = open_application(
            client,
            carrier["id"],
            registration_year=2027,
            distance_basis="ESTIMATED_DISTANCE_BASIS",
        )
        assert_application_totals(
            next_book, application_status="DRAFT", apportioned_vehicle_count=1
        )
        add_schedule_lines(client, next_book["id"], [("IL", 50000.0)])

        response = client.submit_registration_application(
            next_book["id"], PREPARER_1_HEADERS
        )
        validate_error(response, ERR_CARRIER_IRP_INACTIVE)
        assert_application_totals(
            read_application(client, next_book["id"]), application_status="DRAFT"
        )
        assert read_vehicle(client, next_year_unit["id"])["vehicle_status"] == "PENDING"

        # The fuel-tax side is untouched by the registration guard, and the
        # audited quarter reads back exactly as the cascade left it.
        assert_return_settlement(
            read_return(client, quarter["id"]),
            return_status="AUDIT_ADJUSTED",
            settlement_basis="AUDIT_BASIS",
            total_fleet_miles=1000.0,
            total_tax_paid_gallons=100.000,
            fleet_mpg=10.00,
            total_net_tax_due=20.24,
            total_amount_due=20.24,
            audit_assessment_delta=0.00,
        )
