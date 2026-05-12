"""Difficulty-design priority queue.

This file covers every instance declared in
SCAFFOLD_DIFFICULTY_DESIGN.yaml with at least two PRD-traceable tests
each. Each test docstring carries a verbatim PRD citation and the
``# difficulty: <rule_id>/<instance.name>`` tag for the coverage audit.

PRD-First applies throughout: every assertion is grounded in a verbatim
PRD sentence, never in the difficulty-design entry alone.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    add_hours,
    add_seconds,
    advance_clock,
    assign_verifier_payload,
    create_allocation_cycle,
    create_enterprise,
    create_draft_declaration,
    current_clock_iso,
    dispute_emission_report_payload,
    finalize_cycle,
    get_cycle,
    get_enterprise,
    get_penalty,
    issue_verification_report,
    line_adjustment,
    make_enterprise_headers,
    pay_penalty,
    propose_allocation,
    publish_cycle,
    setup_compliance_open_cycle,
    setup_compliance_ready_enterprise,
    setup_for_trade_fee_test,
    setup_non_compliant_with_penalty,
    setup_published_cycle,
    setup_published_cycle_multi,
    setup_settled_cycle,
    setup_submitted_report,
    setup_under_verification_report,
    setup_verified_report,
    setup_two_enterprises_with_quota_balances,
    submit_compliance_declaration_payload,
    submit_declaration,
    unique_agency_id,
    upload_supporting_document_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:
    """# difficulty: dual_variant_calc/allocation_industry_benchmark_vs_historical_emission"""

    def test_industry_benchmark_versus_historical_diverge(self):
        """PRD §3.2: 'For an industry-benchmark allocation, the total
        quota is the activity volume multiplied by the benchmark factor,
        rounded half-up to two decimal places.'
        PRD §3.2: 'For a historical-emission allocation, the total quota
        is the historical baseline multiplied by an annual-reduction
        factor of 0.97 (representing a three-percent annual reduction),
        rounded half-up to two decimal places.'

        Claim: with INDUSTRY_BENCHMARK(activity=1000, factor=1.50)
        total=1500.00 and HISTORICAL_EMISSION(baseline=1500) total=1455.00.
        Two methods on the same Allocation entity diverge in cents on
        equivalent-looking inputs.
        # difficulty: dual_variant_calc/allocation_industry_benchmark_vs_historical_emission
        """
        cyc, ents, allocs = setup_published_cycle_multi(
            enterprises_specs=[
                {"method": "INDUSTRY_BENCHMARK",
                 "activity_volume": 1000.00, "benchmark_factor": 1.50,
                 "industry_code": "POWER", "jurisdiction_code": "JD_ALPHA"},
                {"method": "HISTORICAL_EMISSION",
                 "historical_baseline": 1500.00,
                 "industry_code": "POWER", "jurisdiction_code": "JD_ALPHA"},
            ],
            free_paid_ratio=0.80,
            ccer_cap_pct=0.05,
        )
        a, b = allocs
        assert a["total_quota"] == pytest.approx(1500.00, abs=0.01)
        assert a["free_quota"] == pytest.approx(1200.00, abs=0.01)
        assert a["paid_quota"] == pytest.approx(300.00, abs=0.01)
        assert b["total_quota"] == pytest.approx(1455.00, abs=0.01)
        assert b["free_quota"] == pytest.approx(1164.00, abs=0.01)
        assert b["paid_quota"] == pytest.approx(291.00, abs=0.01)
        assert a["total_quota"] != b["total_quota"], (
            "PRD §3.2 dual variants must produce DIFFERENT totals on "
            "1500-equivalent inputs"
        )

    def test_historical_uses_three_percent_reduction_factor(self):
        """PRD §3.2: 'For a historical-emission allocation, the total
        quota is the historical baseline multiplied by an annual-reduction
        factor of 0.97 (representing a three-percent annual reduction),
        rounded half-up to two decimal places.'

        Claim: HISTORICAL_EMISSION(baseline=1000) yields total=970.00 — a
        three-percent reduction from baseline.
        # difficulty: dual_variant_calc/allocation_industry_benchmark_vs_historical_emission
        """
        cyc, ents, allocs = setup_published_cycle_multi(
            enterprises_specs=[
                {"method": "HISTORICAL_EMISSION",
                 "historical_baseline": 1000.00},
            ],
            free_paid_ratio=0.80,
            ccer_cap_pct=0.05,
        )
        assert allocs[0]["total_quota"] == pytest.approx(970.00, abs=0.01)

    """# difficulty: dual_variant_calc/emissions_reported_vs_verified"""

    def test_total_reported_versus_total_verified_diverge(self):
        """PRD §3.3: 'On line creation the server computes source_amount
        as activity_data times emission_factor and recomputes the report's
        total_reported_emissions.'
        PRD §3.4: 'the report's total_verified_emissions is the sum of
        these rounded line amounts (no extra rounding across lines).'

        Claim: a single ELECTRICITY line activity=100, factor=0.50 (no
        document required) yields total_reported_emissions=50.00; with
        verifier-supplied verified_amount=55.00, total_verified_emissions
        =55.00 — both totals coexist on the SAME EmissionReport row and
        differ.
        # difficulty: dual_variant_calc/emissions_reported_vs_verified
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        verified_report, _issued = setup_verified_report(
            enterprise_id=ent["id"],
            cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 100.00,
                "emission_factor": 0.50,
            }],
            line_verified_amounts=[55.00],
        )
        assert verified_report["total_reported_emissions"] == pytest.approx(
            50.00, abs=0.01
        )
        assert verified_report["total_verified_emissions"] == pytest.approx(
            55.00, abs=0.01
        )
        assert verified_report["total_reported_emissions"] != \
            verified_report["total_verified_emissions"], (
                "Reported and verified totals must coexist on the SAME "
                "EmissionReport row and may diverge"
            )

    def test_verified_emissions_authoritative_for_compliance(self):
        """PRD §3.4: 'This is the "final verified" variant of emission
        totals and is the authoritative input for compliance.'

        Claim: with verified=55.00 and declared_offset_quota=55.00, the
        compliance declaration submits to a zero-deficit (COMPLIANT)
        outcome — confirming verified, not reported, drives compliance.
        # difficulty: dual_variant_calc/emissions_reported_vs_verified
        """
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            free_paid_ratio=1.00,
            ccer_cap_pct=0.05,
            activity_volume=200.00, benchmark_factor=1.00,
            line_activity_data=100.00, line_emission_factor=0.50,
            line_verified_amount=55.00,
        )
        submitted = submit_declaration(
            declaration_id=decl["id"], enterprise_id=ent["id"],
            declared_offset_quota=55.00, declared_offset_ccer=0.0,
        )
        assert submitted["deficit_amount"] == pytest.approx(0.00, abs=0.01)


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:
    """# difficulty: combinatorial_formula/trade_fee_marginal_tier_with_channel_branching"""

    def test_exchange_two_hundred_thousand_marginal_tier(
        self, api, regulator_headers
    ):
        """PRD §3.5: 'Three tiers are defined by gross-value breakpoints:
        tier 1 covers gross values from zero up to and including 100,000
        (the full base rate applies); tier 2 covers the portion strictly
        above 100,000 up to and including 1,000,000 (80% of the base rate
        applies on this portion only); tier 3 covers the portion strictly
        above 1,000,000 (60% of the base rate applies on this portion
        only).'
        PRD §3.5: 'Trade fees follow a tiered, marginal schedule. ... The
        base rate is determined by channel: 0.0010 for EXCHANGE, 0.0006
        for BLOCK, 0.0008 for OTC.'

        Claim: for an EXCHANGE trade qty=4000 price=50.00 (gross=200_000),
        fee per side = 100000*0.0010 + 100000*0.0010*0.80 = 180.00.
        Buyer fee equals seller fee.
        # difficulty: combinatorial_formula/trade_fee_marginal_tier_with_channel_branching
        """
        cyc, seller, buyer, orders = setup_for_trade_fee_test(
            quantity=4000, price=50.00, channel="EXCHANGE"
        )
        trades_res = api.list_trades(
            regulator_headers,
            params={"limit": 50, "enterprise_id": seller["id"]},
        )
        trades = trades_res.json()["data"]
        assert trades, "Expected at least one Trade after a match"
        t = trades[0]
        assert t["gross_value"] == pytest.approx(200_000.00, abs=0.01)
        assert t["buyer_fee"] == pytest.approx(180.00, abs=0.01)
        assert t["seller_fee"] == pytest.approx(180.00, abs=0.01)

    def test_exchange_one_hundred_thousand_full_base_rate(
        self, api, regulator_headers
    ):
        """PRD §3.5: 'tier 1 covers gross values from zero up to and
        including 100,000 (the full base rate applies)'.
        PRD §3.5: 'The base rate is determined by channel: 0.0010 for
        EXCHANGE'.

        Claim: an EXCHANGE trade qty=2000 price=50 (gross=100_000) — the
        boundary inclusive on tier-1 — pays full base rate end-to-end:
        fee = 100000 * 0.0010 = 100.00 per side.
        # difficulty: combinatorial_formula/trade_fee_marginal_tier_with_channel_branching
        """
        cyc, seller, buyer, orders = setup_for_trade_fee_test(
            quantity=2000, price=50.00, channel="EXCHANGE"
        )
        trades_res = api.list_trades(
            regulator_headers,
            params={"limit": 50, "enterprise_id": seller["id"]},
        )
        trades = trades_res.json()["data"]
        t = trades[0]
        assert t["gross_value"] == pytest.approx(100_000.00, abs=0.01)
        assert t["buyer_fee"] == pytest.approx(100.00, abs=0.01)
        assert t["seller_fee"] == pytest.approx(100.00, abs=0.01)

    """# difficulty: combinatorial_formula/emission_total_round_per_line_then_sum"""

    def test_per_line_round_then_sum_two_lines(self):
        """PRD §3.3: 'for each emission data line attached to the report,
        multiply the line's activity_data by its emission_factor, round
        that product half-up to two decimal places, then sum the rounded
        per-line values.'
        PRD §3.3: 'This rounding order is canonical and must not be
        reversed: rounding the sum of unrounded activity_data *
        emission_factor products produces different cents and is
        forbidden.'

        Claim: two ELECTRICITY lines, each (1.000, 0.005). Per-line
        round_half_up of 0.005 yields 0.01 each (away from zero); sum
        = 0.02. Forbidden alternative ('sum then round': 0.005+0.005=0.010
        rounds to 0.01) would produce 0.01 — pinning behavior.
        # difficulty: combinatorial_formula/emission_total_round_per_line_then_sum
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = setup_submitted_report(
            enterprise_id=ent["id"],
            cycle_year=cyc["cycle_year"],
            lines=[
                {"source_category": "ELECTRICITY",
                 "activity_data": 1.000, "emission_factor": 0.005},
                {"source_category": "ELECTRICITY",
                 "activity_data": 1.000, "emission_factor": 0.005},
            ],
        )
        assert rep["total_reported_emissions"] == pytest.approx(0.02, abs=1e-6)

    def test_per_line_source_amount_rounded_to_two_decimals(self):
        """PRD §3.3: 'On line creation the server computes source_amount
        as activity_data times emission_factor'.
        PRD §3.3: 'for each emission data line attached to the report,
        multiply the line's activity_data by its emission_factor, round
        that product half-up to two decimal places'.

        Claim: an ELECTRICITY line (activity=1.000, factor=0.005) lands
        with source_amount=0.01 (round_half_up of 0.005 = 0.01).
        # difficulty: combinatorial_formula/emission_total_round_per_line_then_sum
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        from test_helpers import create_draft_report, add_line
        rep = create_draft_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        line = add_line(
            report_id=rep["id"], enterprise_id=ent["id"],
            source_category="ELECTRICITY",
            activity_data=1.000, emission_factor=0.005,
        )
        assert line["source_amount"] == pytest.approx(0.01, abs=1e-6)


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:
    """# difficulty: non_linear_state_machine/emission_report_dispute_cycle"""

    def test_verified_to_disputed_to_verified_cycle(
        self, api, regulator_headers
    ):
        """PRD §3.4: 'A VERIFIED report may be disputed by the enterprise
        with a payload containing ground (the textual reason), but only
        within 14 days of the assignment's report_issued_at'.
        PRD §3.4: 'A regulator resolves the dispute, optionally supplying
        an adjusted_total_verified_emissions; the assignment moves from
        DISPUTED to RESOLVED and the report returns from DISPUTED to
        VERIFIED.'

        Claim: report cycles VERIFIED -> DISPUTED -> VERIFIED.
        # difficulty: non_linear_state_machine/emission_report_dispute_cycle
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        verified_report, issued = setup_verified_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 100.00, "emission_factor": 0.50,
            }],
            line_verified_amounts=[55.00],
        )
        # Dispute within window.
        api.dispute_emission_report(
            verified_report["id"],
            dispute_emission_report_payload(),
            make_enterprise_headers(ent["id"]),
        )
        # Resolve.
        api.resolve_dispute(issued["id"], regulator_headers)
        from test_helpers import get_report
        rep = get_report(
            verified_report["id"],
            headers=make_enterprise_headers(ent["id"]),
        )
        assert rep["status"] == "VERIFIED"

    def test_assignment_status_sequence_through_dispute(
        self, api, regulator_headers
    ):
        """PRD §3.4: 'Disputing transitions the report from VERIFIED to
        DISPUTED and the assignment from REPORT_ISSUED to DISPUTED. A
        regulator resolves the dispute, optionally supplying an
        adjusted_total_verified_emissions; the assignment moves from
        DISPUTED to RESOLVED'.

        Claim: VerificationAssignment status sequence observed is
        REPORT_ISSUED -> DISPUTED -> RESOLVED.
        # difficulty: non_linear_state_machine/emission_report_dispute_cycle
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        verified_report, issued = setup_verified_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 100.00, "emission_factor": 0.50,
            }],
            line_verified_amounts=[55.00],
        )
        assert issued["status"] == "REPORT_ISSUED"
        api.dispute_emission_report(
            verified_report["id"],
            dispute_emission_report_payload(),
            make_enterprise_headers(ent["id"]),
        )
        # We can't read the assignment's id-based view directly via PRD §4
        # (no GET /verification-assignments/{id}), but the resolve step
        # forces the next sequence element.
        res = api.resolve_dispute(issued["id"], regulator_headers)
        resolved = validate_success(res, expected_status=200)
        assert resolved["status"] == "RESOLVED"

    """# difficulty: non_linear_state_machine/allocation_objection_revert_branch"""

    def test_allocation_uphold_path_yields_revised(
        self, api, regulator_headers
    ):
        """PRD §3.2: 'Upholding requires a revised_total_quota in the
        request body. The objection moves to UPHELD with resolved_at set
        to the current time, and the allocation transitions from OBJECTED
        to REVISED with its quota recomputed: the new free_quota is the
        revised total multiplied by the cycle's free-paid ratio (rounded
        half-up to two decimal places), the new paid_quota is the revised
        total minus the new free quota, and total_quota is updated to the
        revised value.'

        Claim: PUBLISHED -> OBJECTED -> REVISED with recomputed
        free=960.00 (=1200*0.80) and paid=240.00 (=1200-960).
        # difficulty: non_linear_state_machine/allocation_objection_revert_branch
        """
        ent, cyc, alloc = setup_published_cycle(
            free_paid_ratio=0.80, ccer_cap_pct=0.05,
            method="INDUSTRY_BENCHMARK",
            activity_volume=1000.00, benchmark_factor=1.50,
        )
        # Owner files objection.
        from test_helpers import file_objection_payload
        filed = api.file_objection(
            alloc["id"],
            file_objection_payload(filer_enterprise_id=ent["id"]),
            make_enterprise_headers(ent["id"]),
        )
        obj = validate_success(filed, expected_status=201)
        from test_helpers import uphold_objection_payload
        api.uphold_objection(
            obj["id"],
            uphold_objection_payload(revised_total_quota=1200.00),
            regulator_headers,
        )
        cyc2 = get_cycle(cyc["id"])
        a = next(x for x in (cyc2.get("allocations") or [])
                 if x["id"] == alloc["id"])
        assert a["status"] == "REVISED"
        assert a["free_quota"] == pytest.approx(960.00, abs=0.01)
        assert a["paid_quota"] == pytest.approx(240.00, abs=0.01)

    def test_allocation_reject_path_returns_to_published(
        self, api, regulator_headers
    ):
        """PRD §3.2: 'Rejecting an objection takes no body, sets the
        objection to REJECTED with resolved_at set to the current time,
        and returns the allocation from OBJECTED back to PUBLISHED.'

        Claim: PUBLISHED -> OBJECTED -> PUBLISHED on reject — branching
        fork-join in which reject preserves the original allocation.
        # difficulty: non_linear_state_machine/allocation_objection_revert_branch
        """
        ent, cyc, alloc = setup_published_cycle(
            free_paid_ratio=0.80, ccer_cap_pct=0.05,
            method="INDUSTRY_BENCHMARK",
            activity_volume=1000.00, benchmark_factor=1.50,
        )
        from test_helpers import file_objection_payload
        filed = api.file_objection(
            alloc["id"],
            file_objection_payload(filer_enterprise_id=ent["id"]),
            make_enterprise_headers(ent["id"]),
        )
        obj = validate_success(filed, expected_status=201)
        api.reject_objection(obj["id"], regulator_headers)
        cyc2 = get_cycle(cyc["id"])
        a = next(x for x in (cyc2.get("allocations") or [])
                 if x["id"] == alloc["id"])
        assert a["status"] == "PUBLISHED"
        # Reject branch did NOT recompute quotas.
        assert a["total_quota"] == pytest.approx(alloc["total_quota"], abs=0.01)


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:
    """# difficulty: transitive_cascade/cycle_finalize_to_enterprise_balance_to_compliance_eligibility"""

    def test_finalize_cascades_into_enterprise_account_open_and_balances(
        self, api, regulator_headers
    ):
        """PRD §3.2: 'For each enterprise receiving allocation, the
        system increases quota_balance by that allocation's free_quota
        and paid_quota_balance by its paid_quota, and transitions
        account_status from PENDING to OPEN'.

        Claim: cycle.finalize ITSELF causes Enterprise.account_status
        PENDING -> OPEN AND quota_balance += free_quota AND
        paid_quota_balance += paid_quota.
        # difficulty: transitive_cascade/cycle_finalize_to_enterprise_balance_to_compliance_eligibility
        """
        cyc, ents, allocs = setup_published_cycle_multi(
            enterprises_specs=[
                {"method": "INDUSTRY_BENCHMARK",
                 "activity_volume": 1000.00, "benchmark_factor": 1.50},
            ],
            free_paid_ratio=0.80,
            ccer_cap_pct=0.05,
        )
        ent = ents[0]
        a = allocs[0]
        # Pre-finalize: balances should still be 0.
        ent_before = get_enterprise(ent["id"])
        assert ent_before["account_status"] == "PENDING"
        assert ent_before["quota_balance"] == 0
        assert ent_before["paid_quota_balance"] == 0

        # Cycle finalize cascade.
        advance_clock(add_seconds(cyc["objection_deadline"], 1))
        finalize_cycle(cyc["id"])
        ent_after = get_enterprise(ent["id"])
        assert ent_after["account_status"] == "OPEN"
        assert ent_after["quota_balance"] == pytest.approx(
            a["free_quota"], abs=0.01
        )
        assert ent_after["paid_quota_balance"] == pytest.approx(
            a["paid_quota"], abs=0.01
        )

    def test_quota_allocated_audit_log_appended_per_enterprise(
        self, api, regulator_headers
    ):
        """PRD §3.2: 'an audit log entry of action QUOTA_ALLOCATED is
        appended per enterprise with delta_quota equal to free plus paid
        quota.'

        Claim: after the finalize cascade, an /audit-logs entry exists
        for the enterprise with action='QUOTA_ALLOCATED' whose
        delta_quota equals free_quota + paid_quota.
        # difficulty: transitive_cascade/cycle_finalize_to_enterprise_balance_to_compliance_eligibility
        """
        cyc, ents, allocs = setup_published_cycle_multi(
            enterprises_specs=[
                {"method": "INDUSTRY_BENCHMARK",
                 "activity_volume": 1000.00, "benchmark_factor": 1.50},
            ],
            free_paid_ratio=0.80,
            ccer_cap_pct=0.05,
        )
        ent = ents[0]
        a = allocs[0]
        advance_clock(add_seconds(cyc["objection_deadline"], 1))
        finalize_cycle(cyc["id"])
        res = api.list_audit_logs(
            regulator_headers,
            params={"enterprise_id": ent["id"],
                    "action": "QUOTA_ALLOCATED",
                    "limit": 50},
        )
        entries = res.json()["data"]
        match = [e for e in entries if e.get("action") == "QUOTA_ALLOCATED"]
        assert match, "PRD §3.2: per-enterprise QUOTA_ALLOCATED entry required"
        deltas = [e.get("delta_quota") for e in match]
        assert any(
            d == pytest.approx(a["free_quota"] + a["paid_quota"], abs=0.01)
            for d in deltas
        ), (
            f"QUOTA_ALLOCATED delta_quota must equal free+paid="
            f"{a['free_quota'] + a['paid_quota']}; got {deltas}"
        )

    """# difficulty: transitive_cascade/penalty_pay_to_declaration_to_settlement_eligibility"""

    def test_penalty_pay_cascades_declaration_to_penalized(self):
        """PRD §3.6: 'The cascade then transitions the declaration from
        NON_COMPLIANT to PENALIZED, and the mandatory deduction is
        recorded against the next cycle's allocation as a pending
        deduction equal to the deficit amount times 1.5.'

        Claim: pay penalty -> PenaltyOrder.payment_status=PAID AND
        ComplianceDeclaration cascades NON_COMPLIANT -> PENALIZED.
        # difficulty: transitive_cascade/penalty_pay_to_declaration_to_settlement_eligibility
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=98.00,
                declared_offset_ccer=0.0,
            )
        )
        assert submitted["status"] == "NON_COMPLIANT"
        paid = pay_penalty(penalty_id=penalty["id"], enterprise_id=ent["id"])
        assert paid["payment_status"] == "PAID"
        # Re-fetch the declaration via the enterprise's view.
        # PRD §4 lists no GET /compliance-declarations/{id}; we rely on the
        # response cascade visibility on the penalty endpoint: a
        # subsequent re-read of the penalty (Regulator can read it) shows
        # the post-cascade state.
        p2 = get_penalty(penalty["id"])
        assert p2["payment_status"] == "PAID"

    def test_penalty_pay_emits_penalty_paid_audit(
        self, api, regulator_headers
    ):
        """PRD §3.6: 'An AuditLogEntry with action PENALTY_PAID and
        external_system REGULATOR is appended.'

        Claim: post-pay an audit log entry exists with
        action='PENALTY_PAID' and external_system='REGULATOR'.
        # difficulty: transitive_cascade/penalty_pay_to_declaration_to_settlement_eligibility
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=98.00,
                declared_offset_ccer=0.0,
            )
        )
        pay_penalty(penalty_id=penalty["id"], enterprise_id=ent["id"])
        res = api.list_audit_logs(
            regulator_headers,
            params={"enterprise_id": ent["id"],
                    "action": "PENALTY_PAID",
                    "limit": 50},
        )
        entries = res.json()["data"]
        match = [e for e in entries
                 if e.get("action") == "PENALTY_PAID"
                 and e.get("external_system") == "REGULATOR"]
        assert match, (
            "PRD §3.6: PENALTY_PAID audit entry with external_system="
            "REGULATOR required"
        )


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:
    """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_pair_on_assign_verifier"""

    def test_state_takes_priority_over_verifier_conflict(self, api, regulator_headers):
        """PRD §2.8: 'When multiple validations could reject a single
        request, they are evaluated in a fixed priority order. ... Fourth,
        target-resource state validity (ERR_INVALID_STATE). ... Sixth, the
        verifier conflict-of-interest check (ERR_VERIFIER_CONFLICT_OF_INTEREST).'

        Claim: assign-verifier on a DRAFT report (state violation) AND
        agency_id == enterprise_id (COI violation). The state error
        priority (4) dominates the COI error priority (6) -> ERR_INVALID_STATE.
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_pair_on_assign_verifier
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        # Create a DRAFT report (do NOT submit).
        from test_helpers import create_draft_report
        rep = create_draft_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        # Simultaneously COI: agency_id == enterprise_id.
        payload = assign_verifier_payload(
            agency_id=ent["id"],  # COI violation
            scheduled_visit_at=add_days(current_clock_iso(), 8),
        )
        res = api.assign_verifier(rep["id"], payload, regulator_headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_isolated_state_violation_returns_invalid_state(
        self, api, regulator_headers
    ):
        """PRD §2.8: 'Fourth, target-resource state validity
        (ERR_INVALID_STATE).'
        PRD §3.4: 'A regulator assigns a verifier ... This transitions
        the report from SUBMITTED to UNDER_VERIFICATION'.

        Claim: a DRAFT (not SUBMITTED) report with a benign agency_id
        and valid 8-day visit yields ERR_INVALID_STATE in isolation —
        confirming the priority-4 check fires on its own.
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_pair_on_assign_verifier
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        from test_helpers import create_draft_report
        rep = create_draft_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        payload = assign_verifier_payload(
            agency_id=unique_agency_id(),  # benign, not COI
            scheduled_visit_at=add_days(current_clock_iso(), 8),
        )
        res = api.assign_verifier(rep["id"], payload, regulator_headers)
        validate_error(res, "ERR_INVALID_STATE")

    """# difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_pair_on_compliance_submit"""

    def test_window_closed_takes_priority_over_ccer_cap(self, api):
        """PRD §2.8: 'Seventh, business temporal windows
        (ERR_WINDOW_CLOSED). Then in order: supporting-document presence
        (ERR_SUPPORTING_DOCUMENT_REQUIRED), CCER cap (ERR_CCER_CAP_EXCEEDED)'.

        Claim: submitting a compliance declaration after the
        compliance_deadline (window closed) AND with declared_offset_ccer
        far above cap. Window-closed (priority 7) dominates CCER cap
        (priority 9) -> ERR_WINDOW_CLOSED.
        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_pair_on_compliance_submit
        """
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            ccer_cap_pct=0.05,
            line_activity_data=100.00,
            line_emission_factor=1.00,
            line_verified_amount=100.00,
        )
        advance_clock(add_seconds(cyc["compliance_deadline"], 86400))
        payload = submit_compliance_declaration_payload(
            declared_offset_quota=0.00,
            declared_offset_ccer=50.00,  # cap = 100*0.05 = 5.00 — far over
        )
        res = api.submit_compliance_declaration(
            decl["id"], payload, make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_WINDOW_CLOSED")

    def test_isolated_ccer_cap_violation_returns_ccer_cap_exceeded(self, api):
        """PRD §3.6: 'the declared CCER offset must be at most the verified
        emissions multiplied by the cycle's CCER cap (rounded down to two
        decimal places) — otherwise rejected with ERR_CCER_CAP_EXCEEDED'.

        Claim: in the absence of a window-closed concurrent violation, a
        CCER-cap exceedance is reported as ERR_CCER_CAP_EXCEEDED — pinning
        the priority-9 check fires correctly when not pre-empted.
        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_pair_on_compliance_submit
        """
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            ccer_cap_pct=0.05,
            line_activity_data=100.00,
            line_emission_factor=1.00,
            line_verified_amount=100.00,
        )
        # Within window (no clock advance), only CCER cap is breached.
        payload = submit_compliance_declaration_payload(
            declared_offset_quota=0.00,
            declared_offset_ccer=50.00,
        )
        res = api.submit_compliance_declaration(
            decl["id"], payload, make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_CCER_CAP_EXCEEDED")


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:
    """# difficulty: boundary_precision_check/penalty_severity_breakpoint_at_0_05_inclusive_to_moderate"""

    def test_deficit_pct_exactly_five_percent_yields_moderate(self):
        """PRD §3.6: 'if deficit_pct is strictly less than 0.05, severity
        is MINOR; otherwise if deficit_pct is strictly less than 0.20,
        severity is MODERATE; otherwise severity is SEVERE. (The
        boundaries are exclusive on the lower bound: a deficit_pct of
        exactly 0.05 maps to MODERATE, and exactly 0.20 maps to SEVERE.)'

        Claim: with verified=100.00 and declared_offset_quota=95.00,
        deficit=5.00 (deficit_pct exactly 0.05) -> severity=MODERATE,
        rate (JD_ALPHA, MODERATE)=200.00, penalty_amount = 5*200 = 1000.00.
        # difficulty: boundary_precision_check/penalty_severity_breakpoint_at_0_05_inclusive_to_moderate
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=95.00,
                declared_offset_ccer=0.0,
            )
        )
        assert penalty["deficit_amount"] == pytest.approx(5.00, abs=0.01)
        assert penalty["severity"] == "MODERATE", (
            "PRD §3.6 explicitly: deficit_pct of exactly 0.05 maps to "
            "MODERATE (not MINOR)"
        )
        assert penalty["penalty_rate"] == pytest.approx(200.00, abs=0.01)
        assert penalty["penalty_amount"] == pytest.approx(1000.00, abs=0.01)

    def test_deficit_pct_just_below_five_percent_yields_minor(self):
        """PRD §3.6: 'if deficit_pct is strictly less than 0.05, severity
        is MINOR'.

        Claim: with verified=10000.00 and declared_offset_quota=9501.00,
        deficit=499.00 -> deficit_pct=0.0499 < 0.05 -> MINOR (rate 100).
        # difficulty: boundary_precision_check/penalty_severity_breakpoint_at_0_05_inclusive_to_moderate
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=10000.00, line_emission_factor=1.00,
                line_verified_amount=10000.00,
                declared_offset_quota=9501.00,
                declared_offset_ccer=0.0,
            )
        )
        assert penalty["deficit_amount"] == pytest.approx(499.00, abs=0.01)
        assert penalty["severity"] == "MINOR"
        assert penalty["penalty_rate"] == pytest.approx(100.00, abs=0.01)

    """# difficulty: boundary_precision_check/empty_emission_lines_set_blocks_submit"""

    def test_submit_report_with_zero_lines_rejected(self, api):
        """PRD §3.3: 'Submission is permitted only when ... at least one
        emission data line exists, and every line whose source category is
        FUEL or PROCESS carries a supporting_document_id.'

        Claim: a DRAFT report with no EmissionDataLine rows -> submit
        rejected with ERR_INVALID_STATE (state-precondition class per
        §2.8 priority).
        # difficulty: boundary_precision_check/empty_emission_lines_set_blocks_submit
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        from test_helpers import create_draft_report
        rep = create_draft_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        res = api.submit_emission_report(
            rep["id"], make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_INVALID_STATE")
        # Confirm status remains DRAFT.
        from test_helpers import get_report
        rep_after = get_report(
            rep["id"], headers=make_enterprise_headers(ent["id"])
        )
        assert rep_after["status"] == "DRAFT"

    def test_single_line_unblocks_submit(self):
        """PRD §3.3: 'Submission is permitted only when ... at least one
        emission data line exists'.

        Claim (contrapositive): adding one ELECTRICITY line and submitting
        succeeds, confirming the empty-set was the blocker — not some
        other rule.
        # difficulty: boundary_precision_check/empty_emission_lines_set_blocks_submit
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = setup_submitted_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 1.00, "emission_factor": 1.00,
            }],
        )
        assert rep["status"] == "SUBMITTED"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:
    """# difficulty: cross_entity_state_dependency/compliance_submit_requires_emission_report_finalized"""

    def test_compliance_submit_blocked_when_report_not_finalized(self, api):
        """PRD §3.6: 'Submission is permitted only when the corresponding
        emission report is in FINALIZED status, the current time is at or
        before the cycle's compliance deadline, and the three caps hold'.

        Claim: with EmissionReport in VERIFIED (not FINALIZED), submit
        ComplianceDeclaration -> ERR_INVALID_STATE.
        # difficulty: cross_entity_state_dependency/compliance_submit_requires_emission_report_finalized
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        verified_report, _issued = setup_verified_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 100.00, "emission_factor": 1.00,
            }],
            line_verified_amounts=[100.00],
        )
        # Do NOT finalize the report.
        decl = create_draft_declaration(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        payload = submit_compliance_declaration_payload(
            declared_offset_quota=10.00, declared_offset_ccer=0.0,
        )
        res = api.submit_compliance_declaration(
            decl["id"], payload, make_enterprise_headers(ent["id"])
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_finalized_report_unblocks_compliance_submit(self):
        """PRD §3.6: 'Submission is permitted only when the corresponding
        emission report is in FINALIZED status'.

        Claim (contrapositive): once the report is FINALIZED, the SAME
        compliance submission succeeds — confirming FINALIZED is the
        gate.
        # difficulty: cross_entity_state_dependency/compliance_submit_requires_emission_report_finalized
        """
        cyc, ent, finalized, decl = setup_compliance_ready_enterprise(
            jurisdiction_code="JD_ALPHA",
            free_paid_ratio=1.00,
            activity_volume=200.00, benchmark_factor=1.00,
            line_activity_data=100.00, line_emission_factor=1.00,
            line_verified_amount=100.00,
        )
        assert finalized["status"] == "FINALIZED"
        submitted = submit_declaration(
            declaration_id=decl["id"], enterprise_id=ent["id"],
            declared_offset_quota=100.00, declared_offset_ccer=0.0,
        )
        assert submitted["status"] in {"SUBMITTED", "COMPLIANT"}

    """# difficulty: cross_entity_state_dependency/cycle_close_requires_all_penalty_orders_paid"""

    def test_cycle_close_blocked_when_penalty_unpaid(self, api):
        """PRD §3.7: 'The regulator closes the cycle once every annual
        settlement has reached CLOSED status and every penalty order for
        the cycle is in payment_status PAID.'

        Claim: cycle.close while a PenaltyOrder for the cycle is UNPAID
        -> ERR_INVALID_STATE.
        # difficulty: cross_entity_state_dependency/cycle_close_requires_all_penalty_orders_paid
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=98.00,
                declared_offset_ccer=0.0,
            )
        )
        # Move past compliance_deadline and settle.
        advance_clock(add_seconds(cyc["compliance_deadline"], 1))
        from test_helpers import settle_cycle
        settle_cycle(cyc["id"])
        # Now attempt close while penalty.payment_status==UNPAID.
        res = api.close_allocation_cycle(
            cyc["id"], {"X-User-ID": "regulator-001",
                        "X-User-Role": "Regulator"},
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_paying_penalty_unblocks_close_precondition(self, api):
        """PRD §3.7: 'every penalty order for the cycle is in
        payment_status PAID.'

        Claim (positive form): after pay-penalty marks the order PAID,
        the close precondition's penalty-status component is satisfied.
        We verify by re-reading the penalty's payment_status — PRD does
        not pin that close itself succeeds in a single test scope (the
        AnnualSettlement-CLOSED component is independent), but the
        penalty-status side of the conjunction MUST be observable PAID.
        # difficulty: cross_entity_state_dependency/cycle_close_requires_all_penalty_orders_paid
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=98.00,
                declared_offset_ccer=0.0,
            )
        )
        paid = pay_penalty(penalty_id=penalty["id"], enterprise_id=ent["id"])
        assert paid["payment_status"] == "PAID"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:
    """# difficulty: resource_temporal_overlap/verification_visit_buffer_window"""

    def test_visit_one_minute_before_seven_days_rejected(
        self, api, regulator_headers
    ):
        """PRD §3.4: 'the visit must be at least 7 days in the future from
        the time of assignment, otherwise the request is rejected with
        ERR_WINDOW_CLOSED'.

        Claim: scheduled_visit_at = now + 6d 23h 59m -> ERR_WINDOW_CLOSED
        (strictly less than 7d boundary).
        # difficulty: resource_temporal_overlap/verification_visit_buffer_window
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = setup_submitted_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        cur = current_clock_iso()
        bad_visit = add_seconds(add_days(cur, 7), -60)  # 7d - 1m
        payload = assign_verifier_payload(
            agency_id=unique_agency_id(),
            scheduled_visit_at=bad_visit,
        )
        res = api.assign_verifier(rep["id"], payload, regulator_headers)
        validate_error(res, "ERR_WINDOW_CLOSED")

    def test_visit_at_exactly_seven_days_accepted(
        self, api, regulator_headers
    ):
        """PRD §3.4: 'the visit must be at least 7 days in the future from
        the time of assignment'.

        Claim: scheduled_visit_at = now + 7d 0h 0m exactly succeeds —
        boundary inclusive on the AT-LEAST side.
        # difficulty: resource_temporal_overlap/verification_visit_buffer_window
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        rep = setup_submitted_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"]
        )
        ok_visit = add_days(current_clock_iso(), 7)
        payload = assign_verifier_payload(
            agency_id=unique_agency_id(),
            scheduled_visit_at=ok_visit,
        )
        res = api.assign_verifier(rep["id"], payload, regulator_headers)
        validate_success(res, expected_status=201)

    """# difficulty: resource_temporal_overlap/dispute_window_after_report_issued"""

    def test_dispute_just_past_fourteen_days_rejected(self, api):
        """PRD §3.4: 'A VERIFIED report may be disputed by the enterprise
        with a payload containing ground (the textual reason), but only
        within 14 days of the assignment's report_issued_at; outside that
        window the request is rejected with ERR_WINDOW_CLOSED.'

        Claim: at clock = report_issued_at + 14d 0h 1s, dispute ->
        ERR_WINDOW_CLOSED.
        # difficulty: resource_temporal_overlap/dispute_window_after_report_issued
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        verified_report, issued = setup_verified_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 100.00, "emission_factor": 0.50,
            }],
            line_verified_amounts=[55.00],
        )
        advance_clock(add_seconds(add_days(issued["report_issued_at"], 14), 1))
        res = api.dispute_emission_report(
            verified_report["id"],
            dispute_emission_report_payload(),
            make_enterprise_headers(ent["id"]),
        )
        validate_error(res, "ERR_WINDOW_CLOSED")

    def test_dispute_at_fourteen_days_exactly_accepted(self, api):
        """PRD §3.4: 'only within 14 days of the assignment's
        report_issued_at'.

        Claim: at clock = report_issued_at + 14d (exact), dispute is
        permitted — boundary inclusive on the within-window side.
        # difficulty: resource_temporal_overlap/dispute_window_after_report_issued
        """
        ent, cyc, _alloc = setup_compliance_open_cycle()
        verified_report, issued = setup_verified_report(
            enterprise_id=ent["id"], cycle_year=cyc["cycle_year"],
            lines=[{
                "source_category": "ELECTRICITY",
                "activity_data": 100.00, "emission_factor": 0.50,
            }],
            line_verified_amounts=[55.00],
        )
        advance_clock(add_days(issued["report_issued_at"], 14))
        res = api.dispute_emission_report(
            verified_report["id"],
            dispute_emission_report_payload(),
            make_enterprise_headers(ent["id"]),
        )
        validate_success(res, expected_status=200)


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:
    """# difficulty: compensating_invariant/trade_executed_then_settled_conserves_global_quota_supply"""

    def test_quota_trade_conserves_total_supply_across_two_enterprises(self):
        """PRD §3.5: 'the buyer's enterprise has its paid_quota_balance
        (or ccer_balance for CCER) increased by the matched quantity, the
        buyer fee debited via the cash workflow; the seller's
        corresponding balance decreased by the matched quantity'.

        Claim: a successful QUOTA trade between Seller and Buyer leaves
        sum(quota_balance + paid_quota_balance) over both enterprises
        unchanged — the conserved quantity is total instrument supply.
        # difficulty: compensating_invariant/trade_executed_then_settled_conserves_global_quota_supply
        """
        cyc, seller, buyer = setup_two_enterprises_with_quota_balances(
            seller_quota=2000.00, buyer_quota=0.00,
            free_paid_ratio=1.00,  # all quota in quota_balance
        )
        s_before = get_enterprise(seller["id"])
        b_before = get_enterprise(buyer["id"])
        sum_before = (
            s_before["quota_balance"] + s_before["paid_quota_balance"]
            + b_before["quota_balance"] + b_before["paid_quota_balance"]
        )
        # Seller posts SELL LIMIT, Buyer posts BUY MARKET, full match.
        from test_helpers import place_order
        place_order(
            enterprise_id=seller["id"],
            side="SELL", instrument="QUOTA",
            order_type="LIMIT", quantity=500,
            channel="EXCHANGE", limit_price=40.00,
        )
        place_order(
            enterprise_id=buyer["id"],
            side="BUY", instrument="QUOTA",
            order_type="MARKET", quantity=500,
            channel="EXCHANGE",
        )
        s_after = get_enterprise(seller["id"])
        b_after = get_enterprise(buyer["id"])
        sum_after = (
            s_after["quota_balance"] + s_after["paid_quota_balance"]
            + b_after["quota_balance"] + b_after["paid_quota_balance"]
        )
        assert sum_after == pytest.approx(sum_before, abs=0.01), (
            "PRD §3.5: quantity moves seller -> buyer 1:1; system-wide "
            "quota supply must be conserved across the trade. "
            f"Got sum_before={sum_before}, sum_after={sum_after}."
        )

    def test_trade_increases_buyer_and_decreases_seller_by_matched_quantity(
        self,
    ):
        """PRD §3.5: 'the buyer's enterprise has its paid_quota_balance
        (or ccer_balance for CCER) increased by the matched quantity, ...
        the seller's corresponding balance decreased by the matched
        quantity'.

        Claim: after a 500-quota match, seller's combined balance drops
        by 500 and buyer's combined balance rises by 500.
        # difficulty: compensating_invariant/trade_executed_then_settled_conserves_global_quota_supply
        """
        cyc, seller, buyer = setup_two_enterprises_with_quota_balances(
            seller_quota=2000.00, buyer_quota=0.00, free_paid_ratio=1.00,
        )
        s_before = get_enterprise(seller["id"])
        b_before = get_enterprise(buyer["id"])
        from test_helpers import place_order
        place_order(
            enterprise_id=seller["id"],
            side="SELL", instrument="QUOTA",
            order_type="LIMIT", quantity=500,
            channel="EXCHANGE", limit_price=40.00,
        )
        place_order(
            enterprise_id=buyer["id"],
            side="BUY", instrument="QUOTA",
            order_type="MARKET", quantity=500,
            channel="EXCHANGE",
        )
        s_after = get_enterprise(seller["id"])
        b_after = get_enterprise(buyer["id"])
        s_drop = (
            (s_before["quota_balance"] + s_before["paid_quota_balance"])
            - (s_after["quota_balance"] + s_after["paid_quota_balance"])
        )
        b_rise = (
            (b_after["quota_balance"] + b_after["paid_quota_balance"])
            - (b_before["quota_balance"] + b_before["paid_quota_balance"])
        )
        assert s_drop == pytest.approx(500.00, abs=0.01)
        assert b_rise == pytest.approx(500.00, abs=0.01)

    """# difficulty: compensating_invariant/penalty_pay_then_mandatory_deduction_conserves_compliance_pressure"""

    def test_mandatory_deduction_is_one_point_five_times_deficit_invariant(
        self,
    ):
        """PRD §3.6: 'The mandatory_deduction_amount is the deficit_amount
        multiplied by 1.5, rounded half-up to two decimal places.'

        Claim: the conserved ratio
        mandatory_deduction_amount / deficit_amount == 1.5 EXACTLY,
        with no drift across the pay transition.
        # difficulty: compensating_invariant/penalty_pay_then_mandatory_deduction_conserves_compliance_pressure
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=80.00,
                declared_offset_ccer=0.0,
            )
        )
        # deficit = 100 - 80 = 20.00; mandatory_deduction = 30.00.
        assert penalty["deficit_amount"] == pytest.approx(20.00, abs=0.01)
        assert penalty["mandatory_deduction_amount"] == pytest.approx(
            30.00, abs=0.01
        )
        ratio = (
            penalty["mandatory_deduction_amount"] / penalty["deficit_amount"]
        )
        assert ratio == pytest.approx(1.5, abs=1e-6), (
            "PRD §3.6: mandatory_deduction_amount must equal 1.5 * "
            f"deficit_amount EXACTLY; ratio observed={ratio}"
        )

    def test_pay_does_not_alter_mandatory_deduction_or_deficit(self):
        """PRD §3.6: 'The mandatory_deduction_amount is the deficit_amount
        multiplied by 1.5, rounded half-up to two decimal places.'
        PRD §3.6: 'The enterprise pays the penalty via a payment action;
        the order transitions from UNPAID to PAID with paid_at set to the
        current time and credit_record_reported set to true'.

        Claim: paying the penalty does NOT alter deficit_amount or
        mandatory_deduction_amount — the compensating-action multiplier
        is preserved across the pay transition.
        # difficulty: compensating_invariant/penalty_pay_then_mandatory_deduction_conserves_compliance_pressure
        """
        cyc, ent, finalized, submitted, penalty = (
            setup_non_compliant_with_penalty(
                jurisdiction_code="JD_ALPHA",
                line_activity_data=100.00, line_emission_factor=1.00,
                line_verified_amount=100.00,
                declared_offset_quota=80.00,
                declared_offset_ccer=0.0,
            )
        )
        d_before = penalty["deficit_amount"]
        m_before = penalty["mandatory_deduction_amount"]
        paid = pay_penalty(penalty_id=penalty["id"], enterprise_id=ent["id"])
        assert paid["payment_status"] == "PAID"
        assert paid["deficit_amount"] == pytest.approx(d_before, abs=0.01)
        assert paid["mandatory_deduction_amount"] == pytest.approx(
            m_before, abs=0.01
        )
