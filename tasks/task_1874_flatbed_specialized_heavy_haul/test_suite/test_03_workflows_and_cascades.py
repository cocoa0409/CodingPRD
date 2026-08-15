"""Non-linear state machines, transitive cascades, and cross-entity state
dependencies (PRD §3.3, §3.5, §3.7-§3.9)."""
from test_helpers import (
    BILLING,
    DISPATCHER,
    DRIVER,
    SAFETY,
    STATE_AUTHORITY,
    ApiErrorId,
    assert_invoice,
    assert_invoice_arithmetic,
    assert_load,
    assert_permit,
    book_escort,
    create_customer,
    create_filed_and_granted_permit,
    create_load_for_customer,
    create_permit_for_load,
    deny_permit_payload,
    file_and_approve_securement,
    file_permit,
    grant_permit,
    issue_invoice,
    plan_load,
    record_scale_violation,
    report_and_resolve_fine,
    schedule_both_cranes,
    set_clock,
    setup_ca_load_in_transit,
    setup_ca_oversize_overweight_cleared,
    setup_standard_load_in_transit,
    survey_load,
    validate_error,
    validate_success,
)


class TestPermitDenyRefileCycle:
    def _setup_az_overweight_permit(self, api):
        customer = create_customer("Desert Aggregates", 100_000_000)
        load = create_load_for_customer(
            customer["id"],
            cargo_description="Crusher drum", gross_weight_lbs=96000,
            width_in=150, height_in=100, length_in=400,
            origin="Tucson AZ", destination="Flagstaff AZ",
        )
        plan_load(
            load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
            trailer_axle_count=6, driver_name="F. Ibarra",
            driver_oversize_endorsed=True,
        )
        surveyed = survey_load(
            load["id"], route_miles=260, states_crossed=["AZ"],
            min_bridge_clearance_in=200, max_bridge_weight_lbs=120000,
        )
        permit = create_permit_for_load(
            load["id"], "AZ", "OVERWEIGHT",
            expected_load_version=surveyed["version"],
        )
        return permit

    def test_denied_is_not_terminal_and_refile_recomputes(self, api):
        """PRD §3.5: "`DENIED` is not terminal: the clerk re-files after
        amendment, which recomputes the fee on the current weight basis, and
        that negotiation cycle may repeat."

        Design: Difficulty/non_linear_state_machine/permit_deny_refile_cycle
        """
        permit = self._setup_az_overweight_permit(api)
        filed1 = file_permit(permit["id"])
        # AZ OVERWEIGHT base 13000 + excess 16000 lbs x 1 cent = 29000.
        assert filed1["status"] == "FILED"
        assert filed1["fee_cents"] == 29000
        denied = validate_success(
            api.deny_permit(
                permit["id"],
                deny_permit_payload(denial_reason="bridge work on I-10"),
                STATE_AUTHORITY,
            ),
            200,
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "bridge work on I-10"
        filed2 = file_permit(permit["id"])
        assert filed2["status"] == "FILED"
        # No scale ticket exists: refile recomputes on the declared basis.
        assert filed2["fee_cents"] == 29000

    def test_cycle_closes_filed_denied_filed_granted(self, api):
        """PRD §3.5: "Denying a `FILED` permit stores the free-text
        `denial_reason` and moves it to `DENIED`."
        PRD §3.5: "Granting a `FILED` permit stores the legal travel window —
        `travel_window_start` and a `travel_window_end` that must be strictly
        after the start — moves the permit to `GRANTED`, and re-evaluates the
        load's readiness gate."

        Design: Difficulty/non_linear_state_machine/permit_deny_refile_cycle
        """
        permit = self._setup_az_overweight_permit(api)
        file_permit(permit["id"])
        validate_success(
            api.deny_permit(
                permit["id"], deny_permit_payload(), STATE_AUTHORITY,
            ),
            200,
        )
        file_permit(permit["id"])
        granted = grant_permit(permit["id"])
        assert_permit(granted)
        assert granted["status"] == "GRANTED"
        assert granted["travel_window_start"] == "2026-08-10T00:00:00Z"
        assert granted["travel_window_end"] == "2026-08-20T00:00:00Z"


class TestLoadReplanLoopAndHoldBranch:
    def _setup_replan_loop(self, api):
        """SURVEYED -> PLANNED (survey nulled) -> SURVEYED, then full CA
        clearance. Returns the context dict."""
        customer = create_customer("Valley Transformers", 100_000_000)
        load = create_load_for_customer(
            customer["id"],
            cargo_description="Transformer", gross_weight_lbs=96000,
            width_in=150, height_in=100, length_in=400,
            origin="Fresno CA", destination="Bakersfield CA",
        )
        plan_load(
            load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
            trailer_axle_count=6, driver_name="G. Holt",
            driver_oversize_endorsed=True,
        )
        first = survey_load(
            load["id"], route_miles=500, states_crossed=["CA"],
            min_bridge_clearance_in=200, max_bridge_weight_lbs=120000,
        )
        assert first["status"] == "SURVEYED"
        replanned = plan_load(
            load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
            trailer_axle_count=6, driver_name="G. Holt",
            driver_oversize_endorsed=True,
        )
        second = survey_load(
            load["id"], route_miles=500, states_crossed=["CA"],
            min_bridge_clearance_in=200, max_bridge_weight_lbs=120000,
        )
        return customer, load, replanned, second

    def test_replan_loop_demotes_and_nulls_survey(self, api):
        """PRD §3.2: "Re-planning a `SURVEYED` load is permitted because deck
        height and capacity may change, but it invalidates the survey:
        `survey_result` is reset to null."
        PRD §3.3: "A passing survey moves the load from `PLANNED` to
        `SURVEYED`, stores the four survey inputs, sets `survey_result` to
        `PASSED`, and increments the load's `version`."

        Design: Difficulty/non_linear_state_machine/load_replan_loop_and_hold_branch
        """
        _, _, replanned, second = self._setup_replan_loop(api)
        # Replan loop: SURVEYED -> PLANNED demotes and nulls the survey.
        assert replanned["status"] == "PLANNED"
        assert replanned["survey_result"] is None
        # Second survey closes the PLANNED <-> SURVEYED loop.
        assert second["status"] == "SURVEYED"
        assert second["survey_result"] == "PASSED"

    def test_hold_recovery_requires_escort_rebooking(self, api):
        """PRD §3.8: "Release clears `hold_reason` to null, returns the load to
        `SURVEYED`, immediately re-evaluates the readiness gate — which may
        advance it straight back to `CLEARED` if escorts, cranes, and
        securement again satisfy the gate — and increments the load's
        `version`."
        PRD §3.8: "Third, if the load is `CLEARED` or `IN_TRANSIT` it moves to
        `ON_HOLD` with `hold_reason` set to `SCALE_OVERWEIGHT`, and that hold
        cancels every `CONFIRMED` escort booking, freeing the providers'
        windows."

        Design: Difficulty/non_linear_state_machine/load_replan_loop_and_hold_branch
        """
        customer, load, _, second = self._setup_replan_loop(api)
        load_id = load["id"]
        create_filed_and_granted_permit(load_id, "CA", "OVERSIZE")
        p_ow = create_filed_and_granted_permit(load_id, "CA", "OVERWEIGHT")
        book_escort(load_id, provider_name="Valley Pilots", position="REAR")
        schedule_both_cranes(load_id)
        file_and_approve_securement(load_id)
        set_clock("2026-08-12T10:00:00Z")
        validate_success(api.depart_load(load_id, DRIVER), 200)
        # Scale violation: 100000 vs declared 96000 -> hold cascade.
        record_scale_violation(load_id, measured_gross_lbs=100000)
        held = validate_success(api.get_load(load_id, DISPATCHER), 200)
        assert held["status"] == "ON_HOLD"
        assert held["hold_reason"] == "SCALE_OVERWEIGHT"
        # Refile the revoked OVERWEIGHT permit on the measured basis:
        # CA base 15000 + excess 20000 x 1 cent = 35000.
        refiled = file_permit(p_ow["id"])
        assert refiled["fee_cents"] == 35000
        grant_permit(
            p_ow["id"],
            window_start="2026-08-12T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
        )
        released = validate_success(
            api.release_hold_load(load_id, SAFETY), 200
        )
        # Release lands in SURVEYED, NOT CLEARED: the hold cascade cancelled
        # the escort, so the readiness gate cannot refire yet.
        assert released["status"] == "SURVEYED"
        assert released["hold_reason"] is None
        # The first booking was freed by the hold cascade.
        bookings = validate_success(
            api.list_escort_bookings(load_id, DISPATCHER), 200
        )
        assert bookings[0]["status"] == "CANCELLED"
        # Rebooking the escort refires the gate and re-clears the load.
        book_escort(
            load_id, provider_name="Valley Pilots", position="REAR",
            start="2026-08-13T08:00:00Z", end="2026-08-13T12:00:00Z",
        )
        final = validate_success(api.get_load(load_id, DISPATCHER), 200)
        assert final["status"] == "CLEARED"


class TestScaleViolationCascadeDepth4:
    def test_violation_fine_and_permit_revocation_links(self, api):
        """PRD §3.8: "A violating ticket fires the full cascade in one request.
        First, the system creates a `Fine` of kind `OVERWEIGHT` with
        `liable_party` `CUSTOMER`, priced marginally on `excess_lbs`: the first
        2,000 excess pounds at 25 cents per pound, the next 3,000 at 50 cents,
        and every pound beyond 5,000 at 100 cents, each tier priced only on the
        pounds inside it. Second, every `GRANTED` `OVERWEIGHT` or `SUPERLOAD`
        permit of the load flips to `REVOKED`; `OVERSIZE` permits are
        unaffected."

        Design: Difficulty/transitive_cascade/scale_violation_cascade_depth4
        """
        ctx = setup_ca_load_in_transit(company_name="Sierra Crushers")
        load_id = ctx["load"]["id"]
        ticket = record_scale_violation(
            load_id, measured_gross_lbs=100000,
        )
        # 100000 vs declared 96000; 100000*100 > 96000*103 (integer-exact).
        assert ticket["is_violation"] is True
        assert ticket["excess_lbs"] == 4000
        fines = validate_success(api.list_fines(load_id, SAFETY), 200)
        fine = fines[0]
        # Link 1: 2000x25 + 2000x50 marginal = 150000.
        assert fine["kind"] == "OVERWEIGHT"
        assert fine["amount_cents"] == 150000
        assert fine["liable_party"] == "CUSTOMER"
        assert fine["status"] == "PENDING"
        # Link 2 is type-selective: OVERWEIGHT revoked, OVERSIZE untouched.
        permits = validate_success(api.list_permits(load_id, DISPATCHER), 200)
        by_type = {p["permit_type"]: p["status"] for p in permits}
        assert by_type["OVERWEIGHT"] == "REVOKED"
        assert by_type["OVERSIZE"] == "GRANTED"

    def test_hold_escort_cancel_and_depart_rejection_links(self, api):
        """PRD §3.8: "Third, if the load is `CLEARED` or `IN_TRANSIT` it moves
        to `ON_HOLD` with `hold_reason` set to `SCALE_OVERWEIGHT`, and that
        hold cancels every `CONFIRMED` escort booking, freeing the providers'
        windows."
        PRD §3.7: "The load must be `CLEARED` (`ERR_LOAD_INVALID_STATE`)."

        Design: Difficulty/transitive_cascade/scale_violation_cascade_depth4
        """
        ctx = setup_ca_load_in_transit(company_name="Sierra Crushers")
        load_id = ctx["load"]["id"]
        record_scale_violation(load_id, measured_gross_lbs=100000)
        # Link 3: load held.
        load = validate_success(api.get_load(load_id, DISPATCHER), 200)
        assert_load(load)
        assert load["status"] == "ON_HOLD"
        assert load["hold_reason"] == "SCALE_OVERWEIGHT"
        # Link 4: the escort was freed by the hold, not by the original POST.
        bookings = validate_success(
            api.list_escort_bookings(load_id, DISPATCHER), 200
        )
        assert bookings[0]["status"] == "CANCELLED"
        # Second-order consequence: depart is now rejected on load state.
        err = validate_error(
            api.depart_load(load_id, DRIVER),
            ApiErrorId.ERR_LOAD_INVALID_STATE,
        )
        assert err["error_id"] == "ERR_LOAD_INVALID_STATE"


class TestInvoiceVoidCompensationCascade:
    def _setup_suspended_after_issue(self, api):
        """Customer credit 1700000; DAMAGE fine 200000 resolved customer-liable
        tips the issued invoice (1825740) over the limit."""
        ctx = setup_ca_oversize_overweight_cleared(
            company_name="Coastal Aggregates", credit_limit_cents=1_700_000,
            route_miles=2000,
        )
        load_id = ctx["load"]["id"]
        report_and_resolve_fine(
            load_id, kind="DAMAGE", amount_cents=200000,
            resolution="CUSTOMER_LIABLE",
            description="Deck rail bent during loading",
        )
        set_clock("2026-08-12T10:00:00Z")
        validate_success(api.depart_load(load_id, DRIVER), 200)
        validate_success(api.arrive_load(load_id, DRIVER), 200)
        invoice = issue_invoice(load_id)
        return ctx, invoice

    def test_issue_suspends_and_sweeps_fines(self, api):
        """PRD §3.9: "The customer is debited immediately:
        `outstanding_balance_cents` increases by `total_cents`, and if the
        result strictly exceeds `credit_limit_cents` the customer flips to
        `SUSPENDED` per §3.1."
        PRD §3.9: "Creation moves the invoice directly to `ISSUED` and sweeps
        every customer-liable fine still `PENDING` or
        `RESOLVED_CUSTOMER_LIABLE` into `APPLIED`."

        Design: Difficulty/transitive_cascade/invoice_void_compensation_cascade
        """
        ctx, invoice = self._setup_suspended_after_issue(api)
        load_id = ctx["load"]["id"]
        # subtotal 1400000 + 42500 + 48000 + 200000 = 1690500; fuel 8% = 135240
        assert invoice["total_cents"] == 1825740
        customer = validate_success(
            api.get_customer(ctx["customer"]["id"], BILLING), 200
        )
        # Auto-suspension: 1825740 > 1700000.
        assert customer["outstanding_balance_cents"] == 1825740
        assert customer["status"] == "SUSPENDED"
        fines = validate_success(api.list_fines(load_id, BILLING), 200)
        assert fines[0]["status"] == "APPLIED"

    def test_void_compensates_balance_and_unsweeps_without_reinstate(self, api):
        """PRD §3.9: "Voiding, also restricted to `ISSUED` invoices, moves it
        to the terminal `VOID` state, credits the same amount off the
        outstanding balance, and un-sweeps the invoice's fines from `APPLIED`
        back to `PENDING` so that a replacement invoice can legitimately
        include them."
        PRD §3.1: "Reinstatement is performed by a `BillingClerk` and moves
        `SUSPENDED` back to `ACTIVE`, but only when the customer is in fact
        `SUSPENDED` (otherwise `ERR_INVALID_STATE`, HTTP 409) and only when the
        outstanding balance is at or below the credit limit — if it still
        exceeds the limit, the reinstatement is rejected with
        `ERR_REINSTATE_NOT_ALLOWED` (HTTP 409)."

        Design: Difficulty/transitive_cascade/invoice_void_compensation_cascade
        """
        ctx, invoice = self._setup_suspended_after_issue(api)
        load_id = ctx["load"]["id"]
        voided = validate_success(api.void_invoice(invoice["id"], BILLING), 200)
        assert voided["status"] == "VOID"
        customer = validate_success(
            api.get_customer(ctx["customer"]["id"], BILLING), 200
        )
        # Outstanding compensated exactly; fines un-swept; the cascade does
        # NOT auto-reinstate the customer.
        assert customer["outstanding_balance_cents"] == 0
        assert customer["status"] == "SUSPENDED"
        fines = validate_success(api.list_fines(load_id, BILLING), 200)
        assert fines[0]["status"] == "PENDING"
        reinstated = validate_success(
            api.reinstate_customer(ctx["customer"]["id"], BILLING), 200
        )
        assert reinstated["status"] == "ACTIVE"


class TestClearanceGateRequiresAllPermitsGranted:
    def _setup_overweight_stuck_at_filed(self, api):
        """CA load: OVERSIZE GRANTED, OVERWEIGHT stuck at FILED, escort,
        cranes, and securement all satisfied."""
        customer = create_customer("Mission Bell", 100_000_000)
        load = create_load_for_customer(
            customer["id"],
            cargo_description="Switchgear", gross_weight_lbs=96000,
            width_in=150, height_in=100, length_in=400,
            origin="Gilroy CA", destination="Salinas CA",
        )
        plan_load(
            load["id"], trailer_type="EXTENDABLE_DOUBLE_DROP",
            trailer_axle_count=6, driver_name="N. Wade",
            driver_oversize_endorsed=True,
        )
        survey_load(
            load["id"], route_miles=500, states_crossed=["CA"],
            min_bridge_clearance_in=200, max_bridge_weight_lbs=120000,
        )
        create_filed_and_granted_permit(load["id"], "CA", "OVERSIZE")
        p_ow = create_permit_for_load(load["id"], "CA", "OVERWEIGHT")
        file_permit(p_ow["id"])
        book_escort(load["id"], provider_name="Peninsula Pilots",
                    position="REAR")
        schedule_both_cranes(load["id"])
        file_and_approve_securement(load["id"])
        return load, p_ow

    def test_gate_holds_while_permit_only_filed(self, api):
        """PRD §3.7: "All five conditions must hold simultaneously:"
        PRD §3.7: "2. Permits are complete: for every state in
        `states_crossed`, a superload holds a `GRANTED` `SUPERLOAD` permit for
        that state; otherwise the load holds a `GRANTED` `OVERSIZE` permit for
        that state when oversize and a `GRANTED` `OVERWEIGHT` permit when
        overweight, and standard loads need nothing."

        Design: Difficulty/cross_entity_state_dependency/clearance_gate_requires_all_permits_granted
        """
        load, _ = self._setup_overweight_stuck_at_filed(api)
        current = validate_success(api.get_load(load["id"], DISPATCHER), 200)
        # Escort, cranes, and securement are complete, but the gate holds:
        # the OVERWEIGHT permit is merely FILED, not GRANTED.
        assert current["status"] == "SURVEYED"

    def test_permit_grant_refires_gate_and_clears_load(self, api):
        """PRD §3.7: "The readiness gate converts a `SURVEYED` load into a
        `CLEARED` one and is re-evaluated automatically after every permit
        grant, escort booking creation, crane appointment creation, and
        securement approval."
        PRD §3.7: "When all five pass, the load advances to `CLEARED` and its
        `version` increments."

        Design: Difficulty/cross_entity_state_dependency/clearance_gate_requires_all_permits_granted
        """
        load, p_ow = self._setup_overweight_stuck_at_filed(api)
        granted = grant_permit(p_ow["id"])
        assert granted["status"] == "GRANTED"
        # The Permit-side mutation refires the gate — no Load-endpoint call.
        current = validate_success(api.get_load(load["id"], DISPATCHER), 200)
        assert current["status"] == "CLEARED"


class TestInvoiceCreationRequiresLoadDelivered:
    def test_invoice_rejected_while_in_transit(self, api):
        """PRD §3.9: "Final billing begins only after delivery. A
        `BillingClerk` creates the invoice for a `DELIVERED` load, and a load
        may carry at most one `ISSUED` invoice at a time — a second attempt is
        rejected with `ERR_INVOICE_EXISTS` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/invoice_creation_requires_load_delivered
        """
        _, load = setup_standard_load_in_transit(
            company_name="Rogue Valley Lumber"
        )
        err = validate_error(
            api.create_invoice(load["id"], BILLING),
            ApiErrorId.ERR_LOAD_INVALID_STATE,
        )
        assert err["error_id"] == "ERR_LOAD_INVALID_STATE"

    def test_invoice_issued_after_arrive_with_final_totals(self, api):
        """PRD §3.9: "Final billing begins only after delivery. A
        `BillingClerk` creates the invoice for a `DELIVERED` load"
        PRD §3.9: "1. `linehaul_cents` — `route_miles` multiplied by the
        trailer's catalog cost per mile in cents."

        Design: Difficulty/cross_entity_state_dependency/invoice_creation_requires_load_delivered
        """
        _, load = setup_standard_load_in_transit(
            company_name="Rogue Valley Lumber"
        )
        validate_success(api.arrive_load(load["id"], DRIVER), 200)
        inv = issue_invoice(load["id"])
        assert_invoice(inv)
        assert_invoice_arithmetic(inv)
        assert inv["status"] == "ISSUED"
        # linehaul 35000 (100 mi x 350); subtotal 35000; fuel 8% = 2800.
        assert inv["total_cents"] == 37800
