"""Proration statements: dual day-count methods, pinned rounding, day attribution,
OCC, SoD chain, drift detection, and phase gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_approved_income_projection,
    add_approved_price_anchored_projection,
    assert_statement_netting_invariant,
    create_kicked_off_acquisition,
    generate_statement,
    get_acquisition,
    get_acquisition_version,
    get_success_data,
    make_underwriting_manager_headers,
    setup_diligence_complete,
    setup_diligence_complete_with_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

UM1 = TEST_USERS["underwriting_manager_headers"]
UM2 = make_underwriting_manager_headers("um-2")
UM3 = make_underwriting_manager_headers("um-3")


class TestProrationDayCountMethodsDiverge:
    def test_actual_365_vs_bankers_30_360_rent_lines(self, api):
        """PRD §3.8: "Under `ACTUAL_365` the daily rate is the lease's
        `contract_rent_cents` times twelve divided by 365, rounded half up, and
        the day counts are the real calendar day counts above. Under
        `BANKERS_30_360` the daily rate is `contract_rent_cents` divided by 30,
        rounded half up, the period is treated as a 30-day month, seller days
        equal the closing day-of-month minus one, and buyer days equal 30 minus
        the closing day-of-month plus one; identical inputs therefore produce
        different amounts under the two methods. The rent line amount is the
        daily rate times buyer days."

        Design: Difficulty/dual_variant_calc/proration_day_count_methods_diverge
        """
        ctx = setup_diligence_complete()
        acq_id = ctx["acq"]["id"]
        add_approved_price_anchored_projection(acq_id)

        stmt_a = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")
        stmt_b = generate_statement(acq_id, "DRAFT_CLOSING", "BANKERS_30_360")

        lines_a, _ = validate_paginated(api.list_statement_lines(stmt_a["id"], UM1))
        lines_b, _ = validate_paginated(api.list_statement_lines(stmt_b["id"], UM1))
        rent_a = next(l for l in lines_a if l["line_type"] == "RENT")
        rent_b = next(l for l in lines_b if l["line_type"] == "RENT")
        tax_a = next(l for l in lines_a if l["line_type"] == "TAX")
        tax_b = next(l for l in lines_b if l["line_type"] == "TAX")

        assert rent_a["amount_cents"] == 93_708, (
            "ACTUAL_365: daily 4932 x 19 buyer days (Sep 12..30 inclusive)"
        )
        assert rent_b["amount_cents"] == 95_000, (
            "BANKERS_30_360: daily 5000 x 19 buyer days (30 - 12 + 1)"
        )
        assert rent_b["amount_cents"] - rent_a["amount_cents"] == 1_292
        assert tax_a["amount_cents"] == 1_391_781
        assert tax_b["amount_cents"] == 1_391_781, (
            "the TAX line is identical under both day-count methods"
        )

    def test_variants_diverge_by_exactly_1292_on_identical_data(self, api):
        """PRD §3.8: "Rounding order is pinned: each daily rate is rounded half
        up to integer cents first, then multiplied by whole days exactly, and
        statement totals are exact integer sums of the per-line rounded
        amounts. Sum-then-round is forbidden."
        PRD §3.8: "Day attribution follows the closing convention: the seller
        is responsible through the day before `closing_date`, and the buyer
        owns the closing day itself."

        Design: Difficulty/dual_variant_calc/proration_day_count_methods_diverge
        """
        ctx = setup_diligence_complete()
        acq_id = ctx["acq"]["id"]
        add_approved_price_anchored_projection(acq_id)

        stmt_a = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")
        stmt_b = generate_statement(acq_id, "DRAFT_CLOSING", "BANKERS_30_360")
        rent_a = next(l for l in validate_paginated(
            api.list_statement_lines(stmt_a["id"], UM1))[0]
            if l["line_type"] == "RENT")
        rent_b = next(l for l in validate_paginated(
            api.list_statement_lines(stmt_b["id"], UM1))[0]
            if l["line_type"] == "RENT")
        # daily 4932 (ACTUAL_365) vs 5000 (BANKERS_30_360) over the same 19 days
        assert (95_000 - 93_708) == 1_292
        assert rent_a["amount_cents"] == 93_708
        assert rent_b["amount_cents"] == 95_000


class TestProrationRoundingOrderPinned:
    def test_daily_rate_rounded_before_day_multiplication(self, api):
        """PRD §3.8: "Rounding order is pinned: each daily rate is rounded half
        up to integer cents first, then multiplied by whole days exactly, and
        statement totals are exact integer sums of the per-line rounded
        amounts. Sum-then-round is forbidden."

        Design: Difficulty/combinatorial_formula/proration_rounding_order_pinned_mode_b
        """
        # Rent 75005: pinned order gives daily 2466 x 19 = 46854; the forbidden
        # sum-then-round order would give 46852 — a 2-cent discriminator.
        ctx = setup_diligence_complete_with_lease(
            contract_rent_cents=75_005, market_rent_cents=80_000,
            deposit_amount_cents=100_000,
            stated_deposit_cents=102_060)
        acq_id = ctx["acq"]["id"]
        add_approved_price_anchored_projection(acq_id)

        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")
        lines, _ = validate_paginated(api.list_statement_lines(stmt["id"], UM1))
        rent = next(l for l in lines if l["line_type"] == "RENT")
        tax = next(l for l in lines if l["line_type"] == "TAX")
        assert rent["amount_cents"] == 46_854, (
            "daily 2466 first, then x 19 days; not the forbidden 46852"
        )
        assert rent["amount_cents"] != 46_852
        assert tax["amount_cents"] == 1_391_781

        stmt_now = get_success_data(api.get_proration_statement(stmt["id"], UM1))
        assert stmt_now["total_buyer_credits_cents"] == 46_854 + 1_391_781
        assert stmt_now["net_amount_cents"] == 46_854 + 1_391_781
        assert_statement_netting_invariant(stmt_now)

    def test_statement_totals_are_exact_integer_sums_of_rounded_lines(self, api):
        """PRD §3.8: "Every statement carries `total_buyer_credits_cents` as
        the sum of `amount_cents` over its lines whose `direction` is
        `CREDIT_BUYER`, `total_seller_credits_cents` as the same sum over
        `CREDIT_SELLER` lines, and `net_amount_cents` as buyer credits minus
        seller credits, so a negative net means the buyer owes the seller."
        PRD §3.8: "Rounding order is pinned: each daily rate is rounded half up
        to integer cents first, then multiplied by whole days exactly, and
        statement totals are exact integer sums of the per-line rounded
        amounts. Sum-then-round is forbidden."

        Design: Difficulty/combinatorial_formula/proration_rounding_order_pinned_mode_b
        """
        ctx = setup_diligence_complete_with_lease(
            contract_rent_cents=75_005, market_rent_cents=80_000,
            deposit_amount_cents=100_000,
            stated_deposit_cents=102_060)
        acq_id = ctx["acq"]["id"]
        add_approved_price_anchored_projection(acq_id)
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")

        lines, _ = validate_paginated(api.list_statement_lines(stmt["id"], UM1))
        line_sum = sum(l["amount_cents"] for l in lines)
        stmt_now = get_success_data(api.get_proration_statement(stmt["id"], UM1))
        assert stmt_now["total_buyer_credits_cents"] == line_sum == 1_438_635
        assert stmt_now["net_amount_cents"] == 1_438_635


class TestClosingDayAttributionBoundary:
    def test_closing_on_period_first_day_gives_buyer_all_days(self, api):
        """PRD §3.8: "Day attribution follows the closing convention: the
        seller is responsible through the day before `closing_date`, and the
        buyer owns the closing day itself. Seller days count the calendar days
        from the period start through the day before closing; buyer days count
        from the closing date through the period end, closing day included."

        Design: Difficulty/boundary_precision_check/closing_day_attribution_boundary
        """
        # Closing 2026-09-01: the buyer owns all 30 September days (seller 0).
        ctx = setup_diligence_complete_with_lease(
            closing_date="2026-09-01T00:00:00Z",
            diligence_deadline="2026-08-20T00:00:00Z",
            stated_deposit_cents=153_000)
        acq_id = ctx["acq"]["id"]
        add_approved_price_anchored_projection(acq_id)
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")

        lines, _ = validate_paginated(api.list_statement_lines(stmt["id"], UM1))
        rent = next(l for l in lines if l["line_type"] == "RENT")
        tax = next(l for l in lines if l["line_type"] == "TAX")
        assert rent["amount_cents"] == 147_960, (
            "daily 4932 x 30 buyer days: Sep 1..30, closing day owned by the buyer"
        )
        assert rent["amount_cents"] != 143_028, (
            "143028 (4932 x 29) is the off-by-one that hands closing day to the seller"
        )
        assert tax["amount_cents"] == 1_331_507, (
            "round_half_up(2000000 x 243 / 365): seller days Jan 1 .. Aug 31"
        )

    def test_seller_days_exclude_the_closing_day(self, api):
        """PRD §3.8: "Next comes a single tax line of type `TAX` and direction
        `CREDIT_BUYER`, which requires an approved tax reassessment projection
        to exist and is the projected `projected_annual_tax_cents` multiplied
        by the seller days year-to-date — calendar days from January 1 of the
        closing year through the day before closing — divided by 365, rounded
        half up."

        Design: Difficulty/boundary_precision_check/closing_day_attribution_boundary
        """
        ctx = setup_diligence_complete_with_lease(
            closing_date="2026-09-01T00:00:00Z",
            diligence_deadline="2026-08-20T00:00:00Z",
            stated_deposit_cents=153_000)
        acq_id = ctx["acq"]["id"]
        add_approved_price_anchored_projection(acq_id)
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")
        lines, _ = validate_paginated(api.list_statement_lines(stmt["id"], UM1))
        tax = next(l for l in lines if l["line_type"] == "TAX")
        # Seller YTD through Aug 31 = 243 days; the closing day is excluded.
        assert tax["amount_cents"] == 1_331_507
        assert tax["direction"] == "CREDIT_BUYER"


class TestStatementGenerationGates:
    def test_statement_generation_requires_approved_tax_projection(self, api):
        """PRD §3.8: "Next comes a single tax line of type `TAX` and direction
        `CREDIT_BUYER`, which requires an approved tax reassessment projection
        to exist..."
        PRD §3.8: "Approval moves `REVIEWED` to `APPROVED` and enforces three
        checks: ... and an approved tax reassessment projection must exist for
        the acquisition (else `ERR_TAX_PROJECTION_NOT_APPROVED`)."
        PRD §5: `ERR_TAX_PROJECTION_NOT_APPROVED` is HTTP 409.

        Design: Difficulty/cross_entity_state_dependency/statement_generation_requires_approved_tax_projection
        """
        ctx = setup_diligence_complete()
        acq_id = ctx["acq"]["id"]

        resp = api.generate_proration_statement(
            acq_id,
            {"statement_type": "DRAFT_CLOSING", "day_count_method": "ACTUAL_365",
             "expected_acquisition_version": get_acquisition_version(acq_id)},
            UM1)
        validate_error(resp, ApiErrorId.ERR_TAX_PROJECTION_NOT_APPROVED, 409)

        add_approved_price_anchored_projection(acq_id)
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")
        assert stmt["status"] == "DRAFT"
        lines, _ = validate_paginated(api.list_statement_lines(stmt["id"], UM1))
        tax = next(l for l in lines if l["line_type"] == "TAX")
        assert tax["amount_cents"] == 1_391_781

    def test_failed_generate_does_not_consume_the_occ_version(self, api):
        """PRD §2.6: "Generating a proration statement likewise must carry
        `expected_acquisition_version` matching the acquisition's current
        `version`, because generation supersedes the approved statement of the
        preceding type and mutates acquisition fields; a mismatch is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.8: "Next comes a single tax line ... which requires an approved
        tax reassessment projection to exist..."

        Design: Difficulty/cross_entity_state_dependency/statement_generation_requires_approved_tax_projection
        """
        ctx = setup_diligence_complete()
        acq_id = ctx["acq"]["id"]
        version_before = get_acquisition_version(acq_id)

        resp = api.generate_proration_statement(
            acq_id,
            {"statement_type": "DRAFT_CLOSING", "day_count_method": "ACTUAL_365",
             "expected_acquisition_version": version_before},
            UM1)
        validate_error(resp, ApiErrorId.ERR_TAX_PROJECTION_NOT_APPROVED, 409)
        assert get_acquisition_version(acq_id) == version_before, (
            "a rejected generate must not mutate the acquisition"
        )

        # The projection create accepts the same version the failed generate used.
        proj = get_success_data(api.create_tax_projection(
            acq_id,
            {"method": "PURCHASE_PRICE_ANCHORED",
             "expected_acquisition_version": version_before},
            TEST_USERS["analyst_headers"]), 201)
        get_success_data(api.compute_tax_projection(proj["id"],
                                                    TEST_USERS["analyst_headers"]))
        get_success_data(api.approve_tax_projection(proj["id"], UM1))
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")
        assert stmt["status"] == "DRAFT"


class TestStatementSendBackLoop:
    def test_statement_send_back_revision_loop(self, api):
        """PRD §3.8: "Submitting for review moves `DRAFT` to `REVIEWED`,
        requires the caller to differ from `created_by_user_id` (else
        `ERR_SOD_VIOLATION`), and stamps `reviewed_by_user_id`. Sending back
        returns `REVIEWED` to `DRAFT` with an optional `reason` and clears
        `reviewed_by_user_id`."

        Design: Corner/state_machines/statement_send_back_revision_loop
        """
        ctx = setup_diligence_complete()
        acq_id = ctx["acq"]["id"]
        add_approved_price_anchored_projection(acq_id)
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")

        reviewed = validate_success(api.submit_statement_review(stmt["id"], UM2))
        assert reviewed["status"] == "REVIEWED"
        assert reviewed["reviewed_by_user_id"] == "um-2"

        back = validate_success(api.send_back_statement(
            stmt["id"], UM2, reason="fix deposit line"))
        assert back["status"] == "DRAFT"
        after = get_success_data(api.get_proration_statement(stmt["id"], UM1))
        assert after.get("reviewed_by_user_id") is None, (
            "send-back clears reviewed_by_user_id"
        )

        re_reviewed = validate_success(api.submit_statement_review(stmt["id"], UM3))
        assert re_reviewed["status"] == "REVIEWED"
        assert re_reviewed["reviewed_by_user_id"] == "um-3", (
            "the revision loop is repeatable by any non-creator"
        )


class TestStatementSodChain:
    def test_statement_sod_chain(self, api):
        """PRD §2.8: "A proration statement's reviewer must differ from its
        `created_by_user_id`, and its approver must differ from both
        `created_by_user_id` and `reviewed_by_user_id`. ... Each breach is
        rejected with `ERR_SOD_VIOLATION` (HTTP 409)."

        Design: Corner/validations/statement_sod_chain
        """
        ctx = setup_diligence_complete()
        acq_id = ctx["acq"]["id"]
        add_approved_price_anchored_projection(acq_id)
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")

        # Creator um-1 cannot submit for review.
        resp = api.submit_statement_review(stmt["id"], UM1)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 409)

        reviewed = get_success_data(api.submit_statement_review(stmt["id"], UM2))
        assert reviewed["status"] == "REVIEWED"

        # Reviewer um-2 cannot approve.
        resp2 = api.approve_statement(stmt["id"], UM2)
        validate_error(resp2, ApiErrorId.ERR_SOD_VIOLATION, 409)

        approved = validate_success(api.approve_statement(stmt["id"], UM3))
        assert approved["status"] == "APPROVED"


class TestStatementDriftDetection:
    def test_statement_approve_detects_snapshot_drift(self, api):
        """PRD §3.8: "Approval moves `REVIEWED` to `APPROVED` and enforces
        three checks: ... a snapshot-drift check recomputes every generated
        line from live data with the pinned formulas and rejects any mismatch
        with `ERR_STATEMENT_DRIFT` — this is where statements referencing a
        since-superseded tax projection surface; ..."
        PRD §3.6: "A projection leaves `APPROVED` only by supersession — a new
        projection created under the same acquisition, or another projection
        approved — and when an approved projection is superseded, any proration
        statement referencing it drifts: its tax line no longer matches the
        currently approved projection and will fail the approve-time drift
        check described in §3.8 until regenerated."

        Design: Corner/validations/statement_approve_detects_snapshot_drift
        """
        ctx = setup_diligence_complete()
        acq_id = ctx["acq"]["id"]
        proj1 = add_approved_price_anchored_projection(acq_id)
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")
        get_success_data(api.submit_statement_review(stmt["id"], UM2))

        # A second projection supersedes the first; the stored TAX line
        # (1391781) no longer matches live recomputation (2087671).
        proj2 = add_approved_income_projection(acq_id)
        p1_now = get_success_data(api.get_tax_projection(proj1["id"], UM1))
        assert p1_now["status"] == "SUPERSEDED"
        assert proj2["status"] == "APPROVED"

        resp = api.approve_statement(stmt["id"], UM3)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_DRIFT, 409)
        after = get_success_data(api.get_proration_statement(stmt["id"], UM1))
        assert after["status"] == "REVIEWED", "a failed approve must not mutate"


class TestStatementPhaseGate:
    def test_statement_type_phase_gate(self, api):
        """PRD §3.8: "Statement type is gated by acquisition phase: a
        `DRAFT_CLOSING` statement may be generated only while the acquisition
        is `DILIGENCE_COMPLETE` or `PRE_CLOSING`, a `FINAL_CLOSING` only while
        `PRE_CLOSING`, and a `POST_CLOSING_TRUEUP` only while `CLOSED`; any
        other pairing is rejected with
        `ERR_STATEMENT_TYPE_NOT_ALLOWED_FOR_PHASE`."

        Design: Corner/validations/statement_type_phase_gate
        """
        acq = create_kicked_off_acquisition(property_name="Phase Gate")
        resp = api.generate_proration_statement(
            acq["id"],
            {"statement_type": "FINAL_CLOSING", "day_count_method": "ACTUAL_365",
             "expected_acquisition_version": get_acquisition_version(acq["id"])},
            UM1)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_TYPE_NOT_ALLOWED_FOR_PHASE, 409)


class TestAdvanceGate:
    def test_advance_without_approved_draft_statement_rejected(self, api):
        """PRD §3.1: "Advancing to `PRE_CLOSING` requires that a `DRAFT_CLOSING`
        proration statement already exist in `APPROVED` status (else
        `ERR_NO_APPROVED_DRAFT_STATEMENT`)."

        Design: Corner/validations/advance_without_approved_draft_statement_rejected
        """
        ctx = setup_diligence_complete(property_name="NoDraft")
        resp = api.advance_to_pre_closing(ctx["acq"]["id"], UM1)
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_DRAFT_STATEMENT, 409)
        assert get_acquisition(ctx["acq"]["id"])["status"] == "DILIGENCE_COMPLETE"


class TestApproveStateBeatsFiscalDrift:
    def test_approve_draft_statement_with_drift_state_beats_fiscal(self, api):
        """PRD §2.4: "Because earlier checks run before later ones, a request
        that would fail at two levels surfaces the earlier error — for example,
        an approve issued by the statement's own creator reports
        `ERR_SOD_VIOLATION` even if the statement's generated lines would also
        drift."
        PRD §2.4: "then state-machine legality (the 409 state family including
        `ERR_INVALID_STATE_TRANSITION`, the acquisition phase gates,
        `ERR_STATEMENT_NOT_REVIEWED`, ...)"
        PRD §3.8: "An approve attempted on a statement not in `REVIEWED` is
        rejected with `ERR_STATEMENT_NOT_REVIEWED`."

        Design: Difficulty/priority_pair_validation_conflict/approve_draft_statement_with_drift_state_beats_fiscal
        """
        ctx = setup_diligence_complete(property_name="Priority One")
        acq_id = ctx["acq"]["id"]
        proj1 = add_approved_price_anchored_projection(acq_id)
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")
        # Never submitted for review; then the projection is superseded so the
        # stored TAX line (1391781) is stale against live recompute (2087671).
        proj2 = add_approved_income_projection(acq_id)
        assert get_success_data(api.get_tax_projection(proj1["id"], UM1))["status"] == "SUPERSEDED"
        assert proj2["status"] == "APPROVED"

        resp = api.approve_statement(stmt["id"], UM2)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_REVIEWED, 409)

    def test_drift_never_reports_when_state_gate_fails(self, api):
        """PRD §2.4: "then state-machine legality (the 409 state family
        including `ERR_INVALID_STATE_TRANSITION`, the acquisition phase gates,
        `ERR_STATEMENT_NOT_REVIEWED`, `ERR_STATEMENT_NOT_SETTLABLE`,
        `ERR_LEASE_NOT_AUDITED`, and
        `ERR_STATEMENT_TYPE_NOT_ALLOWED_FOR_PHASE`), then
        optimistic-concurrency staleness (`ERR_STALE_VERSION`), then
        referential and segregation-of-duties checks ... and finally fiscal
        rechecks (`ERR_STATEMENT_DRIFT`, `ERR_ADJUSTMENT_EXCEEDS_CLAIMABLE`,
        `ERR_DEPOSIT_VARIANCE_UNRESOLVED`)."
        PRD §3.6: "A projection leaves `APPROVED` only by supersession — a new
        projection created under the same acquisition, or another projection
        approved..."

        Design: Difficulty/priority_pair_validation_conflict/approve_draft_statement_with_drift_state_beats_fiscal
        """
        ctx = setup_diligence_complete(property_name="Priority One B")
        acq_id = ctx["acq"]["id"]
        add_approved_price_anchored_projection(acq_id)
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")
        add_approved_income_projection(acq_id)  # supersedes; statement drifts

        resp = api.approve_statement(stmt["id"], UM2)
        err = validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_REVIEWED, 409)
        assert err["error_id"] != "ERR_STATEMENT_DRIFT", (
            "state (not REVIEWED) precedes the fiscal drift check"
        )
        after = get_success_data(api.get_proration_statement(stmt["id"], UM1))
        assert after["status"] == "DRAFT"


class TestStatementManualLineReversalConservesNet:
    def _scenario(self, api):
        """DRAFT_CLOSING statement carrying RENT 93708 + TAX 1391781 buyer,
        PREPAID 1084930 + 657600 seller, PAYROLL 100000 buyer (deposit not yet
        queued, so no DEPOSIT_TRANSFER line)."""
        from test_helpers import (
            add_approved_employee_decision,
            add_assumed_low_risk_policy,
            add_assumed_service_contract,
            setup_verified_unit,
            complete_diligence,
        )
        ctx = setup_verified_unit(property_name="Invariant One")
        acq_id = ctx["acq"]["id"]
        add_assumed_service_contract(
            acq_id, prepaid_through_date="2026-12-31T00:00:00Z")
        add_assumed_low_risk_policy(acq_id)
        add_approved_employee_decision(
            acq_id, employee_ref="emp-2", decision="RETAIN",
            notice_date="2026-08-10T00:00:00Z",
            effective_date="2026-08-25T00:00:00Z")
        complete_diligence(acq_id)
        add_approved_price_anchored_projection(acq_id)
        stmt = generate_statement(acq_id, "DRAFT_CLOSING", "ACTUAL_365")
        return acq_id, stmt

    def test_statement_manual_line_reversal_conserves_net(self, api):
        """PRD §3.8: "Every statement carries `total_buyer_credits_cents` as
        the sum of `amount_cents` over its lines whose `direction` is
        `CREDIT_BUYER`, `total_seller_credits_cents` as the same sum over
        `CREDIT_SELLER` lines, and `net_amount_cents` as buyer credits minus
        seller credits, so a negative net means the buyer owes the seller."
        PRD §3.8: "While a statement is `DRAFT`, an `UnderwritingManager` may
        append a manual line by supplying `expected_statement_version` per §2.6
        together with the `line_type`, `direction`, `amount_cents`, and an
        optional free-text `memo`; the append recomputes the statement's totals
        and increments the statement's `version` by one."

        Design: Difficulty/compensating_invariant/statement_manual_line_reversal_conserves_net
        """
        from test_helpers import add_statement_line_payload
        acq_id, stmt = self._scenario(api)
        # Baseline totals: buyer 93708 + 1391781 + 100000; seller 1084930 + 657600.
        assert stmt["total_buyer_credits_cents"] == 1_585_489
        assert stmt["total_seller_credits_cents"] == 1_742_530
        assert stmt["net_amount_cents"] == -157_041
        sv0 = stmt["version"]

        get_success_data(api.add_statement_line(
            stmt["id"],
            add_statement_line_payload(sv0, direction="CREDIT_BUYER",
                                       amount_cents=50_000, memo="escrow pad"),
            UM1), 201)
        mid = get_success_data(api.get_proration_statement(stmt["id"], UM1))
        assert mid["version"] == sv0 + 1, "each append bumps the version by 1"
        assert mid["total_buyer_credits_cents"] == 1_635_489
        assert mid["net_amount_cents"] == -107_041

        get_success_data(api.add_statement_line(
            stmt["id"],
            add_statement_line_payload(mid["version"], direction="CREDIT_SELLER",
                                       amount_cents=50_000, memo="pad reversal"),
            UM1), 201)
        end = get_success_data(api.get_proration_statement(stmt["id"], UM1))
        assert end["total_buyer_credits_cents"] == 1_635_489
        assert end["total_seller_credits_cents"] == 1_792_530
        assert end["net_amount_cents"] == -157_041, (
            "forward + reversal conserves net_amount_cents exactly"
        )

    def test_manual_line_pair_returns_net_to_baseline(self, api):
        """PRD §3.8: "Every statement carries `total_buyer_credits_cents` as
        the sum of `amount_cents` over its lines whose `direction` is
        `CREDIT_BUYER`, `total_seller_credits_cents` as the same sum over
        `CREDIT_SELLER` lines, and `net_amount_cents` as buyer credits minus
        seller credits, so a negative net means the buyer owes the seller."
        PRD §2.6: "Appending a manual line to a proration statement must carry
        `expected_statement_version` equal to the statement's current
        `version`, since the append recomputes the statement's totals; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Difficulty/compensating_invariant/statement_manual_line_reversal_conserves_net
        """
        from test_helpers import add_statement_line_payload
        acq_id, stmt = self._scenario(api)
        baseline_net = stmt["net_amount_cents"]
        baseline_version = stmt["version"]

        get_success_data(api.add_statement_line(
            stmt["id"],
            add_statement_line_payload(baseline_version, direction="CREDIT_BUYER",
                                       amount_cents=50_000, memo="escrow pad"),
            UM1), 201)
        v1 = get_success_data(api.get_proration_statement(stmt["id"], UM1))["version"]
        assert v1 == baseline_version + 1

        get_success_data(api.add_statement_line(
            stmt["id"],
            add_statement_line_payload(v1, direction="CREDIT_SELLER",
                                       amount_cents=50_000, memo="pad reversal"),
            UM1), 201)
        end = get_success_data(api.get_proration_statement(stmt["id"], UM1))
        assert end["version"] == baseline_version + 2
        assert end["net_amount_cents"] == baseline_net, (
            "net(forward + reversal) == net(baseline): no drift"
        )
