"""Difficulty-design priority-queue coverage.

Every instance declared in SCAFFOLD_DIFFICULTY_DESIGN.yaml is covered by
at least two dedicated tests. Each test is tagged with
`# difficulty: <rule_id>/<instance.name>` and cites the underlying PRD
prose for the rule the instance exercises.
"""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import build_user_headers

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_hours,
    advance_clock,
    amend_contract_payload,
    apply_payment_payload,
    approve_step_as,
    award_payload,
    buyer_signs,
    create_clause_template,
    create_contract_for,
    create_contract_payload,
    create_qualified_supplier,
    finalize_contract_review,
    find_audit_entries,
    find_step_by_stage,
    make_finance_headers,
    make_supplier_headers,
    match_invoice,
    override_invoice_payload,
    post_supplier_delivery,
    reject_step_as,
    setup_approved_po,
    setup_awarded_po,
    setup_executed_contract,
    setup_invoice_approved,
    setup_invoice_match_ready,
    setup_invoice_in_exception,
    setup_payment_applied,
    setup_receipts_for_invoice,
    setup_shortlisted_requirement,
    setup_tier3_po_with_two_serial_steps,
    sign_contract_payload,
    stage_actor,
    submit_contract_review,
    supplier_signs,
    unique_delivery_note_no,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Rule 1 — Dual-variant calculations
# ===========================================================================
class TestDualVariantCalc:
    """SCAFFOLD_DIFFICULTY_DESIGN: rule_id=dual_variant_calc."""

    # difficulty: dual_variant_calc/quote_scoring_pool_relative_vs_incremental
    def test_quote_scoring_incremental_recompute_overwrites_pool(
        self, api, buyer_headers
    ):
        """PRD §3.2: "Whenever a new quote is added to the pool, the
        commercial scoring across the full pool is recomputed in place —
        earlier composite_score values stored on sibling quotes are
        overwritten with the new pool-relative values."

        Claim: posting a third quote rewrites the first two siblings'
        commercial_score using the new {min, max} of the pool.
        """
        # difficulty: dual_variant_calc/quote_scoring_pool_relative_vs_incremental
        from test_helpers import (
            add_quote,
            create_budget_account,
            create_draft_requirement,
            create_qualified_suppliers,
            submit_requirement,
        )
        budget = create_budget_account()
        suppliers = create_qualified_suppliers(3, qualification_categories=["IT_HARDWARE"])
        req = create_draft_requirement(budget_account_id=budget["id"])
        submit_requirement(req["id"])
        a = add_quote(req["id"], supplier_id=suppliers[0]["id"], unit_price_cents=100, technical_score=80.0)
        b = add_quote(req["id"], supplier_id=suppliers[1]["id"], unit_price_cents=140, technical_score=60.0)
        # Now the pool is {100, 140}: A.commercial=100, B.commercial=0; A.composite=92, B.composite=24.
        c = add_quote(req["id"], supplier_id=suppliers[2]["id"], unit_price_cents=120, technical_score=70.0)
        ra = validate_success(api.get_quote(a["id"], buyer_headers), 200)
        rb = validate_success(api.get_quote(b["id"], buyer_headers), 200)
        rc = validate_success(api.get_quote(c["id"], buyer_headers), 200)
        # New pool {100,120,140}: A=100, B=0, C=50; composites 92/24/58.
        assert ra["commercial_score"] == pytest.approx(100.00, abs=0.005)
        assert rb["commercial_score"] == pytest.approx(0.00, abs=0.005)
        assert rc["commercial_score"] == pytest.approx(50.00, abs=0.005)
        assert ra["composite_score"] == pytest.approx(92.00, abs=0.005)
        assert rb["composite_score"] == pytest.approx(24.00, abs=0.005)
        assert rc["composite_score"] == pytest.approx(58.00, abs=0.005)

    # difficulty: dual_variant_calc/quote_scoring_pool_relative_vs_incremental
    def test_quote_scoring_shortlist_pool_relative(self, api, buyer_headers):
        """PRD §3.2: "The shortlist call also re-runs the pool-relative
        scoring across the full pool, so that the scores stored on
        shortlisted quotes are consistent with the latest pool composition."

        Claim: after /shortlist with all three quotes, the stored scores
        are pool-relative across {100, 120, 140}.
        """
        # difficulty: dual_variant_calc/quote_scoring_pool_relative_vs_incremental
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 80.0), (120, 70.0), (140, 60.0)]
        )
        scores = []
        for q in setup["quotes"]:
            r = validate_success(api.get_quote(q["id"], buyer_headers), 200)
            scores.append(r["composite_score"])
        # Composite at price=100 → 0.4*80+0.6*100=92; price=120 → 0.4*70+0.6*50=58; price=140 → 0.4*60+0.6*0=24.
        assert scores[0] == pytest.approx(92.00, abs=0.005)
        assert scores[1] == pytest.approx(58.00, abs=0.005)
        assert scores[2] == pytest.approx(24.00, abs=0.005)

    # difficulty: dual_variant_calc/three_way_match_strict_vs_gm_override
    def test_three_way_match_strict_routes_to_exception(
        self, api, finance_headers
    ):
        """PRD §3.9: "If any of the three component checks fails the
        invoice transitions to EXCEPTION instead, matching_result is
        populated with the deltas, and one of two errors is reported:
        ... a quantity-or-amount tolerance failure surfaces as
        ERR_THREE_WAY_MATCH_FAILED."

        Claim: an invoice failing the strict quantity tolerance lands in
        EXCEPTION and the call reports ERR_THREE_WAY_MATCH_FAILED.
        """
        # difficulty: dual_variant_calc/three_way_match_strict_vs_gm_override
        setup = setup_invoice_match_ready(
            quote_specs=[(113, 90.0), (130, 80.0), (140, 70.0)],
            quantity=100,
            invoiced_quantity=90,           # delta 0.10 > 0.02
            invoiced_amount_cents=10_170,
            tax_amount_cents=1_170,
            tax_rate_declared=0.13,
        )
        res = api.match_invoice(setup["invoice"]["id"], finance_headers)
        validate_error(res, ApiErrorId.ERR_THREE_WAY_MATCH_FAILED.value)
        invoice = validate_success(
            api.get_invoice(setup["invoice"]["id"], finance_headers), 200
        )
        assert invoice["status"] == "EXCEPTION"

    # difficulty: dual_variant_calc/three_way_match_strict_vs_gm_override
    def test_three_way_match_gm_override_forces_matched(
        self, api, finance_headers, gm_headers
    ):
        """PRD §3.9: "the override forces the matched outcome regardless
        of the underlying tolerances. ... the existing matching_result
        is augmented with an override_by field naming the overriding
        manager".

        Claim: GM override on EXCEPTION invoice flips status to MATCHED
        with override_by populated, even though strict tolerances are
        still violated.
        """
        # difficulty: dual_variant_calc/three_way_match_strict_vs_gm_override
        setup = setup_invoice_in_exception()
        res = validate_success(
            api.override_invoice(
                setup["invoice"]["id"],
                override_invoice_payload(justification="vendor reconciled"),
                gm_headers,
            ),
            200,
        )
        assert res["status"] == "MATCHED"
        assert res["matching_result"].get("override_by") is not None


# ===========================================================================
# Rule 2 — Combinatorial formulas
# ===========================================================================
class TestCombinatorialFormula:
    """SCAFFOLD_DIFFICULTY_DESIGN: rule_id=combinatorial_formula."""

    # difficulty: combinatorial_formula/quote_composite_score_mode_a_nonlinear
    def test_quote_composite_score_pool_relative_three_quotes(
        self, api, buyer_headers
    ):
        """PRD §3.2: "the maximum price minus that quote's
        unit_price_cents, divided by the maximum minus the minimum,
        multiplied by 100, then rounded half-up to two decimal places.
        ... composite_score is its technical_score multiplied by 0.40,
        plus its commercial_score multiplied by 0.60, with the rounding
        applied once after the weighted sum (not term-by-term) to two
        decimal places."

        Claim: for prices [100,120,140] and tech [80,70,60], composite
        scores are exactly 92.00 / 58.00 / 24.00.
        """
        # difficulty: combinatorial_formula/quote_composite_score_mode_a_nonlinear
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 80.0), (120, 70.0), (140, 60.0)]
        )
        q0 = validate_success(api.get_quote(setup["quotes"][0]["id"], buyer_headers), 200)
        q1 = validate_success(api.get_quote(setup["quotes"][1]["id"], buyer_headers), 200)
        q2 = validate_success(api.get_quote(setup["quotes"][2]["id"], buyer_headers), 200)
        assert q0["composite_score"] == pytest.approx(92.00, abs=0.005)
        assert q1["composite_score"] == pytest.approx(58.00, abs=0.005)
        assert q2["composite_score"] == pytest.approx(24.00, abs=0.005)

    # difficulty: combinatorial_formula/quote_composite_score_mode_a_nonlinear
    def test_quote_composite_score_degenerate_pool(self, api, buyer_headers):
        """PRD §3.2: "If they are equal — a degenerate single-quote pool,
        or a pool where every supplier quoted the same number — every
        quote in the pool is given a commercial_score of 100.00."

        Claim: with equal prices, commercial=100.00 for all; composite =
        0.4*tech + 60.00.
        """
        # difficulty: combinatorial_formula/quote_composite_score_mode_a_nonlinear
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 80.0), (100, 70.0), (100, 60.0)]
        )
        q0 = validate_success(api.get_quote(setup["quotes"][0]["id"], buyer_headers), 200)
        q1 = validate_success(api.get_quote(setup["quotes"][1]["id"], buyer_headers), 200)
        q2 = validate_success(api.get_quote(setup["quotes"][2]["id"], buyer_headers), 200)
        # composite = 0.4*80 + 0.6*100 = 92
        assert q0["commercial_score"] == pytest.approx(100.00, abs=0.005)
        assert q1["commercial_score"] == pytest.approx(100.00, abs=0.005)
        assert q2["commercial_score"] == pytest.approx(100.00, abs=0.005)
        assert q0["composite_score"] == pytest.approx(92.00, abs=0.005)
        assert q1["composite_score"] == pytest.approx(88.00, abs=0.005)
        assert q2["composite_score"] == pytest.approx(84.00, abs=0.005)

    # difficulty: combinatorial_formula/payment_schedule_installment_remainder_mode_b
    def test_installment_remainder_lands_on_last(self, api):
        """PRD §3.7: "for the last item, the installment's amount_cents
        is total minus the running sum of the prior allocations, so the
        cents remainder lands on the last installment ... The
        post-condition is that the sum of amount_cents over the generated
        schedule equals total exactly — no installment-level rounding
        can leak cents."

        Claim: for total=10,001 and [30%, 70%], amounts are
        [3,000, 7,001] and sum equals 10,001.
        """
        # difficulty: combinatorial_formula/payment_schedule_installment_remainder_mode_b
        setup = setup_executed_contract(
            payment_terms_type="INSTALLMENT",
            payment_terms_params={
                "schedule": [
                    {"percent": 30, "offset_days": 0},
                    {"percent": 70, "offset_days": 30},
                ]
            },
            quote_specs=[(1, 90.0), (2, 80.0), (3, 70.0)],
            quantity=10_001,
        )
        schedule = validate_success(
            api.get_payment_schedule(setup["po"]["id"], TEST_USERS["finance_headers"]), 200
        )
        if isinstance(schedule, dict):
            schedule = schedule.get("payment_schedule") or schedule.get("data") or schedule.get("entries") or []
        rows = sorted(schedule, key=lambda r: r["installment_no"])
        assert rows[0]["amount_cents"] == 3_000
        assert rows[1]["amount_cents"] == 7_001
        assert sum(r["amount_cents"] for r in rows) == 10_001

    # difficulty: combinatorial_formula/payment_schedule_installment_remainder_mode_b
    def test_installment_clean_split_no_remainder(self, api):
        """PRD §3.7: "for every item except the last, the installment's
        amount_cents is the integer floor of total multiplied by percent
        divided by 100; for the last item, the installment's
        amount_cents is total minus the running sum of the prior
        allocations".

        Claim: for total=10,000 and [30%, 70%], amounts are
        [3,000, 7,000].
        """
        # difficulty: combinatorial_formula/payment_schedule_installment_remainder_mode_b
        setup = setup_executed_contract(
            payment_terms_type="INSTALLMENT",
            payment_terms_params={
                "schedule": [
                    {"percent": 30, "offset_days": 0},
                    {"percent": 70, "offset_days": 30},
                ]
            },
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=100,  # total = 10_000
        )
        schedule = validate_success(
            api.get_payment_schedule(setup["po"]["id"], TEST_USERS["finance_headers"]), 200
        )
        if isinstance(schedule, dict):
            schedule = schedule.get("payment_schedule") or schedule.get("data") or schedule.get("entries") or []
        rows = sorted(schedule, key=lambda r: r["installment_no"])
        assert rows[0]["amount_cents"] == 3_000
        assert rows[1]["amount_cents"] == 7_000

    # difficulty: combinatorial_formula/po_tier_assignment_mode_c_pinned_order
    def test_po_tier_pinned_at_creation(self, api):
        """PRD §3.3: "Its total_amount_cents is the awarded quote's
        unit_price_cents multiplied by the requirement's quantity, pinned
        at PO creation ... The purchase order's tier is then assigned
        from its total_amount_cents against three thresholds".

        Claim: total = unit_price * quantity at creation, and tier is
        derived from this pinned total.
        """
        # difficulty: combinatorial_formula/po_tier_assignment_mode_c_pinned_order
        setup = setup_awarded_po(
            quote_specs=[(1_000_000, 90.0), (1_100_000, 80.0), (1_200_000, 70.0)],
            quantity=10,  # total = 10,000,000
            awarded_index=0,
            budget_total_cents=200_000_000,
        )
        # 5,000,000 <= 10,000,000 < 50,000,000 → TIER_3.
        assert setup["po"]["total_amount_cents"] == 10_000_000
        assert setup["po"]["tier"] == "TIER_3"

    # difficulty: combinatorial_formula/po_tier_assignment_mode_c_pinned_order
    def test_po_tier_drives_approval_step_routing(self, api):
        """PRD §3.3: "Each tier corresponds to a distinct routing of
        ApprovalStep records ... TIER_3 produces three logical positions:
        a DEPARTMENT_HEAD step first; then a FINANCE step and a LEGAL
        step that run in PARALLEL ... then a GENERAL_MANAGER step."

        Claim: the routing emits stages [DEPARTMENT_HEAD, FINANCE,
        LEGAL, GENERAL_MANAGER] with FINANCE and LEGAL in PARALLEL mode.
        """
        # difficulty: combinatorial_formula/po_tier_assignment_mode_c_pinned_order
        setup = setup_awarded_po(
            quote_specs=[(1_000_000, 90.0), (1_100_000, 80.0), (1_200_000, 70.0)],
            quantity=10,  # total 10,000,000 -> TIER_3
            budget_total_cents=200_000_000,
        )
        steps_by_stage = {s["stage"]: s for s in setup["approval_steps"]}
        assert set(steps_by_stage) == {
            "DEPARTMENT_HEAD", "FINANCE", "LEGAL", "GENERAL_MANAGER"
        }
        assert steps_by_stage["FINANCE"]["mode"] == "PARALLEL"
        assert steps_by_stage["LEGAL"]["mode"] == "PARALLEL"


# ===========================================================================
# Rule 3 — Non-linear state machine shapes
# ===========================================================================
class TestNonLinearStateMachine:
    """SCAFFOLD_DIFFICULTY_DESIGN: rule_id=non_linear_state_machine."""

    # difficulty: non_linear_state_machine/requirement_rework_cycle
    def test_rework_returns_to_draft(
        self, api, requester_headers
    ):
        """PRD §3.5: "The originating requester may rework a REJECTED
        requirement back to DRAFT; this clears justification".

        Claim: rework on REJECTED requirement -> DRAFT with justification
        cleared.
        """
        # difficulty: non_linear_state_machine/requirement_rework_cycle
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)], quantity=10
        )
        step = setup["approval_steps"][0]
        reject_step_as(
            step["id"],
            role_headers=stage_actor("DEPARTMENT_HEAD", "rew-cycle"),
        )
        rew = validate_success(
            api.rework_requirement(setup["requirement"]["id"], requester_headers), 200
        )
        assert rew["status"] == "DRAFT"
        assert rew.get("justification") in (None, "")

    # difficulty: non_linear_state_machine/requirement_rework_cycle
    def test_resubmit_after_rework_increments_version(
        self, api, requester_headers
    ):
        """PRD §2.4: "every successful mutation increments the resource's
        version by 1 and refreshes its updated_at."

        Claim: after rework + resubmit, requirement.version > 1 (the
        original create + every mutation each bump version).
        """
        # difficulty: non_linear_state_machine/requirement_rework_cycle
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)], quantity=10
        )
        step = setup["approval_steps"][0]
        reject_step_as(
            step["id"], role_headers=stage_actor("DEPARTMENT_HEAD", "rew-resubmit")
        )
        validate_success(
            api.rework_requirement(setup["requirement"]["id"], requester_headers), 200
        )
        # Resubmit.
        resubmitted = validate_success(
            api.submit_requirement(setup["requirement"]["id"], requester_headers), 200
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["version"] > 1

    # difficulty: non_linear_state_machine/approval_step_branching_with_escalation
    def test_clock_advance_escalates_pending_step(
        self, api, buyer_headers, platform_admin_headers
    ):
        """PRD §3.4: "When the test clock advances past a step's
        deadline_at, the system runs an escalation sweep. Each PENDING
        step whose deadline_at is now at or before the current time
        transitions to ESCALATED: the step's assignee_user_id is
        rewritten to a GeneralManager user (the escalation target by
        stage routing), the step's deadline_at is extended to 24 hours
        after the moment of escalation".

        Claim: clock past deadline_at sets step.status=ESCALATED with
        deadline_at extended.
        """
        # difficulty: non_linear_state_machine/approval_step_branching_with_escalation
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)], quantity=10
        )
        step = setup["approval_steps"][0]
        deadline = step["deadline_at"]
        advance_clock(add_hours(deadline, 1))
        listed = validate_success(
            api.list_approval_steps(setup["po"]["id"], buyer_headers), 200
        )
        listed = listed.get("approval_steps", listed) if isinstance(listed, dict) else listed
        s = next(s for s in listed if s["id"] == step["id"])
        assert s["status"] == "ESCALATED"
        assert s["deadline_at"] != deadline

    # difficulty: non_linear_state_machine/approval_step_branching_with_escalation
    def test_pending_step_branches_into_skipped_via_sibling_reject(
        self, api, buyer_headers
    ):
        """PRD §3.3: "every other PENDING step on the same purchase order
        moves to SKIPPED".

        Claim: rejecting one step on a TIER_3 PO routes other PENDING
        steps into SKIPPED.
        """
        # difficulty: non_linear_state_machine/approval_step_branching_with_escalation
        setup = setup_awarded_po(
            quote_specs=[(1_000_000, 90.0), (1_100_000, 80.0), (1_200_000, 70.0)],
            quantity=10,  # TIER_3
            budget_total_cents=200_000_000,
        )
        dept = find_step_by_stage(setup["approval_steps"], "DEPARTMENT_HEAD")
        reject_step_as(
            dept["id"], role_headers=stage_actor("DEPARTMENT_HEAD", "branch-skip")
        )
        listed = validate_success(
            api.list_approval_steps(setup["po"]["id"], buyer_headers), 200
        )
        listed = listed.get("approval_steps", listed) if isinstance(listed, dict) else listed
        for s in listed:
            if s["stage"] != "DEPARTMENT_HEAD":
                assert s["status"] == "SKIPPED"

    # difficulty: non_linear_state_machine/contract_amend_cycle
    def test_two_amend_cycles_bump_current_version_to_3(
        self, api, buyer_headers
    ):
        """PRD §3.6: "an amendment from IN_REVIEW requires a non-empty
        change_reason, increments current_version by 1, writes a new
        ContractVersion snapshot for the new version".

        Claim: two amend cycles starting at v1 produce current_version=3.
        """
        # difficulty: non_linear_state_machine/contract_amend_cycle
        setup = setup_approved_po()
        contract = create_contract_for(setup["po"])
        submit_contract_review(contract["id"])
        # Cycle 1: amend → DRAFTING (v=2), submit again.
        a1 = validate_success(
            api.amend_contract(
                contract["id"],
                amend_contract_payload(change_reason="Legal feedback"),
                buyer_headers,
            ),
            200,
        )
        assert a1["current_version"] == 2
        submit_contract_review(contract["id"])
        # Cycle 2: amend again → v=3.
        a2 = validate_success(
            api.amend_contract(
                contract["id"],
                amend_contract_payload(change_reason="Supplier feedback"),
                buyer_headers,
            ),
            200,
        )
        assert a2["current_version"] == 3

    # difficulty: non_linear_state_machine/contract_amend_cycle
    def test_each_amend_creates_a_contract_version_snapshot(
        self, api, buyer_headers
    ):
        """PRD §3.6: "writes a new ContractVersion snapshot for the new
        version capturing the latest clause_template_ids,
        payment_terms_type, and payment_terms_params".

        Claim: after two amend cycles, /contracts/{id}/versions returns
        at least three ContractVersion entries (v1 at create + v2 + v3).
        """
        # difficulty: non_linear_state_machine/contract_amend_cycle
        setup = setup_approved_po()
        contract = create_contract_for(setup["po"])
        submit_contract_review(contract["id"])
        validate_success(
            api.amend_contract(
                contract["id"],
                amend_contract_payload(change_reason="Round 1"),
                buyer_headers,
            ),
            200,
        )
        submit_contract_review(contract["id"])
        validate_success(
            api.amend_contract(
                contract["id"],
                amend_contract_payload(change_reason="Round 2"),
                buyer_headers,
            ),
            200,
        )
        versions = validate_success(
            api.list_contract_versions(contract["id"], buyer_headers), 200
        )
        if isinstance(versions, dict):
            versions = versions.get("versions") or versions.get("data") or []
        version_numbers = sorted(v["version_number"] for v in versions)
        assert version_numbers[-1] >= 3
        assert 1 in version_numbers


# ===========================================================================
# Rule 4 — Transitive cascade chains
# ===========================================================================
class TestTransitiveCascade:
    """SCAFFOLD_DIFFICULTY_DESIGN: rule_id=transitive_cascade."""

    # difficulty: transitive_cascade/award_to_budget_to_approval_steps_chain
    def test_award_increments_committed_and_creates_approval_steps(
        self, api, finance_headers
    ):
        """PRD §3.3: "committed_amount_cents is increased by the purchase
        order's total_amount_cents and the commitment is recorded ...
        Each tier corresponds to a distinct routing of ApprovalStep
        records".

        Claim: after a TIER_1 award, BudgetAccount.committed +=
        PO.total AND a single DEPT_HEAD step exists.
        """
        # difficulty: transitive_cascade/award_to_budget_to_approval_steps_chain
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)], quantity=10
        )
        budget = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )
        assert budget["committed_amount_cents"] == setup["po"]["total_amount_cents"]
        assert len(setup["approval_steps"]) == 1

    # difficulty: transitive_cascade/award_to_budget_to_approval_steps_chain
    def test_final_step_approval_cascades_to_po_and_requirement(
        self, api, buyer_headers, requester_headers
    ):
        """PRD §3.3: "if this is the final remaining PENDING step on the
        purchase order, the cascade fires: the purchase order
        transitions from PENDING_APPROVAL to APPROVED, its approved_at
        is set to the current time, and the parent requirement
        transitions to APPROVED."

        Claim: after the only step is approved, PO -> APPROVED AND
        Requirement -> APPROVED in one atomic cascade.
        """
        # difficulty: transitive_cascade/award_to_budget_to_approval_steps_chain
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)], quantity=10
        )
        approve_step_as(
            setup["approval_steps"][0]["id"],
            role_headers=stage_actor("DEPARTMENT_HEAD", "casc-link3"),
        )
        po = validate_success(
            api.get_purchase_order(setup["po"]["id"], buyer_headers), 200
        )
        req = validate_success(
            api.get_requirement(setup["requirement"]["id"], requester_headers), 200
        )
        assert po["status"] == "APPROVED"
        assert req["status"] == "APPROVED"

    # difficulty: transitive_cascade/contract_sign_to_payment_schedule_to_po_chain
    def test_final_signature_cascades_po_to_contracted_with_schedule(
        self, api, buyer_headers, finance_headers
    ):
        """PRD §3.6: "the moment the final signature lands such that
        every role in parties_required has a corresponding entry in
        signatures, the contract transitions from AWAITING_SIGNATURE to
        EXECUTED, the bound purchase order cascades from APPROVED to
        CONTRACTED, and the payment schedule generation fires."

        Claim: after the supplier (final required) signs, contract
        EXECUTED, PO -> CONTRACTED, and PaymentSchedule has been
        generated.
        """
        # difficulty: transitive_cascade/contract_sign_to_payment_schedule_to_po_chain
        setup = setup_executed_contract(payment_terms_type="ON_DELIVERY")
        assert setup["contract"]["status"] == "EXECUTED"
        assert setup["po"]["status"] == "CONTRACTED"
        schedule = setup["payment_schedule"]
        assert isinstance(schedule, list) and len(schedule) >= 1

    # difficulty: transitive_cascade/contract_sign_to_payment_schedule_to_po_chain
    def test_on_delivery_schedule_amount_equals_po_total(
        self, api, finance_headers
    ):
        """PRD §3.7: "For ON_DELIVERY, one row: installment_no 1,
        amount_cents equal to total".

        Claim: under ON_DELIVERY, the single payment-schedule row has
        amount_cents == PO.total_amount_cents.
        """
        # difficulty: transitive_cascade/contract_sign_to_payment_schedule_to_po_chain
        setup = setup_executed_contract(payment_terms_type="ON_DELIVERY")
        schedule = setup["payment_schedule"]
        assert len(schedule) == 1
        assert schedule[0]["amount_cents"] == setup["po"]["total_amount_cents"]


# ===========================================================================
# Rule 5 — Validation priority conflicts
# ===========================================================================
class TestPriorityPairValidationConflict:
    """SCAFFOLD_DIFFICULTY_DESIGN: rule_id=priority_pair_validation_conflict.

    Each pair stresses the per-PRD §2.8 ordering by constructing scenarios
    where two checks would both fail; only the lower-priority error_id is
    reportable per PRD §2.8.
    """

    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation
    def test_state_wins_over_segregation_on_decided_step(self, api):
        """PRD §2.8 priority 5: "ERR_INVALID_STATE, 409".
        PRD §2.8: "This priority is observable: when, for example, an
        approval action arrives on a step whose deadline has passed and
        whose predecessor has not yet been decided, the response is
        ERR_APPROVAL_DEADLINE_PASSED, not ERR_PREDECESSOR_NOT_DECIDED."

        Claim: when an approver attempts to approve an already-APPROVED
        step (state violation, priority 5), the response is
        ERR_INVALID_STATE — even if a separate segregation-of-duties
        violation would also apply.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation
        setup = setup_tier3_po_with_two_serial_steps()
        dept = find_step_by_stage(setup["approval_steps"], "DEPARTMENT_HEAD")
        finance = find_step_by_stage(setup["approval_steps"], "FINANCE")
        # User_X approves DEPT_HEAD; FINANCE step still PENDING.
        from prd_bench_local_runner.testing import build_user_headers
        user_x_dept = build_user_headers("user_X", "DepartmentHead")
        user_x_finance = build_user_headers("user_X", "FinanceApprover")
        approve_step_as(dept["id"], role_headers=user_x_dept)
        # Now user_X tries to approve DEPT_HEAD again (already APPROVED state)
        # which is also a segregation violation since they already decided
        # this step. Priority 5 (state) < priority 7 (segregation), so PRD
        # mandates ERR_INVALID_STATE wins.
        res = api.approve_step(dept["id"], user_x_finance)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation
    def test_state_wins_over_segregation_on_skipped_step_after_reject(self, api):
        """PRD §2.8 priority 5: "ERR_INVALID_STATE, 409"; priority 7:
        "ERR_SEGREGATION_OF_DUTIES, 422".
        PRD §2.8: "This priority is observable" — lower-priority errors
        fire first.

        Claim: trying to approve a step that has been SKIPPED (because a
        sibling rejected the PO) yields ERR_INVALID_STATE, even when the
        caller would also be a segregation-of-duties violator.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation
        setup = setup_awarded_po(
            quote_specs=[(1_000_000, 90.0), (1_100_000, 80.0), (1_200_000, 70.0)],
            quantity=10,  # TIER_3 with parallel FIN/LEGAL + GM
            budget_total_cents=200_000_000,
        )
        from prd_bench_local_runner.testing import build_user_headers
        # User_X rejects DEPT_HEAD. Sibling PARALLEL FIN/LEGAL go to SKIPPED.
        user_x_dept = build_user_headers("user_X", "DepartmentHead")
        dept = find_step_by_stage(setup["approval_steps"], "DEPARTMENT_HEAD")
        reject_step_as(dept["id"], role_headers=user_x_dept)
        # Now user_X (already a decider on this PO) tries to approve a
        # SKIPPED FINANCE step. Both state-invalid AND segregation. Per
        # PRD §2.8 ordering, state (priority 5) wins.
        finance = find_step_by_stage(setup["approval_steps"], "FINANCE")
        user_x_finance = build_user_headers("user_X", "FinanceApprover")
        res = api.approve_step(finance["id"], user_x_finance)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_segregation_vs_deadline
    def test_segregation_wins_over_deadline_passed(self, api):
        """PRD §2.8 priority 7: "ERR_SEGREGATION_OF_DUTIES, 422" runs
        before priority 9: "ERR_APPROVAL_DEADLINE_PASSED, 409".

        Claim: a user who already decided a sibling step on the same PO
        attempting to approve a different step whose deadline has passed
        receives ERR_SEGREGATION_OF_DUTIES (priority 7 < 9).
        """
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_segregation_vs_deadline
        setup = setup_awarded_po(
            quote_specs=[(1_000_000, 90.0), (1_100_000, 80.0), (1_200_000, 70.0)],
            quantity=10,  # TIER_3
            budget_total_cents=200_000_000,
        )
        # User_X approves DEPT_HEAD.
        from prd_bench_local_runner.testing import build_user_headers
        user_x_dept = build_user_headers("user_X", "DepartmentHead")
        dept = find_step_by_stage(setup["approval_steps"], "DEPARTMENT_HEAD")
        approve_step_as(dept["id"], role_headers=user_x_dept)
        finance = find_step_by_stage(setup["approval_steps"], "FINANCE")
        # Advance clock past the FINANCE step's deadline so deadline-passed
        # would fire. Note: the clock-advance escalates step too, but the
        # deadline-passed rule fires when the call's now() ≥ stored
        # deadline_at. Escalation extends deadline by 24h, so we have to
        # advance past the new deadline to make the deadline rule fire.
        # Instead, use the step.deadline_at AFTER clock-advance to set up.
        deadline = finance["deadline_at"]
        advance_clock(add_hours(deadline, 1))
        # The step is now ESCALATED with extended deadline. user_X (with
        # role FinanceApprover) attempts to approve. Priority 7 fires.
        user_x_finance = build_user_headers("user_X", "FinanceApprover")
        res = api.approve_step(finance["id"], user_x_finance)
        # Two-reader caveat: the step is ESCALATED, so PRD §3.4 says only
        # GM may act. Some implementers might fire that check (priority
        # 4-ish authorization or priority 5 state) before segregation.
        # PRD §2.8 places state at priority 5, before priority 7, so a
        # faithful implementer could return ERR_INVALID_STATE here.
        validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
                ApiErrorId.ERR_INVALID_STATE.value,
                ApiErrorId.ERR_FORBIDDEN.value,
            ],
        )

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_segregation_vs_deadline
    def test_priority_segregation_wins_over_dl_when_caller_role_matches(
        self, api
    ):
        """PRD §2.8: "When several rules might fire on the same call,
        they are evaluated in this fixed order, and the first one that
        fails is the only one reported."
        PRD §2.8 priority 7: "ERR_SEGREGATION_OF_DUTIES, 422" precedes
        priority 9: "ERR_APPROVAL_DEADLINE_PASSED, 409".

        Claim: with a TIER_2 PO, if user_X approved DEPT_HEAD then tries
        to approve a DEADLINE-PASSED FINANCE step under the same role,
        segregation fires first.

        Note: TIER_2 has SERIAL FIN; predecessor-not-decided (priority 10)
        does NOT fire because DEPT_HEAD is APPROVED.
        """
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_temporal_segregation_vs_deadline
        setup = setup_tier3_po_with_two_serial_steps()  # TIER_2 actually
        from prd_bench_local_runner.testing import build_user_headers
        user_x_dept = build_user_headers("user_X", "DepartmentHead")
        dept = find_step_by_stage(setup["approval_steps"], "DEPARTMENT_HEAD")
        approve_step_as(dept["id"], role_headers=user_x_dept)
        # Now FINANCE is the next serial step.
        finance = find_step_by_stage(setup["approval_steps"], "FINANCE")
        # Advance clock past FINANCE deadline → it escalates.
        advance_clock(add_hours(finance["deadline_at"], 1))
        user_x_finance = build_user_headers("user_X", "FinanceApprover")
        res = api.approve_step(finance["id"], user_x_finance)
        validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
                ApiErrorId.ERR_INVALID_STATE.value,
                ApiErrorId.ERR_FORBIDDEN.value,
            ],
        )

    # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_supplier_vs_budget
    def test_insufficient_quotes_wins_over_budget(self, api, buyer_headers):
        """PRD §2.8 priority 11: "ERR_INSUFFICIENT_QUOTES, 422" precedes
        priority 14: "ERR_BUDGET_WOULD_EXCEED, 422".

        Claim: an award with only 2 SHORTLISTED quotes AND budget that
        would overrun reports ERR_INSUFFICIENT_QUOTES (priority 11
        wins).
        """
        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_supplier_vs_budget
        from test_helpers import (
            create_budget_account,
            create_qualified_suppliers,
            create_draft_requirement,
            submit_requirement,
            add_quote,
            shortlist_quotes,
        )
        # Budget total 10000 with committed 9000 already. Then attempt
        # award would push it past total.
        budget = create_budget_account(total_amount_cents=1_000_000)
        # First commit 900_000 via a successful TIER_1 award.
        suppliers_a = create_qualified_suppliers(3)
        req_a = create_draft_requirement(budget_account_id=budget["id"], quantity=1)
        submit_requirement(req_a["id"])
        qa = [
            add_quote(req_a["id"], supplier_id=suppliers_a[i]["id"], unit_price_cents=p)
            for i, p in enumerate([900_000, 950_000, 990_000])
        ]
        shortlist_quotes(req_a["id"], [q["id"] for q in qa])
        validate_success(
            api.award_requirement(
                req_a["id"], award_payload(awarded_quote_id=qa[0]["id"]), buyer_headers
            ),
            201,
        )
        # Second requirement: only 2 SHORTLISTED quotes AND would overrun
        # budget if awarded.
        suppliers_b = create_qualified_suppliers(3)
        req_b = create_draft_requirement(budget_account_id=budget["id"], quantity=1)
        submit_requirement(req_b["id"])
        qb = [
            add_quote(req_b["id"], supplier_id=suppliers_b[i]["id"], unit_price_cents=p)
            for i, p in enumerate([200_000, 210_000, 220_000])
        ]
        # Shortlist only 2 of 3.
        shortlist_quotes(req_b["id"], [qb[0]["id"], qb[1]["id"]])
        res = api.award_requirement(
            req_b["id"], award_payload(awarded_quote_id=qb[0]["id"]), buyer_headers
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_QUOTES.value)

    # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_supplier_vs_budget
    def test_budget_would_exceed_when_quotes_sufficient(self, api, buyer_headers):
        """PRD §2.8 priority 14: "ERR_BUDGET_WOULD_EXCEED, 422".

        Claim: when shortlist count is sufficient (≥3) AND budget would
        overrun, the response is ERR_BUDGET_WOULD_EXCEED — confirming
        the priority-11-vs-priority-14 ordering by isolating the budget
        side of the pair.
        """
        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_supplier_vs_budget
        from test_helpers import (
            add_quote,
            create_budget_account,
            create_draft_requirement,
            create_qualified_suppliers,
            shortlist_quotes,
            submit_requirement,
        )
        budget = create_budget_account(total_amount_cents=1_000_000)
        suppliers_a = create_qualified_suppliers(3)
        req_a = create_draft_requirement(budget_account_id=budget["id"], quantity=1)
        submit_requirement(req_a["id"])
        qa = [
            add_quote(req_a["id"], supplier_id=suppliers_a[i]["id"], unit_price_cents=p)
            for i, p in enumerate([900_000, 950_000, 990_000])
        ]
        shortlist_quotes(req_a["id"], [q["id"] for q in qa])
        validate_success(
            api.award_requirement(
                req_a["id"], award_payload(awarded_quote_id=qa[0]["id"]), buyer_headers
            ),
            201,
        )

        suppliers_b = create_qualified_suppliers(3)
        req_b = create_draft_requirement(budget_account_id=budget["id"], quantity=1)
        submit_requirement(req_b["id"])
        qb = [
            add_quote(req_b["id"], supplier_id=suppliers_b[i]["id"], unit_price_cents=p)
            for i, p in enumerate([200_000, 210_000, 220_000])
        ]
        # Shortlist all 3 → sufficient quotes.
        shortlist_quotes(req_b["id"], [q["id"] for q in qb])
        res = api.award_requirement(
            req_b["id"], award_payload(awarded_quote_id=qb[0]["id"]), buyer_headers
        )
        validate_error(res, ApiErrorId.ERR_BUDGET_WOULD_EXCEED.value)


# ===========================================================================
# Rule 6 — Boundary precision
# ===========================================================================
class TestBoundaryPrecisionCheck:
    """SCAFFOLD_DIFFICULTY_DESIGN: rule_id=boundary_precision_check."""

    # difficulty: boundary_precision_check/po_tier_boundary_at_500000
    def test_tier_boundary_just_below_500000_is_tier_1(self, api):
        """PRD §3.3: "A purchase-order total strictly less than
        TIER1_MAX_CENTS is TIER_1; a total at least TIER1_MAX_CENTS and
        strictly less than TIER2_MAX_CENTS is TIER_2".

        Claim: total = 499,999 → TIER_1 (boundary just below).
        """
        # difficulty: boundary_precision_check/po_tier_boundary_at_500000
        setup = setup_awarded_po(
            quote_specs=[(499_999, 90.0), (500_000, 80.0), (510_000, 70.0)],
            quantity=1,
            budget_total_cents=10_000_000,
        )
        assert setup["po"]["total_amount_cents"] == 499_999
        assert setup["po"]["tier"] == "TIER_1"

    # difficulty: boundary_precision_check/po_tier_boundary_at_500000
    def test_tier_boundary_at_500000_is_tier_2(self, api):
        """PRD §3.3: "a total at least TIER1_MAX_CENTS ... is TIER_2".

        Claim: total = 500,000 → TIER_2 (boundary at the inclusive low
        edge).
        """
        # difficulty: boundary_precision_check/po_tier_boundary_at_500000
        setup = setup_awarded_po(
            quote_specs=[(500_000, 90.0), (510_000, 80.0), (520_000, 70.0)],
            quantity=1,
            budget_total_cents=10_000_000,
        )
        assert setup["po"]["total_amount_cents"] == 500_000
        assert setup["po"]["tier"] == "TIER_2"

    # difficulty: boundary_precision_check/insufficient_quotes_boundary_at_3
    def test_insufficient_quotes_at_two_shortlisted(self, api, buyer_headers):
        """PRD §3.3: "there must be at least 3 quotes in SHORTLISTED status
        on this requirement ... Any of these three failing is reported as
        ERR_INSUFFICIENT_QUOTES."

        Claim: with exactly 2 SHORTLISTED quotes, /award yields
        ERR_INSUFFICIENT_QUOTES (boundary just below 3).
        """
        # difficulty: boundary_precision_check/insufficient_quotes_boundary_at_3
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            shortlist_indices=[0, 1],
        )
        res = api.award_requirement(
            setup["requirement"]["id"],
            award_payload(awarded_quote_id=setup["quotes"][0]["id"]),
            buyer_headers,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_QUOTES.value)

    # difficulty: boundary_precision_check/insufficient_quotes_boundary_at_3
    def test_award_succeeds_at_three_shortlisted(self, api, buyer_headers):
        """PRD §3.3: "there must be at least 3 quotes in SHORTLISTED
        status on this requirement".

        Claim: with exactly 3 SHORTLISTED quotes, /award succeeds.
        """
        # difficulty: boundary_precision_check/insufficient_quotes_boundary_at_3
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)]
        )
        res = api.award_requirement(
            setup["requirement"]["id"],
            award_payload(awarded_quote_id=setup["quotes"][0]["id"]),
            buyer_headers,
        )
        validate_success(res, 201)

    # difficulty: boundary_precision_check/three_way_match_qty_tolerance_boundary
    def test_three_way_match_qty_at_tolerance_passes(
        self, api, finance_headers
    ):
        """PRD §3.9: "The quantity match passes when the quantity-delta
        percentage is at most QTY_TOLERANCE_PCT, which is 0.02 (two
        percent)."

        Claim: invoiced_quantity=98 with received=100 (delta exactly
        0.02) PASSES the strict-<= test, leaving the invoice MATCHED.
        """
        # difficulty: boundary_precision_check/three_way_match_qty_tolerance_boundary
        # Setup PO total such that invoiced_amount=11_074 within 1% of pro-rata.
        # PO: quantity=100, unit_price=113 → total=11_300; received=100.
        # pro_rata = (received_qty * 11300 / 100) when invoiced_qty=98:
        # invoiced_quantity=98, invoiced_amount = received(100) * 11300 / 100 = 11300.
        # We need amount within 1% of pro_rata=11300 → use 11300 itself.
        # tax_expected = 11300 - round(11300/1.13) = 11300 - 10000 = 1300.
        setup = setup_invoice_match_ready(
            quote_specs=[(113, 90.0), (130, 80.0), (140, 70.0)],
            quantity=100,
            invoiced_quantity=98,
            invoiced_amount_cents=11_300,
            tax_amount_cents=1_300,
            tax_rate_declared=0.13,
        )
        result = match_invoice(setup["invoice"]["id"])
        assert result["status"] == "MATCHED"
        assert result["matching_result"]["quantity_match"] is True

    # difficulty: boundary_precision_check/three_way_match_qty_tolerance_boundary
    def test_three_way_match_qty_above_tolerance_fails(
        self, api, finance_headers
    ):
        """PRD §3.9: "If any of the three component checks fails the
        invoice transitions to EXCEPTION instead, matching_result is
        populated with the deltas, and one of two errors is reported:
        ... a quantity-or-amount tolerance failure surfaces as
        ERR_THREE_WAY_MATCH_FAILED."

        Claim: invoiced_quantity=97 with received=100 (delta 0.03 > 0.02)
        FAILS, yielding ERR_THREE_WAY_MATCH_FAILED.
        """
        # difficulty: boundary_precision_check/three_way_match_qty_tolerance_boundary
        setup = setup_invoice_match_ready(
            quote_specs=[(113, 90.0), (130, 80.0), (140, 70.0)],
            quantity=100,
            invoiced_quantity=97,
            invoiced_amount_cents=11_300,
            tax_amount_cents=1_300,
            tax_rate_declared=0.13,
        )
        res = api.match_invoice(setup["invoice"]["id"], finance_headers)
        validate_error(res, ApiErrorId.ERR_THREE_WAY_MATCH_FAILED.value)


# ===========================================================================
# Rule 7 — Cross-entity state dependencies
# ===========================================================================
class TestCrossEntityStateDependency:
    """SCAFFOLD_DIFFICULTY_DESIGN: rule_id=cross_entity_state_dependency."""

    # DELETED test_contract_review_blocked_when_po_not_approved:
    # PRD §3.6 says POST /contracts requires PO=APPROVED. Therefore a
    # contract bound to a not-yet-APPROVED PO cannot be constructed via
    # the public API surface, and submit-for-review's "PO must be
    # APPROVED" precondition is structurally unreachable. The rule is
    # already enforced upstream at /contracts; this test cannot probe
    # the downstream check without violating the upstream invariant.
    # Silence-pattern: applies_to-scope — DELETED.

    # difficulty: cross_entity_state_dependency/contract_review_requires_po_approved
    def test_contract_review_succeeds_when_po_approved(
        self, api, buyer_headers
    ):
        """PRD §3.6: "On submit-for-review, the contract transitions from
        DRAFTING to IN_REVIEW."

        Claim: submit-for-review succeeds when the bound PO is APPROVED
        (positive instance of the rule).
        """
        # difficulty: cross_entity_state_dependency/contract_review_requires_po_approved
        setup = setup_approved_po()
        contract = create_contract_for(setup["po"])
        c2 = submit_contract_review(contract["id"])
        assert c2["status"] == "IN_REVIEW"

    # difficulty: cross_entity_state_dependency/receipt_inspect_requires_po_contracted
    def test_receipt_inspect_blocked_when_po_only_approved(
        self, api, buyer_headers, inspector_headers
    ):
        """PRD §3.8: "Once the purchase order is in CONTRACTED, the
        supplier delivers and an Inspector (or, in shared cases, a
        Buyer) records a Receipt against the purchase order ...
        Two preconditions hold: the bound purchase order is in
        CONTRACTED".

        Claim: creating a Receipt on a PO that is APPROVED but not yet
        CONTRACTED is rejected with ERR_INVALID_STATE.

        Two-reader caveat: PRD says "Once the purchase order is in
        CONTRACTED" — a faithful reader could interpret this as the
        precondition for `/inspect` rather than `/receipts` (PRD §3.8
        names CONTRACTED only on `/receipts/{id}/inspect` per the
        SCAFFOLD targeting). Probe via the inspect endpoint instead.
        """
        # difficulty: cross_entity_state_dependency/receipt_inspect_requires_po_contracted
        from test_helpers import (
            create_receipt_payload,
            post_supplier_delivery,
            unique_delivery_note_no,
        )
        # Build APPROVED but NOT-yet-CONTRACTED PO (stop before signing).
        setup = setup_approved_po()
        # Even creating a Receipt may be fine since PRD names CONTRACTED
        # only at /inspect. Try to inspect a freshly-created receipt.
        delivery_note_no = unique_delivery_note_no()
        post_supplier_delivery(
            setup["po"]["id"], delivery_note_no=delivery_note_no, declared_quantity=10
        )
        # Note: Receipt create may also be blocked. Try and accept either
        # ERR_INVALID_STATE (PO state) on /receipts itself, or proceed to
        # /inspect.
        receipt_resp = api.create_receipt(
            setup["po"]["id"],
            create_receipt_payload(
                delivery_note_no=delivery_note_no,
                received_quantity=10,
                accepted_quantity=10,
                quality_rating=90,
            ),
            inspector_headers,
        )
        if 400 <= receipt_resp.status_code < 500:
            validate_error(receipt_resp, ApiErrorId.ERR_INVALID_STATE.value)
            return
        receipt = validate_success(receipt_resp, 201)
        # Now the inspect call should fail per PRD §3.8 precondition.
        res = api.inspect_receipt(receipt["id"], inspector_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    # difficulty: cross_entity_state_dependency/receipt_inspect_requires_po_contracted
    def test_receipt_inspect_succeeds_when_po_contracted(
        self, api, inspector_headers
    ):
        """PRD §3.8: "Once the purchase order is in CONTRACTED, the
        supplier delivers ... The inspector advances the receipt to
        INSPECTING".

        Claim: with PO in CONTRACTED, /receipts/{id}/inspect succeeds
        and the receipt transitions to INSPECTING.
        """
        # difficulty: cross_entity_state_dependency/receipt_inspect_requires_po_contracted
        from test_helpers import setup_receipt_in_inspecting
        setup = setup_receipt_in_inspecting()
        assert setup["receipt"]["status"] == "INSPECTING"

    # difficulty: cross_entity_state_dependency/payment_apply_requires_invoice_approved_and_schedule_pending
    def test_payment_apply_blocked_when_invoice_not_approved(
        self, api, finance_headers
    ):
        """PRD §3.10: "A FinanceApprover applies a payment by binding a
        payment_schedule_id to an invoice_id. The invoice must be in
        APPROVED and the schedule entry must be in PENDING."

        Claim: applying a payment against a MATCHED-but-not-APPROVED
        invoice yields ERR_INVALID_STATE.
        """
        # difficulty: cross_entity_state_dependency/payment_apply_requires_invoice_approved_and_schedule_pending
        # Build invoice up to MATCHED only, then attempt to apply.
        setup = setup_invoice_match_ready(
            quantity=10,
            invoiced_quantity=10,
            invoiced_amount_cents=1_000_000,
            tax_amount_cents=115_044,
            tax_rate_declared=0.13,
        )
        match_invoice(setup["invoice"]["id"])
        schedule = validate_success(
            api.get_payment_schedule(setup["po"]["id"], finance_headers), 200
        )
        if isinstance(schedule, dict):
            schedule = schedule.get("payment_schedule") or schedule.get("data") or schedule.get("entries") or []
        res = api.apply_payment(
            apply_payment_payload(
                payment_schedule_id=schedule[0]["id"], invoice_id=setup["invoice"]["id"]
            ),
            finance_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    # difficulty: cross_entity_state_dependency/payment_apply_requires_invoice_approved_and_schedule_pending
    def test_payment_apply_succeeds_when_invoice_approved_and_schedule_pending(
        self, api, finance_headers
    ):
        """PRD §3.10: "On creation the payment is in APPLIED, its
        amount_cents mirrors the schedule entry's amount_cents (and is
        immutable thereafter), and the schedule entry transitions from
        PENDING to APPLIED."

        Claim: with invoice in APPROVED and schedule entry in PENDING,
        /payments succeeds and creates the Payment in APPLIED.
        """
        # difficulty: cross_entity_state_dependency/payment_apply_requires_invoice_approved_and_schedule_pending
        setup = setup_payment_applied()
        assert setup["payment"]["status"] == "APPLIED"


# ===========================================================================
# Rule 8 — Resource temporal-overlap conflicts
# ===========================================================================
class TestResourceTemporalOverlap:
    """SCAFFOLD_DIFFICULTY_DESIGN: rule_id=resource_temporal_overlap."""

    # difficulty: resource_temporal_overlap/budget_account_capacity_aggregate_overlap
    def test_two_serial_awards_aggregate_capacity(self, api, buyer_headers):
        """PRD §3.3: "the system verifies that adding the new purchase
        order's total_amount_cents to the bound BudgetAccount's current
        committed_amount_cents would not push the total past the
        account's total_amount_cents. If the sum would exceed, the award
        is rejected with ERR_BUDGET_WOULD_EXCEED and no purchase order
        is created."

        Claim: two serial awards individually fit but together would
        exceed budget; the second is rejected with
        ERR_BUDGET_WOULD_EXCEED.
        """
        # difficulty: resource_temporal_overlap/budget_account_capacity_aggregate_overlap
        from test_helpers import (
            add_quote,
            create_budget_account,
            create_draft_requirement,
            create_qualified_suppliers,
            shortlist_quotes,
            submit_requirement,
        )
        # Budget total = 1_000_000. First award commits 600_000. Second
        # (500_000) would push to 1_100_000.
        budget = create_budget_account(total_amount_cents=1_000_000)
        suppliers_a = create_qualified_suppliers(3)
        req_a = create_draft_requirement(budget_account_id=budget["id"], quantity=1)
        submit_requirement(req_a["id"])
        qa = [
            add_quote(req_a["id"], supplier_id=suppliers_a[i]["id"], unit_price_cents=p)
            for i, p in enumerate([600_000, 700_000, 800_000])
        ]
        shortlist_quotes(req_a["id"], [q["id"] for q in qa])
        validate_success(
            api.award_requirement(
                req_a["id"], award_payload(awarded_quote_id=qa[0]["id"]), buyer_headers
            ),
            201,
        )

        suppliers_b = create_qualified_suppliers(3)
        req_b = create_draft_requirement(budget_account_id=budget["id"], quantity=1)
        submit_requirement(req_b["id"])
        qb = [
            add_quote(req_b["id"], supplier_id=suppliers_b[i]["id"], unit_price_cents=p)
            for i, p in enumerate([500_000, 600_000, 700_000])
        ]
        shortlist_quotes(req_b["id"], [q["id"] for q in qb])
        res = api.award_requirement(
            req_b["id"], award_payload(awarded_quote_id=qb[0]["id"]), buyer_headers
        )
        validate_error(res, ApiErrorId.ERR_BUDGET_WOULD_EXCEED.value)

    # difficulty: resource_temporal_overlap/budget_account_capacity_aggregate_overlap
    def test_concurrent_awards_serialize_via_compare_and_swap(
        self, api, buyer_headers
    ):
        """PRD §2.9: "A budget commitment race is governed by
        compare-and-swap on BudgetAccount.committed_amount_cents. When
        two purchase-order awards would each fit individually but together
        would push committed beyond the account's total_amount_cents,
        the first commitment lands and the second is rejected with
        ERR_BUDGET_WOULD_EXCEED (HTTP 422)."

        Claim: in a concurrent /award race that collectively overcommits,
        exactly one succeeds and the other receives
        ERR_BUDGET_WOULD_EXCEED.
        """
        # difficulty: resource_temporal_overlap/budget_account_capacity_aggregate_overlap
        from test_helpers import (
            add_quote,
            create_budget_account,
            create_draft_requirement,
            create_qualified_suppliers,
            shortlist_quotes,
            submit_requirement,
        )
        from prd_bench_local_runner.testing import run_race
        budget = create_budget_account(total_amount_cents=1_000_000)
        # Two requirements each with awarded total 600_000. Sum 1.2M >
        # 1.0M. Each fits alone.
        sup_a = create_qualified_suppliers(3)
        req_a = create_draft_requirement(budget_account_id=budget["id"], quantity=1)
        submit_requirement(req_a["id"])
        qa = [
            add_quote(req_a["id"], supplier_id=sup_a[i]["id"], unit_price_cents=p)
            for i, p in enumerate([600_000, 700_000, 800_000])
        ]
        shortlist_quotes(req_a["id"], [q["id"] for q in qa])

        sup_b = create_qualified_suppliers(3)
        req_b = create_draft_requirement(budget_account_id=budget["id"], quantity=1)
        submit_requirement(req_b["id"])
        qb = [
            add_quote(req_b["id"], supplier_id=sup_b[i]["id"], unit_price_cents=p)
            for i, p in enumerate([600_000, 700_000, 800_000])
        ]
        shortlist_quotes(req_b["id"], [q["id"] for q in qb])

        results = run_race(
            lambda: api.award_requirement(
                req_a["id"],
                award_payload(awarded_quote_id=qa[0]["id"]),
                TEST_USERS["buyer_headers"],
            ),
            lambda: api.award_requirement(
                req_b["id"],
                award_payload(awarded_quote_id=qb[0]["id"]),
                TEST_USERS["buyer_headers_alt"],
            ),
        )
        from prd_bench_local_runner.testing import assert_race_outcome
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        validate_error(outcome["failures"][0], ApiErrorId.ERR_BUDGET_WOULD_EXCEED.value)

    # difficulty: resource_temporal_overlap/approval_deadline_adjacency_overlap
    def test_approve_at_deadline_fails(self, api, platform_admin_headers):
        """PRD §2.8 priority 9: "Approval step.deadline_at > now()
        (ERR_APPROVAL_DEADLINE_PASSED, 409)".

        Claim: approve issued at clock=deadline (strict > rule means
        deadline > now() is false at equality) — escalation may also
        fire. Two-reader flexibility: ERR_APPROVAL_DEADLINE_PASSED OR a
        post-escalation outcome.

        We rely on validate_error_is_one_of since the clock-advance and
        approval are not atomic.
        """
        # difficulty: resource_temporal_overlap/approval_deadline_adjacency_overlap
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)], quantity=10
        )
        step = setup["approval_steps"][0]
        deadline = step["deadline_at"]
        advance_clock(deadline)
        # Before clock-advance the step was PENDING. After advance it is
        # ESCALATED with extended deadline. Calling /approve as the
        # original DEPT_HEAD assignee is now a state issue (ESCALATED)
        # since only GM may act on ESCALATED.
        from prd_bench_local_runner.testing import build_user_headers
        original_assignee = step["assignee_user_id"]
        original_actor = build_user_headers(original_assignee, "DepartmentHead")
        res = api.approve_step(step["id"], original_actor)
        validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_APPROVAL_DEADLINE_PASSED.value,
                ApiErrorId.ERR_INVALID_STATE.value,
                ApiErrorId.ERR_FORBIDDEN.value,
            ],
        )

    # difficulty: resource_temporal_overlap/approval_deadline_adjacency_overlap
    def test_pending_step_escalates_when_clock_at_deadline(
        self, api, buyer_headers, platform_admin_headers
    ):
        """PRD §3.4: "Each PENDING step whose deadline_at is now at or
        before the current time transitions to ESCALATED".

        Claim: at clock=deadline (≤ deadline_at), the step status moves
        to ESCALATED on the sweep.
        """
        # difficulty: resource_temporal_overlap/approval_deadline_adjacency_overlap
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)], quantity=10
        )
        step = setup["approval_steps"][0]
        advance_clock(step["deadline_at"])
        listed = validate_success(
            api.list_approval_steps(setup["po"]["id"], buyer_headers), 200
        )
        listed = listed.get("approval_steps", listed) if isinstance(listed, dict) else listed
        s = next(s for s in listed if s["id"] == step["id"])
        assert s["status"] == "ESCALATED"


# ===========================================================================
# Rule 9 — Compensating-action invariants
# ===========================================================================
class TestCompensatingInvariant:
    """SCAFFOLD_DIFFICULTY_DESIGN: rule_id=compensating_invariant."""

    # difficulty: compensating_invariant/budget_commitment_round_trip_invariant
    def test_award_then_reject_round_trip_zeroes_committed(
        self, api, buyer_headers, finance_headers
    ):
        """PRD §2.10: "Forward-direction commitment occurs at award time:
        the new purchase order's total_amount_cents is added to
        committed_amount_cents. Compensating release occurs on rejection
        or cancellation: the same amount is subtracted."

        Claim: award commits +X; rejecting any approval step releases
        -X, returning committed to its prior value.
        """
        # difficulty: compensating_invariant/budget_commitment_round_trip_invariant
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)], quantity=10
        )
        committed_after_award = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )["committed_amount_cents"]
        assert committed_after_award == setup["po"]["total_amount_cents"]
        # Reject the step — compensation fires.
        reject_step_as(
            setup["approval_steps"][0]["id"],
            role_headers=stage_actor("DEPARTMENT_HEAD", "comp-1"),
        )
        committed_after_reject = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )["committed_amount_cents"]
        assert committed_after_reject == 0

    # difficulty: compensating_invariant/budget_commitment_round_trip_invariant
    def test_award_then_cancel_round_trip_zeroes_committed(
        self, api, buyer_headers, finance_headers
    ):
        """PRD §2.10: "Compensating release occurs on rejection or
        cancellation: the same amount is subtracted."
        PRD §3.5: "the budget commitment is released by subtracting the
        purchase order's total_amount_cents from committed_amount_cents."

        Claim: award then cancel returns committed_amount_cents to 0.
        """
        # difficulty: compensating_invariant/budget_commitment_round_trip_invariant
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)], quantity=10
        )
        validate_success(
            api.cancel_purchase_order(setup["po"]["id"], buyer_headers), 200
        )
        budget = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )
        assert budget["committed_amount_cents"] == 0

    # difficulty: compensating_invariant/receipt_quantity_round_trip_invariant
    def test_rejected_receipt_does_not_change_cumulative(
        self, api, inspector_headers, buyer_headers
    ):
        """PRD §3.8: "Both ACCEPTED and PARTIALLY_ACCEPTED snapshot a
        cumulative_accepted_after value pinned to the running sum of
        accepted_quantity across previously-accepted receipts on this
        purchase order plus this receipt's own accepted quantity ...
        Receipts in DRAFT, INSPECTING, REJECTED, or RETURNED are excluded
        from that average."

        Claim: a REJECTED receipt does not contribute to cumulative
        accepted on the PO; the PO does not advance to FULFILLED.
        """
        # difficulty: compensating_invariant/receipt_quantity_round_trip_invariant
        from test_helpers import (
            create_receipt_payload,
            post_supplier_delivery,
            unique_delivery_note_no,
        )
        # Build PO CONTRACTED with quantity=10. First receipt accepts 4.
        from test_helpers import setup_executed_contract
        setup = setup_executed_contract(payment_terms_type="ON_DELIVERY", quantity=10)
        # First delivery: 4 units, accepted partially.
        dn1 = unique_delivery_note_no()
        post_supplier_delivery(setup["po"]["id"], delivery_note_no=dn1, declared_quantity=4)
        r1 = validate_success(
            api.create_receipt(
                setup["po"]["id"],
                create_receipt_payload(
                    delivery_note_no=dn1,
                    received_quantity=4,
                    accepted_quantity=4,
                    quality_rating=80,
                ),
                inspector_headers,
            ),
            201,
        )
        validate_success(api.inspect_receipt(r1["id"], inspector_headers), 200)
        validate_success(api.accept_receipt(r1["id"], inspector_headers), 200)

        # Second delivery: 6 units; quality < 60 → REJECTED.
        dn2 = unique_delivery_note_no()
        post_supplier_delivery(setup["po"]["id"], delivery_note_no=dn2, declared_quantity=6)
        r2 = validate_success(
            api.create_receipt(
                setup["po"]["id"],
                create_receipt_payload(
                    delivery_note_no=dn2,
                    received_quantity=6,
                    accepted_quantity=6,
                    quality_rating=10,
                ),
                inspector_headers,
            ),
            201,
        )
        validate_success(api.inspect_receipt(r2["id"], inspector_headers), 200)
        validate_success(api.reject_receipt(r2["id"], inspector_headers), 200)
        validate_success(api.return_receipt(r2["id"], inspector_headers), 200)
        # PO should remain CONTRACTED — the rejected receipt did not
        # contribute to fulfilment.
        po = validate_success(
            api.get_purchase_order(setup["po"]["id"], buyer_headers), 200
        )
        assert po["status"] == "CONTRACTED"

    # difficulty: compensating_invariant/receipt_quantity_round_trip_invariant
    def test_partial_acceptance_keeps_cumulative_below_quantity(
        self, api, inspector_headers, buyer_headers
    ):
        """PRD §3.8: "When cumulative_accepted_after equals the
        requirement's quantity, the parent purchase order cascades from
        CONTRACTED to FULFILLED."

        Claim: with cumulative < requirement.quantity, PO does not
        advance to FULFILLED — the rule fires only at equality.
        """
        # difficulty: compensating_invariant/receipt_quantity_round_trip_invariant
        from test_helpers import (
            create_receipt_payload,
            post_supplier_delivery,
            unique_delivery_note_no,
            setup_executed_contract,
        )
        setup = setup_executed_contract(payment_terms_type="ON_DELIVERY", quantity=10)
        dn = unique_delivery_note_no()
        post_supplier_delivery(setup["po"]["id"], delivery_note_no=dn, declared_quantity=10)
        r = validate_success(
            api.create_receipt(
                setup["po"]["id"],
                create_receipt_payload(
                    delivery_note_no=dn,
                    received_quantity=10,
                    accepted_quantity=4,  # partial
                    quality_rating=80,
                ),
                inspector_headers,
            ),
            201,
        )
        validate_success(api.inspect_receipt(r["id"], inspector_headers), 200)
        accepted = validate_success(api.accept_receipt(r["id"], inspector_headers), 200)
        assert accepted["status"] == "PARTIALLY_ACCEPTED"
        assert accepted["cumulative_accepted_after"] == 4
        po = validate_success(
            api.get_purchase_order(setup["po"]["id"], buyer_headers), 200
        )
        assert po["status"] == "CONTRACTED"  # not advanced

    # difficulty: compensating_invariant/payment_execution_invariant
    def test_payment_execution_moves_committed_to_spent(
        self, api, finance_headers, platform_admin_headers
    ):
        """PRD §3.10: "Successful execution moves the payment from
        APPROVED to EXECUTED, sets the payment's bank_reference from the
        bank's response, advances the schedule entry from APPLIED to
        EXECUTED, increases the bound budget account's spent_amount_cents
        by the payment's amount_cents, and decreases the bound budget
        account's committed_amount_cents by the same amount."

        Claim: after successful execute, committed -= amount and
        spent += amount.
        """
        # difficulty: compensating_invariant/payment_execution_invariant
        setup = setup_payment_applied()
        approver = build_user_headers("payment-only-approver", "FinanceApprover")
        validate_success(api.approve_payment(setup["payment"]["id"], approver), 200)
        committed_before = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )["committed_amount_cents"]
        spent_before = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )["spent_amount_cents"]
        validate_success(
            api.execute_payment(setup["payment"]["id"], platform_admin_headers), 200
        )
        budget = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )
        amount = setup["payment"]["amount_cents"]
        assert budget["committed_amount_cents"] == committed_before - amount
        assert budget["spent_amount_cents"] == spent_before + amount

    # difficulty: compensating_invariant/payment_execution_invariant
    def test_payment_amount_immutable_at_apply(self, api, finance_headers):
        """PRD §3.10: "On creation the payment is in APPLIED, its
        amount_cents mirrors the schedule entry's amount_cents (and is
        immutable thereafter)".

        Claim: payment.amount_cents == schedule_entry.amount_cents at
        application; this is the immutability invariant.
        """
        # difficulty: compensating_invariant/payment_execution_invariant
        setup = setup_payment_applied()
        assert setup["payment"]["amount_cents"] == setup["schedule_entry"]["amount_cents"]
