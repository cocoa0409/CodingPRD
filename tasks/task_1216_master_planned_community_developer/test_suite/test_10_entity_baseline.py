"""Corner coverage: entity creation defaults, request-shape rejection, typed
404 sweeps, optional-field defaults, and conditional/enum validation."""
from test_helpers import (
    api_client,
    create_active_community,
    create_community_payload,
    create_phase,
    get_success_data,
    validate_error,
    is_valid_uuid,
    is_iso8601_timestamp,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
)
from test_helpers.factories import (
    create_amenity_payload,
    create_budget_payload,
    create_line_item_payload,
    create_lot_payload,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]
REVIEWER = TEST_USERS["design_reviewer_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]


class TestCommunityCreationDefaultsAndEnvelope:
    def test_fresh_community_defaults_and_envelope(self):
        """PRD §3.1: "A new community begins in `PLANNING` status with `closed_unit_count` zero and `transition_stage` `DECLARANT_CONTROL`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."
        PRD §2.4: "a system-managed integer that increments with every modification to the resource."

        Design: Corner/entities/community_creation_defaults_and_envelope
        """
        resp = api_client.create_community(
            create_community_payload(community_name="Solstice Ranch", total_planned_units=100),
            EXEC,
        )
        assert resp.status_code == 201, f"create must return 201, got {resp.status_code}"
        body = resp.json()
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        data = body["data"]
        assert data["status"] == "PLANNING"
        assert data["transition_stage"] == "DECLARANT_CONTROL"
        assert data["closed_unit_count"] == 0
        assert data["version"] == 1

        fetched = get_success_data(api_client.get_community(data["id"], EXEC))
        assert fetched["community_name"] == "Solstice Ranch"
        assert fetched["total_planned_units"] == 100
        assert fetched["status"] == "PLANNING"
        assert fetched["transition_stage"] == "DECLARANT_CONTROL"


class TestCommunityCreateRequestShape:
    def test_missing_required_total_planned_units(self):
        """PRD §2.9 rung 4: "Request shape — required fields present, primitive
        types correct, enum members valid, no undeclared fields, scalar
        constraints honored; otherwise ERR_VALIDATION (HTTP 400)."
        PRD §3.1: a community requires "the total_planned_units — the total
        residential units planned at full build-out, which must be at least 1".

        Design: Corner/entities/community_create_missing_required_returns_validation
        """
        resp = api_client.create_community({"community_name": "No Units"}, EXEC)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_undeclared_computed_field_rejected(self):
        """PRD §2.9 rung 4: "no undeclared fields ... otherwise ERR_VALIDATION
        (HTTP 400)."
        PRD §2.4 lists the system-managed fields; closed_unit_count is a
        computed counter, not a create input.

        Design: Corner/entities/community_create_with_undeclared_field_returns_validation
        """
        resp = api_client.create_community(
            {"community_name": "Computed Trick", "total_planned_units": 10, "closed_unit_count": 5},
            EXEC,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestNotFoundSweepSalesSide:
    def test_typed_404_per_sales_resource(self):
        """PRD §2.10: "Each resource type has its own not-found error — `ERR_COMMUNITY_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_AMENITY_NOT_FOUND`, `ERR_BUILDER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CLOSING_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_DISTRICT_NOT_FOUND`, `ERR_ADVANCE_NOT_FOUND`, `ERR_LEVY_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RSVP_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_BOARD_SEAT_NOT_FOUND` — so a caller can always tell which reference failed."

        Design: Corner/entities/not_found_sweep_sales_side
        """
        expectations = [
            (api_client.get_phase, ApiErrorId.ERR_PHASE_NOT_FOUND),
            (api_client.get_amenity, ApiErrorId.ERR_AMENITY_NOT_FOUND),
            (api_client.get_builder, ApiErrorId.ERR_BUILDER_NOT_FOUND),
            (api_client.get_agreement, ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            (api_client.get_tranche, ApiErrorId.ERR_TRANCHE_NOT_FOUND),
            (api_client.get_lot, ApiErrorId.ERR_LOT_NOT_FOUND),
            (api_client.get_closing, ApiErrorId.ERR_CLOSING_NOT_FOUND),
        ]
        for getter, error_id in expectations:
            resp = getter(NON_EXISTENT_UUID, EXEC)
            validate_error(resp, error_id)


class TestNotFoundSweepGovernanceSide:
    def test_typed_404_per_governance_resource(self):
        """PRD §2.10: "Each resource type has its own not-found error — `ERR_COMMUNITY_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_AMENITY_NOT_FOUND`, `ERR_BUILDER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CLOSING_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_DISTRICT_NOT_FOUND`, `ERR_ADVANCE_NOT_FOUND`, `ERR_LEVY_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RSVP_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_BOARD_SEAT_NOT_FOUND` — so a caller can always tell which reference failed."

        Design: Corner/entities/not_found_sweep_governance_side
        """
        expectations = [
            (api_client.get_budget, CTRL, ApiErrorId.ERR_BUDGET_NOT_FOUND),
            (api_client.get_line_item, CTRL, ApiErrorId.ERR_LINE_ITEM_NOT_FOUND),
            (api_client.get_assessment_rate, CTRL, ApiErrorId.ERR_RATE_NOT_FOUND),
            (api_client.get_district, CTRL, ApiErrorId.ERR_DISTRICT_NOT_FOUND),
            (api_client.get_advance, CTRL, ApiErrorId.ERR_ADVANCE_NOT_FOUND),
            (api_client.get_levy, CTRL, ApiErrorId.ERR_LEVY_NOT_FOUND),
            (api_client.get_payment, CTRL, ApiErrorId.ERR_PAYMENT_NOT_FOUND),
            (api_client.get_board_seat, DIRECTOR, ApiErrorId.ERR_BOARD_SEAT_NOT_FOUND),
        ]
        for getter, headers, error_id in expectations:
            resp = getter(NON_EXISTENT_UUID, headers)
            validate_error(resp, error_id)


class TestNotFoundSweepLifestyleSide:
    def test_typed_404_per_lifestyle_resource(self):
        """PRD §2.10: "Each resource type has its own not-found error — `ERR_COMMUNITY_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_AMENITY_NOT_FOUND`, `ERR_BUILDER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CLOSING_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_DISTRICT_NOT_FOUND`, `ERR_ADVANCE_NOT_FOUND`, `ERR_LEVY_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RSVP_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_BOARD_SEAT_NOT_FOUND` — so a caller can always tell which reference failed."

        Design: Corner/entities/not_found_sweep_lifestyle_side
        """
        expectations = [
            (api_client.get_application, REVIEWER, ApiErrorId.ERR_APPLICATION_NOT_FOUND),
            (api_client.get_violation, REVIEWER, ApiErrorId.ERR_VIOLATION_NOT_FOUND),
            (api_client.get_event, LIFESTYLE, ApiErrorId.ERR_EVENT_NOT_FOUND),
            (api_client.get_rsvp, LIFESTYLE, ApiErrorId.ERR_RSVP_NOT_FOUND),
            (api_client.get_appointment, LIFESTYLE, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND),
            (api_client.get_resident, LIFESTYLE, ApiErrorId.ERR_RESIDENT_NOT_FOUND),
            (api_client.get_notice, LIFESTYLE, ApiErrorId.ERR_NOTICE_NOT_FOUND),
            (api_client.get_community, EXEC, ApiErrorId.ERR_COMMUNITY_NOT_FOUND),
        ]
        for getter, headers, error_id in expectations:
            resp = getter(NON_EXISTENT_UUID, headers)
            validate_error(resp, error_id)


class TestLotAndBudgetDefaultsApplied:
    def test_omitted_optional_inputs_land_declared_defaults(self):
        """PRD §3.4: "A `DeclarantExecutive` plats a `Lot` by naming its `phase_id` and its assessor `parcel_number` — unique within the community, with duplicates rejected as `ERR_VALIDATION` — plus an optional `lot_premium_cents` (zero or more, defaulting to 0) for view, corner, or oversize premiums.". "A new lot is PLATTED".
        PRD §3.5: "A `DeclarantController` drafts an `AssociationBudget` for a `community_id` and a `fiscal_year` (2020 or later), optionally offsetting the assessment requirement with `non_assessment_income_cents` (zero or more, default 0)." and "an
        is_reserve flag (default false)".
        PRD §3.5: "The budget's `total_expense_cents` — the sum of all line amounts — and its `reserve_cents` — the sum over reserve lines only — are recomputed as lines are added."

        Design: Corner/entities/lot_and_budget_defaults_applied
        """
        community = create_active_community("Defaults Depot", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        budget = get_success_data(
            api_client.create_budget(
                create_budget_payload(community_id=community["id"], fiscal_year=2027), CTRL
            )
        )
        assert budget["non_assessment_income_cents"] == 0
        assert budget["total_expense_cents"] == 0

        lot = get_success_data(
            api_client.create_lot(create_lot_payload(phase_id=phase["id"], parcel_number="L1"), EXEC)
        )
        assert lot["lot_premium_cents"] == 0
        assert lot["status"] == "PLATTED"

        line = get_success_data(
            api_client.create_line_item(
                create_line_item_payload(
                    budget_id=budget["id"], category="UTILITIES", amount_cents=700000
                ),
                CTRL,
            )
        )
        assert line["is_reserve"] is False

        reread = get_success_data(api_client.get_budget(budget["id"], CTRL))
        assert reread["total_expense_cents"] == 700000
        assert reread["reserve_cents"] == 0


class TestAmenityConditionalTriggerAndEnumValidation:
    def test_trigger_pair_and_enum_membership_validated(self):
        """PRD §3.2: "Delivery may also be keyed to sell-through: `trigger_phase_id` and `trigger_unit_count` form a nullable pair — either both are present or neither is, and when present the amenity must be `OPEN` before the trigger phase's `closed_lot_count` exceeds `trigger_unit_count`.".
        PRD §3.2: "A `DeclarantExecutive` commits an `Amenity` with an `amenity_type` of `CLUBHOUSE`, `POOL`, `PARK`, `TRAIL_NETWORK`, `FITNESS_CENTER`, or `EVENT_LAWN`; a statutory outside date `hard_deadline_date`; and a `budgeted_cost_cents` of zero or more.".
        PRD §2.9 rung 4: "enum members valid ... otherwise ERR_VALIDATION".

        Design: Corner/entities/amenity_conditional_trigger_and_enum_validation
        """
        community = create_active_community("Enum Enclave", 10)
        phase = create_phase(community["id"], "P1", 1, 5)

        resp_pair = api_client.create_amenity(
            create_amenity_payload(
                community_id=community["id"], amenity_type="POOL",
                trigger_phase_id=phase["id"],
            ),
            EXEC,
        )
        validate_error(resp_pair, ApiErrorId.ERR_VALIDATION)

        resp_enum = api_client.create_amenity(
            create_amenity_payload(
                community_id=community["id"], amenity_type="GOLF_COURSE",
            ),
            EXEC,
        )
        validate_error(resp_enum, ApiErrorId.ERR_VALIDATION)
