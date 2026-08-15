"""Warranty claims: dual-basis eligibility, cross-entity review gate, unit
commercial dimension, and adjudication RBAC."""
from test_helpers import (
    ApiErrorId,
    add_shipment,
    get_claim,
    get_unit,
    make_claim,
    make_customer_headers,
    record_assembly,
    record_run_in,
    set_clock,
    setup_approved_order,
    setup_claim_under_review,
    setup_completed_order,
    setup_ready_to_ship_order,
    validate_error,
    validate_success,
)


class TestDualBasisEligibility:
    def test_eligibility_expired_calendar_when_hours_leg_covered(
            self, api, intake_coordinator_headers):
        """PRD §3.7: "The calendar leg measures whole days between the
        claim's `created_at` and the order's `completed_at_utc`: covered at
        no more than 365 days, failed as `EXPIRED_CALENDAR` beyond that. The
        combined `eligibility` is `COVERED` only when both legs are covered;
        when the hours leg fails it is reported as `EXPIRED_HOURS` — the
        hours basis is evaluated before the calendar basis — and otherwise
        `EXPIRED_CALENDAR`."

        Design: Difficulty/dual_variant_calc/warranty_hours_basis_vs_calendar_basis_on_claim
        """
        # Complete the order with the logical clock at 2025-06-01 so the
        # completion calendar anchor sits 461 days before claim time.
        set_clock("2025-06-01T00:00:00Z")
        ctx = setup_completed_order(serial_number="GBX-2002", hours=1_200,
                                    rigging_bay_date="2025-07-20")
        assert ctx["order"]["completed_at_hours"] == 1_200

        # Unit accumulates 1800 service hours post-reman (covered on hours),
        # then the clock jumps 461 days past completion (expired on
        # calendar): the two bases diverge on identical claim data.
        api.record_service_hours(ctx["unit"]["id"], 3_000,
                                 intake_coordinator_headers)
        set_clock("2026-09-05T00:00:00Z")
        claim = make_claim(ctx["order"]["id"], ctx["customer"]["id"],
                           reported_hours=3_000,
                           claim_reason="output seal leak")
        assert claim["warranty_clock_start_hours"] == 1_200
        assert claim["hours_since_reman"] == 1_800  # <= 2000: hours covered
        assert claim["eligibility"] == "EXPIRED_CALENDAR"

    def test_eligibility_expired_hours_when_calendar_leg_covered(
            self, api, intake_coordinator_headers):
        """PRD §3.7: "The hours leg computes `hours_since_reman` as
        `reported_hours` minus `warranty_clock_start_hours`: covered when
        that figure is no greater than 2,000 hours — a claim at exactly 2,000
        hours is covered, one at 2,001 is not — and failed as
        `EXPIRED_HOURS` otherwise."

        Design: Difficulty/dual_variant_calc/warranty_hours_basis_vs_calendar_basis_on_claim
        """
        # Clock never advances: the calendar leg stays at 0 days, covered.
        ctx = setup_completed_order(serial_number="GBX-2003", hours=1_200,
                                    rigging_bay_date="2026-08-09")
        api.record_service_hours(ctx["unit"]["id"], 3_201,
                                 intake_coordinator_headers)
        claim = make_claim(ctx["order"]["id"], ctx["customer"]["id"],
                           reported_hours=3_201, claim_reason="bearing wear")
        assert claim["warranty_clock_start_hours"] == 1_200
        assert claim["hours_since_reman"] == 2_001  # > 2000: hours expired
        assert claim["eligibility"] == "EXPIRED_HOURS"


class TestHoursBoundary:
    def test_warranty_hours_boundary_2000_covered_2001_expired(
            self, api, intake_coordinator_headers):
        """PRD §3.7: "covered when that figure is no greater than 2,000
        hours — a claim at exactly 2,000 hours is covered, one at 2,001 is
        not — and failed as `EXPIRED_HOURS` otherwise."

        Design: Corner/calculations/warranty_hours_boundary_2000_covered_2001_expired
        """
        ctx1 = setup_completed_order(serial_number="GBX-W1",
                                     rigging_bay_date="2026-08-08")
        ctx2 = setup_completed_order(serial_number="GBX-W2",
                                     legal_name="Warr Co Two",
                                     rigging_bay_date="2026-08-09")
        api.record_service_hours(ctx1["unit"]["id"], 2_000,
                                 intake_coordinator_headers)
        api.record_service_hours(ctx2["unit"]["id"], 2_001,
                                 intake_coordinator_headers)

        covered = make_claim(ctx1["order"]["id"], ctx1["customer"]["id"],
                             reported_hours=2_000,
                             claim_reason="noise at boundary")
        assert covered["hours_since_reman"] == 2_000
        assert covered["eligibility"] == "COVERED"

        expired = make_claim(ctx2["order"]["id"], ctx2["customer"]["id"],
                             reported_hours=2_001,
                             claim_reason="noise past boundary")
        assert expired["hours_since_reman"] == 2_001
        assert expired["eligibility"] == "EXPIRED_HOURS"

    def test_claim_hours_regression_rejected(self, api,
                                             intake_coordinator_headers):
        """PRD §3.7: "supplying the unit's `reported_hours` — its cumulative
        service hours at claim time, which may not be below the unit's
        current `cumulative_service_hours` odometer (`ERR_HOURS_REGRESSION`)".

        Design: Corner/calculations/warranty_hours_regression_rejected
        """
        ctx = setup_completed_order(serial_number="GBX-RG",
                                    rigging_bay_date="2026-08-12")
        api.record_service_hours(ctx["unit"]["id"], 4_000,
                                 intake_coordinator_headers)
        resp = api.create_warranty_claim(
            ctx["order"]["id"],
            {"reported_hours": 3_500, "claim_reason": "odometer rolled back"},
            make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_HOURS_REGRESSION.value)


class TestReviewGate:
    def test_review_rejected_while_order_not_completed(
            self, api, quality_inspector_headers):
        """PRD §3.7: "A `QualityInspector` moves an `OPEN` claim to
        `UNDER_REVIEW` only once its linked order stands `COMPLETED`
        (`ERR_ORDER_NOT_COMPLETED`) — completion guaranteeing that a passing
        run-in established the oil baseline the review leans on".

        Design: Difficulty/cross_entity_state_dependency/warranty_review_requires_completed_order_then_baseline
        """
        ctx = setup_ready_to_ship_order(serial_number="GBX-B1")
        # Run-in PASSED (oil baseline exists) but the order is only
        # READY_TO_SHIP — not COMPLETED.
        claim = make_claim(ctx["order"]["id"], ctx["customer"]["id"],
                           reported_hours=50, claim_reason="premature noise")
        assert claim["status"] == "OPEN"

        resp = api.review_warranty_claim(claim["id"],
                                         quality_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_COMPLETED.value)
        assert get_claim(claim["id"])["status"] == "OPEN"

    def test_claim_filed_in_flight_resolves_after_completion(
            self, api, quality_inspector_headers, reman_engineer_headers,
            service_manager_headers, intake_coordinator_headers):
        """PRD §3.7: "The order need not be finished: a claim may be opened
        while the order is still in flight, in which case it sits `OPEN` with
        its `eligibility` unset (null) until resolution is possible. Once the
        linked order is `COMPLETED` — already so at filing time, or later
        upon completion — the claim's `warranty_clock_start_hours` is copied
        from the order's `completed_at_hours` snapshot and the dual-basis
        verdict is computed."

        Design: Difficulty/cross_entity_state_dependency/warranty_review_requires_completed_order_then_baseline
        """
        # Walk an approved order into IN_BUILD, then file the claim early.
        ctx = setup_approved_order(serial_number="GBX-B2")
        order_id = ctx["order"]["id"]
        api.start_build(order_id, reman_engineer_headers)

        claim = make_claim(order_id, ctx["customer"]["id"], reported_hours=0,
                           claim_reason="early rattle")
        assert claim["status"] == "OPEN"
        assert claim.get("eligibility") is None

        # Finish the pipeline: assembly, passing run-in, freight, completion.
        api.start_assembly(order_id, reman_engineer_headers)
        record_assembly(order_id)
        api.submit_assembly(order_id, quality_inspector_headers)
        record_run_in(order_id)
        shipment = add_shipment(order_id, direction="OUTBOUND", weight_kg=400,
                                rigging_bay_date="2026-08-18",
                                rigging_bay_hours=2)
        api.ship_order(order_id, service_manager_headers)
        api.deliver_shipment(shipment["id"], intake_coordinator_headers)
        order = validate_success(
            api.complete_order(order_id, service_manager_headers))
        assert order["status"] == "COMPLETED"

        data = validate_success(
            api.review_warranty_claim(claim["id"], quality_inspector_headers))
        assert data["status"] == "UNDER_REVIEW"
        resolved = get_claim(claim["id"])
        assert resolved["warranty_clock_start_hours"] == order["completed_at_hours"]
        assert resolved["hours_since_reman"] == 0
        assert resolved["eligibility"] == "COVERED"


class TestParallelDimensions:
    def test_commercial_review_leaves_physical_untouched(
            self, api, quality_inspector_headers):
        """PRD §3.1: "A gear unit carries two independent status dimensions
        on the same row. ... Neither dimension implies the other."
        PRD §3.7: "the move also flips the unit's `commercial_status` to
        `UNDER_WARRANTY_REVIEW`."

        Design: Difficulty/non_linear_state_machine/gear_unit_parallel_physical_and_commercial_dimensions
        """
        ctx = setup_completed_order(serial_number="GBX-P1",
                                    rigging_bay_date="2026-08-05")
        claim = make_claim(ctx["order"]["id"], ctx["customer"]["id"],
                           reported_hours=100, claim_reason="vibration")
        data = validate_success(
            api.review_warranty_claim(claim["id"], quality_inspector_headers))
        assert data["status"] == "UNDER_REVIEW"

        unit = get_unit(ctx["unit"]["id"])
        # Physical axis untouched by the commercial transition: completion
        # returned the unit to IN_SERVICE and it stays there.
        assert unit["physical_status"] == "IN_SERVICE"
        assert unit["commercial_status"] == "UNDER_WARRANTY_REVIEW"

    def test_commercial_deny_restores_standard_physical_untouched(
            self, api, service_manager_headers):
        """PRD §3.7: "denial (`UNDER_REVIEW → DENIED`) returns the unit's
        `commercial_status` to `STANDARD`."
        PRD §3.1: "A gear unit carries two independent status dimensions on
        the same row. ... Neither dimension implies the other."

        Design: Difficulty/non_linear_state_machine/gear_unit_parallel_physical_and_commercial_dimensions
        """
        ctx = setup_claim_under_review(reported_hours=100,
                                       serial_number="GBX-P2",
                                       rigging_bay_date="2026-08-06")
        data = validate_success(
            api.deny_warranty_claim(ctx["claim"]["id"],
                                    service_manager_headers))
        assert data["status"] == "DENIED"
        unit = get_unit(ctx["unit"]["id"])
        assert unit["commercial_status"] == "STANDARD"
        assert unit["physical_status"] == "IN_SERVICE"


class TestAdjudication:
    def test_expired_claim_cannot_be_approved(self, api,
                                              service_manager_headers,
                                              intake_coordinator_headers):
        """PRD §3.7: "approval (`UNDER_REVIEW → APPROVED`) is permitted only
        when `eligibility` is `COVERED`, any other verdict failing with
        `ERR_WARRANTY_EXPIRED`".

        Design: Corner/calculations/expired_warranty_claim_cannot_be_approved
        """
        ctx = setup_claim_under_review(reported_hours=3_000,
                                       advance_unit_hours=3_000,
                                       serial_number="GBX-EXP",
                                       rigging_bay_date="2026-08-11")
        assert ctx["claim"]["eligibility"] == "EXPIRED_HOURS"

        resp = api.approve_warranty_claim(ctx["claim"]["id"],
                                          service_manager_headers)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED.value)
        assert get_claim(ctx["claim"]["id"])["status"] == "UNDER_REVIEW"

    def test_inspector_cannot_approve_claim(self, api,
                                            quality_inspector_headers):
        """PRD §3.7: "Adjudication belongs to the `ServiceManager`: approval
        (`UNDER_REVIEW → APPROVED`) is permitted only when `eligibility` is
        `COVERED`, any other verdict failing with `ERR_WARRANTY_EXPIRED`, and
        it flags the unit `WARRANTY_FLAGGED` — which in turn blocks future
        check-in per §3.1; denial (`UNDER_REVIEW → DENIED`) returns the
        unit's `commercial_status` to `STANDARD`."
        PRD §2.1: "A request whose role is not permitted for the target
        endpoint — or that fails an entity-backed ownership check — is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/quality_inspector_cannot_approve_warranty
        """
        ctx = setup_claim_under_review(reported_hours=100,
                                       serial_number="GBX-SG",
                                       rigging_bay_date="2026-08-16")
        resp = api.approve_warranty_claim(ctx["claim"]["id"],
                                          quality_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        assert get_claim(ctx["claim"]["id"])["status"] == "UNDER_REVIEW"

    def test_flagged_unit_checkin_blocked(self, api,
                                          service_manager_headers,
                                          intake_coordinator_headers):
        """PRD §3.7: "approval (`UNDER_REVIEW → APPROVED`) ... flags the unit
        `WARRANTY_FLAGGED` — which in turn blocks future check-in per §3.1".
        PRD §3.1: "a unit whose `commercial_status` is `WARRANTY_FLAGGED` may
        not be checked in (`ERR_UNIT_FLAGGED`)".

        Design: Corner/errors/error_unit_flagged_blocks_checkin
        """
        ctx = setup_claim_under_review(reported_hours=100,
                                       serial_number="GBX-FL",
                                       rigging_bay_date="2026-08-13")
        data = validate_success(
            api.approve_warranty_claim(ctx["claim"]["id"],
                                       service_manager_headers))
        assert data["status"] == "APPROVED"
        unit = get_unit(ctx["unit"]["id"])
        assert unit["commercial_status"] == "WARRANTY_FLAGGED"
        assert unit["physical_status"] == "IN_SERVICE"

        resp = api.check_in_unit(ctx["unit"]["id"], intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_FLAGGED.value)
        unit = get_unit(ctx["unit"]["id"])
        assert unit["commercial_status"] == "WARRANTY_FLAGGED"
        assert unit["physical_status"] == "IN_SERVICE"
