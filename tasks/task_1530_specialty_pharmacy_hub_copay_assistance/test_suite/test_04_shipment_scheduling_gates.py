"""Shipment creation and ship-time gates: enrollment readiness, cold chain
vs refill-spacing ordering, terminal-enrollment state vs funding capacity,
minimum refill spacing, and the first-fill training gate."""
from test_helpers import (
    ApiErrorId,
    api_client,
    complete_training_visit,
    create_active_with_delivered_fill,
    create_approved_enrollment,
    create_enrollment,
    create_program,
    create_pa_pending_enrollment,
    create_shipment_payload,
    deliver,
    enrollment_version,
    get_enrollment,
    match_assistance_payload,
    request_shipment,
    set_clock,
    ship,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

CM = TEST_USERS["case_manager_headers"]
FC = TEST_USERS["financial_counselor_headers"]


class TestEnrollmentReadinessGate:

    def test_shipment_creation_rejected_while_enrollment_in_intake(self):
        """PRD section 3.6: "Creation requires the enrollment to stand in
        `PA_PENDING`, `APPROVED`, or `ACTIVE`; any other non-terminal state
        yields `ERR_ENROLLMENT_NOT_READY_FOR_SHIPMENT`, and a terminal
        enrollment yields `ERR_ENROLLMENT_DISCONTINUED`."

        Design: Difficulty/cross_entity_state_dependency/shipment_creation_gated_on_enrollment_state
        """
        prog = create_program(name="ProgX1")
        enr = create_enrollment(prog["id"], patient_ref="PAT-N")
        resp = api_client.create_shipment(
            enr["id"], create_shipment_payload(
                requested_delivery_date="2026-08-03"), CM)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_READY_FOR_SHIPMENT)

    def test_shipment_creation_succeeds_once_benefits_approve_enrollment(self):
        """PRD section 3.6: "Otherwise — enrollment `APPROVED` or `ACTIVE`
        with no `RESERVED` assistance present — the shipment enters
        `SCHEDULED` directly at creation."
        PRD section 3.6: "Each shipment receives a per-enrollment
        `fill_number`, one greater than the highest fill number already on
        the enrollment and starting at one, and a `fill_type` of
        `FIRST_FILL` when no prior `DELIVERED` shipment exists for the
        enrollment, otherwise `REFILL`."

        Design: Difficulty/cross_entity_state_dependency/shipment_creation_gated_on_enrollment_state
        """
        ctx = create_approved_enrollment(patient_ref="PAT-N2")
        resp = api_client.create_shipment(
            ctx["enrollment"]["id"], create_shipment_payload(
                requested_delivery_date="2026-08-03"), CM)
        fill = validate_success(resp, expected_status=201)
        assert fill["status"] == "SCHEDULED"
        assert fill["fill_type"] == "FIRST_FILL"
        assert fill["fill_number"] == 1


class TestShipFromRequested:

    def test_shipment_ship_from_requested_returns_invalid_transition(self):
        """PRD section 3.6: "A shipment created while its enrollment sits in
        `PA_PENDING` enters `REQUESTED`, and so does one created under an
        `APPROVED` or `ACTIVE` enrollment while a `RESERVED` assistance
        still blocks clearance."
        PRD section 3.6: "The `PharmacyPartner` ships a `SCHEDULED`
        shipment. Shipping requires the enrollment to stand in `APPROVED` or
        `ACTIVE` and no `RESERVED` assistance to remain on it; attempting to
        ship a shipment still `REQUESTED` is rejected with
        `ERR_INVALID_TRANSITION`."
        PRD section 3.6: "At ship time the financial split runs against the
        shipment's frozen `patient_cost_share_cents`, and its three outputs
        — `assistance_pay_cents`, `patient_pay_cents`, and
        `payer_accumulator_delta_cents` — are null until the shipment
        reaches `SHIPPED`, at which point they are stamped onto it:"

        Design: Corner/state_machines/shipment_ship_from_requested_returns_invalid_transition
        """
        ctx = create_pa_pending_enrollment(patient_ref="PAT-S2")
        fill = request_shipment(
            ctx["enrollment"]["id"], requested_delivery_date="2026-08-05")
        assert fill["status"] == "REQUESTED", \
            "a fill created during PA_PENDING enters REQUESTED"

        resp = api_client.ship_shipment(fill["id"],
                                        TEST_USERS["pharmacy_partner_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
        assert fill["assistance_pay_cents"] is None, \
            "split outputs stay null until SHIPPED"
        assert fill["patient_pay_cents"] is None
        assert fill["payer_accumulator_delta_cents"] is None


class TestColdChainBeatsRefillSpacing:

    def _setup_active_with_delivery(self):
        """Cold-chain program (max transit 48, min spacing 20); fill 1
        delivered 2026-08-10 with the clock at 2026-08-10."""
        ctx = create_approved_enrollment(
            patient_ref="PAT-K",
            program_overrides={
                "requires_cold_chain": True,
                "max_transit_hours": 48,
                "min_days_between_fills": 20,
            })
        enr_id = ctx["enrollment"]["id"]
        fill_1 = request_shipment(
            enr_id, requested_delivery_date="2026-08-01", transit_hours=24)
        ship(fill_1["id"])
        set_clock("2026-08-10T00:00:00Z")
        deliver(fill_1["id"], "2026-08-10")
        return enr_id

    def test_cold_chain_violation_wins_over_spacing_violation(self):
        """PRD section 2.6: "The ordering is observable. A shipment request
        naming a missing enrollment surfaces the 404 before its body is even
        inspected; a stale-version outcome report create surfaces
        `ERR_STALE_VERSION` before its period-overlap check runs; and on
        shipment creation a cold-chain violation surfaces before the
        training or adherence gates, which in turn surface before refill
        spacing is examined."
        PRD section 3.6: "Cold chain comes first: when the program's
        `requires_cold_chain` is set, the planned `transit_hours` must not
        exceed the program's `max_transit_hours`, and a shipment that would
        run longer is rejected with `ERR_COLD_CHAIN_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/cold_chain_beats_refill_spacing
        """
        enr_id = self._setup_active_with_delivery()
        # transit 72 > max 48 AND requested 2026-08-20 < 08-10 + 20 days:
        # both rules are violated; the safety error must win.
        resp = api_client.create_shipment(
            enr_id, create_shipment_payload(
                requested_delivery_date="2026-08-20", transit_hours=72), CM)
        validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_EXCEEDED)

    def test_spacing_violation_surfaces_once_cold_chain_passes(self):
        """PRD section 2.6: "The ordering is observable. A shipment request
        naming a missing enrollment surfaces the 404 before its body is even
        inspected; a stale-version outcome report create surfaces
        `ERR_STALE_VERSION` before its period-overlap check runs; and on
        shipment creation a cold-chain violation surfaces before the
        training or adherence gates, which in turn surface before refill
        spacing is examined."
        PRD section 3.6: "Then the refill gates: a `REFILL` requires
        confirmed adherence of at least 80.0 percent (§3.7), failing
        which creation is rejected with `ERR_ADHERENCE_TOO_LOW`, and its
        `requested_delivery_date` must fall no earlier than the latest
        `DELIVERED` shipment's `delivered_date` plus the program's
        `min_days_between_fills` days — an earlier date is rejected with
        `ERR_REFILL_SPACING_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/cold_chain_beats_refill_spacing
        """
        enr_id = self._setup_active_with_delivery()
        # Same too-early date but a compliant transit time: cold chain
        # passes and the temporal error is what surfaces.
        resp = api_client.create_shipment(
            enr_id, create_shipment_payload(
                requested_delivery_date="2026-08-20", transit_hours=24), CM)
        validate_error(resp, ApiErrorId.ERR_REFILL_SPACING_VIOLATION)


class TestTerminalEnrollmentMatchPriority:

    def _setup_discontinued_enrollment(self):
        ctx = create_approved_enrollment(patient_ref="PAT-J")
        enr_id = ctx["enrollment"]["id"]
        validate_success(api_client.discontinue_enrollment(
            enr_id, {"reason": "patient withdrew"}, CM), expected_status=200)
        return enr_id

    def test_match_on_terminal_enrollment_returns_enrollment_discontinued(self):
        """PRD section 2.6: "Incoming requests pass through a fixed cascade
        of checks, evaluated in the following order, and the first failing
        check determines the error returned".
        PRD section 3.2: "Once an enrollment stands in `DISCONTINUED` or
        `DENIED_CLOSED`, every child-mutating operation against it is
        rejected with `ERR_ENROLLMENT_DISCONTINUED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_terminal_enrollment_match
        """
        enr_id = self._setup_discontinued_enrollment()
        # No foundation pools exist, so the funding-capacity check (last in
        # the cascade) would also fail; the earlier state check must win.
        resp = api_client.match_copay_assistance(
            enr_id,
            match_assistance_payload(
                enrollment_version(enr_id), assistance_type="FOUNDATION"),
            FC)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_DISCONTINUED)

    def test_rejected_terminal_match_creates_nothing(self):
        """PRD section 2.6: "Incoming requests pass through a fixed cascade
        of checks, evaluated in the following order, and the first failing
        check determines the error returned".
        PRD section 3.2: "Once an enrollment stands in `DISCONTINUED` or
        `DENIED_CLOSED`, every child-mutating operation against it is
        rejected with `ERR_ENROLLMENT_DISCONTINUED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_terminal_enrollment_match
        """
        enr_id = self._setup_discontinued_enrollment()
        version = enrollment_version(enr_id)
        resp = api_client.match_copay_assistance(
            enr_id, match_assistance_payload(version,
                                             assistance_type="FOUNDATION"),
            FC)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_DISCONTINUED)
        _, meta = validate_paginated(api_client.list_copay_assistances(enr_id, FC))
        assert meta["total_count"] == 0, "a rejected match creates nothing"
        assert enrollment_version(enr_id) == version, \
            "a rejected match must not advance the enrollment version"


class TestRefillSpacingBoundary:

    def _setup_delivered_fill(self):
        ctx = create_active_with_delivered_fill(
            patient_ref="PAT-Q", days_supply=30,
            requested_delivery_date="2026-08-01", delivered_date="2026-08-01")
        set_clock("2026-08-15T00:00:00Z")
        return ctx["enrollment"]["id"]

    def test_refill_one_day_short_of_minimum_gap_rejected(self):
        """PRD section 3.6: "Then the refill gates: a `REFILL` requires
        confirmed adherence of at least 80.0 percent (§3.7), failing
        which creation is rejected with `ERR_ADHERENCE_TOO_LOW`, and its
        `requested_delivery_date` must fall no earlier than the latest
        `DELIVERED` shipment's `delivered_date` plus the program's
        `min_days_between_fills` days — an earlier date is rejected with
        `ERR_REFILL_SPACING_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/refill_minimum_gap_spacing
        """
        enr_id = self._setup_delivered_fill()
        # 2026-08-20 is 19 days after the 2026-08-01 delivery; the minimum
        # is 20, so the request is one day early.
        resp = api_client.create_shipment(
            enr_id, create_shipment_payload(
                requested_delivery_date="2026-08-20"), CM)
        validate_error(resp, ApiErrorId.ERR_REFILL_SPACING_VIOLATION)

    def test_refill_at_exactly_minimum_gap_accepted(self):
        """PRD section 3.6: "Then the refill gates: a `REFILL` requires
        confirmed adherence of at least 80.0 percent (§3.7), failing
        which creation is rejected with `ERR_ADHERENCE_TOO_LOW`, and its
        `requested_delivery_date` must fall no earlier than the latest
        `DELIVERED` shipment's `delivered_date` plus the program's
        `min_days_between_fills` days — an earlier date is rejected with
        `ERR_REFILL_SPACING_VIOLATION`."
        PRD section 3.6: "Each shipment receives a per-enrollment
        `fill_number`, one greater than the highest fill number already on
        the enrollment and starting at one, and a `fill_type` of
        `FIRST_FILL` when no prior `DELIVERED` shipment exists for the
        enrollment, otherwise `REFILL`."

        Design: Difficulty/resource_temporal_overlap/refill_minimum_gap_spacing
        """
        enr_id = self._setup_delivered_fill()
        # 2026-08-21 is exactly 20 days after delivery: the spacing
        # comparison is inclusive, so this passes.
        resp = api_client.create_shipment(
            enr_id, create_shipment_payload(
                requested_delivery_date="2026-08-21"), CM)
        fill = validate_success(resp, expected_status=201)
        assert fill["fill_number"] == 2
        assert fill["fill_type"] == "REFILL"


class TestFirstFillTrainingGate:

    def test_training_gate_blocks_first_fill_until_session_completed(self):
        """PRD section 3.6: "Next, the first-fill training gate: when the
        program's `requires_injection_training` is set, a `FIRST_FILL`
        requires `training_sessions_completed` of at least one, failing
        which creation is rejected with `ERR_TRAINING_INCOMPLETE`."
        PRD section 3.5: "A `COMPLETED` resolution increments the
        enrollment's `training_sessions_completed` by one — a parent
        mutation that bumps the enrollment's `version`, which
        concurrency-guarded writers will observe."

        Design: Corner/errors/err_training_incomplete_trigger_coverage
        """
        ctx = create_approved_enrollment(
            patient_ref="PAT-T1",
            program_overrides={"requires_injection_training": True})
        enr_id = ctx["enrollment"]["id"]

        resp = api_client.create_shipment(
            enr_id, create_shipment_payload(
                requested_delivery_date="2026-08-03"), CM)
        validate_error(resp, ApiErrorId.ERR_TRAINING_INCOMPLETE)

        complete_training_visit(enr_id, nurse_id="nurse-1")

        resp = api_client.create_shipment(
            enr_id, create_shipment_payload(
                requested_delivery_date="2026-08-03"), CM)
        fill = validate_success(resp, expected_status=201)
        assert fill["status"] == "SCHEDULED", \
            "the identical request succeeds after one COMPLETED visit"
