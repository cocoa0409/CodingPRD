"""Entity-record compliance: creation echoes, read-backs, defaults, computed and system
fields, enum and ordering constraints, and foreign-key existence on the wet lease API."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_aircraft,
    assert_deposit_conservation,
    assert_flight_leg,
    assert_lease_agreement,
    assert_regulatory_approval,
    create_aircraft,
    create_aircraft_payload,
    create_captain_payload,
    create_lease_payload,
    create_lessee,
    create_flight_leg_payload,
    is_iso8601_timestamp,
    schedule_leg,
    set_clock,
    setup_active_lease,
    setup_draft_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_admin_headers"]

CLOCK = "2026-09-01T00:00:00Z"


class TestLeaseAgreementRecord:
    def test_lease_creation_echoes_contract_fields_with_draft_status_and_seeded_deposit(
        self, api
    ):
        """PRD §4: Operations that bring a new resource into existence — registering a lessee, an airframe or a crew member, drafting a lease, filing a docket, attaching a certificate, enrolling a qualification, scheduling a leg, requesting a substitution, preparing an invoice, filing a reliability report, or serving termination (which creates the return-conditions record) — return `201 Created`.
        PRD §3.2: Commercially the lease carries `block_hour_rate_usd_cents`, the all-in ACMI rate per block hour in cents (at least 1); `min_guaranteed_block_hours_per_month`, a strictly positive number of hours carried to four decimal places representing the guarantee before proration; and `shortfall_credit_pct`, a fraction between 0 and 1 inclusive, carried to four decimal places, giving the share of lessor-attributable shortfall value credited back to the lessee.
        PRD §3.2: `substitution_rights` is `LESSOR_UNILATERAL` or `LESSEE_CONSENT_REQUIRED`, deciding whether the lessor may swap airframes on its own authority.
        PRD §3.2: `reliability_basis` is `DEPARTURE` or `SCHEDULED`, deciding which reliability variant binds.
        PRD §3.2: A freshly drafted lease has `status` `DRAFT`, `suspension_reason` null, `lifetime_credited_block_minutes` 0, `return_deposit_applied_cents` 0 and `return_deposit_remaining_cents` equal to `return_deposit_cents`.
        PRD §2.9: On every lease, `return_deposit_applied_cents` plus `return_deposit_remaining_cents` equals `return_deposit_cents` at all times.
        PRD §2.4: `version` (integer): an integer that starts at 1 and increments by 1 on every mutation of the resource.
        PRD §3.5: On a first activation the airframe must be `AVAILABLE` with `assigned_lease_id` null.

        Design: Corner/entities/lease_creation_returns_declared_fields_with_draft_status_and_zeroed_ledgers
        """
        set_clock(api, CLOCK)
        lessee = create_lessee(api)
        aircraft = create_aircraft(api)

        payload = create_lease_payload(lessee["id"], aircraft["id"])
        lease = validate_success(api.create_lease(payload, OPS), 201)

        assert_lease_agreement(lease)
        assert lease["status"] == "DRAFT", "a freshly drafted lease must have status DRAFT"
        assert lease["suspension_reason"] is None, (
            "suspension_reason must be null on a freshly drafted lease"
        )
        assert lease["lessee_id"] == lessee["id"], "lessee_id must be echoed back verbatim"
        assert lease["primary_aircraft_id"] == aircraft["id"], (
            "primary_aircraft_id must be echoed back verbatim"
        )
        assert lease["term_start_date"] == "2026-09-01"
        assert lease["term_end_date"] == "2026-12-31"
        assert lease["block_hour_rate_usd_cents"] == 480000, (
            "block_hour_rate_usd_cents is an integer count of cents echoed verbatim"
        )
        assert float(lease["min_guaranteed_block_hours_per_month"]) == pytest.approx(
            5, abs=0.0001
        ), "min_guaranteed_block_hours_per_month must be echoed as 5 hours"
        assert float(lease["shortfall_credit_pct"]) == pytest.approx(0.60, abs=0.0001), (
            "shortfall_credit_pct must be echoed as the supplied 0.60 fraction"
        )
        assert lease["crew_provided_by"] == "LESSOR"
        assert lease["maintenance_provided_by"] == "LESSOR"
        assert lease["insurance_provided_by"] == "LESSOR"
        assert lease["operational_control"] == "LESSOR"
        assert lease["substitution_rights"] == "LESSOR_UNILATERAL"
        assert lease["reliability_basis"] == "DEPARTURE"
        assert lease["required_maintenance_program_ref"] == "MP-B738-REV12"
        assert float(lease["return_hours_since_check_max"]) == pytest.approx(
            300.00, abs=0.001
        )
        assert lease["return_cycles_since_check_max"] == 120
        assert float(lease["return_fuel_kg_required"]) == pytest.approx(4000, abs=0.001)
        assert lease["return_liability_cap_cents"] == 900000
        assert lease["return_deposit_cents"] == 500000
        assert lease["redelivery_icao"] == "EGSS"

        assert lease["lifetime_credited_block_minutes"] == 0, (
            "lifetime_credited_block_minutes must be 0 on a freshly drafted lease"
        )
        assert lease["return_deposit_applied_cents"] == 0, (
            "return_deposit_applied_cents must be 0 on a freshly drafted lease"
        )
        assert lease["return_deposit_remaining_cents"] == 500000, (
            "return_deposit_remaining_cents must equal return_deposit_cents on a "
            "freshly drafted lease"
        )
        assert_deposit_conservation(lease)
        assert lease["version"] == 1, "a newly created resource carries version 1"

        airframe = validate_success(api.get_aircraft(aircraft["id"], TECH))
        assert airframe["status"] == "AVAILABLE", (
            "drafting a lease must leave the named airframe AVAILABLE for its first "
            "activation"
        )
        assert airframe["assigned_lease_id"] is None, (
            "drafting a lease must leave assigned_lease_id null on the named airframe"
        )

    def test_lease_creation_ignores_client_supplied_status_and_version(self, api):
        """PRD §3.2: A freshly drafted lease has `status` `DRAFT`, `suspension_reason` null, `lifetime_credited_block_minutes` 0, `return_deposit_applied_cents` 0 and `return_deposit_remaining_cents` equal to `return_deposit_cents`.
        PRD §3.2: Its `status` will travel through `DRAFT`, `PENDING_REGULATORY_APPROVAL`, `APPROVED`, `ACTIVE`, `SUSPENDED` and `TERMINATING` before settling in one of the two terminal states, `RETURNED` or `WITHDRAWN`.
        PRD §3.5: `suspension_reason` is null in every state other than `SUSPENDED`.
        PRD §2.4: `version` (integer): an integer that starts at 1 and increments by 1 on every mutation of the resource.
        PRD §2.4: `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, written once when the row is created.
        PRD §3.5: On a first activation the airframe must be `AVAILABLE` with `assigned_lease_id` null.
        PRD §3.8: The first window is opened by lease activation; each close opens the next.

        Design: Corner/entities/lease_system_fields_generated_and_client_status_input_ignored
        """
        set_clock(api, CLOCK)
        lessee = create_lessee(api)
        aircraft = create_aircraft(api)

        payload = create_lease_payload(
            lessee["id"],
            aircraft["id"],
            status="ACTIVE",
            suspension_reason="AIRFRAME_AOG",
            version=99,
        )
        lease = validate_success(api.create_lease(payload, OPS), 201)

        assert lease["status"] == "DRAFT", (
            "status is server-managed: a client-supplied ACTIVE must not shortcut the "
            "DRAFT -> PENDING_REGULATORY_APPROVAL -> APPROVED -> ACTIVE ladder"
        )
        assert lease["suspension_reason"] is None, (
            "suspension_reason must be null in every state other than SUSPENDED"
        )
        assert lease["version"] == 1, (
            "version is server-minted and starts at 1, whatever the client sends"
        )
        assert is_iso8601_timestamp(lease["created_at"]), (
            "created_at must be a server-minted ISO 8601 UTC timestamp"
        )
        assert is_iso8601_timestamp(lease["updated_at"]), (
            "updated_at must be a server-minted ISO 8601 UTC timestamp"
        )

        airframe = validate_success(api.get_aircraft(aircraft["id"], TECH))
        assert airframe["status"] == "AVAILABLE", (
            "no airframe is assigned before the lease is activated"
        )
        assert airframe["assigned_lease_id"] is None, (
            "assigned_lease_id must stay null until activation writes it"
        )

        periods, meta = validate_paginated(
            api.list_utilization_periods(BILLING, params={"lease_id": lease["id"]})
        )
        assert meta["total_count"] == 0, (
            "the first utilization period is opened by activation, not by drafting"
        )
        assert periods == []

    def test_lease_creation_with_term_end_before_term_start_is_rejected(self, api):
        """PRD §3.2: A `LessorOpsController` drafts the lease by naming the counterparty and the airframe — `lessee_id` and `primary_aircraft_id` — and the calendar term as `term_start_date` and `term_end_date`, both `YYYY-MM-DD` UTC dates, both inclusive, with the end date not earlier than the start date.
        PRD §2.8: **Request shape** — every required field present, every enum value a declared member, every number within its sign and range constraints, every ISO 8601 datetime and every `YYYY-MM-DD` date parseable, and a leg's `scheduled_in` strictly after its `scheduled_out`; otherwise `ERR_INVALID_REQUEST`.

        Design: Corner/entities/lease_term_end_before_term_start_returns_invalid_request
        """
        set_clock(api, CLOCK)
        lessee = create_lessee(api)
        aircraft = create_aircraft(api)

        payload = create_lease_payload(
            lessee["id"],
            aircraft["id"],
            term_start_date="2026-12-31",
            term_end_date="2026-09-01",
        )
        validate_error(api.create_lease(payload, OPS), ApiErrorId.ERR_INVALID_REQUEST)

        leases, meta = validate_paginated(
            api.list_leases(OPS, params={"lessee_id": lessee["id"]})
        )
        assert meta["total_count"] == 0, (
            "an inverted term must be refused before any lease row is written"
        )
        assert leases == []

    def test_lease_retrieval_with_unknown_id_returns_lease_not_found(self, api):
        """PRD §2.8: **Existence**, resolved in this order and, where a single request carries several identifiers of one kind, left to right in the order the fields are declared in the request: a lessee identifier (`lesseeId` in the path or `lessee_id` in the body) resolving to a `Lessee`, else `ERR_LESSEE_NOT_FOUND`; then every aircraft identifier (`aircraftId`, `primary_aircraft_id`, `original_aircraft_id`, `substitute_aircraft_id`, `aircraft_id`) resolving to an `Aircraft`, else `ERR_AIRCRAFT_NOT_FOUND`; then `leaseId` or `lease_id` resolving to a `LeaseAgreement`, else `ERR_LEASE_NOT_FOUND`; then `crewMemberId`, `crew_member_id`, `captain_id` and `first_officer_id` resolving to `CrewMember` rows, else `ERR_CREW_MEMBER_NOT_FOUND`; then `qualificationId`, else `ERR_QUALIFICATION_NOT_FOUND`; then `approvalId`, else `ERR_APPROVAL_NOT_FOUND`; then `certificateId`, else `ERR_CERTIFICATE_NOT_FOUND`; then `legId` in the path and `repositioning_leg_id` in the body, else `ERR_FLIGHT_LEG_NOT_FOUND`; then `substitutionId`, else `ERR_SUBSTITUTION_NOT_FOUND`; then `periodId` in the path and `period_id` in the body, else `ERR_PERIOD_NOT_FOUND`; then `invoiceId`, else `ERR_INVOICE_NOT_FOUND`; then `reportId`, else `ERR_REPORT_NOT_FOUND`; then `returnId`, else `ERR_RETURN_CONDITION_NOT_FOUND`.
        PRD §2.2: The `error_id` is a unique, machine-readable string that identifies the specific error.
        PRD §2.2: The `message` provides a human-readable explanation of what went wrong.

        Design: Corner/entities/lease_retrieval_with_unknown_id_returns_lease_not_found
        """
        set_clock(api, CLOCK)

        response = api.get_lease("00000000-0000-4000-8000-000000000000", OPS)
        error = validate_error(response, ApiErrorId.ERR_LEASE_NOT_FOUND, 404)
        assert error["error_id"] == "ERR_LEASE_NOT_FOUND", (
            "an unknown lease id must come back as ERR_LEASE_NOT_FOUND in the error "
            "envelope, not as 200 with a null body"
        )
        assert isinstance(error["message"], str) and error["message"], (
            "the error envelope must carry a human-readable message"
        )


class TestAircraftRecord:
    def test_aircraft_retrieval_returns_stored_airframe_record(self, api):
        """PRD §4: Every operation that modifies an existing resource, and every read, returns `200 OK`.
        PRD §3.1: Airframes are registered by technical control with a `tail_number` (the registration mark, five to seven characters, unique across the fleet — a repeat is rejected with `ERR_DUPLICATE_TAIL_NUMBER`), a `type_designator` naming the exact ICAO variant, a `type_family` naming the commercial family that variant belongs to, a certified `seat_count` of at least 1, an `mtow_kg` maximum take-off weight of at least 1, the `maintenance_program_ref` identifying the continuous-airworthiness programme the airframe is enrolled in, and three opening counters: `airframe_hours_total`, `hours_since_last_check` and `cycles_since_last_check`.
        PRD §3.1: A new airframe starts with `status` `AVAILABLE` and `assigned_lease_id` null; that field is non-null exactly while the airframe is the airframe of record for a lease.
        PRD §2.5: Airframe hour counters are held to two decimal places, and the substitution eligibility comparison on hours since last heavy check is likewise made at two decimal places.
        PRD §2.4: `version` (integer): an integer that starts at 1 and increments by 1 on every mutation of the resource.

        Design: Corner/entities/aircraft_retrieval_returns_stored_airframe_record
        """
        set_clock(api, CLOCK, TECH)
        created = create_aircraft(api)

        airframe = validate_success(api.get_aircraft(created["id"], OPS), 200)

        assert_aircraft(airframe)
        assert airframe["id"] == created["id"], "the read must return the same row"
        assert airframe["tail_number"] == "G-ACMI"
        assert airframe["type_designator"] == "B738", (
            "type_designator names the exact ICAO variant and is stored verbatim"
        )
        assert airframe["type_family"] == "B737", (
            "type_family names the commercial family and is stored verbatim"
        )
        assert airframe["seat_count"] == 189
        assert airframe["mtow_kg"] == 79000
        assert airframe["maintenance_program_ref"] == "MP-B738-REV12"
        assert float(airframe["airframe_hours_total"]) == pytest.approx(
            24000.00, abs=0.001
        ), "airframe_hours_total must be returned unchanged at two decimal places"
        assert float(airframe["hours_since_last_check"]) == pytest.approx(
            120.00, abs=0.001
        ), "hours_since_last_check must be returned unchanged at two decimal places"
        assert airframe["cycles_since_last_check"] == 40
        assert airframe["status"] == "AVAILABLE", "a new airframe starts AVAILABLE"
        assert airframe["assigned_lease_id"] is None, (
            "assigned_lease_id is null until the airframe becomes a lease's airframe of "
            "record"
        )
        assert airframe["version"] == 1, "an unmutated airframe carries version 1"

    def test_aircraft_creation_without_mtow_kg_is_rejected_and_persists_nothing(self, api):
        """PRD §3.1: Airframes are registered by technical control with a `tail_number` (the registration mark, five to seven characters, unique across the fleet — a repeat is rejected with `ERR_DUPLICATE_TAIL_NUMBER`), a `type_designator` naming the exact ICAO variant, a `type_family` naming the commercial family that variant belongs to, a certified `seat_count` of at least 1, an `mtow_kg` maximum take-off weight of at least 1, the `maintenance_program_ref` identifying the continuous-airworthiness programme the airframe is enrolled in, and three opening counters: `airframe_hours_total`, `hours_since_last_check` and `cycles_since_last_check`.
        PRD §2.8: **Request shape** — every required field present, every enum value a declared member, every number within its sign and range constraints, every ISO 8601 datetime and every `YYYY-MM-DD` date parseable, and a leg's `scheduled_in` strictly after its `scheduled_out`; otherwise `ERR_INVALID_REQUEST`.

        Design: Corner/entities/aircraft_creation_missing_required_mtow_kg_returns_invalid_request
        """
        set_clock(api, CLOCK, TECH)

        payload = create_aircraft_payload(
            tail_number="G-ZZZZ",
            airframe_hours_total=100.00,
            hours_since_last_check=10.00,
            cycles_since_last_check=3,
        )
        payload.pop("mtow_kg")

        validate_error(
            api.create_aircraft(payload, TECH), ApiErrorId.ERR_INVALID_REQUEST, 400
        )

        fleet, meta = validate_paginated(api.list_aircraft(TECH))
        assert meta["total_count"] == 0, (
            "an airframe registered without mtow_kg must not be persisted"
        )
        assert fleet == []


class TestCrewMemberRecord:
    def test_crew_member_creation_with_undeclared_crew_role_is_rejected(self, api):
        """PRD §3.1: Crew members are registered by operations control with a `full_name` as printed on the general declaration, an `employee_no` payroll number unique across the crew register, a `crew_role` of `CAPTAIN`, `FIRST_OFFICER` or `CABIN`, and a non-empty `type_ratings` array of the ICAO type designators the crew member currently holds a rating on.
        PRD §2.8: **Request shape** — every required field present, every enum value a declared member, every number within its sign and range constraints, every ISO 8601 datetime and every `YYYY-MM-DD` date parseable, and a leg's `scheduled_in` strictly after its `scheduled_out`; otherwise `ERR_INVALID_REQUEST`.

        Design: Corner/entities/crew_member_creation_with_undeclared_crew_role_returns_invalid_request
        """
        set_clock(api, CLOCK)

        payload = create_captain_payload(
            full_name="C Vance",
            employee_no="EMP-1099",
            crew_role="PILOT_IN_COMMAND",
        )

        validate_error(
            api.create_crew_member(payload, OPS), ApiErrorId.ERR_INVALID_REQUEST, 400
        )


class TestRegulatoryApprovalRecord:
    def test_docket_opened_by_filing_defaults_to_under_review_round_one(self, api):
        """PRD §4: Operations that bring a new resource into existence — registering a lessee, an airframe or a crew member, drafting a lease, filing a docket, attaching a certificate, enrolling a qualification, scheduling a leg, requesting a substitution, preparing an invoice, filing a reliability report, or serving termination (which creates the return-conditions record) — return `201 Created`.
        PRD §3.2: Filing is admissible only from `DRAFT`, requires the operational-control structure to be lawful, and requires the lessee to be `ACTIVE`; it advances the lease from `DRAFT` to `PENDING_REGULATORY_APPROVAL`.
        PRD §3.2: When the lease owns no prior docket, a `RegulatoryApproval` row is created against it with `determination` `UNDER_REVIEW`, `review_round` 1, and both `conditions` and `open_condition_codes` empty.
        PRD §3.2: Every determination sets `decided_at` to the current logical instant.
        PRD §3.2: When the lease already owns a docket whose `determination` is `DENIED`, no second row is created: that docket is refiled in place, moving `DENIED` back to `UNDER_REVIEW`, incrementing `review_round` by 1, resetting `conditions` and `open_condition_codes` to empty, clearing `decided_at`, and overwriting `authority_docket_no` with the newly supplied value.

        Design: Corner/entities/regulatory_docket_defaults_review_round_one_and_empty_conditions
        """
        scenario = setup_draft_lease(api, clock=CLOCK)
        lease_id = scenario["lease"]["id"]

        docket = validate_success(
            api.submit_lease_for_approval(
                lease_id, {"authority_docket_no": "CAA-2026-4471"}, OPS
            ),
            201,
        )

        assert_regulatory_approval(docket)
        assert docket["lease_id"] == lease_id, "the docket is opened against the lease"
        assert docket["authority_docket_no"] == "CAA-2026-4471", (
            "the supplied authority docket number is stored verbatim"
        )
        assert docket["determination"] == "UNDER_REVIEW", (
            "a docket created by filing starts UNDER_REVIEW"
        )
        assert docket["review_round"] == 1, "the first filing is review_round 1"
        assert docket["conditions"] == [], "conditions start empty on a new docket"
        assert docket["open_condition_codes"] == [], (
            "open_condition_codes start empty on a new docket"
        )
        assert docket["decided_at"] is None, (
            "decided_at is written by a determination, so it is null on a docket still "
            "UNDER_REVIEW"
        )

        lease = validate_success(api.get_lease(lease_id, OPS))
        assert lease["status"] == "PENDING_REGULATORY_APPROVAL", (
            "filing advances the lease from DRAFT to PENDING_REGULATORY_APPROVAL"
        )


class TestFlightLegRecord:
    def test_scheduled_block_minutes_floors_seconds_at_creation(self, api):
        """PRD §3.6: `scheduled_block_minutes` is computed once at creation and never changes: it is the whole number of minutes between `scheduled_out` and `scheduled_in`, with any remaining seconds discarded.
        PRD §2.5: Converting an elapsed interval into whole minutes always discards the remaining seconds; a 59-minute-and-59-second interval is 59 minutes.
        PRD §3.6: The leg is created with `status` `SCHEDULED` and `billing_state` `UNBILLED`; `actual_out`, `actual_in`, `cancelling_party` and `cancel_reason` are all null, `technical_delay_minutes` is 0, `block_minutes` and `billable_block_minutes` are 0, and `crew_requalification_required` is false.

        Design: Corner/entities/flight_leg_scheduled_block_minutes_computed_and_client_supplied_value_ignored
        """
        scenario = setup_active_lease(api)

        leg = schedule_leg(
            api,
            scenario,
            scheduled_out="2026-09-08T06:00:00Z",
            scheduled_in="2026-09-08T08:35:30Z",
        )

        assert_flight_leg(leg)
        assert leg["scheduled_block_minutes"] == 155, (
            "a 2h35m30s schedule is 155 whole minutes with the seconds discarded"
        )
        assert leg["block_minutes"] == 0, "block_minutes stays 0 until completion"
        assert leg["billable_block_minutes"] == 0, (
            "billable_block_minutes stays 0 until completion"
        )
        assert leg["actual_out"] is None, "actual_out is null on a scheduled leg"
        assert leg["actual_in"] is None, "actual_in is null on a scheduled leg"
        assert leg["cancelling_party"] is None
        assert leg["cancel_reason"] is None
        assert leg["technical_delay_minutes"] == 0
        assert leg["crew_requalification_required"] is False
        assert leg["status"] == "SCHEDULED", "a leg is created SCHEDULED"
        assert leg["billing_state"] == "UNBILLED", "a leg is created UNBILLED"

    def test_client_supplied_minute_figures_are_not_honoured_at_scheduling(self, api):
        """PRD §3.6: `scheduled_block_minutes` is computed once at creation and never changes: it is the whole number of minutes between `scheduled_out` and `scheduled_in`, with any remaining seconds discarded.
        PRD §3.6: The leg is created with `status` `SCHEDULED` and `billing_state` `UNBILLED`; `actual_out`, `actual_in`, `cancelling_party` and `cancel_reason` are all null, `technical_delay_minutes` is 0, `block_minutes` and `billable_block_minutes` are 0, and `crew_requalification_required` is false.

        Design: Corner/entities/flight_leg_scheduled_block_minutes_computed_and_client_supplied_value_ignored
        """
        scenario = setup_active_lease(api)

        payload = create_flight_leg_payload(
            scenario["lease"]["id"],
            scenario["aircraft"]["id"],
            scenario["captain"]["id"],
            scenario["first_officer"]["id"],
            scheduled_out="2026-09-08T06:00:00Z",
            scheduled_in="2026-09-08T08:35:30Z",
            scheduled_block_minutes=999,
            block_minutes=999,
            billable_block_minutes=999,
        )
        leg = validate_success(api.create_flight_leg(payload, OPS), 201)

        assert leg["scheduled_block_minutes"] == 155, (
            "scheduled_block_minutes is derived from the two scheduled instants, not "
            "taken from the request"
        )
        assert leg["block_minutes"] == 0, (
            "block_minutes is written at completion and is 0 at creation"
        )
        assert leg["billable_block_minutes"] == 0, (
            "billable_block_minutes is written at completion and is 0 at creation"
        )
        assert leg["status"] == "SCHEDULED"
        assert leg["billing_state"] == "UNBILLED"

    def test_scheduling_with_unknown_aircraft_id_returns_aircraft_not_found(self, api):
        """PRD §2.8: **Existence**, resolved in this order and, where a single request carries several identifiers of one kind, left to right in the order the fields are declared in the request: a lessee identifier (`lesseeId` in the path or `lessee_id` in the body) resolving to a `Lessee`, else `ERR_LESSEE_NOT_FOUND`; then every aircraft identifier (`aircraftId`, `primary_aircraft_id`, `original_aircraft_id`, `substitute_aircraft_id`, `aircraft_id`) resolving to an `Aircraft`, else `ERR_AIRCRAFT_NOT_FOUND`; then `leaseId` or `lease_id` resolving to a `LeaseAgreement`, else `ERR_LEASE_NOT_FOUND`; then `crewMemberId`, `crew_member_id`, `captain_id` and `first_officer_id` resolving to `CrewMember` rows, else `ERR_CREW_MEMBER_NOT_FOUND`; then `qualificationId`, else `ERR_QUALIFICATION_NOT_FOUND`; then `approvalId`, else `ERR_APPROVAL_NOT_FOUND`; then `certificateId`, else `ERR_CERTIFICATE_NOT_FOUND`; then `legId` in the path and `repositioning_leg_id` in the body, else `ERR_FLIGHT_LEG_NOT_FOUND`; then `substitutionId`, else `ERR_SUBSTITUTION_NOT_FOUND`; then `periodId` in the path and `period_id` in the body, else `ERR_PERIOD_NOT_FOUND`; then `invoiceId`, else `ERR_INVOICE_NOT_FOUND`; then `reportId`, else `ERR_REPORT_NOT_FOUND`; then `returnId`, else `ERR_RETURN_CONDITION_NOT_FOUND`.
        PRD §2.8: Because most write endpoints in this system guard against half a dozen distinct failures, the order in which checks run is part of the contract: the first check that fails determines the response, and a later check never masks an earlier one.

        Design: Corner/entities/flight_leg_with_unknown_aircraft_id_returns_aircraft_not_found
        """
        scenario = setup_active_lease(api)
        lease_id = scenario["lease"]["id"]

        payload = create_flight_leg_payload(
            lease_id,
            "11111111-1111-4111-8111-111111111111",
            scenario["captain"]["id"],
            scenario["first_officer"]["id"],
            scheduled_out="2026-09-08T06:00:00Z",
            scheduled_in="2026-09-08T08:00:00Z",
        )

        validate_error(
            api.create_flight_leg(payload, OPS), ApiErrorId.ERR_AIRCRAFT_NOT_FOUND, 404
        )

        legs, meta = validate_paginated(
            api.list_flight_legs(OPS, params={"lease_id": lease_id})
        )
        assert meta["total_count"] == 0, (
            "an unknown aircraft_id must be refused before any leg row is written"
        )
        assert legs == []

    def test_flight_leg_listing_paginates_within_the_billing_state_filter(self, api):
        """PRD §2.3: `limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum is 100.
        PRD §2.3: `offset` is the number of rows to skip; it defaults to 0 and its minimum accepted value is 0.
        PRD §2.3: List responses report `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope.
        PRD §2.3: Flight legs accept `lease_id`, `aircraft_id`, `captain_id`, `first_officer_id`, `status` and `billing_state`.
        PRD §2.3: Beyond pagination, list endpoints accept foreign-key and status filters that make every relationship in the model reverse-reachable.
        PRD §2.10: A leg is created `SCHEDULED`; `COMPLETED`, `CANCELLED_LESSEE`, `CANCELLED_LESSOR` and `DIVERTED` are terminal.
        PRD §2.10: `billing_state` is the financial dimension: `UNBILLED`, `PROVISIONALLY_BILLED`, `FINALIZED` or `CREDITED`. A leg is created `UNBILLED`.

        Design: Corner/entities/flight_leg_listing_paginates_and_filters_by_billing_state
        """
        scenario = setup_active_lease(api)
        lease_id = scenario["lease"]["id"]
        for day in ("05", "12", "19"):
            schedule_leg(
                api,
                scenario,
                scheduled_out=f"2026-09-{day}T06:00:00Z",
                scheduled_in=f"2026-09-{day}T08:00:00Z",
            )

        first_page, first_meta = validate_paginated(
            api.list_flight_legs(
                BILLING,
                params={
                    "lease_id": lease_id,
                    "billing_state": "UNBILLED",
                    "limit": 2,
                    "offset": 0,
                },
            )
        )
        assert len(first_page) == 2, "limit 2 must cap the first page at two rows"
        assert first_meta["total_count"] == 3, (
            "total_count must report the size of the filtered set, which holds three "
            "UNBILLED legs"
        )
        assert first_meta["has_more"] is True, (
            "has_more must be true while unread rows remain inside the filtered set"
        )

        second_page, second_meta = validate_paginated(
            api.list_flight_legs(
                BILLING,
                params={
                    "lease_id": lease_id,
                    "billing_state": "UNBILLED",
                    "limit": 2,
                    "offset": 2,
                },
            )
        )
        assert len(second_page) == 1, "offset 2 must skip the first two filtered rows"
        assert second_meta["total_count"] == 3, (
            "total_count is unaffected by the page slice"
        )
        assert second_meta["has_more"] is False, (
            "has_more must be false once the filtered set is exhausted"
        )

        for leg in first_page + second_page:
            assert leg["billing_state"] == "UNBILLED", (
                "the billing_state filter must admit only UNBILLED legs"
            )
            assert leg["status"] == "SCHEDULED", "each leg was created SCHEDULED"

        finalized, finalized_meta = validate_paginated(
            api.list_flight_legs(
                BILLING, params={"lease_id": lease_id, "billing_state": "FINALIZED"}
            )
        )
        assert finalized == [], "no leg has reached FINALIZED yet"
        assert finalized_meta["total_count"] == 0, (
            "total_count must be 0 for a filter that matches nothing"
        )
        assert finalized_meta["has_more"] is False
