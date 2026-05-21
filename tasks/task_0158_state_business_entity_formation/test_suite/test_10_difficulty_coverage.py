"""Difficulty-design coverage — at least TWO dedicated tests per
instance declared in SCAFFOLD_DIFFICULTY_DESIGN.yaml.

Each test cites the PRD prose that states the underlying rule. The
tag on each docstring's first comment line records which
(rule_id / instance.name) the test covers.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_boi_ownership,
    add_boi_ownership_payload,
    add_days,
    advance_clock_by_days,
    api_client,
    approve_foreign_qualification,
    assert_event_types_present,
    assert_events_in_chronological_order,
    assert_status,
    create_accepted_annual_report,
    create_and_activate_entity,
    create_annual_report_payload,
    create_beneficial_owner,
    create_boi_report,
    create_draft_annual_report,
    create_foreign_qualification_payload,
    create_pending_foreign_qualification,
    create_qualified_foreign,
    create_registered_agent,
    create_submitted_annual_report,
    create_tax_assessment,
    create_tax_assessment_payload,
    credit_deposit,
    delete_boi_ownership,
    file_boi_report,
    get_entity,
    get_tax_assessment,
    iso_now,
    list_compliance_events,
    make_filer_headers,
    pay_tax_assessment,
    patch_annual_report_payload,
    refund_tax_assessment,
    reject_annual_report_payload,
    server_now_year,
    setup_active_corp_with_shares,
    setup_active_entity_eligible_for_annual_report,
    setup_assessment_in_delinquent,
    setup_assessment_in_overdue,
    setup_entity_delinquent_for_60d,
    setup_initial_boi_filed,
    setup_owners_full_100,
    submit_annual_report,
    validate_error,
    validate_paginated,
    validate_success,
    ADMIN_DISSOLUTION_WAIT_DAYS,
    BOI_STALE_TIMER_DAYS,
    LATE_FEE_FLAT_CENTS,
    TAX_DELINQUENCY_DAYS,
)


# =============================================================================
# Rule 1 — Dual-variant calculations
# =============================================================================
class TestRule1DualVariantCalc:

    def test_franchise_tax_authorized_shares_method_12000_shares(self, api):
        # difficulty: dual_variant_calc/franchise_tax_authorized_vs_assumed_par
        """PRD §3.6: "when authorized shares exceed 10,000, the base
        tax is 25,000 cents plus 8,500 cents for each additional block
        of 10,000 shares, where the additional-share count beyond
        10,000 is divided by 10,000 and rounded up to the next whole
        block (so 10,001 shares already counts as one additional block,
        yielding 33,500 cents)."

        Claim: CORP{authorized_shares=12000} + AUTHORIZED_SHARES method
        → base_tax_cents=33500.
        """
        entity, _ = setup_active_corp_with_shares(
            authorized_shares=12000,
            total_gross_assets_cents=100_000_000,
            total_issued_shares=8000,
        )
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "AUTHORIZED_SHARES",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        a = validate_success(resp, expected_status=201)
        assert a["base_tax_cents"] == 33500

    def test_franchise_tax_assumed_par_value_method_yields_distinct_tax(
        self, api,
    ):
        # difficulty: dual_variant_calc/franchise_tax_authorized_vs_assumed_par
        """PRD §3.6: "the system computes an 'assumed par value per
        share' as total_gross_assets_cents divided by
        total_issued_shares (as an exact rational, no rounding yet),
        multiplies that ratio by authorized_shares to obtain an
        'assumed par value capital' figure (again, exact rational),
        divides that figure by 100,000,000 cents (a million dollars),
        rounds the quotient up to the next whole integer (call that
        count 'millions'), and produces a base tax of millions
        multiplied by 40,000 cents."

        Claim: CORP{authorized_shares=12000, total_gross_assets_cents=
        66_000_000, total_issued_shares=8000} + ASSUMED_PAR_VALUE →
        base_tax_cents=40000.

        Math: par/share = 66_000_000 / 8000 = 8250;
              apv_capital = 8250 * 12000 = 99_000_000;
              millions = ceil(99_000_000 / 100_000_000) = 1;
              tax = 1 * 40000 = 40000.

        Inputs are chosen so the chosen method (ASSUMED_PAR_VALUE=40000)
        is within the 50% sanity rail of the alternative
        (AUTHORIZED_SHARES=33500): 40000 / 33500 ≈ 1.19, well under
        the 1.5x rail required by PRD §3.6.
        """
        entity, _ = setup_active_corp_with_shares(
            authorized_shares=12000,
            total_gross_assets_cents=66_000_000,
            total_issued_shares=8000,
        )
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], server_now_year(), "ASSUMED_PAR_VALUE",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        a = validate_success(resp, expected_status=201)
        assert a["base_tax_cents"] == 40000, (
            f"Expected base_tax_cents=40000, got {a['base_tax_cents']}"
        )

    def test_exposure_score_provisional_uses_live_ownership_rows(
        self, api,
    ):
        # difficulty: dual_variant_calc/boi_exposure_provisional_vs_finalized
        """PRD §3.9: "The provisional variant sums, over every
        currently-active BOIOwnership row for the entity (those with
        terminated_at either null or strictly after the current clock
        instant), the ownership percentage expressed as a fraction
        (ownership_percent_basis_points divided by 10,000) multiplied
        by a per-owner risk weight derived from the owner's
        identifying_document_type ... The final sum is rounded to two
        decimal places using the round-half-up rule."

        Claim: provisional view sums the LIVE ownership rows using the
        currently-recorded risk weights. With one
        STATE_DRIVERS_LICENSE owner at 40% (weight 1) and one
        FOREIGN_PASSPORT owner at 60% (weight 3), provisional_score =
        0.40*1 + 0.60*3 = 2.20.
        """
        entity, _ = create_and_activate_entity()
        o1 = create_beneficial_owner(
            identifying_document_type="STATE_DRIVERS_LICENSE",
        )
        o2 = create_beneficial_owner(
            identifying_document_type="FOREIGN_PASSPORT",
        )
        add_boi_ownership(entity["id"], o1["id"], 4000)
        add_boi_ownership(entity["id"], o2["id"], 6000)
        resp = api.get_exposure_summary(
            entity["id"], make_filer_headers(entity["id"]),
            params={"view": "provisional"},
        )
        summary = validate_success(resp)
        # PRD §3.9: rounded to 2 decimal places with round-half-up.
        # The exact field name is not pinned by PRD; the summary is an
        # "object" containing the score. We accept either
        # provisional_score or score with view metadata.
        score = (summary.get("provisional_score")
                 or summary.get("score"))
        assert score is not None, (
            f"Exposure summary must carry a provisional score; got "
            f"{summary}"
        )
        assert abs(float(score) - 2.20) < 0.005, (
            f"provisional score must be 2.20, got {score}"
        )

    def test_exposure_score_finalized_uses_filed_snapshot(self, api):
        # difficulty: dual_variant_calc/boi_exposure_provisional_vs_finalized
        """PRD §3.9: "The finalized variant computes the same weighted
        sum, but over the snapshot of BOIOwnership rows that were
        active at the most recent BOIReport.filed_at whose status is
        either CURRENT or CORRECTED — that is, what the regulator
        currently sees on file."

        Claim: when the snapshot has not changed since the FILED point,
        finalized_score == provisional_score for that snapshot.
        Setup: same two owners at 40%/60% (weights 1 + 3), filed
        INITIAL → finalized_score = 2.20.
        """
        entity, _ = create_and_activate_entity()
        o1 = create_beneficial_owner(
            identifying_document_type="STATE_DRIVERS_LICENSE",
        )
        o2 = create_beneficial_owner(
            identifying_document_type="FOREIGN_PASSPORT",
        )
        add_boi_ownership(entity["id"], o1["id"], 4000)
        add_boi_ownership(entity["id"], o2["id"], 6000)
        rep = create_boi_report(entity["id"], "INITIAL")
        file_boi_report(rep["id"], entity["id"])
        resp = api.get_exposure_summary(
            entity["id"], make_filer_headers(entity["id"]),
            params={"view": "finalized"},
        )
        summary = validate_success(resp)
        score = (summary.get("finalized_score")
                 or summary.get("score"))
        assert score is not None
        assert abs(float(score) - 2.20) < 0.005


# =============================================================================
# Rule 2 — Combinatorial formula
# =============================================================================
class TestRule2CombinatorialFormula:

    def test_late_fee_per_line_rounding_with_three_inputs(self, api):
        # difficulty: combinatorial_formula/late_fee_three_input_threshold_with_per_line_rounding
        """PRD §3.6: "Multiply base_tax_cents by 0.015 (the constant
        MONTHLY_INTEREST_RATE, representing 1.5% per month) and round
        the product half-up to the nearest cent — this rounding is
        per-line, applied to the monthly amount before it is multiplied
        by the capped month count. Multiply that rounded monthly amount
        by the capped month count. Add the constant LATE_FEE_FLAT_CENTS
        of 20,000 cents (a flat 200-dollar penalty). The sum is
        late_fee_cents."

        Claim: an OVERDUE assessment's late_fee_cents follows
        per-line rounding: monthly = round_half_up(base*0.015), then
        monthly*months_late + 20000. For base=33500 the monthly is
        round_half_up(502.5)=503 cents.

        Observable: late_fee >= 20000 (the flat penalty) and equals
        20000 + 503*months_late where months_late >= 1 after the
        sweep flips to OVERDUE.
        """
        _entity, assessment = setup_assessment_in_overdue(
            authorized_shares=12000, days_past_due=5,
        )
        # Once OVERDUE, the late_fee must be at least 20000 + 503*1.
        assert assessment["status"] == "OVERDUE"
        assert assessment["late_fee_cents"] >= 20000 + 503, (
            f"Expected late_fee >= {20000 + 503} for OVERDUE base "
            f"33500; got {assessment['late_fee_cents']}"
        )
        # The fee must be exactly 20000 + 503*months_late for some
        # months_late in [1, 18]. Pull out the implied months count.
        late = assessment["late_fee_cents"]
        flat = 20000
        per_month = 503
        diff = late - flat
        assert diff >= 0 and diff % per_month == 0, (
            f"Late fee {late} doesn't fit 20000 + 503*N for any "
            f"integer N (per-line rounding rule)"
        )
        months = diff // per_month
        assert 1 <= months <= 18

    def test_total_due_pinned_evaluation_order_with_credit(self, api):
        # difficulty: combinatorial_formula/total_due_with_credit_pinned_evaluation_order
        """PRD §3.6: "PINNED EVALUATION ORDER: 1) Compute
        late_fee_cents from franchise_tax_late_fee FIRST (uses current
        status). 2) Compute pre_credit_due = base_tax_cents +
        late_fee_cents. 3) Compute credit_applied_cents = min(
        BusinessEntity.credit_balance_cents at time of pay,
        pre_credit_due). credit_balance_cents is sourced from the
        ENTITY's running balance, NOT recomputed here. 4) total_due_cents
        = pre_credit_due - credit_applied_cents. 5) On PAY: decrement
        BusinessEntity.credit_balance_cents by credit_applied_cents
        (atomic with status transition). Late_fee_cents is NOT
        recomputed after step 4."

        Wait — that prose is the SCAFFOLD's pinned-order language; the
        PRD reformulates it. Per PRD §3.6:

        "First, compute late_fee_cents from the late-fee rule using
        the current status and clock instant. Second, compute a
        pre-credit due figure as base_tax_cents plus late_fee_cents.
        Third, compute a credit_applied_cents figure as the smaller of
        the entity's current credit_balance_cents and the pre-credit
        due figure ... Fourth, set total_due_cents to the pre-credit
        due figure minus credit_applied_cents. Fifth — and only on a
        payment — atomically decrement the entity's
        credit_balance_cents by credit_applied_cents."

        Claim: with base=30000 (LLC FLAT) and credit_balance=10000, on
        pay total_due_cents == 30000 + 0 - 10000 = 20000 and the
        entity's credit_balance drops to 0.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        credit_deposit(entity["id"], 10000)
        # Current server year keeps due_date in the future → ASSESSED
        # with late_fee_cents=0 at pay time, satisfying the pinned-order
        # observable.
        assessment = create_tax_assessment(
            entity["id"], server_now_year(), "FLAT",
        )
        # Pay while still ASSESSED, so late_fee_cents=0.
        resp = api.pay_tax_assessment(
            assessment["id"], make_filer_headers(entity["id"]),
        )
        paid = validate_success(resp)
        assert_status(paid, "PAID")
        assert paid["base_tax_cents"] == 30000
        assert paid["late_fee_cents"] == 0
        assert paid["total_due_cents"] == 20000, (
            f"Expected total_due_cents=20000 (=30000+0-10000), "
            f"got {paid['total_due_cents']}"
        )
        ent = get_entity(entity["id"], make_filer_headers(entity["id"]))
        assert ent["credit_balance_cents"] == 0


# =============================================================================
# Rule 3 — Non-linear state-machine
# =============================================================================
class TestRule3NonLinearStateMachine:

    def test_annual_report_reject_revision_cycle(
        self, api, tax_officer_headers,
    ):
        # difficulty: non_linear_state_machine/annual_report_reject_to_draft_revision_cycle
        """PRD §3.5: "The lifecycle is DRAFT → SUBMITTED → ACCEPTED,
        with a revision loop: a REJECTED report cycles back to DRAFT
        and the cycle may repeat without bound."

        Claim: SUBMITTED → REJECTED → DRAFT → SUBMITTED → REJECTED.
        The REJECTED state vertex is revisited.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        sub = create_submitted_annual_report(entity["id"], report_year)
        # First reject.
        r1 = api.reject_annual_report(
            sub["id"],
            reject_annual_report_payload("missing principal_office_address"),
            tax_officer_headers,
        )
        r1 = validate_success(r1)
        assert_status(r1, "REJECTED")
        # PATCH back to DRAFT.
        patch_resp = api.patch_annual_report(
            sub["id"],
            patch_annual_report_payload(
                principal_office_address="123 Main",
            ),
            make_filer_headers(entity["id"]),
        )
        patched = validate_success(patch_resp)
        assert_status(patched, "DRAFT")
        # rejection_reason cleared.
        assert patched.get("rejection_reason") in (None, "")
        # Re-submit.
        sub2 = api.submit_annual_report(
            sub["id"], make_filer_headers(entity["id"]),
        )
        sub2 = validate_success(sub2)
        assert_status(sub2, "SUBMITTED")
        # Second reject — REJECTED state revisited.
        r2 = api.reject_annual_report(
            sub["id"],
            reject_annual_report_payload("needs officer count"),
            tax_officer_headers,
        )
        r2 = validate_success(r2)
        assert_status(r2, "REJECTED")

    def test_boi_report_current_stale_current_cycle(self, api):
        # difficulty: non_linear_state_machine/boi_report_current_stale_current_cycle
        """PRD §3.8: "the cycle CURRENT → STALE → CURRENT via timely
        update"

        Claim: a CURRENT BOIReport that ages out to STALE (after the
        ownership-change 30-day timer) is rescued by an UPDATE-typed
        BOIReport's filing, which transitions the new report to
        CURRENT and emits BOI_CORRECTED. The CURRENT vertex is
        revisited.
        """
        entity, _ = create_and_activate_entity()
        # First, get an INITIAL CURRENT report on file.
        rep, owners, ownerships = setup_initial_boi_filed(entity["id"])
        # Force an ownership change to start the stale-timer.
        delete_boi_ownership(entity["id"], ownerships[-1]["id"])
        # Re-add the same owner to keep sum at 10000 — that's a fresh
        # ownership row so total stays valid for the eventual UPDATE.
        same_owner = owners[-1]
        add_boi_ownership(entity["id"], same_owner["id"], 6000)
        # Age past 30 days so the original report goes STALE.
        advance_clock_by_days(BOI_STALE_TIMER_DAYS + 1)
        # Re-read entity — its compliance_status should drop.
        ent = get_entity(entity["id"], make_filer_headers(entity["id"]))
        assert ent["compliance_status"] == "NOT_IN_GOOD_STANDING", (
            f"After BOI goes stale, entity compliance must be "
            f"NOT_IN_GOOD_STANDING, got {ent['compliance_status']}"
        )
        # Now file an UPDATE BOIReport which rescues the prior STALE
        # back to CORRECTED and brings the new report to CURRENT.
        update_rep = create_boi_report(entity["id"], "UPDATE")
        updated = file_boi_report(update_rep["id"], entity["id"])
        assert_status(updated, "CURRENT")
        events = list_compliance_events(entity["id"])
        # PRD §3.8 says a BOI_CORRECTED event is emitted on the rescue.
        assert_event_types_present(events, ["BOI_STALE", "BOI_CORRECTED"])


# =============================================================================
# Rule 4 — Transitive cascade chains
# =============================================================================
class TestRule4TransitiveCascade:

    def test_tax_overdue_to_delinquent_to_admin_dissolve_to_foreign_revoked(
        self, api,
    ):
        # difficulty: transitive_cascade/tax_overdue_to_delinquent_to_admin_dissolved_depth3
        """PRD §3.10: "an ASSESSED → OVERDUE transition drives the
        entity from GOOD_STANDING to NOT_IN_GOOD_STANDING, an
        OVERDUE → DELINQUENT transition drives the entity from
        NOT_IN_GOOD_STANDING to DELINQUENT"
        PRD §3.11: "Its sole precondition is that the entity has been
        in compliance_status DELINQUENT for at least sixty days"
        PRD §3.11: "cascades every QUALIFIED foreign qualification to
        REVOKED (setting revoked_at on each)"

        Claim: the depth-4 chain holds. ASSESSED → OVERDUE
        (compliance: GOOD→NOT_IN), OVERDUE → DELINQUENT (compliance:
        NOT_IN→DELINQUENT), wait 60 days, admin-dissolve, qualified
        foreign cascade-transitions to REVOKED.
        """
        # Build a CORP with a QUALIFIED foreign while still in good
        # standing — qualifying requires GOOD_STANDING.
        from test_helpers import advance_clock_by_days
        entity, _ = create_and_activate_entity(
            entity_type="CORP", home_state="DE", authorized_shares=5000,
        )
        qual, _ = create_qualified_foreign(
            entity["id"], foreign_state="NY",
        )
        assert qual["status"] == "QUALIFIED"
        # Create an assessment and drive past due_date + 90 days.
        # Use server year so the assessment starts as ASSESSED rather
        # than being immediately past due, and ratchet forward
        # deterministically.
        assessment = create_tax_assessment(
            entity["id"], server_now_year(), "AUTHORIZED_SHARES",
        )
        advance_clock_by_days(5)
        a = get_tax_assessment(assessment["id"])
        ratchet = 0
        while a["status"] != "DELINQUENT" and ratchet < 24:
            advance_clock_by_days(30)
            ratchet += 1
            a = get_tax_assessment(assessment["id"])
        assert a["status"] == "DELINQUENT"
        ent = get_entity(entity["id"], make_filer_headers(entity["id"]))
        assert ent["compliance_status"] == "DELINQUENT"
        # Sit on DELINQUENT for the admin-dissolve wait.
        advance_clock_by_days(ADMIN_DISSOLUTION_WAIT_DAYS + 5)
        # Admin-dissolve.
        resp = api.administratively_dissolve_entity(
            entity["id"], TEST_USERS["compliance_officer_headers"],
        )
        dissolved = validate_success(resp)
        assert_status(dissolved, "ADMINISTRATIVELY_DISSOLVED",
                      field="formation_status")
        # Verify events include the expected chain.
        events = list_compliance_events(entity["id"])
        assert_event_types_present(
            events,
            ["TAX_OVERDUE", "TAX_DELINQUENT",
             "ADMIN_DISSOLVED", "FOREIGN_REVOKED"],
        )

    def test_boi_ownership_change_to_stale_drops_compliance(self, api):
        # difficulty: transitive_cascade/boi_ownership_change_to_stale_to_compliance_loss_depth3
        """PRD §3.8: "If a CURRENT BOI report is in place and a
        BOIOwnership row is added or terminated for the entity, the
        report becomes vulnerable to going STALE: thirty days after
        the ownership change, if no UPDATE or CORRECTION BOIReport has
        been filed in the interim, the system transitions the report
        CURRENT → STALE, sets stale_at to the current clock instant,
        drives the entity's compliance_status from GOOD_STANDING to
        NOT_IN_GOOD_STANDING, begins accruing penalty_cents per the
        BOI penalty rule"

        Claim: terminating a BOIOwnership row + advancing the clock by
        31 days drives the entity into NOT_IN_GOOD_STANDING and emits
        a BOI_STALE event.
        """
        entity, _ = create_and_activate_entity()
        _rep, _owners, ownerships = setup_initial_boi_filed(entity["id"])
        # Termination triggers the stale-timer.
        delete_boi_ownership(entity["id"], ownerships[0]["id"])
        advance_clock_by_days(BOI_STALE_TIMER_DAYS + 1)
        ent = get_entity(entity["id"], make_filer_headers(entity["id"]))
        assert ent["compliance_status"] == "NOT_IN_GOOD_STANDING"
        events = list_compliance_events(entity["id"])
        assert_event_types_present(events, ["BOI_STALE"])


# =============================================================================
# Rule 5 — Validation priority pair conflicts
# =============================================================================
class TestRule5PriorityPairConflict:

    def test_invalid_state_wins_over_segregation_on_accept(
        self, api,
    ):
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation
        """PRD §2.11: "ERR_INVALID_STATE (priority 6) takes precedence
        over ERR_ENTITY_NOT_ACTIVE (priority 7), which in turn takes
        precedence over segregation of duties (priority 8) and all
        business-safety/business-constraint checks below it."

        Claim: an ALREADY-ACCEPTED annual report accepted by a caller
        whose X-User-ID would also violate segregation-of-duties is
        rejected with ERR_INVALID_STATE (priority 6) — not
        ERR_SEGREGATION_OF_DUTIES (priority 8).
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        accepted = create_accepted_annual_report(entity["id"], report_year)
        # Re-accept by a caller whose X-User-ID equals the entity's id
        # (would normally trigger ERR_SEGREGATION_OF_DUTIES). The state
        # check (priority 6) must short-circuit first.
        from test_helpers import make_tax_officer_headers
        bad_headers = make_tax_officer_headers(entity["id"])
        resp = api.accept_annual_report(accepted["id"], bad_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_invalid_tax_method_wins_over_duplicate_tax_year(
        self, api,
    ):
        # difficulty: priority_pair_validation_conflict/business_fiscal_vs_business_constraint_tax_method
        """PRD §2.11: validation priority order:
        "(20) tax-method choice matches entity type ... (22) tax-year
        uniqueness."
        Priority 20 < 22; therefore the fiscal-method error wins over
        the constraint error.

        Claim: an LLC with an existing 2024 FLAT assessment, attempting
        a second 2024 assessment with calculation_method=
        AUTHORIZED_SHARES — both ERR_INVALID_TAX_METHOD (priority 20)
        and ERR_DUPLICATE_TAX_YEAR (priority 22) would apply.
        Priority 20 wins: error must be ERR_INVALID_TAX_METHOD.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        create_tax_assessment(entity["id"], 2024, "FLAT")
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "AUTHORIZED_SHARES",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TAX_METHOD.value)


# =============================================================================
# Rule 6 — Boundary precision
# =============================================================================
class TestRule6BoundaryPrecision:

    def test_authorized_shares_5000_exactly_yields_17500(self, api):
        # difficulty: boundary_precision_check/authorized_shares_tier_boundary_5000_vs_5001
        """PRD §3.6: "when authorized shares are at most 5,000, the
        base tax is 17,500 cents"

        Claim: authorized_shares=5000 (tier-1 upper boundary,
        inclusive) → base_tax_cents=17500.
        """
        entity, _ = setup_active_corp_with_shares(authorized_shares=5000)
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "AUTHORIZED_SHARES",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        a = validate_success(resp, expected_status=201)
        assert a["base_tax_cents"] == 17500

    def test_authorized_shares_5001_just_over_yields_25000(self, api):
        # difficulty: boundary_precision_check/authorized_shares_tier_boundary_5000_vs_5001
        """PRD §3.6: "when authorized shares are at most 10,000, the
        base tax is 25,000 cents"

        Claim: authorized_shares=5001 (just past tier-1 boundary) →
        base_tax_cents=25000.
        """
        entity, _ = setup_active_corp_with_shares(authorized_shares=5001)
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "AUTHORIZED_SHARES",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        a = validate_success(resp, expected_status=201)
        assert a["base_tax_cents"] == 25000

    def test_ownership_sum_9999_rejected(self, api):
        # difficulty: boundary_precision_check/ownership_sum_empty_vs_full_10000_bps
        """PRD §3.8: "the sum of active BOIOwnership.ownership_percent_
        basis_points rows for the entity ... must equal exactly 10,000
        at the moment of filing — a violation yields
        ERR_OWNERSHIP_NOT_100"

        Claim: sum=9999 (one bps short) → ERR_OWNERSHIP_NOT_100.
        """
        entity, _ = create_and_activate_entity()
        owner = create_beneficial_owner()
        add_boi_ownership(entity["id"], owner["id"], 9999)
        rep = create_boi_report(entity["id"], "INITIAL")
        resp = api.file_boi_report(
            rep["id"], make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_NOT_100.value)

    def test_ownership_sum_exactly_10000_accepted(self, api):
        # difficulty: boundary_precision_check/ownership_sum_empty_vs_full_10000_bps
        """PRD §3.8: "the sum of active BOIOwnership.ownership_percent_
        basis_points rows for the entity ... must equal exactly 10,000
        at the moment of filing"

        Claim: sum=10000 (exactly 100%) → file succeeds (status
        progresses to CURRENT).
        """
        entity, _ = create_and_activate_entity()
        _owners, _ = setup_owners_full_100(entity["id"])
        rep = create_boi_report(entity["id"], "INITIAL")
        resp = api.file_boi_report(
            rep["id"], make_filer_headers(entity["id"]),
        )
        filed = validate_success(resp)
        assert_status(filed, "CURRENT")


# =============================================================================
# Rule 7 — Cross-entity state dependency
# =============================================================================
class TestRule7CrossEntityStateDependency:

    def test_foreign_qualification_approve_requires_good_standing(
        self, api,
    ):
        # difficulty: cross_entity_state_dependency/foreign_qualification_requires_business_entity_good_standing
        """PRD §3.7: "Approval transitions PENDING → QUALIFIED and
        requires three concurrent conditions: the parent entity's
        compliance_status is GOOD_STANDING (not NOT_IN_GOOD_STANDING
        and not DELINQUENT)"

        Claim: a foreign qualification approval on a parent entity in
        NOT_IN_GOOD_STANDING (due to an OVERDUE tax assessment) →
        ERR_INVALID_STATE (the qualification row's preconditions are
        not satisfied).
        """
        # Set up an entity with an OVERDUE tax assessment (so the
        # parent is NOT_IN_GOOD_STANDING), then create a pending
        # qualification and attempt approve.
        entity, _assessment = setup_assessment_in_overdue(
            authorized_shares=5000, tax_year=2024, days_past_due=10,
        )
        # Create a pending qualification while the parent is NOT_IN.
        qual, _ = create_pending_foreign_qualification(
            entity["id"], "NY",
        )
        resp = api.approve_foreign_qualification(
            qual["id"], TEST_USERS["state_registrar_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_voluntary_dissolve_blocked_by_stale_boi(self, api):
        # difficulty: cross_entity_state_dependency/voluntary_dissolution_requires_no_active_dependents
        """PRD §3.11: "Voluntary dissolution is blocked when any of
        three dependencies is present: ... any BOIReport with status
        equal to STALE ... A blocking dependency yields
        ERR_HAS_DEPENDENCIES with HTTP 409."

        Claim: a STALE BOIReport blocks dissolve →
        ERR_HAS_DEPENDENCIES (independent entity pair from instance 1).
        """
        from test_helpers import setup_entity_with_stale_boi
        entity, _, _ = setup_entity_with_stale_boi()
        resp = api.dissolve_entity(
            entity["id"], make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HAS_DEPENDENCIES.value)


# =============================================================================
# Rule 8 — Resource temporal overlap
# =============================================================================
class TestRule8ResourceTemporalOverlap:

    def test_foreign_qualification_overlap_rejected(self, api):
        # difficulty: resource_temporal_overlap/foreign_qualification_unique_open_window_per_state_pair
        """PRD §3.7: "Only one non-terminal qualification (that is,
        with status neither WITHDRAWN nor REVOKED) may exist for a
        given (business_entity_id, foreign_state) pair at a time; a
        second attempt yields ERR_DUPLICATE_FOREIGN_QUALIFICATION"

        Claim: while a first PENDING qualification is open, a second
        creation for the same (entity, foreign_state) →
        ERR_DUPLICATE_FOREIGN_QUALIFICATION.
        """
        entity, _ = create_and_activate_entity(home_state="DE")
        agent_ny = create_registered_agent(service_state="NY")
        first = create_foreign_qualification_payload(
            entity["id"], "NY", agent_ny["id"], iso_now(),
        )
        validate_success(
            api.create_foreign_qualification(
                first, make_filer_headers(entity["id"]),
            ),
            expected_status=201,
        )
        second = create_foreign_qualification_payload(
            entity["id"], "NY", agent_ny["id"], iso_now(),
        )
        resp = api.create_foreign_qualification(
            second, make_filer_headers(entity["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_DUPLICATE_FOREIGN_QUALIFICATION.value,
        )

    def test_annual_report_year_window_unique(self, api):
        # difficulty: resource_temporal_overlap/annual_report_unique_year_window_per_entity
        """PRD §3.5: "the same report_year may not already be covered
        by a SUBMITTED or ACCEPTED annual report for that entity."

        Claim: a second AnnualReport for the same report_year, while a
        prior one is in SUBMITTED status, → ERR_DUPLICATE_ANNUAL_REPORT.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        create_submitted_annual_report(entity["id"], report_year)
        resp = api.create_annual_report(
            create_annual_report_payload(entity["id"], report_year),
            make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ANNUAL_REPORT.value)


# =============================================================================
# Rule 9 — Compensating invariant
# =============================================================================
class TestRule9CompensatingInvariant:

    def test_pay_refund_restores_credit_balance(self, api):
        # difficulty: compensating_invariant/tax_pay_refund_credit_balance_conserved
        """PRD §3.6: "the credit-balance conservation invariant: the
        global sum of every entity's credit_balance_cents plus every
        PAID assessment's credit_applied_cents is preserved across
        pay-refund cycles."
        PRD §3.6: "atomically restores the entity's
        credit_balance_cents by exactly the credit_applied_cents
        figure that was deducted at payment."

        Claim: deposit 50000 → pay (deducts 17500 for tier-1 CORP) →
        refund → balance returns to 50000.
        """
        entity, _ = setup_active_corp_with_shares(authorized_shares=5000)
        credit_deposit(entity["id"], 50000)
        # AUTHORIZED_SHARES @ 5000 → base = 17500. Use current server
        # year so the assessment stays ASSESSED (no late-fee accrual)
        # — the conservation invariant the test asserts is purely about
        # the credit-balance round-trip, not late-fee dynamics.
        assessment = create_tax_assessment(
            entity["id"], server_now_year(), "AUTHORIZED_SHARES",
        )
        pay_tax_assessment(assessment["id"], entity["id"])
        ent_after_pay = get_entity(
            entity["id"], make_filer_headers(entity["id"]),
        )
        assert ent_after_pay["credit_balance_cents"] == 50000 - 17500
        # Compensating refund.
        refund_tax_assessment(assessment["id"])
        ent_after_refund = get_entity(
            entity["id"], make_filer_headers(entity["id"]),
        )
        assert ent_after_refund["credit_balance_cents"] == 50000, (
            f"After refund, credit_balance must return to 50000, "
            f"got {ent_after_refund['credit_balance_cents']}"
        )

    def test_boi_ownership_add_then_delete_preserves_active_bps_sum(
        self, api,
    ):
        # difficulty: compensating_invariant/boi_ownership_add_terminate_bps_sum_conserved
        """PRD §3.8: "an integer in the closed interval from 0 to
        10,000, where 10,000 basis points equals 100%."
        PRD §3.8: "removing an ownership row is a soft-delete that
        stamps terminated_at to the current clock instant rather than
        removing the row."

        Claim: an active sum invariant holds across a forward/
        compensating action pair — adding a new BOIOwnership row
        (delta bps) increases the live sum, deleting the same row
        (soft-delete via terminated_at) returns it to baseline.
        Filing a fresh BOIReport at each phase exercises the active-
        sum rule, which is the public observable of "live sum".
        """
        entity, _ = create_and_activate_entity()
        o1 = create_beneficial_owner()
        # Baseline: 10000 bps.
        add_boi_ownership(entity["id"], o1["id"], 10000)
        # A BOIReport file should succeed at baseline.
        rep1 = create_boi_report(entity["id"], "INITIAL")
        filed1 = file_boi_report(rep1["id"], entity["id"])
        assert_status(filed1, "CURRENT")
        # Forward action: add a second active ownership row.
        o2 = create_beneficial_owner(
            identifying_document_type="STATE_DRIVERS_LICENSE",
        )
        extra = add_boi_ownership(entity["id"], o2["id"], 2500)
        # Sum is now 12500; a NEW file attempt must reject because the
        # sum != 10000. (We must create a CORRECTION-typed report so
        # the INITIAL allowed-once-only rule isn't tripped.)
        bad_rep = create_boi_report(entity["id"], "CORRECTION")
        bad_resp = api.file_boi_report(
            bad_rep["id"], make_filer_headers(entity["id"]),
        )
        validate_error(bad_resp, ApiErrorId.ERR_OWNERSHIP_NOT_100.value)
        # Compensating action: delete the extra row → sum back to 10000.
        delete_boi_ownership(entity["id"], extra["id"])
        # A new UPDATE-typed report should now file cleanly because the
        # active sum is 10000 again.
        good_rep = create_boi_report(entity["id"], "UPDATE")
        good_resp = api.file_boi_report(
            good_rep["id"], make_filer_headers(entity["id"]),
        )
        filed2 = validate_success(good_resp)
        assert_status(filed2, "CURRENT")
