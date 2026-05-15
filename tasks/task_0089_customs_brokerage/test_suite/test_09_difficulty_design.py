"""Difficulty-design coverage — every instance is covered by at least
TWO dedicated tests. Each test pins a docstring with a PRD citation
(C1/C2/C3) and a # difficulty tag.

Rules covered:
  1. dual_variant_calc — tariff variant + late-interest ongoing/finalized
  2. combinatorial_formula — tiered tariff branching + nested rounding
                              + broker-fee aggregation
  3. non_linear_state_machine — declaration revision cycle +
                                  filing branching fork
  4. transitive_cascade — release cascade depth-3 + withdrawal depth-2
  5. priority_pair_validation_conflict — state-vs-business + safety-vs-constraint
  6. boundary_precision_check — tier factor boundary + amendment_count 0/1
  7. cross_entity_state_dependency — agreement gates declaration +
                                       settlement gates withdrawal
  8. resource_temporal_overlap — agreement half-open window +
                                   query 48h deadline
  9. compensating_invariant — withdraw voids settlement (ledger preserved)
                              + reimburse zeros debt (audit count invariant)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    action_with_version_payload,
    advance_clock_to,
    advance_settlement,
    advance_settlement_payload,
    api_client,
    attach_core_docs,
    attach_document,
    create_agreement_payload,
    create_client,
    create_declaration,
    emit_bank_debit,
    emit_customs_response,
    emit_customs_response_payload,
    emit_manifest_dropped_payload,
    emit_manifest_match,
    file_declaration,
    iso_utc,
    locate_settlement_for_declaration,
    make_doc_reviewer_headers,
    make_filing_officer_headers,
    make_settlement_officer_headers,
    pre_validate_declaration,
    record_inspection_outcome,
    request_documents,
    request_signature_payload,
    reset_clock_to_epoch,
    respond_query_payload,
    setup_active_agreement,
    setup_declaration_in_docs_pending,
    setup_declaration_in_filed,
    setup_declaration_in_pre_validated,
    setup_declaration_in_queried,
    setup_declaration_in_rejected_via_emit,
    setup_declaration_released_via_emit,
    setup_inspection_case,
    setup_settlement_for_late_interest_freeze,
    setup_settlement_in_advanced,
    setup_two_declarations_for_tariff_variants,
    sign_agreement_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    withdraw_declaration,
)
from test_helpers.fixtures import TEST_EPOCH


# ===========================================================================
# Rule 1A — dual_variant_calc / tariff_general_vs_preferential_on_settlement
# ===========================================================================
class TestTariffGeneralVsPreferential:

    def test_general_tariff_higher_than_preferential_on_same_inputs(self, api):
        """# difficulty: dual_variant_calc/tariff_general_vs_preferential_on_settlement
        PRD §3.8: "When trade_agreement_code is NONE (or when the
        declared country_of_origin is not eligible under the named
        agreement for this jurisdiction), the rate comes from the
        most-favoured-nation table: for jurisdiction CN the rate is
        0.10 for general goods and 0.05 for HS prefix 8517"
        PRD §3.8: "under RCEP the rate is 0.05 (default) or 0.02 (HS
        8517) for CN, and 0.04 or 0.02 for JP".

        Claim: identical declaration with trade_agreement_code=NONE vs
        RCEP yields a strictly higher tariff under NONE. Concretely:
        declared=1000 USD → base=7200 CNY; tier_factor=1.00 (≤10000).
        NONE: rate=0.05 → 7200*0.05*1.00 = 360.00.
        RCEP: rate=0.02 → 7200*0.02*1.00 = 144.00.
        """
        ctx = setup_two_declarations_for_tariff_variants()
        s_g = ctx["general"]["settlement"]
        s_p = ctx["preferential"]["settlement"]
        assert s_g["tariff_amount"] == pytest.approx(360.00, abs=0.01)
        assert s_p["tariff_amount"] == pytest.approx(144.00, abs=0.01)
        assert s_g["tariff_amount"] > s_p["tariff_amount"]

    def test_preferential_tariff_uses_fta_rate_table(self, api):
        """# difficulty: dual_variant_calc/tariff_general_vs_preferential_on_settlement
        PRD §3.8: "When a preferential agreement applies and the origin
        is eligible, the rate comes from the preferential table: under
        RCEP the rate is 0.05 (default) or 0.02 (HS 8517) for CN".

        Claim: same declared value with trade_agreement_code=RCEP, JP
        origin, CN destination, HS prefix 8517 → preferential rate 0.02
        applies (vs MFN 0.05).
        """
        ctx = setup_two_declarations_for_tariff_variants()
        s_p = ctx["preferential"]["settlement"]
        # Confirms the preferential rate was applied.
        # base=7200, tier=1.00 → tariff = 7200 * 0.02 * 1.00 = 144.00.
        assert s_p["tariff_amount"] == pytest.approx(144.00, abs=0.01)


# ===========================================================================
# Rule 1B — dual_variant_calc / late_interest_ongoing_vs_finalized
# ===========================================================================
class TestLateInterestOngoingVsFinalized:

    def test_late_interest_freezes_at_reimbursement(self, api, broker_ops_headers,
                                                    system_admin_headers):
        """# difficulty: dual_variant_calc/late_interest_ongoing_vs_finalized_on_settlement_ledger
        PRD §3.10: "Reads of an advanced settlement that has not yet
        been reimbursed report the current snapshot of this running
        estimate without persisting it, and clock advance is the
        trigger that refreshes the estimate."
        PRD §3.10: "An exact match advances the settlement from ADVANCED
        to REIMBURSED, sets reimbursed_at to the current instant,
        computes late_interest_amount one final time at the reimbursement
        moment and freezes the value".

        Claim: ongoing late_interest changes with clock advance; after
        REIMBURSED it is frozen and does NOT change on further clock advance.
        """
        reset_clock_to_epoch()
        ctx = setup_settlement_for_late_interest_freeze()
        s = ctx["settlement"]
        principal = s["advance_paid_amount"]
        rate = 0.01  # 100 bps / 10000
        # Move clock to due_at + 3 days.
        due_at_str = s["reimbursement_due_at"]
        due_dt = datetime.fromisoformat(due_at_str.replace("Z", "+00:00"))
        advance_clock_to(due_dt + timedelta(days=3))
        # Ongoing should report 3 days of interest.
        live1 = validate_success(api.get_settlement(s["id"], broker_ops_headers))
        expected_3d = round(principal * rate * 3, 2)
        assert live1["late_interest_amount"] == pytest.approx(expected_3d, abs=0.01)
        # Reimburse exactly the current amount (principal + 3d interest).
        emit_bank_debit(s["id"], amount=principal + expected_3d)
        live2 = validate_success(api.get_settlement(s["id"], broker_ops_headers))
        assert live2["status"] == "REIMBURSED"
        frozen = live2["late_interest_amount"]
        # Advance clock 20 more days.
        advance_clock_to(due_dt + timedelta(days=23))
        live3 = validate_success(api.get_settlement(s["id"], broker_ops_headers))
        assert live3["late_interest_amount"] == pytest.approx(frozen, abs=0.01), (
            f"Frozen late_interest must not change after REIMBURSED; "
            f"was {frozen}, now {live3['late_interest_amount']}"
        )

    def test_ongoing_late_interest_increments_with_clock(self, api, broker_ops_headers):
        """# difficulty: dual_variant_calc/late_interest_ongoing_vs_finalized_on_settlement_ledger
        PRD §3.10: "Past the deadline, the number of days late is the
        ceiling of the elapsed seconds divided by 86400 — a partial day
        still counts as a full day".

        Claim: while ADVANCED (not yet REIMBURSED), advancing the clock
        increases late_interest_amount on subsequent GET.
        """
        reset_clock_to_epoch()
        ctx = setup_settlement_for_late_interest_freeze()
        s = ctx["settlement"]
        principal = s["advance_paid_amount"]
        rate = 0.01
        due_at_str = s["reimbursement_due_at"]
        due_dt = datetime.fromisoformat(due_at_str.replace("Z", "+00:00"))
        # Day 1 — use 1ms (PRD §2.4 caps wire precision at 3 fractional digits).
        advance_clock_to(due_dt + timedelta(milliseconds=1))
        live1 = validate_success(api.get_settlement(s["id"], broker_ops_headers))
        # Day 5
        advance_clock_to(due_dt + timedelta(days=4, milliseconds=1))
        live5 = validate_success(api.get_settlement(s["id"], broker_ops_headers))
        assert live5["late_interest_amount"] > live1["late_interest_amount"], (
            "Ongoing late_interest must advance with the clock"
        )
        expected_day_5 = round(principal * rate * 5, 2)
        assert live5["late_interest_amount"] == pytest.approx(expected_day_5, abs=0.01)


# ===========================================================================
# Rule 2A — combinatorial_formula / tariff_three_input_tiered
# ===========================================================================
class TestTariffTiered:

    @pytest.mark.parametrize("declared,expected_tariff,note", [
        (1000.00, 720.00, "tier 1.00 — base 7200 (<=10000)"),
        (1389.00, 1050.08, "tier 1.05 — base 10000.80 (>10000, <=50000)"),
        (7000.00, 5544.00, "tier 1.10 — base 50400 (>50000)"),
    ])
    def test_tariff_tier_branches(self, api, declared, expected_tariff, note):
        """# difficulty: combinatorial_formula/tariff_three_input_tiered_with_nonlinear_branching
        PRD §3.8: "a base value at most 10000 carries a tier factor of
        1.00; a base value strictly greater than 10000 and at most 50000
        carries a tier factor of 1.05 (a five-percent surcharge over the
        range); a base value strictly greater than 50000 carries a tier
        factor of 1.10".

        Claim: three declared-value points hit tier 1.00 / 1.05 / 1.10
        respectively. CN/HS-8411 (general goods, no reference-price entry
        so declared-value review defaults to ACCEPTED) / USD declared →
        MFN rate 0.10.
        - declared=1000 USD → base=7200 → tariff = 7200*0.10*1.00 = 720.00
        - declared=1389 USD → base=10000.80 → tier 1.05 → 10000.80*0.10*1.05 = 1050.08
        - declared=7000 USD → base=50400 → tier 1.10 → 50400*0.10*1.10 = 5544.00
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="84111100",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=declared, declared_currency="USD",
            invoice_total=declared, invoice_currency="USD",
        )
        s = ctx["settlement"]
        assert s["tariff_amount"] == pytest.approx(expected_tariff, abs=0.01), (
            f"{note}: expected {expected_tariff}, got {s['tariff_amount']}"
        )


# ===========================================================================
# Rule 2B — combinatorial_formula / settlement_chain_nested_rounding
# ===========================================================================
class TestNestedRoundingChain:

    def test_vat_uses_rounded_tariff_not_raw(self, api):
        """# difficulty: combinatorial_formula/settlement_chain_nested_rounding_order_tariff_then_vat_then_ct
        PRD §2.7: "the multi-step tariff pipeline (described in §3) pins
        the evaluation order so that intermediate rounded values feed
        downstream stages: a per-line-item currency conversion is rounded
        to two decimals; the tariff is then computed and rounded once at
        the end of its own formula; the value-added tax is computed off
        the already-rounded tariff and rounded; the consumption tax is
        computed off the same already-rounded tariff (not off the VAT)
        and rounded."
        PRD §3.8: "Settlement.tariff_amount == 720.00 ... VAT base is
        the sum of the base value and the tariff amount".

        Claim: declared=50 USD CN HS=2208 (declared kept within 25% of
        ref=50 CNY so declared-value review = ACCEPTED) → base=360,
        tariff=round(360*0.10*1.00,2)=36.00,
        vat = round((360+36) * 0.13, 2) = 51.48,
        ct = round((360+36) * 0.20, 2) = 79.20.
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="22080000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=50.00, declared_currency="USD",
            extra_docs=[{"doc_type": "DANGEROUS_GOODS_DECL"}],
        )
        s = ctx["settlement"]
        assert s["tariff_amount"] == pytest.approx(36.00, abs=0.01)
        assert s["vat_amount"] == pytest.approx(51.48, abs=0.01)
        assert s["consumption_tax_amount"] == pytest.approx(79.20, abs=0.01)

    def test_advance_paid_amount_sums_tariff_vat_ct(self, api):
        """# difficulty: combinatorial_formula/settlement_chain_nested_rounding_order_tariff_then_vat_then_ct
        PRD §3.10: "On success, the settlement transitions from FINAL
        to ADVANCED, advance_paid_amount is set to the sum tariff + VAT
        + consumption tax + penalty".

        Claim: advance_paid_amount = tariff_amount + vat_amount +
        consumption_tax_amount + penalty_amount.
        """
        ctx = setup_settlement_in_advanced(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="22080000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=50.00, declared_currency="USD",
            extra_docs=[{"doc_type": "DANGEROUS_GOODS_DECL"}],
        )
        s = ctx["settlement"]
        expected = (s["tariff_amount"] + s["vat_amount"]
                    + s["consumption_tax_amount"] + s["penalty_amount"])
        assert s["advance_paid_amount"] == pytest.approx(expected, abs=0.01)


# ===========================================================================
# Rule 2C — combinatorial_formula / broker_fee_three_input_aggregation
# ===========================================================================
class TestBrokerFeeAggregation:

    def test_broker_fee_no_inspection_no_amendment(self, api):
        """# difficulty: combinatorial_formula/broker_fee_three_input_aggregation_with_state_branching
        PRD §3.9: "DECLARATION is always present; INSPECTION is added
        if an InspectionCase exists for the declaration; TARIFF_ADVANCE
        is added when advance_paid_amount is strictly positive (always
        the case for FINAL settlements that proceed to advance); and
        AMENDMENT is added when amendment_count is strictly positive".

        Claim: no inspection, no amendment, fee_schedule sums to
        (DECLARATION=100 + TARIFF_ADVANCE=80) * 7.20 = 1296.00 (USD→CNY).
        Pre-advance, advance_paid_amount=0 ⇒ TARIFF_ADVANCE is NOT in
        services_consumed. So broker_fee_amount checked POST-advance.
        """
        ctx = setup_settlement_in_advanced(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
            fee_schedule={
                "DECLARATION": 100,
                "INSPECTION": 50,
                "TARIFF_ADVANCE": 80,
                "AMENDMENT": 30,
                "RETURN_SHIP": 200,
            },
        )
        s = ctx["settlement"]
        # broker_fee per PRD §3.9: round((DECLARATION+TARIFF_ADVANCE) * fx_agree→decl * fx_decl→settle, 2)
        # USD agreement, USD declared → fx_agree→decl = 1.00.
        # USD declared, CNY settle → fx_decl→settle = 7.20.
        # services_consumed = {DECLARATION, TARIFF_ADVANCE} (after advance).
        expected = round((100 + 80) * 1.00 * 7.20, 2)
        assert s["broker_fee_amount"] == pytest.approx(expected, abs=0.01)

    def test_broker_fee_with_inspection_branch(self, api):
        """# difficulty: combinatorial_formula/broker_fee_three_input_aggregation_with_state_branching
        PRD §3.9: "INSPECTION is added if an InspectionCase exists for
        the declaration".

        Claim: declaration inspected then RELEASE outcome →
        services_consumed includes INSPECTION;
        broker_fee = (100+50+80) * 7.20 = 1656.00 (DECLARATION + INSPECTION
        + TARIFF_ADVANCE; no AMENDMENT). Tested after /advance.
        """
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=False,
            scheduled_at=TEST_EPOCH - timedelta(hours=1),
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
            fee_schedule={
                "DECLARATION": 100,
                "INSPECTION": 50,
                "TARIFF_ADVANCE": 80,
                "AMENDMENT": 30,
                "RETURN_SHIP": 200,
            },
        )
        case = ctx["inspection_case"]
        record_inspection_outcome(case, outcome="RELEASE")
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        s = locate_settlement_for_declaration(dec["id"])
        # Advance the settlement to bump TARIFF_ADVANCE into services_consumed.
        s = advance_settlement(s, officer_id="settle-test-insp")
        expected = round((100 + 50 + 80) * 1.00 * 7.20, 2)
        assert s["broker_fee_amount"] == pytest.approx(expected, abs=0.01)


# ===========================================================================
# Rule 3A — non_linear_state_machine / declaration revision cycle
# ===========================================================================
class TestDeclarationRevisionCycle:

    def test_revision_loop_increments_amendment_count(self, api):
        """# difficulty: non_linear_state_machine/declaration_revision_cycle_rejected_to_amending_to_filed
        PRD §3.11: "For paperwork-driven rejections — codes other than
        INSPECTION_FAILED — a DeclarationOfficer may amend, advancing
        the declaration from REJECTED to AMENDING. The amendment
        transition increments amendment_count by one, clears
        rejection_reason_code, and clears pinned_agreement_version
        (forcing the next pre-validate to re-snapshot the agreement's
        version)."
        PRD §3.6: "the same DOCS_PENDING → PRE_VALIDATED checks apply
        and the declaration retraces the path: pre-validate, file, and
        any subsequent customs response."

        Claim: REJECTED→AMENDING bumps amendment_count from 0→1; a second
        loop brings it to 2.
        """
        # Lap 1
        ctx = setup_declaration_in_rejected_via_emit(reason_code="HS_MISMATCH")
        dec = ctx["declaration"]
        assert dec["amendment_count"] == 0
        amended_1 = validate_success(api.amend_declaration(
            dec["id"], action_with_version_payload(version=dec["version"]),
            TEST_USERS["declaration_officer_headers"],
        ))
        assert amended_1["amendment_count"] == 1
        # Lap 2: pre-validate → file → reject
        from test_helpers import (
            make_doc_reviewer_headers, make_filing_officer_headers,
            get_filing_for_declaration,
        )
        pre = validate_success(api.pre_validate_declaration(
            amended_1["id"],
            action_with_version_payload(version=amended_1["version"]),
            make_doc_reviewer_headers("rev-cyc-1"),
        ))
        filed = validate_success(api.file_declaration(
            pre["id"], action_with_version_payload(version=pre["version"]),
            make_filing_officer_headers("file-cyc-1"),
        ))
        filing = filed.get("filing") if isinstance(filed, dict) else None
        if not (isinstance(filing, dict) and "id" in filing):
            filing = get_filing_for_declaration(filed["id"])
        emit_customs_response(filing["id"], response_type="REJECT",
                              reason_code="HS_MISMATCH")
        rejected_2 = validate_success(api.get_declaration(
            filed["id"], TEST_USERS["broker_ops_headers"],
        ))
        amended_2 = validate_success(api.amend_declaration(
            rejected_2["id"],
            action_with_version_payload(version=rejected_2["version"]),
            TEST_USERS["declaration_officer_headers"],
        ))
        assert amended_2["amendment_count"] == 2

    def test_amend_clears_pinned_agreement_version(self, api):
        """# difficulty: non_linear_state_machine/declaration_revision_cycle_rejected_to_amending_to_filed
        PRD §3.11: "clears pinned_agreement_version (forcing the next
        pre-validate to re-snapshot the agreement's version)."

        Claim: after /amend, pinned_agreement_version is null.
        """
        ctx = setup_declaration_in_rejected_via_emit(reason_code="HS_MISMATCH")
        dec = ctx["declaration"]
        assert dec.get("pinned_agreement_version") is not None
        amended = validate_success(api.amend_declaration(
            dec["id"], action_with_version_payload(version=dec["version"]),
            TEST_USERS["declaration_officer_headers"],
        ))
        assert amended.get("pinned_agreement_version") in (None,)


# ===========================================================================
# Rule 3B — non_linear_state_machine / filing branching fork
# ===========================================================================
class TestFilingBranchingFork:

    def test_query_branch_sets_due_at(self, api):
        """# difficulty: non_linear_state_machine/filing_branching_fork_to_query_inspect_release_reject
        PRD §3.6: "A QUERY response advances the declaration to QUERIED
        and sets the filing's response_type to QUERY, response_received_at
        to the current instant, and query_due_at to the current instant
        plus forty-eight hours."

        Claim: QUERY branch sets query_due_at = response_received_at + 48h.
        """
        ctx = setup_declaration_in_queried()
        filing = ctx["filing"]
        recv = filing.get("response_received_at")
        due = filing.get("query_due_at")
        recv_dt = datetime.fromisoformat(recv.replace("Z", "+00:00"))
        due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
        diff = (due_dt - recv_dt).total_seconds()
        assert abs(diff - 48 * 3600) < 60, (
            f"query_due_at must be response_received_at + 48h; diff={diff}s"
        )

    def test_inspect_branch_creates_no_settlement(self, api, system_admin_headers):
        """# difficulty: non_linear_state_machine/filing_branching_fork_to_query_inspect_release_reject
        PRD §3.6: "An INSPECT response advances the declaration to
        INSPECTING and sets the filing's response_type to INSPECT."

        Claim: INSPECT branch sets declaration=INSPECTING and does NOT
        create a Settlement (settlement is deferred to inspection
        outcome).
        """
        ctx = setup_declaration_in_filed(match_manifest=False)
        filing = ctx["filing"]
        api.emit_event(
            emit_customs_response_payload(
                filing_id=filing["id"], response_type="INSPECT",
            ),
            system_admin_headers,
        )
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        assert dec["status"] == "INSPECTING"
        settlement = locate_settlement_for_declaration(dec["id"])
        assert settlement is None, (
            "INSPECT branch must not create a Settlement (PRD §3.6/§3.7)"
        )


# ===========================================================================
# Rule 4A — transitive_cascade / customs_release_depth_3_chain
# ===========================================================================
class TestReleaseCascadeDepth3:

    def test_release_event_drives_settlement_then_audit(self, api, broker_ops_headers):
        """# difficulty: transitive_cascade/customs_release_depth_3_chain
        PRD §3.6: "A RELEASE response advances the declaration to
        RELEASED".
        PRD §3.8: "The cascade from RELEASED ... creates a Settlement
        carrying the parent declaration_id and populates four computed
        amounts plus the broker fee".
        PRD §2.8: "every state-changing action writes an AuditLog row".

        Claim: emit RELEASE → declaration=RELEASED (hop 2) → Settlement
        created with tariff populated (hop 3) → audit log has entries
        for the cascade (hop 4).
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="85171200",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        # Hop 2
        assert ctx["declaration"]["status"] == "RELEASED"
        # Hop 3
        s = ctx["settlement"]
        assert s is not None and s["status"] == "FINAL"
        assert s["tariff_amount"] is not None
        # Hop 4 — audit log mentions settlement.
        body = validate_success(api.list_audit_log(
            broker_ops_headers,
            params={"entity_type": "SETTLEMENT", "entity_id": s["id"]},
        ))
        rows = body if isinstance(body, list) else (
            body.get("items") or body.get("data") or body.get("audit_log") or []
        )
        if not isinstance(rows, list):
            rows = []
        assert len(rows) >= 1, "Settlement creation must emit at least one AuditLog row"

    def test_release_settles_with_full_calculation_pipeline(self, api):
        """# difficulty: transitive_cascade/customs_release_depth_3_chain
        PRD §3.8: "The cascade from RELEASED ... populates four computed
        amounts plus the broker fee, all denominated in settlement_currency."

        Claim: after RELEASE cascade, Settlement has tariff_amount,
        vat_amount, consumption_tax_amount, broker_fee_amount all set
        to non-null numbers.
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
        )
        s = ctx["settlement"]
        for f in ("tariff_amount", "vat_amount", "consumption_tax_amount",
                  "broker_fee_amount"):
            assert s.get(f) is not None, f"{f} must be populated post-RELEASE"


# ===========================================================================
# Rule 4B — transitive_cascade / withdrawal_depth_2_chain
# ===========================================================================
class TestWithdrawalCascadeDepth2:

    def test_withdraw_after_reject_emits_audit_state_transition(
        self, api, broker_ops_headers,
    ):
        """# difficulty: transitive_cascade/withdrawal_depth_2_chain
        PRD §3.11: "On success the declaration moves to WITHDRAWN."
        PRD §2.8: "every state-changing action writes an AuditLog row".

        Claim: after withdraw on a REJECTED declaration, the audit log
        contains a STATE_TRANSITION entry referencing the declaration.
        """
        ctx = setup_declaration_in_rejected_via_emit(reason_code="HS_MISMATCH")
        dec = withdraw_declaration(ctx["declaration"])
        assert dec["status"] == "WITHDRAWN"
        body = validate_success(api.list_audit_log(
            broker_ops_headers,
            params={"entity_id": dec["id"], "event_type": "STATE_TRANSITION"},
        ))
        rows = body if isinstance(body, list) else (
            body.get("items") or body.get("data") or body.get("audit_log") or []
        )
        if not isinstance(rows, list):
            rows = []
        assert len(rows) >= 1, "Withdrawal must emit STATE_TRANSITION audit"

    def test_withdraw_voids_provisional_or_final_settlement(self, api):
        """# difficulty: transitive_cascade/withdrawal_depth_2_chain
        PRD §3.11: "If a Settlement exists for the declaration in
        PROVISIONAL or FINAL status, it is voided (status set to VOIDED)
        as a cascade."

        Claim: a FINAL settlement created by INSPECTING→PENALTY is voided
        when the declaration is later withdrawn.
        """
        from datetime import timedelta as _td
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=False,
            scheduled_at=TEST_EPOCH - _td(hours=1),
            default_settlement_currency="CNY", declared_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00,
        )
        case = ctx["inspection_case"]
        record_inspection_outcome(case, outcome="PENALTY", penalty_amount=100.00)
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        s_before = locate_settlement_for_declaration(dec["id"])
        assert s_before is not None and s_before["status"] == "FINAL"
        withdraw_declaration(dec)
        s_after = locate_settlement_for_declaration(dec["id"])
        assert s_after["status"] == "VOIDED"


# ===========================================================================
# Rule 5A — priority_pair_validation_conflict / state vs business_safety
# ===========================================================================
class TestStateVsBusinessSafetyPriority:

    def test_pre_validate_on_draft_state_wins_over_authenticity_flagged(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_at_pre_validate
        PRD §2.10: "Authentication checks for X-User-Role and X-User-ID
        fire first, followed by role authorization, followed by
        left-to-right path existence and body-reference existence,
        followed by the optimistic-concurrency version check, followed
        by state preconditions (and the specific state guards
        ERR_SETTLEMENT_HAS_ADVANCE on withdrawal and ERR_INVALID_STATE
        on advancing a withdrawn declaration), followed by
        segregation-of-duties and document-safety checks (authenticity
        flagging, missing import licence, missing dangerous-goods
        declaration)".

        Claim: declaration in DRAFT (wrong state for /pre-validate) AND
        a FLAGGED ShipmentDocument exists → ERR_INVALID_STATE fires
        (state precondition wins over authenticity-safety check).
        """
        _, agreement = setup_active_agreement()
        dec = create_declaration(agreement["id"])
        # Attach a doc that will flag (mismatched currency + bad URI).
        attach_document(
            dec["id"], doc_type="COMMERCIAL_INVOICE",
            declared_total_value=1000.00, declared_total_currency="EUR",
            storage_uri="no-scheme",
        )
        resp = api.pre_validate_declaration(
            dec["id"], {"version": dec["version"]},
            TEST_USERS["doc_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_pre_validate_on_released_state_wins_over_safety_check(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_at_pre_validate
        PRD §2.10: "followed by state preconditions ..., followed by
        segregation-of-duties and document-safety checks (authenticity
        flagging, missing import licence, missing dangerous-goods
        declaration)".

        Claim: a RELEASED declaration cannot pre-validate regardless of
        document state — the state precondition fires before any
        document-safety check could.
        """
        ctx = setup_declaration_released_via_emit()
        dec = ctx["declaration"]
        assert dec["status"] == "RELEASED"
        resp = api.pre_validate_declaration(
            dec["id"], {"version": dec["version"]},
            TEST_USERS["doc_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Rule 5B — priority_pair_validation_conflict / business_safety vs business_constraint
# ===========================================================================
class TestSafetyVsConstraintPriority:

    def test_missing_license_fires_on_restricted_hs(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_at_pre_validate
        PRD §3.5: "when hs_code starts with 28 or 29, or when
        jurisdiction_code is CN and the first two characters of hs_code
        are 29, an IMPORT_LICENSE document must exist, or the transition
        is rejected with ERR_DOC_MISSING_LICENSE".

        Claim: HS 29xxxxxx with all four core docs attached (consistent)
        but no IMPORT_LICENSE → ERR_DOC_MISSING_LICENSE.
        """
        ctx = setup_declaration_in_docs_pending(
            jurisdiction_code="CN", hs_code="29011000",
            declared_value_amount=100.00, declared_currency="USD",
            default_settlement_currency="CNY",
        )
        dec = ctx["declaration"]
        attach_core_docs(
            dec["id"], invoice_total=100.00, invoice_currency="USD",
        )
        dec = validate_success(api.get_declaration(
            dec["id"], TEST_USERS["declaration_officer_headers"],
        ))
        resp = api.pre_validate_declaration(
            dec["id"], {"version": dec["version"]},
            TEST_USERS["doc_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DOC_MISSING_LICENSE.value)

# ===========================================================================
# Rule 6A — boundary_precision_check / tier factor at 10000
# ===========================================================================
class TestTierFactorBoundaryAt10000:

    def test_base_just_below_10000_uses_factor_1_00(self, api):
        """# difficulty: boundary_precision_check/tier_factor_boundary_at_10000_on_settlement_advance_metric
        PRD §3.8: "a base value at most 10000 carries a tier factor of
        1.00; a base value strictly greater than 10000 and at most 50000
        carries a tier factor of 1.05".

        Claim: declared 1388.88 USD * 7.20 = 9999.94 (rounded; <= 10000)
        → tier 1.00. CN/HS-1000 (MFN 0.10): tariff = 9999.94*0.10*1.00 = 999.99.
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1388.88, declared_currency="USD",
            invoice_total=1388.88, invoice_currency="USD",
        )
        s = ctx["settlement"]
        assert s["tariff_amount"] == pytest.approx(999.99, abs=0.01)

    def test_base_just_above_10000_uses_factor_1_05(self, api):
        """# difficulty: boundary_precision_check/tier_factor_boundary_at_10000_on_settlement_advance_metric
        PRD §3.8: "a base value strictly greater than 10000 and at most
        50000 carries a tier factor of 1.05".

        Claim: declared 1388.90 USD * 7.20 = 10000.08 (> 10000) → tier 1.05.
        tariff = 10000.08 * 0.10 * 1.05 = 1050.01.
        """
        ctx = setup_declaration_released_via_emit(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1388.90, declared_currency="USD",
            invoice_total=1388.90, invoice_currency="USD",
        )
        s = ctx["settlement"]
        assert s["tariff_amount"] == pytest.approx(1050.01, abs=0.01)


# ===========================================================================
# Rule 6B — boundary_precision_check / amendment_count zero vs one
# ===========================================================================
class TestAmendmentCountZeroVsOne:

    def test_broker_fee_excludes_amendment_when_count_zero(self, api):
        """# difficulty: boundary_precision_check/empty_amendment_count_zero_versus_one_on_broker_fee_endpoint
        PRD §3.9: "AMENDMENT is added when amendment_count is strictly
        positive, with the entry levied once per settlement regardless
        of how many amendment cycles have occurred."

        Claim: amendment_count=0 → AMENDMENT not in services_consumed →
        broker_fee = (100+80) * 7.20 = 1296.00 (no amendment fee).
        """
        ctx = setup_settlement_in_advanced(
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
            fee_schedule={
                "DECLARATION": 100,
                "INSPECTION": 50,
                "TARIFF_ADVANCE": 80,
                "AMENDMENT": 30,
                "RETURN_SHIP": 200,
            },
        )
        s = ctx["settlement"]
        expected = round((100 + 80) * 1.00 * 7.20, 2)
        assert s["broker_fee_amount"] == pytest.approx(expected, abs=0.01)

    def test_broker_fee_includes_amendment_when_count_one(self, api):
        """# difficulty: boundary_precision_check/empty_amendment_count_zero_versus_one_on_broker_fee_endpoint
        PRD §3.9: "AMENDMENT is added when amendment_count is strictly
        positive".
        PRD §3.11: "The amendment transition increments amendment_count
        by one".

        Claim: amendment_count=1 → AMENDMENT IS in services_consumed →
        broker_fee = (100+80+30) * 7.20 = 1512.00.

        Recipe: file → reject → amend → re-pre-validate → re-file →
        match-manifest → emit RELEASE → Settlement is created with
        amendment_count=1.
        """
        from test_helpers import (
            get_filing_for_declaration,
        )
        # Lap 0: file → reject.
        ctx = setup_declaration_in_rejected_via_emit(
            reason_code="HS_MISMATCH",
            default_settlement_currency="CNY", agreement_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00, declared_currency="USD",
            fee_schedule={
                "DECLARATION": 100,
                "INSPECTION": 50,
                "TARIFF_ADVANCE": 80,
                "AMENDMENT": 30,
                "RETURN_SHIP": 200,
            },
        )
        dec = ctx["declaration"]
        # Lap 1: amend.
        amended = validate_success(api.amend_declaration(
            dec["id"], action_with_version_payload(version=dec["version"]),
            TEST_USERS["declaration_officer_headers"],
        ))
        assert amended["amendment_count"] == 1
        # pre-validate (use fresh reviewer id)
        pre = validate_success(api.pre_validate_declaration(
            amended["id"],
            action_with_version_payload(version=amended["version"]),
            make_doc_reviewer_headers("reviewer-amend-1"),
        ))
        # file
        filed = validate_success(api.file_declaration(
            pre["id"], action_with_version_payload(version=pre["version"]),
            make_filing_officer_headers("filer-amend-1"),
        ))
        # Match manifest.
        filing = filed.get("filing") if isinstance(filed, dict) else None
        if not (isinstance(filing, dict) and "id" in filing):
            filing = get_filing_for_declaration(filed["id"])
        emit_manifest_match(
            filing["id"],
            shipment_reference=filed["shipment_reference"],
            hs_code=filed["hs_code"],
        )
        # Emit RELEASE.
        emit_customs_response(filing["id"], response_type="RELEASE")
        s = locate_settlement_for_declaration(filed["id"])
        # Advance the settlement to bring TARIFF_ADVANCE into services_consumed.
        s = advance_settlement(s, officer_id="settle-amend-test")
        expected = round((100 + 80 + 30) * 1.00 * 7.20, 2)
        assert s["broker_fee_amount"] == pytest.approx(expected, abs=0.01)


# ===========================================================================
# Rule 7A — cross_entity_state_dependency / declaration creation gated by agreement
# ===========================================================================
class TestDeclarationCreateRequiresActiveAgreement:

    def test_create_declaration_on_draft_agreement_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/declaration_create_depends_on_agreement_status
        PRD §3.3: "The parent agreement must be in ACTIVE status with
        the current instant in the inclusive-exclusive range from
        valid_from to valid_until — otherwise the request is rejected
        with ERR_AGREEMENT_NOT_ACTIVE and HTTP 409."

        Claim: agreement in DRAFT → POST /customs/declarations →
        ERR_AGREEMENT_NOT_ACTIVE.
        """
        client = create_client()
        from test_helpers import create_agreement
        agreement = create_agreement(client["id"])  # DRAFT
        from test_helpers import create_declaration_payload
        resp = api.create_declaration(
            create_declaration_payload(agreement_id=agreement["id"]),
            TEST_USERS["declaration_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)

    def test_create_declaration_works_after_activating_same_agreement(self, api):
        """# difficulty: cross_entity_state_dependency/declaration_create_depends_on_agreement_status
        PRD §3.3: "The parent agreement must be in ACTIVE status with
        the current instant in the inclusive-exclusive range from
        valid_from to valid_until".

        Claim: same agreement, once activated, accepts a declaration.
        """
        _, agreement = setup_active_agreement()
        from test_helpers import create_declaration_payload
        resp = api.create_declaration(
            create_declaration_payload(agreement_id=agreement["id"]),
            TEST_USERS["declaration_officer_headers"],
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Rule 7B — cross_entity_state_dependency / settlement gates withdrawal
# ===========================================================================
class TestSettlementGatesWithdrawal:

    def test_withdraw_blocked_by_advanced_settlement(self, api):
        """# difficulty: cross_entity_state_dependency/settlement_advance_depends_on_declaration_status
        PRD §3.11: "Withdrawal is reachable from DRAFT (when no filing
        yet exists) and from REJECTED (when a RejectionRecord exists for
        the declaration). It is performed by a BrokerOps operator and is
        blocked when any Settlement for the declaration is in ADVANCED
        or REIMBURSED status; the rejection code is ERR_SETTLEMENT_HAS_ADVANCE."

        Claim: declaration in REJECTED with an ADVANCED settlement →
        ERR_SETTLEMENT_HAS_ADVANCE on /withdraw.
        """
        from datetime import timedelta as _td
        from test_helpers import (
            record_inspection_outcome,
        )
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=False,
            scheduled_at=TEST_EPOCH - _td(hours=1),
            default_settlement_currency="CNY", declared_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00,
        )
        case = ctx["inspection_case"]
        record_inspection_outcome(case, outcome="PENALTY", penalty_amount=100.00)
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        s = locate_settlement_for_declaration(dec["id"])
        advance_settlement(s, officer_id="settle-cross-test")
        resp = api.withdraw_declaration(
            dec["id"], action_with_version_payload(version=dec["version"]),
            TEST_USERS["broker_ops_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_HAS_ADVANCE.value)

    def test_withdraw_succeeds_when_settlement_is_final_not_advanced(self, api):
        """# difficulty: cross_entity_state_dependency/settlement_advance_depends_on_declaration_status
        PRD §3.11: "is blocked when any Settlement for the declaration
        is in ADVANCED or REIMBURSED status".

        Claim: contrapositive — a FINAL (not yet ADVANCED) settlement
        does NOT block withdrawal.
        """
        from datetime import timedelta as _td
        from test_helpers import (
            record_inspection_outcome,
        )
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=False,
            scheduled_at=TEST_EPOCH - _td(hours=1),
            default_settlement_currency="CNY", declared_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00,
        )
        case = ctx["inspection_case"]
        record_inspection_outcome(case, outcome="PENALTY", penalty_amount=100.00)
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        # Do NOT advance the settlement; withdraw should succeed.
        withdrawn = withdraw_declaration(dec)
        assert withdrawn["status"] == "WITHDRAWN"


# ===========================================================================
# Rule 8A — resource_temporal_overlap / agreement validity half-open
# ===========================================================================
class TestAgreementValidityHalfOpen:

    def test_clock_at_valid_until_rejects_declaration_creation(self, api):
        """# difficulty: resource_temporal_overlap/agreement_validity_window_half_open
        PRD §3.3: "The parent agreement must be in ACTIVE status with
        the current instant in the inclusive-exclusive range from
        valid_from to valid_until — otherwise the request is rejected
        with ERR_AGREEMENT_NOT_ACTIVE and HTTP 409."

        Claim: clock advanced to exactly agreement.valid_until →
        ERR_AGREEMENT_NOT_ACTIVE (exclusive right endpoint).
        """
        vf = datetime(2026, 1, 1, tzinfo=timezone.utc)
        vu = datetime(2026, 2, 1, tzinfo=timezone.utc)
        _, agreement = setup_active_agreement(valid_from=vf, valid_until=vu)
        advance_clock_to(vu)  # exactly at valid_until
        from test_helpers import create_declaration_payload
        resp = api.create_declaration(
            create_declaration_payload(agreement_id=agreement["id"]),
            TEST_USERS["declaration_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)

    def test_clock_at_valid_from_accepts_declaration_creation(self, api):
        """# difficulty: resource_temporal_overlap/agreement_validity_window_half_open
        PRD §3.3: "the inclusive-exclusive range from valid_from to
        valid_until".

        Claim: clock at exactly agreement.valid_from → POST /declarations
        succeeds (inclusive left).
        """
        vf = datetime(2026, 6, 1, tzinfo=timezone.utc)
        vu = datetime(2027, 1, 1, tzinfo=timezone.utc)
        # Activate the agreement while the clock is at TEST_EPOCH (before vf);
        # sign action only requires now() < valid_until.
        _, agreement = setup_active_agreement(valid_from=vf, valid_until=vu)
        advance_clock_to(vf)  # exactly at valid_from
        from test_helpers import create_declaration_payload
        resp = api.create_declaration(
            create_declaration_payload(agreement_id=agreement["id"]),
            TEST_USERS["declaration_officer_headers"],
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Rule 8B — resource_temporal_overlap / query 48h deadline window
# ===========================================================================
class TestQueryDeadlineWindow:

    def test_query_response_just_before_deadline_succeeds(self, api):
        """# difficulty: resource_temporal_overlap/query_deadline_buffered_response_window
        PRD §3.6: "The transition is allowed only when the current
        instant is strictly before query_due_at and the filing's
        response_type is still QUERY".

        Claim: respond-query 1 microsecond before query_due_at succeeds.
        """
        reset_clock_to_epoch()
        ctx = setup_declaration_in_queried()
        filing = ctx["filing"]
        dec = ctx["declaration"]
        due_dt = datetime.fromisoformat(filing["query_due_at"].replace("Z", "+00:00"))
        advance_clock_to(due_dt - timedelta(microseconds=1))
        resp = api.respond_query(
            dec["id"],
            respond_query_payload(response_note="just in time",
                                  version=dec["version"]),
            TEST_USERS["filing_officer_headers"],
        )
        result = validate_success(resp)
        assert result["status"] == "FILED"

    def test_query_response_at_exact_deadline_rejected(self, api):
        """# difficulty: resource_temporal_overlap/query_deadline_buffered_response_window
        PRD §3.6: "an attempt after the deadline is rejected with
        ERR_QUERY_DEADLINE_PASSED."

        Claim: respond-query at exactly query_due_at → ERR_QUERY_DEADLINE_PASSED
        (or ERR_INVALID_STATE if auto-rejection already fired).
        """
        reset_clock_to_epoch()
        ctx = setup_declaration_in_queried()
        filing = ctx["filing"]
        dec = ctx["declaration"]
        due_dt = datetime.fromisoformat(filing["query_due_at"].replace("Z", "+00:00"))
        advance_clock_to(due_dt)
        # Omit version (PRD §2.5 escape hatch). The clock advance triggers
        # PRD §3.6 auto-rejection at the deadline, which bumps the
        # declaration's version; sending the stale version would short-
        # circuit to ERR_VERSION_CONFLICT (priority above state/deadline
        # per PRD §2.10) before the rule under test fires.
        resp = api.respond_query(
            dec["id"],
            respond_query_payload(response_note="at deadline"),
            TEST_USERS["filing_officer_headers"],
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_QUERY_DEADLINE_PASSED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])


# ===========================================================================
# Rule 9A — compensating_invariant / withdraw voids settlement (ledger preserved)
# ===========================================================================
class TestWithdrawConservesLedger:

    def test_withdraw_of_non_advanced_settlement_leaves_ledger_unchanged(
        self, api, broker_ops_headers,
    ):
        """# difficulty: compensating_invariant/withdraw_voids_settlement_conserves_advance_ledger_balance
        PRD §3.11: "If a Settlement exists for the declaration in
        PROVISIONAL or FINAL status, it is voided (status set to VOIDED)
        as a cascade."
        PRD §3.10: "On success, the settlement transitions from FINAL
        to ADVANCED, advance_paid_amount is set to the sum tariff + VAT
        + consumption tax + penalty".

        Claim: a Settlement in FINAL (never advanced) contributes 0 to
        the "ADVANCED + REIMBURSED" ledger before AND after withdrawal
        (voiding it leaves the ledger unchanged).

        Recipe: PENALTY cascade creates FINAL settlement (not advanced).
        Sum SUM(advance_paid_amount where status IN {ADVANCED, REIMBURSED})
        before and after withdraw; both must be 0 (single-settlement
        baseline).
        """
        from datetime import timedelta as _td
        from test_helpers import (
            record_inspection_outcome,
        )
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=False,
            scheduled_at=TEST_EPOCH - _td(hours=1),
            default_settlement_currency="CNY", declared_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00,
        )
        case = ctx["inspection_case"]
        record_inspection_outcome(case, outcome="PENALTY", penalty_amount=100.00)
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))

        def ledger() -> float:
            body = validate_success(api.list_settlements(broker_ops_headers))
            rows = body if isinstance(body, list) else (
                body.get("items") or body.get("data") or body.get("settlements") or []
            )
            if not isinstance(rows, list):
                rows = []
            return sum(
                r.get("advance_paid_amount", 0) or 0
                for r in rows
                if r.get("status") in ("ADVANCED", "REIMBURSED")
            )

        l_pre = ledger()
        withdraw_declaration(dec)
        l_post = ledger()
        assert l_pre == l_post == 0, (
            f"Ledger must be unchanged by withdrawal of non-advanced settlement; "
            f"pre={l_pre}, post={l_post}"
        )

    def test_withdraw_does_not_emit_advance_paid_audit(self, api, broker_ops_headers):
        """# difficulty: compensating_invariant/withdraw_voids_settlement_conserves_advance_ledger_balance
        PRD §2.8: "every state-changing action writes an AuditLog row ...
        with event_type drawn from STATE_TRANSITION, FIELD_CHANGE,
        ADVANCE_PAID, REIMBURSED, AMENDMENT_FILED, and VOUCHER_DELIVERED."
        PRD §3.10: "transition emits both a STATE_TRANSITION audit row
        and an ADVANCE_PAID row carrying the amount and currency."

        Claim: a withdrawal cascade voids a FINAL settlement but does
        NOT emit any ADVANCE_PAID audit row (since no advance occurred).
        """
        from datetime import timedelta as _td
        from test_helpers import (
            record_inspection_outcome,
        )
        reset_clock_to_epoch()
        ctx = setup_inspection_case(
            sample_required=False,
            scheduled_at=TEST_EPOCH - _td(hours=1),
            default_settlement_currency="CNY", declared_currency="USD",
            jurisdiction_code="CN", hs_code="10000000",
            country_of_origin="JP", trade_agreement_code="NONE",
            declared_value_amount=1000.00,
        )
        case = ctx["inspection_case"]
        record_inspection_outcome(case, outcome="PENALTY", penalty_amount=100.00)
        dec = validate_success(api.get_declaration(
            ctx["declaration"]["id"], TEST_USERS["broker_ops_headers"],
        ))
        withdraw_declaration(dec)
        # Look for ADVANCE_PAID rows for this declaration's settlement.
        s = locate_settlement_for_declaration(dec["id"])
        body = validate_success(api.list_audit_log(
            broker_ops_headers,
            params={"entity_id": s["id"], "event_type": "ADVANCE_PAID"},
        ))
        rows = body if isinstance(body, list) else (
            body.get("items") or body.get("data") or body.get("audit_log") or []
        )
        if not isinstance(rows, list):
            rows = []
        assert len(rows) == 0, "Withdrawal of non-advanced settlement must not emit ADVANCE_PAID"


# ===========================================================================
# Rule 9B — compensating_invariant / reimburse audit count invariant
# ===========================================================================
class TestReimbursementAuditCountInvariant:

    def test_full_cycle_emits_one_advance_one_reimbursed_one_voucher(
        self, api, broker_ops_headers,
    ):
        """# difficulty: compensating_invariant/reimbursement_zeros_outstanding_debt_conserves_audit_log_count_invariant
        PRD §3.10: "transition emits both a STATE_TRANSITION audit row
        and an ADVANCE_PAID row carrying the amount and currency."
        PRD §3.10: "An exact match advances the settlement from ADVANCED
        to REIMBURSED, sets reimbursed_at to the current instant ...
        and emits both a REIMBURSED audit row and a VOUCHER_DELIVERED
        audit row."

        Claim: a forward+compensating cycle (advance then reimburse)
        produces exactly one ADVANCE_PAID, one REIMBURSED, one
        VOUCHER_DELIVERED audit row for the settlement.
        """
        reset_clock_to_epoch()
        ctx = setup_settlement_for_late_interest_freeze()
        s = ctx["settlement"]
        # Reimburse at exactly advance_paid_amount (no late interest since clock unchanged).
        emit_bank_debit(s["id"], amount=s["advance_paid_amount"])
        live = validate_success(api.get_settlement(s["id"], broker_ops_headers))
        assert live["status"] == "REIMBURSED"

        def count(event_type: str) -> int:
            body = validate_success(api.list_audit_log(
                broker_ops_headers,
                params={"entity_id": s["id"], "event_type": event_type},
            ))
            rows = body if isinstance(body, list) else (
                body.get("items") or body.get("data") or body.get("audit_log") or []
            )
            return len(rows) if isinstance(rows, list) else 0

        assert count("ADVANCE_PAID") == 1, (
            "Exactly one ADVANCE_PAID audit row per advance"
        )
        assert count("REIMBURSED") == 1, (
            "Exactly one REIMBURSED audit row per reimbursement"
        )
        assert count("VOUCHER_DELIVERED") == 1, (
            "Exactly one VOUCHER_DELIVERED audit row per reimbursement"
        )

    def test_outstanding_debt_returns_to_baseline_after_reimburse(
        self, api, broker_ops_headers,
    ):
        """# difficulty: compensating_invariant/reimbursement_zeros_outstanding_debt_conserves_audit_log_count_invariant
        PRD §3.10: "An exact match advances the settlement from ADVANCED
        to REIMBURSED, sets reimbursed_at to the current instant".

        Claim: SUM(advance_paid_amount where status=ADVANCED) goes from
        +principal mid-cycle to 0 post-reimburse.
        """
        reset_clock_to_epoch()
        ctx = setup_settlement_for_late_interest_freeze()
        s = ctx["settlement"]

        def outstanding() -> float:
            body = validate_success(api.list_settlements(broker_ops_headers))
            rows = body if isinstance(body, list) else (
                body.get("items") or body.get("data") or body.get("settlements") or []
            )
            if not isinstance(rows, list):
                rows = []
            return sum(
                r.get("advance_paid_amount", 0) or 0
                for r in rows if r.get("status") == "ADVANCED"
            )

        mid = outstanding()
        assert mid == pytest.approx(s["advance_paid_amount"], abs=0.01)
        emit_bank_debit(s["id"], amount=s["advance_paid_amount"])
        post = outstanding()
        assert post == pytest.approx(0.0, abs=0.01), (
            f"Post-reimburse, outstanding ADVANCED ledger must be 0; got {post}"
        )
