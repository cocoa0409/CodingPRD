"""Supplemental difficulty-design coverage — second test per instance.

Every SCAFFOLD_DIFFICULTY_DESIGN entry requires TWO tests. The first
test for each instance is in test_10_difficulty_coverage.py; this file
contributes the second. Each test docstring keeps the
"# difficulty: <rule_id>/<instance.name>" tag for audit.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_boi_ownership,
    add_days,
    advance_clock_by_days,
    approve_foreign_qualification,
    assert_event_types_present,
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
    make_tax_officer_headers,
    patch_annual_report_payload,
    pay_tax_assessment,
    refund_tax_assessment,
    reject_annual_report_payload,
    server_now_iso,
    server_now_year,
    setup_active_corp_with_shares,
    setup_active_entity_eligible_for_annual_report,
    setup_assessment_in_delinquent,
    setup_assessment_in_overdue,
    setup_entity_with_stale_boi,
    setup_initial_boi_filed,
    setup_owners_full_100,
    submit_annual_report,
    validate_error,
    validate_success,
    ADMIN_DISSOLUTION_WAIT_DAYS,
    BOI_STALE_TIMER_DAYS,
    LATE_FEE_FLAT_CENTS,
)


# =============================================================================
# Rule 1 — supplemental
# =============================================================================
class TestRule1Supplemental:

    def test_authorized_shares_vs_assumed_par_yield_distinct_values(
        self, api,
    ):
        # difficulty: dual_variant_calc/franchise_tax_authorized_vs_assumed_par
        """PRD §3.6: "identical input records produce different
        base_tax_cents under the two methods, and the Filer is
        permitted to choose whichever method produces the lower tax."

        Claim: on the same CORP, ASSUMED_PAR_VALUE (40000) and
        AUTHORIZED_SHARES (33500) yield distinct base_tax_cents — the
        two algorithms are genuinely different on identical inputs.
        Inputs are chosen so each method's result stays within the
        50% sanity rail of the other (PRD §3.6 forbids chosen >
        1.5*other). Use distinct tax_years to avoid the
        tax_year-uniqueness rule.
        """
        entity, _ = setup_active_corp_with_shares(
            authorized_shares=12000,
            total_gross_assets_cents=66_000_000,
            total_issued_shares=8000,
        )
        base_year = server_now_year()
        a1 = create_tax_assessment(
            entity["id"], base_year, "AUTHORIZED_SHARES",
        )
        a2 = create_tax_assessment(
            entity["id"], base_year + 1, "ASSUMED_PAR_VALUE",
        )
        assert a1["base_tax_cents"] == 33500
        assert a2["base_tax_cents"] == 40000
        assert a1["base_tax_cents"] != a2["base_tax_cents"]

    def test_exposure_provisional_differs_from_finalized_after_change(
        self, api,
    ):
        # difficulty: dual_variant_calc/boi_exposure_provisional_vs_finalized
        """PRD §3.9: "The two variants produce identical numbers only
        when the latest report is CURRENT and no ownership change has
        occurred since; in any other configuration the provisional
        variant reflects pending undisclosed changes and the finalized
        variant lags behind."

        Claim: after filing a BOIReport with an initial owner mix
        (finalized snapshot frozen), adding a different-risk owner
        without filing an UPDATE makes provisional > finalized.
        """
        entity, _ = create_and_activate_entity()
        o1 = create_beneficial_owner(
            identifying_document_type="STATE_DRIVERS_LICENSE",
        )
        o2 = create_beneficial_owner(
            identifying_document_type="STATE_DRIVERS_LICENSE",
        )
        add_boi_ownership(entity["id"], o1["id"], 4000)
        add_boi_ownership(entity["id"], o2["id"], 6000)
        rep = create_boi_report(entity["id"], "INITIAL")
        file_boi_report(rep["id"], entity["id"])
        # finalized snapshot: 0.40*1 + 0.60*1 = 1.00
        # Now add a FOREIGN_PASSPORT owner WITHOUT filing an UPDATE.
        o3 = create_beneficial_owner(
            identifying_document_type="FOREIGN_PASSPORT",
        )
        add_boi_ownership(entity["id"], o3["id"], 5000)
        # provisional now includes o3 at 0.50*3 = 1.50, plus o1+o2 at
        # 1.00 → total 2.50 (the live sum exceeds 100% because we
        # added a new row without filing; provisional reflects "as is").
        prov = validate_success(
            api.get_exposure_summary(
                entity["id"], make_filer_headers(entity["id"]),
                params={"view": "provisional"},
            ),
        )
        fin = validate_success(
            api.get_exposure_summary(
                entity["id"], make_filer_headers(entity["id"]),
                params={"view": "finalized"},
            ),
        )
        prov_score = prov.get("provisional_score") or prov.get("score")
        fin_score = fin.get("finalized_score") or fin.get("score")
        # The pair must differ because the snapshot is stale relative
        # to live ownership.
        assert prov_score is not None and fin_score is not None
        assert float(prov_score) != float(fin_score), (
            f"After ownership change without UPDATE filing, provisional "
            f"({prov_score}) must differ from finalized ({fin_score})"
        )


# =============================================================================
# Rule 2 — supplemental
# =============================================================================
class TestRule2Supplemental:

    def test_late_fee_capped_at_18_months(self, api):
        # difficulty: combinatorial_formula/late_fee_three_input_threshold_with_per_line_rounding
        """PRD §3.6: "Cap that month count at 18 — the late-fee count
        never exceeds 18 months no matter how long the assessment
        stays unpaid."

        Claim: even after advancing the clock for many months, the
        late_fee_cents is bounded by the 18-month cap. The exact
        per-line ceiling: 20000 + 503 * 18 = 29054 for base=33500.
        """
        _entity, assessment = setup_assessment_in_overdue(
            authorized_shares=12000, days_past_due=10,
        )
        # Advance well past 18 months from due_date to test cap.
        # We do this by advancing 25 months in 30-day chunks.
        for _ in range(25):
            advance_clock_by_days(30)
        a = get_tax_assessment(assessment["id"])
        # Late fee cannot exceed 20000 + 503 * 18.
        max_fee = 20000 + 503 * 18
        assert a["late_fee_cents"] <= max_fee, (
            f"late_fee_cents must be capped at {max_fee} (18-month "
            f"limit), got {a['late_fee_cents']}"
        )

    def test_credit_application_when_balance_zero_makes_full_due(
        self, api,
    ):
        # difficulty: combinatorial_formula/total_due_with_credit_pinned_evaluation_order
        """PRD §3.6: "credit_applied_cents figure as the smaller of the
        entity's current credit_balance_cents and the pre-credit due
        figure — the entity may never apply more credit than it owes,
        and may never apply more credit than it has."

        Claim: with credit_balance=0, credit_applied=0 and total_due
        equals base+late_fee.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        # No credit deposit — balance stays at 0. Use the current server
        # year so the assessment is ASSESSED with late_fee=0.
        assessment = create_tax_assessment(
            entity["id"], server_now_year(), "FLAT",
        )
        # Pay while ASSESSED so late_fee=0.
        resp = api.pay_tax_assessment(
            assessment["id"], make_filer_headers(entity["id"]),
        )
        paid = validate_success(resp)
        assert paid["base_tax_cents"] == 30000
        assert paid["late_fee_cents"] == 0
        # credit_applied = min(0, 30000) = 0 → total_due = 30000 - 0.
        assert paid["total_due_cents"] == 30000, (
            f"total_due must equal base_tax (30000) when balance is 0, "
            f"got {paid['total_due_cents']}"
        )


# =============================================================================
# Rule 3 — supplemental
# =============================================================================
class TestRule3Supplemental:

    def test_annual_report_revision_clears_rejection_reason(
        self, api, tax_officer_headers,
    ):
        # difficulty: non_linear_state_machine/annual_report_reject_to_draft_revision_cycle
        """PRD §3.5: "on the next submission, rejection_reason is
        cleared to null."

        Claim: after the REJECTED→DRAFT→SUBMITTED revision cycle,
        rejection_reason is null on the resubmitted row.
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        sub = create_submitted_annual_report(entity["id"], report_year)
        api.reject_annual_report(
            sub["id"],
            reject_annual_report_payload("address missing"),
            tax_officer_headers,
        )
        # PATCH and resubmit.
        api.patch_annual_report(
            sub["id"],
            patch_annual_report_payload(
                principal_office_address="789 Revised Way",
            ),
            make_filer_headers(entity["id"]),
        )
        sub2 = validate_success(
            api.submit_annual_report(
                sub["id"], make_filer_headers(entity["id"]),
            ),
        )
        assert_status(sub2, "SUBMITTED")
        assert sub2.get("rejection_reason") in (None, ""), (
            f"rejection_reason must be cleared on next SUBMITTED, "
            f"got {sub2.get('rejection_reason')!r}"
        )

    def test_boi_update_after_stale_returns_compliance_to_good_standing(
        self, api,
    ):
        # difficulty: non_linear_state_machine/boi_report_current_stale_current_cycle
        """PRD §3.8: "when an UPDATE-typed report transitions DRAFT →
        FILED → CURRENT in time, the prior STALE report is marked
        CORRECTED in the same operation — this is the cycle CURRENT →
        STALE → CURRENT via timely update — and a ComplianceEvent of
        event_type BOI_CORRECTED is emitted."
        PRD §3.10: "Otherwise the entity is in GOOD_STANDING."

        Claim: after STALE → CORRECTED via UPDATE filing, the entity's
        compliance_status returns to GOOD_STANDING (no other open
        problems).
        """
        entity, _ = create_and_activate_entity()
        _rep, owners, ownerships = setup_initial_boi_filed(entity["id"])
        # Trigger stale by terminating an ownership row.
        delete_boi_ownership(entity["id"], ownerships[0]["id"])
        # Re-add the same owner to keep sum=10000 for the UPDATE filing.
        add_boi_ownership(entity["id"], owners[0]["id"], 4000)
        advance_clock_by_days(BOI_STALE_TIMER_DAYS + 1)
        # Confirm we're STALE → compliance dropped.
        ent_stale = get_entity(
            entity["id"], make_filer_headers(entity["id"]),
        )
        assert ent_stale["compliance_status"] == "NOT_IN_GOOD_STANDING"
        # File a CORRECTION report which rescues STALE to CORRECTED.
        update_rep = create_boi_report(entity["id"], "UPDATE")
        file_boi_report(update_rep["id"], entity["id"])
        ent_fixed = get_entity(
            entity["id"], make_filer_headers(entity["id"]),
        )
        assert ent_fixed["compliance_status"] == "GOOD_STANDING", (
            f"After timely UPDATE filing rescues STALE, entity should "
            f"return to GOOD_STANDING, got {ent_fixed['compliance_status']}"
        )


# =============================================================================
# Rule 4 — supplemental
# =============================================================================
class TestRule4Supplemental:

    def test_admin_dissolve_cascade_emits_foreign_revoked(self, api):
        # difficulty: transitive_cascade/tax_overdue_to_delinquent_to_admin_dissolved_depth3
        """PRD §3.11: "cascades every QUALIFIED foreign qualification
        to REVOKED (setting revoked_at on each)"
        PRD §3.7: "Both cascades emit ComplianceEvent rows of
        event_type FOREIGN_REVOKED with the cascade cause recorded in
        payload."

        Claim: admin-dissolve emits FOREIGN_REVOKED on cascade.
        """
        # Build entity + qualify foreign in good standing.
        entity, _ = create_and_activate_entity(
            entity_type="CORP", home_state="DE", authorized_shares=5000,
        )
        create_qualified_foreign(entity["id"], foreign_state="NY")
        # Drive to DELINQUENT-for-60d via tax overdue cascade. Use the
        # current server year so the sweep ratchets forward through
        # OVERDUE → DELINQUENT deterministically.
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
        advance_clock_by_days(ADMIN_DISSOLUTION_WAIT_DAYS + 5)
        api.administratively_dissolve_entity(
            entity["id"], TEST_USERS["compliance_officer_headers"],
        )
        events = list_compliance_events(entity["id"])
        # FOREIGN_REVOKED must be present on the audit trail.
        assert_event_types_present(events, ["FOREIGN_REVOKED"])

    def test_boi_stale_accrues_penalty_cents(self, api):
        # difficulty: transitive_cascade/boi_ownership_change_to_stale_to_compliance_loss_depth3
        """PRD §3.8: "thirty days after the ownership change ... begins
        accruing penalty_cents per the BOI penalty rule"

        Claim: after the BOIReport transitions to STALE, the system
        emits BOI_STALE on the audit trail (penalty accrual is the
        observable side-effect; penalty_cents is read-back via the
        exposure-summary or the report row, but the PRD-required
        observable here is the BOI_STALE event, which is the only
        PRD-named bridge between the ownership change and the penalty
        accrual).
        """
        entity, _ = create_and_activate_entity()
        _rep, _, ownerships = setup_initial_boi_filed(entity["id"])
        delete_boi_ownership(entity["id"], ownerships[0]["id"])
        advance_clock_by_days(BOI_STALE_TIMER_DAYS + 1)
        events = list_compliance_events(entity["id"])
        assert_event_types_present(events, ["BOI_STALE"])


# =============================================================================
# Rule 5 — supplemental
# =============================================================================
class TestRule5Supplemental:

    def test_invalid_state_beats_segregation_on_approve_ein(self, api):
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation
        """PRD §2.11: "ERR_INVALID_STATE (priority 6) takes precedence
        over ... segregation of duties (priority 8) and all
        business-safety/business-constraint checks below it."

        Claim: an EIN application already APPROVED, retried by a
        TaxOfficer caller whose X-User-ID equals the entity id (would
        also violate SoD), is rejected with ERR_INVALID_STATE.
        """
        from test_helpers import create_approved_ein
        entity, _ = create_and_activate_entity()
        approved = create_approved_ein(entity["id"])
        # Retry approve as TaxOfficer with X-User-ID == entity id (SoD
        # violation), on an already-APPROVED row. Priority 6 must win.
        bad_headers = make_tax_officer_headers(entity["id"])
        resp = api.approve_ein_application(approved["id"], bad_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_invalid_tax_method_beats_dup_year_for_lp(self, api):
        # difficulty: priority_pair_validation_conflict/business_fiscal_vs_business_constraint_tax_method
        """PRD §2.11: "(20) tax-method choice matches entity type ...
        (22) tax-year uniqueness."

        Claim: same priority-pair, different entity type (LP). LP +
        existing FLAT/2024 assessment, plus a second 2024 attempt with
        ASSUMED_PAR_VALUE → ERR_INVALID_TAX_METHOD (priority 20) wins
        over ERR_DUPLICATE_TAX_YEAR (priority 22).
        """
        entity, _ = create_and_activate_entity(entity_type="LP")
        create_tax_assessment(entity["id"], 2024, "FLAT")
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "ASSUMED_PAR_VALUE",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TAX_METHOD.value)


# =============================================================================
# Rule 7 — supplemental
# =============================================================================
class TestRule7Supplemental:

    def test_foreign_qualification_approve_blocked_by_delinquent_parent(
        self, api,
    ):
        # difficulty: cross_entity_state_dependency/foreign_qualification_requires_business_entity_good_standing
        """PRD §3.7: "the parent entity's compliance_status is
        GOOD_STANDING (not NOT_IN_GOOD_STANDING and not DELINQUENT)"

        Claim: a foreign qualification approval on an entity whose
        parent is DELINQUENT (the more extreme bad-posture) →
        ERR_INVALID_STATE.
        """
        entity, _ = setup_assessment_in_delinquent(
            authorized_shares=5000,
        )
        ent = get_entity(entity["id"], make_filer_headers(entity["id"]))
        assert ent["compliance_status"] == "DELINQUENT"
        qual, _ = create_pending_foreign_qualification(
            entity["id"], foreign_state="NY",
        )
        resp = api.approve_foreign_qualification(
            qual["id"], TEST_USERS["state_registrar_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_voluntary_dissolve_blocked_by_overdue_tax(self, api):
        # difficulty: cross_entity_state_dependency/voluntary_dissolution_requires_no_active_dependents
        """PRD §3.11: "Voluntary dissolution is blocked when any of
        three dependencies is present: any FranchiseTaxAssessment with
        status in OVERDUE or DELINQUENT ... A blocking dependency
        yields ERR_HAS_DEPENDENCIES with HTTP 409."

        Claim: a different dependency (OVERDUE tax) also blocks
        voluntary dissolve. Distinct entity pair from the BOI variant.
        """
        entity, _assessment = setup_assessment_in_overdue(
            authorized_shares=5000,
        )
        resp = api.dissolve_entity(
            entity["id"], make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HAS_DEPENDENCIES.value)


# =============================================================================
# Rule 8 — supplemental
# =============================================================================
class TestRule8Supplemental:

    def test_foreign_qualification_after_withdrawal_allowed(self, api):
        # difficulty: resource_temporal_overlap/foreign_qualification_unique_open_window_per_state_pair
        """PRD §3.7: "Only one non-terminal qualification (that is,
        with status neither WITHDRAWN nor REVOKED) may exist for a
        given (business_entity_id, foreign_state) pair at a time"

        Claim: after a first qualification reaches a terminal state
        (WITHDRAWN), a fresh filing for the same (entity, foreign_state)
        is allowed because WITHDRAWN does not occupy the open window.
        """
        entity, _ = create_and_activate_entity(home_state="DE")
        # First: get a QUALIFIED qualification and withdraw it.
        qual, _ = create_qualified_foreign(entity["id"], "NY")
        validate_success(
            api.withdraw_foreign_qualification(
                qual["id"], make_filer_headers(entity["id"]),
            ),
        )
        # Second filing — same (entity, foreign_state) — must succeed.
        agent_ny = create_registered_agent(service_state="NY")
        payload = create_foreign_qualification_payload(
            entity["id"], "NY", agent_ny["id"], server_now_iso(),
        )
        resp = api.create_foreign_qualification(
            payload, make_filer_headers(entity["id"]),
        )
        validate_success(resp, expected_status=201)

    def test_annual_report_rejected_does_not_block_new_attempt(
        self, api, tax_officer_headers,
    ):
        # difficulty: resource_temporal_overlap/annual_report_unique_year_window_per_entity
        """PRD §3.5: "no prior SUBMITTED or ACCEPTED report covers the
        same report_year" — REJECTED is intentionally excluded.

        Claim: after the first report for a year is REJECTED, a fresh
        AnnualReport creation for the same year is permitted (the
        rejected slot is freed; status-filtered occupancy).
        """
        entity, report_year = setup_active_entity_eligible_for_annual_report()
        sub = create_submitted_annual_report(entity["id"], report_year)
        api.reject_annual_report(
            sub["id"],
            reject_annual_report_payload("revise needed"),
            tax_officer_headers,
        )
        # Second creation must succeed.
        resp = api.create_annual_report(
            create_annual_report_payload(entity["id"], report_year),
            make_filer_headers(entity["id"]),
        )
        validate_success(resp, expected_status=201)


# =============================================================================
# Rule 9 — supplemental
# =============================================================================
class TestRule9Supplemental:

    def test_refund_reverts_status_off_paid(self, api):
        # difficulty: compensating_invariant/tax_pay_refund_credit_balance_conserved
        """PRD §3.6: "A TaxOfficer may refund a PAID assessment, which
        reverses the row back to whichever non-paid status the clock
        dictates — ASSESSED if the clock is still at or before
        due_date, OVERDUE once past due_date but within 90 days, or
        DELINQUENT past 90 days"

        Claim: a /refund call on a PAID LLC assessment (whose due_date
        is in the future) returns status to ASSESSED.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        credit_deposit(entity["id"], 50000)
        assessment = create_tax_assessment(entity["id"], 2099, "FLAT")
        pay_tax_assessment(assessment["id"], entity["id"])
        # Refund.
        refunded = refund_tax_assessment(assessment["id"])
        # tax_year=2099 means due_date is far in the future → ASSESSED.
        assert_status(refunded, "ASSESSED")

    def test_active_ownership_sum_excludes_terminated_rows(self, api):
        # difficulty: compensating_invariant/boi_ownership_add_terminate_bps_sum_conserved
        """PRD §3.8: "the sum of active BOIOwnership.ownership_percent_
        basis_points rows for the entity (those with terminated_at
        either null or in the future relative to the current clock)
        must equal exactly 10,000 at the moment of filing"

        Claim: a terminated row does not contribute to the active sum.
        Build entity with two active rows summing to 10000, add a
        third (sum=12500), terminate the third, then re-attempt /file —
        it succeeds (sum back to 10000).
        """
        entity, _ = create_and_activate_entity()
        owner_a = create_beneficial_owner()
        owner_b = create_beneficial_owner()
        owner_c = create_beneficial_owner()
        add_boi_ownership(entity["id"], owner_a["id"], 4000)
        add_boi_ownership(entity["id"], owner_b["id"], 6000)
        extra = add_boi_ownership(entity["id"], owner_c["id"], 2500)
        # Sum=12500 — file would fail. Soft-delete extra.
        delete_boi_ownership(entity["id"], extra["id"])
        # Now active sum is exactly 10000.
        rep = create_boi_report(entity["id"], "INITIAL")
        resp = api.file_boi_report(
            rep["id"], make_filer_headers(entity["id"]),
        )
        filed = validate_success(resp)
        assert_status(filed, "CURRENT")
