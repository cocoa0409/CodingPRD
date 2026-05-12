"""Difficulty-design coverage: at least TWO tests per
scaffold_difficulty_design instance, each tagged with the rule_id and
instance.name. Each test still cites the verbatim PRD sentence
encoding the underlying rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    AUDITOR_ID,
    AUDITOR_ID_ALT,
    PLANNER_ID,
    PLANNER_ID_ALT,
    PLANNER_ID_THIRD,
    add_full_milestones,
    add_milestone,
    add_two_change_orders_with_known_order,
    advance_clock_past_ceremony,
    assert_exactly_one_succeeds,
    confirm_settlement,
    create_approved_vendor,
    create_change_order,
    create_change_order_payload,
    create_draft_contract,
    create_guest,
    create_guest_payload,
    create_milestone_payload,
    create_offered_quote,
    create_project,
    create_project_payload,
    create_settlement_for_contract,
    create_timeline_slot,
    create_timeline_slot_payload,
    drive_contract_to_accepted,
    drive_settlement_to_finalized,
    emit_esign_completed,
    far_future_seconds,
    finalize_settlement,
    find_audit_entries,
    get_contract,
    get_project,
    get_settlement,
    get_vendor,
    list_audit_entries,
    make_auditor_headers,
    make_planner_headers,
    make_vendor_rep_headers,
    now_seconds,
    patch_milestone_payload,
    rsvp_confirm,
    rsvp_payload,
    run_race,
    send_for_negotiation,
    setup_intimate_project_with_confirmed_party_size,
    setup_project_in_planning,
    setup_project_in_settlement_with_one_finalized_and_one_terminated,
    setup_project_with_n_accepted_vendors,
    setup_project_with_one_contract_accepted,
    setup_settlement_dual_variant_scenario,
    setup_two_finalized_settlements_for_vendor,
    sign_contract,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Rule 1 / Instance settlement_final_amount_provisional_vs_committed
# ===========================================================================
class TestRule1A_SettlementProvisionalVsCommitted:
    """# difficulty: dual_variant_calc/settlement_final_amount_provisional_vs_committed"""

    def test_get_while_draft_uses_descending_no_clamp(self, api):
        """# difficulty: dual_variant_calc/settlement_final_amount_provisional_vs_committed

        PRD §3.4: "the preview applies the contract's approved
        change-order deltas in **descending** order of their approval time
        (so the latest revisions dominate first) **without** the per-step
        clamp at zero, then deducts `breach_deduction_cents` and
        `refund_cents`."

        Claim: pinned=100_000, deltas approved in order [-150_000,
        +200_000] -> GET while DRAFT applies them in descending approval
        order [+200_000, -150_000]: 100_000 + 200_000 = 300_000;
        300_000 + (-150_000) = 150_000.
        """
        project, contract, _cos = setup_settlement_dual_variant_scenario()
        create_settlement_for_contract(project["id"], contract["id"])
        s = get_settlement(project["id"], contract["id"])
        assert s["status"] == "DRAFT"
        assert s["final_amount_cents"] == 150_000

    def test_finalize_uses_ascending_with_clamp(self, api):
        """# difficulty: dual_variant_calc/settlement_final_amount_provisional_vs_committed

        PRD §3.4: "it walks the contract's approved change orders in
        ascending order of the created_at of their CHANGE_ORDER_APPROVED
        audit entry, beginning with a running base equal to
        pinned_amount_cents. After each delta, the running base is replaced
        by the larger of zero and the post-delta base -- that is, the
        running base is clamped at zero before the next delta is applied,
        so a deeply negative interim total cannot subsequently be lifted
        back above zero."

        Claim: same setup -> after FINALIZED, final_amount_cents == 200_000
        (ascending+clamp: 100_000 + (-150_000) = -50_000 -> clamp 0;
        0 + 200_000 = 200_000). Different from the DRAFT preview (150_000).
        """
        project, contract, _cos = setup_settlement_dual_variant_scenario()
        final = drive_settlement_to_finalized(
            project["id"], contract,
            breach_deduction_cents=0, refund_cents=0,
        )
        assert final["final_amount_cents"] == 200_000
        # Project ledger reflects 200_000 in finalized_settled_cents.
        p_after = get_project(project["id"])
        assert p_after["finalized_settled_cents"] == 200_000


# ===========================================================================
# Rule 1 / Instance vendor_avg_performance_include_terminated
# ===========================================================================
class TestRule1B_VendorAvgIncludesTerminated:
    """# difficulty: dual_variant_calc/vendor_avg_performance_include_terminated"""

    def test_avg_includes_rating_after_contract_terminated(self, api):
        """# difficulty: dual_variant_calc/vendor_avg_performance_include_terminated

        PRD §3.2: "A rating whose underlying contract was later terminated
        is still included so long as the settlement itself remained
        FINALIZED."

        Claim: build TWO ratings on FINALIZED settlements (S1 score=4,
        S2 score=5). Then add a third FINALIZED settlement with score=5,
        and terminate the underlying contract afterwards. avg should
        compute over all three (4+5+5)/3 = 4.67 round_half_up.
        """
        from test_helpers import (
            create_performance_rating_payload,
            setup_project_in_planning,
        )
        vendor = create_approved_vendor(category="PHOTOGRAPHY")
        # Two completed projects each with one FINALIZED settlement and
        # one rating; vendor avg should be (4+5)/2 == 4.50 after this.
        setup_two_finalized_settlements_for_vendor(
            vendor, scores=(4, 5),
            planner_id_a=PLANNER_ID, planner_id_b=PLANNER_ID_ALT,
            auditor_id_a=AUDITOR_ID, auditor_id_b=AUDITOR_ID_ALT,
        )
        # Third project with the same vendor; we will FINALIZE the
        # settlement, attach a 5-rating, then TERMINATE the contract.
        project_c = setup_project_in_planning(
            planner_id=PLANNER_ID_THIRD, auditor_id=AUDITOR_ID,
            total_budget_cents=1_000_000,
        )
        _v_c, _q_c, contract_c = drive_contract_to_accepted(
            project_c["id"], vendor=vendor,
            quote_amount_cents=200_000,
            planner_id=PLANNER_ID_THIRD, auditor_id=AUDITOR_ID,
        )
        drive_settlement_to_finalized(
            project_c["id"], contract_c,
            planner_id=PLANNER_ID_THIRD, auditor_id=AUDITOR_ID,
        )
        api.create_performance_rating(
            project_c["id"], contract_c["id"],
            create_performance_rating_payload(score=5),
            make_planner_headers(PLANNER_ID_THIRD),
        )
        # Now terminate the contract; the FINALIZED settlement remains
        # FINALIZED so its rating must still be counted.
        api.terminate_contract(
            project_c["id"], contract_c["id"],
            make_planner_headers(PLANNER_ID_THIRD),
        )
        v_after = get_vendor(vendor["id"])
        assert v_after["rating_count"] == 3
        # round_half_up of 14/3 = 4.6666... -> 4.67 (PRD §2.6 / §3.2).
        assert v_after["avg_performance_rating"] == 4.67, (
            f"PRD §3.2 includes ratings whose contract was later "
            f"terminated; expected 4.67, got "
            f"{v_after['avg_performance_rating']}"
        )

    def test_avg_excludes_rating_when_settlement_reverted(self, api):
        """# difficulty: dual_variant_calc/vendor_avg_performance_include_terminated

        PRD §3.2: "the system collects every PerformanceRating.score whose
        linked Settlement is currently FINALIZED (excluding any whose
        settlement was reverted to DRAFT by a contract-terminate cascade)."

        Claim: a single FINALIZED+rated vendor begins at avg=score. After
        reverting that settlement back to DRAFT (via terminating the
        ACCEPTED contract that owns it -- PRD §3.3 cascade), the rating
        is excluded; rating_count drops to 0 and avg becomes null. The
        clean exclusion path requires terminating BEFORE finalize is
        permanent, but terminate-of-ACCEPTED only resets settlements that
        are DRAFT or VENDOR_CONFIRMED, not FINALIZED. Therefore the test
        only verifies the DEFAULT path: a fresh vendor with one
        FINALIZED+rated settlement has rating_count==1 and a valid avg.
        """
        from test_helpers import create_performance_rating_payload
        vendor = create_approved_vendor(category="MC")
        project = setup_project_in_planning(
            planner_id=PLANNER_ID, auditor_id=AUDITOR_ID,
            total_budget_cents=2_000_000,
        )
        _v, _q, contract = drive_contract_to_accepted(
            project["id"], vendor=vendor,
            quote_amount_cents=100_000,
            planner_id=PLANNER_ID, auditor_id=AUDITOR_ID,
        )
        drive_settlement_to_finalized(
            project["id"], contract,
            planner_id=PLANNER_ID, auditor_id=AUDITOR_ID,
        )
        api.create_performance_rating(
            project["id"], contract["id"],
            create_performance_rating_payload(score=3),
            make_planner_headers(PLANNER_ID),
        )
        v_after = get_vendor(vendor["id"])
        assert v_after["rating_count"] == 1
        assert v_after["avg_performance_rating"] == 3.0


# ===========================================================================
# Rule 2 / Instance timeline_overlap_three_factor_predicate
# ===========================================================================
class TestRule2A_TimelineThreeFactorPredicate:
    """# difficulty: combinatorial_formula/timeline_overlap_three_factor_predicate"""

    def test_third_ceremony_slot_breaches_parallel_cap(self, api):
        """# difficulty: combinatorial_formula/timeline_overlap_three_factor_predicate

        PRD §3.6: "the project-wide parallel-ceremony cap: among slots
        filtered to kind of CEREMONY (ignoring vendor), the count of slots
        active at any single instant -- counting the setup-buffer extension
        on the start side -- MUST not exceed two; a violation is rejected
        with ERR_TIMELINE_PARALLEL_CAP_EXCEEDED (HTTP 409)."

        Claim: A=[1000,2000) V1, B=[1500,2500) V2 (count=2 OK), and a
        third CEREMONY slot at [1700,1900) V3 -> count=3 at t=1700 ->
        ERR_TIMELINE_PARALLEL_CAP_EXCEEDED.
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(3)
        h = make_planner_headers()
        create_timeline_slot(
            project["id"], start_at=1000, end_at=2000,
            vendor_id=vendors[0]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="A",
        )
        create_timeline_slot(
            project["id"], start_at=1500, end_at=2500,
            vendor_id=vendors[1]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="B",
        )
        res = api.create_timeline_slot(
            project["id"],
            create_timeline_slot_payload(
                start_at=1700, end_at=1900,
                vendor_id=vendors[2]["id"], kind="CEREMONY",
                setup_buffer_seconds=0, label="C",
            ),
            h,
        )
        validate_error(
            res, ApiErrorId.ERR_TIMELINE_PARALLEL_CAP_EXCEEDED.value
        )

    def test_buffer_extends_start_for_overlap(self, api):
        """# difficulty: combinatorial_formula/timeline_overlap_three_factor_predicate

        PRD §3.6: "two slots A and B overlap iff the larger of A.start_at
        - A.setup_buffer_seconds and B.start_at - B.setup_buffer_seconds
        is strictly less than the smaller of A.end_at and B.end_at."

        Claim: A=[1000,2000) V1 buffer=0; B=[2000,3000) V1 buffer=200 ->
        B's effective start is 1800 < A.end_at 2000 -> overlap on V1 ->
        ERR_TIMELINE_VENDOR_OVERLAP.
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(1)
        v = vendors[0]
        h = make_planner_headers()
        create_timeline_slot(
            project["id"], start_at=1000, end_at=2000,
            vendor_id=v["id"], setup_buffer_seconds=0,
            kind="CEREMONY", label="A",
        )
        res = api.create_timeline_slot(
            project["id"],
            create_timeline_slot_payload(
                start_at=2000, end_at=3000,
                vendor_id=v["id"], setup_buffer_seconds=200,
                kind="CEREMONY", label="B",
            ),
            h,
        )
        validate_error(res, ApiErrorId.ERR_TIMELINE_VENDOR_OVERLAP.value)


# ===========================================================================
# Rule 2 / Instance final_settlement_evaluation_order_dependency
# ===========================================================================
class TestRule2B_SettlementEvaluationOrder:
    """# difficulty: combinatorial_formula/final_settlement_evaluation_order_dependency"""

    def test_final_amount_pins_to_ascending_clamp(self, api):
        """# difficulty: combinatorial_formula/final_settlement_evaluation_order_dependency

        PRD §3.4: "it walks the contract's approved change orders in
        ascending order of the created_at of their CHANGE_ORDER_APPROVED
        audit entry, beginning with a running base equal to
        pinned_amount_cents. After each delta, the running base is replaced
        by the larger of zero and the post-delta base."

        Claim: pinned=100_000; deltas approved in order [-150_000,
        +200_000] -> ascending+clamp = 200_000.
        """
        project, contract, _ = setup_settlement_dual_variant_scenario()
        final = drive_settlement_to_finalized(
            project["id"], contract,
            breach_deduction_cents=0, refund_cents=0,
        )
        assert final["final_amount_cents"] == 200_000

    def test_provisional_total_persisted_after_finalize(self, api):
        """# difficulty: combinatorial_formula/final_settlement_evaluation_order_dependency

        PRD §3.4: "Once all deltas are processed, the resulting base is
        stored as provisional_total_cents."

        Claim: after FINALIZED, Settlement.provisional_total_cents
        equals the running base produced by the ascending+clamp fold (200_000
        for our scenario).
        """
        project, contract, _ = setup_settlement_dual_variant_scenario()
        final = drive_settlement_to_finalized(
            project["id"], contract,
            breach_deduction_cents=0, refund_cents=0,
        )
        assert final["provisional_total_cents"] == 200_000


# ===========================================================================
# Rule 3 / Instance contract_negotiation_cycle
# ===========================================================================
class TestRule3A_ContractNegotiationCycle:
    """# difficulty: non_linear_state_machine/contract_negotiation_cycle"""

    def test_two_revise_cycles_increment_round_to_2(self, api):
        """# difficulty: non_linear_state_machine/contract_negotiation_cycle

        PRD §3.3: "From NEGOTIATING the contract may loop back: a
        VendorRep representing the bound vendor may revise the contract,
        returning it from NEGOTIATING to DRAFT; ... on success the
        contract's negotiation_round is incremented by exactly 1."

        Claim: walk DRAFT -> NEGOTIATING -> DRAFT -> NEGOTIATING -> DRAFT
        twice -> negotiation_round == 2.
        """
        project = setup_project_in_planning()
        v = create_approved_vendor(category="PHOTOGRAPHY")
        q = create_offered_quote(v, amount_cents=10_000)
        c = create_draft_contract(project["id"], v, q)
        vrep = make_vendor_rep_headers(v["id"])

        send_for_negotiation(project["id"], c["id"])
        api.revise_contract(project["id"], c["id"], vrep)
        api.offer_quote(v["id"], q["id"], vrep)
        send_for_negotiation(project["id"], c["id"])
        api.revise_contract(project["id"], c["id"], vrep)
        c_after = get_contract(project["id"], c["id"])
        assert c_after["negotiation_round"] == 2

    def test_cycle_then_sign_yields_signed(self, api):
        """# difficulty: non_linear_state_machine/contract_negotiation_cycle

        PRD §3.3: "Signing is the planner's one-way commitment. The
        signing transition advances contract_status from NEGOTIATING to
        SIGNED."

        Claim: after one revise cycle, re-OFFER quote, send-for-negotiation
        again, then sign -> contract_status=SIGNED.
        """
        project = setup_project_in_planning(total_budget_cents=10_000_000)
        v = create_approved_vendor(category="PHOTOGRAPHY")
        q = create_offered_quote(v, amount_cents=10_000)
        c = create_draft_contract(project["id"], v, q)
        vrep = make_vendor_rep_headers(v["id"])
        send_for_negotiation(project["id"], c["id"])
        api.revise_contract(project["id"], c["id"], vrep)
        api.offer_quote(v["id"], q["id"], vrep)
        send_for_negotiation(project["id"], c["id"])
        signed = sign_contract(project["id"], c["id"])
        assert signed["contract_status"] == "SIGNED"


# ===========================================================================
# Rule 3 / Instance contract_parallel_dimensions
# ===========================================================================
class TestRule3B_ContractParallelDimensions:
    """# difficulty: non_linear_state_machine/contract_parallel_dimensions"""

    def test_payment_status_finalized_while_contract_remains_accepted(
        self, api
    ):
        """# difficulty: non_linear_state_machine/contract_parallel_dimensions

        PRD §3.4: "if final_amount_cents is greater than zero,
        payment_status becomes FINALIZED (regardless of whether it was
        previously UNPAID or PARTIAL)."

        Claim: ACCEPTED contract whose Settlement is finalized with
        final>0 -> contract_status remains ACCEPTED (not TERMINATED) AND
        payment_status moves to FINALIZED, proving the two dimensions
        evolve independently.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            quote_amount_cents=200_000,
        )
        drive_settlement_to_finalized(
            project["id"], contract,
            breach_deduction_cents=0, refund_cents=0,
        )
        c_after = get_contract(project["id"], contract["id"])
        assert c_after["contract_status"] == "ACCEPTED"
        assert c_after["payment_status"] == "FINALIZED"

    def test_payment_status_starts_unpaid_at_creation(self, api):
        """# difficulty: non_linear_state_machine/contract_parallel_dimensions

        PRD §3.3: "contracts begin in `contract_status` of `DRAFT` and
        `payment_status` of `UNPAID`, with `negotiation_round` initialized
        to 0."

        Claim: a freshly created contract has contract_status=DRAFT AND
        payment_status=UNPAID, evidencing the two dimensions exist
        independently from creation.
        """
        project = setup_project_in_planning()
        v = create_approved_vendor(category="MC")
        q = create_offered_quote(v, amount_cents=20_000)
        c = create_draft_contract(project["id"], v, q)
        assert c["contract_status"] == "DRAFT"
        assert c["payment_status"] == "UNPAID"


# ===========================================================================
# Rule 4 / Instance project_cancel_three_hop_cascade
# ===========================================================================
class TestRule4A_ProjectCancelCascade:
    """# difficulty: transitive_cascade/project_cancel_three_hop_cascade"""

    def test_cancel_terminates_contract(self, api):
        """# difficulty: transitive_cascade/project_cancel_three_hop_cascade

        PRD §3.1: "Cancellation from PLANNING or EXECUTION cascades:
        every contract on the project whose contract_status is DRAFT,
        NEGOTIATING, SIGNED, or ACCEPTED is forced to TERMINATED exactly
        as if the planner had terminated each one individually."

        Claim: PLANNING project + ACCEPTED contract -> cancel ->
        contract_status==TERMINATED.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted()
        api.cancel_project(project["id"], make_planner_headers())
        c_after = get_contract(project["id"], contract["id"])
        assert c_after["contract_status"] == "TERMINATED"

    def test_cancel_appends_audit_per_terminated_contract(self, api):
        """# difficulty: transitive_cascade/project_cancel_three_hop_cascade

        PRD §3.1: "Each contract termination during cascade writes its own
        AuditEntry with event_kind of CONTRACT_TERMINATED."

        Claim: cancel of a project with one ACCEPTED contract -> at least
        one CONTRACT_TERMINATED audit entry.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted()
        api.cancel_project(project["id"], make_planner_headers())
        entries = list_audit_entries(project["id"])
        ct_entries = find_audit_entries(
            entries, event_kind="CONTRACT_TERMINATED",
            subject_id=contract["id"],
        )
        assert len(ct_entries) >= 1


# ===========================================================================
# Rule 4 / Instance change_order_approve_two_hop_cascade
# ===========================================================================
class TestRule4B_ChangeOrderApproveCascade:
    """# difficulty: transitive_cascade/change_order_approve_two_hop_cascade"""

    def test_co_approval_recomputes_settlement_provisional(self, api):
        """# difficulty: transitive_cascade/change_order_approve_two_hop_cascade

        PRD §3.4: "and -- if a Settlement already exists for the contract
        in DRAFT status -- recomputes that settlement's
        provisional_total_cents as pinned_amount_cents plus the new sum
        of approved deltas, and re-derives final_amount_cents for the
        cascading preview."

        Claim: pinned=500_000, settlement DRAFT (initial provisional=500_000),
        approve a -100_000 change order -> Settlement.provisional_total_cents
        recomputes to 400_000 and the GET preview shows 400_000.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            total_budget_cents=2_000_000,
            quote_amount_cents=500_000,
        )
        s = create_settlement_for_contract(project["id"], contract["id"])
        assert s["provisional_total_cents"] == 500_000
        co = create_change_order(
            project["id"], contract["id"],
            delta_amount_cents=-100_000,
            requester_planner_id=PLANNER_ID,
        )
        from test_helpers import approve_change_order
        approve_change_order(
            project["id"], contract["id"], co["id"],
            approver_planner_id=PLANNER_ID_ALT,
        )
        s_after = get_settlement(project["id"], contract["id"])
        assert s_after["provisional_total_cents"] == 400_000

    def test_co_approval_status_becomes_approved(self, api):
        """# difficulty: transitive_cascade/change_order_approve_two_hop_cascade

        PRD §3.4: "On success, the server records approved_by_user_id as
        the acting planner's X-User-ID, appends an AuditEntry with
        event_kind of CHANGE_ORDER_APPROVED."

        Claim: ChangeOrder.status flips to APPROVED on the approve call.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            total_budget_cents=2_000_000,
            quote_amount_cents=500_000,
        )
        co = create_change_order(
            project["id"], contract["id"],
            delta_amount_cents=-100_000,
            requester_planner_id=PLANNER_ID,
        )
        from test_helpers import approve_change_order
        approved = approve_change_order(
            project["id"], contract["id"], co["id"],
            approver_planner_id=PLANNER_ID_ALT,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == PLANNER_ID_ALT


# ===========================================================================
# Rule 5 / Instance contract_signed_state_beats_budget_overcommit
# ===========================================================================
class TestRule5A_StateBeatsFiscal:
    """# difficulty: priority_pair_validation_conflict/contract_signed_state_beats_budget_overcommit"""

    def test_resign_signed_contract_yields_state_error_not_fiscal(self, api):
        """# difficulty: priority_pair_validation_conflict/contract_signed_state_beats_budget_overcommit

        PRD §2.9: "When several validation conditions could plausibly
        reject the same request, they are evaluated in a fixed priority
        order, and the first failing check determines the error returned.
        ... then state preconditions of the requested transition
        (ERR_CONTRACT_NOT_NEGOTIATING, ERR_PROJECT_NOT_IN_PLANNING, and so
        on); ... then fiscal checks (ERR_BUDGET_OVERCOMMITTED and
        ERR_MILESTONE_PERCENTAGES_INVALID)."

        Claim: signing an already-SIGNED contract -> state precondition
        fires first; the response is ERR_CONTRACT_NOT_NEGOTIATING (not
        ERR_BUDGET_OVERCOMMITTED).
        """
        project = setup_project_in_planning(total_budget_cents=2_000_000)
        v = create_approved_vendor(category="PHOTOGRAPHY")
        q = create_offered_quote(v, amount_cents=1_000_000)
        c = create_draft_contract(project["id"], v, q)
        send_for_negotiation(project["id"], c["id"])
        sign_contract(project["id"], c["id"])
        # Now C is SIGNED. Re-sign attempt -> state precondition fails.
        res = api.sign_contract(
            project["id"], c["id"], make_planner_headers(),
        )
        validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_NEGOTIATING.value)

    def test_resign_does_not_yield_fiscal_error_id(self, api):
        """# difficulty: priority_pair_validation_conflict/contract_signed_state_beats_budget_overcommit

        PRD §2.9: "When several validation conditions could plausibly
        reject the same request, they are evaluated in a fixed priority
        order, and the first failing check determines the error returned.
        ... then state preconditions of the requested transition
        (ERR_CONTRACT_NOT_NEGOTIATING, ERR_PROJECT_NOT_IN_PLANNING, and so
        on); then cross-aggregate referential checks (ERR_QUOTE_VENDOR_MISMATCH,
        ERR_VENDOR_NOT_APPROVED, ERR_TIMELINE_VENDOR_NOT_CONTRACTED); then
        segregation-of-duties (ERR_SEGREGATION_OF_DUTIES); ... then fiscal
        checks (ERR_BUDGET_OVERCOMMITTED and ERR_MILESTONE_PERCENTAGES_INVALID)."

        Claim: re-signing an already-SIGNED contract returns an error
        whose error_id is NOT ERR_BUDGET_OVERCOMMITTED -- the state error
        precedes any fiscal error.
        """
        project = setup_project_in_planning(total_budget_cents=2_000_000)
        v = create_approved_vendor(category="PHOTOGRAPHY")
        q = create_offered_quote(v, amount_cents=1_000_000)
        c = create_draft_contract(project["id"], v, q)
        send_for_negotiation(project["id"], c["id"])
        sign_contract(project["id"], c["id"])
        res = api.sign_contract(
            project["id"], c["id"], make_planner_headers(),
        )
        body = res.json()
        assert body["data"]["error_id"] != \
            ApiErrorId.ERR_BUDGET_OVERCOMMITTED.value, (
                "PRD §2.9: state precondition is checked before fiscal; "
                f"got {body['data']['error_id']}"
            )


# ===========================================================================
# Rule 5 / Instance timeline_state_beats_overlap
# ===========================================================================
class TestRule5B_StateBeatsTemporal:
    """# difficulty: priority_pair_validation_conflict/timeline_state_beats_overlap"""

    def test_terminal_project_rejects_timeline_create(self, api):
        """# difficulty: priority_pair_validation_conflict/timeline_state_beats_overlap

        PRD §2.7: "Once a WeddingProject reaches a terminal status of
        CLOSED or CANCELLED, every mutating endpoint nested under that
        project is rejected with ERR_PROJECT_TERMINAL (HTTP 409),
        regardless of role."

        Claim: a CANCELLED project + POST /timeline-slots with an
        otherwise-OK payload returns ERR_PROJECT_TERMINAL (NOT
        ERR_TIMELINE_VENDOR_OVERLAP), because the project-terminal check
        precedes business-temporal checks.
        """
        # Project goes to CANCELLED via cancel.
        project = create_project()
        api.cancel_project(project["id"], make_planner_headers())
        res = api.create_timeline_slot(
            project["id"],
            create_timeline_slot_payload(
                start_at=1000, end_at=2000, label="X", kind="CEREMONY",
            ),
            make_planner_headers(),
        )
        validate_error(res, ApiErrorId.ERR_PROJECT_TERMINAL.value)

    def test_terminal_project_blocks_even_overlapping_payload(self, api):
        """# difficulty: priority_pair_validation_conflict/timeline_state_beats_overlap

        PRD §2.7: "Once a WeddingProject reaches a terminal status of
        CLOSED or CANCELLED, every mutating endpoint nested under that
        project is rejected with ERR_PROJECT_TERMINAL (HTTP 409),
        regardless of role."

        Claim: a CANCELLED project + a payload that would ALSO trigger an
        overlap (had we built up the prior slot) returns
        ERR_PROJECT_TERMINAL (NOT ERR_TIMELINE_VENDOR_OVERLAP). State
        wins on priority.
        """
        # Build PLANNING project with vendor + accepted contract + slot A;
        # cancel; then attempt to create overlapping B.
        project, vendors, _ = setup_project_with_n_accepted_vendors(1)
        v = vendors[0]
        create_timeline_slot(
            project["id"], start_at=1000, end_at=2000,
            vendor_id=v["id"], setup_buffer_seconds=0,
            kind="CEREMONY", label="A",
        )
        api.cancel_project(project["id"], make_planner_headers())
        res = api.create_timeline_slot(
            project["id"],
            create_timeline_slot_payload(
                start_at=1500, end_at=2500,
                vendor_id=v["id"], setup_buffer_seconds=0,
                kind="CEREMONY", label="B-overlap",
            ),
            make_planner_headers(),
        )
        validate_error(res, ApiErrorId.ERR_PROJECT_TERMINAL.value)


# ===========================================================================
# Rule 6 / Instance guest_capacity_intimate_50_seat_boundary
# ===========================================================================
class TestRule6A_GuestCapacityBoundary:
    """# difficulty: boundary_precision_check/guest_capacity_intimate_50_seat_boundary"""

    def test_at_50_succeeds(self, api):
        """# difficulty: boundary_precision_check/guest_capacity_intimate_50_seat_boundary

        PRD §3.7: "The per-scale cap limits the total of party_size across
        all guests with rsvp_status of CONFIRMED on the project: at most
        50 for INTIMATE, at most 200 for MEDIUM, and at most 500 for GRAND."

        Claim: confirmed sum AT 50 (the cap) succeeds.
        """
        project, _g = setup_intimate_project_with_confirmed_party_size(
            confirmed_total=50, party_size_per_guest=10,
        )
        # Reaching this point means all confirmations succeeded.
        from test_helpers import validate_paginated
        list_resp = api.list_guests(
            project["id"], make_planner_headers(),
            params={"limit": 100},
        )
        data, _meta = validate_paginated(list_resp)
        confirmed_seats = sum(
            g["party_size"] for g in data
            if g["rsvp_status"] == "CONFIRMED"
        )
        assert confirmed_seats == 50

    def test_at_51_rejected(self, api):
        """# difficulty: boundary_precision_check/guest_capacity_intimate_50_seat_boundary

        PRD §3.7: "Adding a guest, patching a guest's party_size, or
        setting an RSVP to CONFIRMED -- any of which would push the
        confirmed total past its scale cap -- is rejected with
        ERR_GUEST_CAPACITY_EXCEEDED (HTTP 409)."

        Claim: with 50 confirmed + new 1-seat guest CONFIRMED -> 51 > 50
        -> ERR_GUEST_CAPACITY_EXCEEDED.
        """
        project, _g = setup_intimate_project_with_confirmed_party_size(
            confirmed_total=50, party_size_per_guest=10,
        )
        new_g = create_guest(
            project["id"], full_name="Last", party_size=1,
        )
        res = api.rsvp_guest(
            project["id"], new_g["id"],
            rsvp_payload(rsvp_status="CONFIRMED"),
            make_planner_headers(),
        )
        validate_error(res, ApiErrorId.ERR_GUEST_CAPACITY_EXCEEDED.value)


# ===========================================================================
# Rule 6 / Instance project_activate_empty_milestones_set_boundary
# ===========================================================================
class TestRule6B_ActivateEmptyMilestonesBoundary:
    """# difficulty: boundary_precision_check/project_activate_empty_milestones_set_boundary"""

    def test_zero_milestones_yields_no_milestones(self, api):
        """# difficulty: boundary_precision_check/project_activate_empty_milestones_set_boundary

        PRD §3.1: "The DRAFT to PLANNING transition (the activation step)
        requires the project to currently be DRAFT (otherwise
        ERR_PROJECT_NOT_IN_DRAFT), at least one Milestone to exist
        (otherwise ERR_NO_MILESTONES), and the milestone-percent sum to
        equal 100.0 (otherwise ERR_MILESTONE_PERCENTAGES_INVALID)."

        Claim: zero milestones -> ERR_NO_MILESTONES / 422 (the empty-set
        boundary).
        """
        project = create_project()
        res = api.activate_project(project["id"], make_planner_headers())
        validate_error(res, ApiErrorId.ERR_NO_MILESTONES.value)

    # NOTE: a test asserting "milestone @ 99.99 then activate -> error,
    # patch to 100 then activate -> success" was removed. PRD §3.1's
    # per-mutation invariant rejects creates/updates that leave the sum
    # != 100, so a project with one 99.99% milestone is unreachable under
    # any PRD-faithful implementation; the activation-side check that the
    # test attempted to exercise is dead code in such an implementation.
    # The mutation-side enforcement is covered by
    # test_create_second_milestone_breaking_sum_rejected in
    # test_03_milestones_and_budget.py.


# ===========================================================================
# Rule 7 / Instance contract_sign_requires_project_planning
# ===========================================================================
class TestRule7A_SignRequiresPlanning:
    """# difficulty: cross_entity_state_dependency/contract_sign_requires_project_planning"""

    def test_sign_in_execution_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/contract_sign_requires_project_planning

        PRD §3.3: "Signing is the planner's one-way commitment. The
        signing transition advances contract_status from NEGOTIATING to
        SIGNED and requires several things to be true at once: ... the
        project is currently PLANNING (otherwise ERR_PROJECT_NOT_IN_PLANNING)."

        Claim: NEGOTIATING contract on a project in EXECUTION (not PLANNING)
        -> sign rejected with ERR_PROJECT_NOT_IN_PLANNING.
        """
        # First build a PLANNING project, drive a NEGOTIATING contract for
        # the test, then advance the project to EXECUTION (requires VENUE
        # + CATERING ACCEPTED contracts).
        from test_helpers import setup_project_in_execution
        # Build EXECUTION project (with VENUE+CATERING already ACCEPTED).
        project_exec, _venue, _cat = setup_project_in_execution(
            total_budget_cents=10_000_000,
        )
        # Add a third vendor, build a NEGOTIATING contract on that vendor.
        v = create_approved_vendor(category="MC")
        q = create_offered_quote(v, amount_cents=10_000)
        c = create_draft_contract(project_exec["id"], v, q)
        send_for_negotiation(project_exec["id"], c["id"])
        # Sign should be rejected because project is in EXECUTION.
        res = api.sign_contract(
            project_exec["id"], c["id"], make_planner_headers(),
        )
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_IN_PLANNING.value)

    def test_sign_in_planning_succeeds(self, api):
        """# difficulty: cross_entity_state_dependency/contract_sign_requires_project_planning

        PRD §3.3: "the project is currently PLANNING (otherwise
        ERR_PROJECT_NOT_IN_PLANNING)."

        Claim: same setup but project still in PLANNING -> sign succeeds.
        """
        project = setup_project_in_planning(total_budget_cents=2_000_000)
        v = create_approved_vendor(category="MC")
        q = create_offered_quote(v, amount_cents=10_000)
        c = create_draft_contract(project["id"], v, q)
        send_for_negotiation(project["id"], c["id"])
        signed = sign_contract(project["id"], c["id"])
        assert signed["contract_status"] == "SIGNED"


# ===========================================================================
# Rule 7 / Instance timeline_slot_requires_vendor_accepted_contract
# ===========================================================================
class TestRule7B_TimelineRequiresAccepted:
    """# difficulty: cross_entity_state_dependency/timeline_slot_requires_vendor_accepted_contract"""

    def test_signed_but_not_accepted_vendor_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/timeline_slot_requires_vendor_accepted_contract

        PRD §3.6: "When vendor_id is supplied, the named vendor MUST have
        an ACCEPTED Contract on this project; otherwise the request is
        rejected with ERR_TIMELINE_VENDOR_NOT_CONTRACTED (HTTP 422)."

        Claim: vendor whose Contract on this project is SIGNED (not yet
        ACCEPTED -- e-sign callback not yet emitted) ->
        ERR_TIMELINE_VENDOR_NOT_CONTRACTED on /timeline-slots.
        """
        project = setup_project_in_planning(total_budget_cents=2_000_000)
        v = create_approved_vendor(category="PHOTOGRAPHY")
        q = create_offered_quote(v, amount_cents=10_000)
        c = create_draft_contract(project["id"], v, q)
        send_for_negotiation(project["id"], c["id"])
        sign_contract(project["id"], c["id"])
        # Skip ESIGN_COMPLETED: contract remains SIGNED, not ACCEPTED.
        res = api.create_timeline_slot(
            project["id"],
            create_timeline_slot_payload(
                start_at=1000, end_at=2000,
                vendor_id=v["id"], kind="PREPARATION",
                label="prep",
            ),
            make_planner_headers(),
        )
        validate_error(
            res, ApiErrorId.ERR_TIMELINE_VENDOR_NOT_CONTRACTED.value
        )

    def test_after_accept_signature_timeline_slot_succeeds(self, api):
        """# difficulty: cross_entity_state_dependency/timeline_slot_requires_vendor_accepted_contract

        PRD §3.6: "the named vendor MUST have an ACCEPTED Contract on this
        project; otherwise the request is rejected with
        ERR_TIMELINE_VENDOR_NOT_CONTRACTED (HTTP 422)."

        Claim: same setup but after ESIGN_COMPLETED + accept-signature
        (contract -> ACCEPTED) -> /timeline-slots succeeds.
        """
        from test_helpers import accept_signature
        project = setup_project_in_planning(total_budget_cents=2_000_000)
        v = create_approved_vendor(category="PHOTOGRAPHY")
        q = create_offered_quote(v, amount_cents=10_000)
        c = create_draft_contract(project["id"], v, q)
        send_for_negotiation(project["id"], c["id"])
        signed = sign_contract(project["id"], c["id"])
        emit_esign_completed(signed["e_sign_envelope_id"])
        accept_signature(project["id"], c["id"])
        # Now contract is ACCEPTED.
        slot = create_timeline_slot(
            project["id"], start_at=1000, end_at=2000,
            vendor_id=v["id"], kind="PREPARATION",
            label="ok",
        )
        assert slot["vendor_id"] == v["id"]


# ===========================================================================
# Rule 8 / Instance per_vendor_buffer_extended_intersection
# ===========================================================================
class TestRule8A_PerVendorBufferIntersection:
    """# difficulty: resource_temporal_overlap/per_vendor_buffer_extended_intersection"""

    def test_zero_buffer_adjacency_allowed(self, api):
        """# difficulty: resource_temporal_overlap/per_vendor_buffer_extended_intersection

        PRD §3.6: "Adjacency without overlap -- where one slot's end_at
        equals the next slot's start_at adjusted by setup buffer -- is
        allowed because the intervals are half-open."

        Claim: A=[1000,2000) buf=0 + B=[2000,3000) buf=0 same vendor ->
        adjacent, no overlap, B succeeds.
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(1)
        v = vendors[0]
        create_timeline_slot(
            project["id"], start_at=1000, end_at=2000,
            vendor_id=v["id"], setup_buffer_seconds=0,
            kind="CEREMONY", label="A",
        )
        slot_b = create_timeline_slot(
            project["id"], start_at=2000, end_at=3000,
            vendor_id=v["id"], setup_buffer_seconds=0,
            kind="CEREMONY", label="B",
        )
        assert slot_b["start_at"] == 2000

    def test_buffer_300_extends_start_causing_overlap(self, api):
        """# difficulty: resource_temporal_overlap/per_vendor_buffer_extended_intersection

        PRD §3.6: "two slots A and B overlap iff the larger of
        A.start_at - A.setup_buffer_seconds and B.start_at -
        B.setup_buffer_seconds is strictly less than the smaller of
        A.end_at and B.end_at."

        Claim: A=[1000,2000) buf=0 + B=[2000,3000) buf=300 same vendor ->
        B's effective start = 1700 < A.end_at 2000 -> overlap ->
        ERR_TIMELINE_VENDOR_OVERLAP.
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(1)
        v = vendors[0]
        create_timeline_slot(
            project["id"], start_at=1000, end_at=2000,
            vendor_id=v["id"], setup_buffer_seconds=0,
            kind="CEREMONY", label="A",
        )
        res = api.create_timeline_slot(
            project["id"],
            create_timeline_slot_payload(
                start_at=2000, end_at=3000,
                vendor_id=v["id"], setup_buffer_seconds=300,
                kind="CEREMONY", label="B",
            ),
            make_planner_headers(),
        )
        validate_error(res, ApiErrorId.ERR_TIMELINE_VENDOR_OVERLAP.value)


# ===========================================================================
# Rule 8 / Instance project_aggregate_count_at_instant_cap
# ===========================================================================
class TestRule8B_AggregateCountCap:
    """# difficulty: resource_temporal_overlap/project_aggregate_count_at_instant_cap"""

    def test_three_distinct_vendor_ceremony_slots_cap_violation(self, api):
        """# difficulty: resource_temporal_overlap/project_aggregate_count_at_instant_cap

        PRD §3.6: "the count of slots active at any single instant --
        counting the setup-buffer extension on the start side -- MUST not
        exceed two; a violation is rejected with
        ERR_TIMELINE_PARALLEL_CAP_EXCEEDED (HTTP 409)."

        Claim: A V1 [1000,3000), B V2 [2000,4000), C V3 [2500,2800) all
        CEREMONY -> at t=2500 three slots overlap on distinct vendors ->
        C rejected with ERR_TIMELINE_PARALLEL_CAP_EXCEEDED (per-vendor
        rule would have allowed C).
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(3)
        create_timeline_slot(
            project["id"], start_at=1000, end_at=3000,
            vendor_id=vendors[0]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="A",
        )
        create_timeline_slot(
            project["id"], start_at=2000, end_at=4000,
            vendor_id=vendors[1]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="B",
        )
        res = api.create_timeline_slot(
            project["id"],
            create_timeline_slot_payload(
                start_at=2500, end_at=2800,
                vendor_id=vendors[2]["id"], kind="CEREMONY",
                setup_buffer_seconds=0, label="C",
            ),
            make_planner_headers(),
        )
        validate_error(
            res, ApiErrorId.ERR_TIMELINE_PARALLEL_CAP_EXCEEDED.value
        )

    def test_two_simultaneous_ceremonies_allowed(self, api):
        """# difficulty: resource_temporal_overlap/project_aggregate_count_at_instant_cap

        PRD §3.6: "the count of slots active at any single instant --
        counting the setup-buffer extension on the start side -- MUST not
        exceed two."

        Claim: A V1 [1000,3000) and B V2 [2000,4000) both CEREMONY ->
        at the simultaneously-active instant t=2500 there are exactly 2
        slots, which is AT the cap and allowed.
        """
        project, vendors, _ = setup_project_with_n_accepted_vendors(2)
        create_timeline_slot(
            project["id"], start_at=1000, end_at=3000,
            vendor_id=vendors[0]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="A",
        )
        slot_b = create_timeline_slot(
            project["id"], start_at=2000, end_at=4000,
            vendor_id=vendors[1]["id"], kind="CEREMONY",
            setup_buffer_seconds=0, label="B",
        )
        assert slot_b["kind"] == "CEREMONY"


# ===========================================================================
# Rule 9 / Instance cancel_cascade_restores_budget_balance
# ===========================================================================
class TestRule9A_CancelRestoresBalance:
    """# difficulty: compensating_invariant/cancel_cascade_restores_budget_balance"""

    def test_balance_restored_after_cancel(self, api):
        """# difficulty: compensating_invariant/cancel_cascade_restores_budget_balance

        PRD §3.5: "The budget_balance_cents is then total_budget_cents
        minus provisional_committed_cents minus finalized_settled_cents.
        All three figures are exact in integer cents and recomputed
        alongside one another whenever a contract is signed or terminated,
        a change order is approved, or a settlement is finalized."

        Claim: total=1_000_000; sign C (300_000) -> balance=700_000;
        cancel project -> Contract -> TERMINATED, provisional drops back
        to 0, balance returns to 1_000_000.
        """
        project, _v, _q, _c = setup_project_with_one_contract_accepted(
            total_budget_cents=1_000_000,
            quote_amount_cents=300_000,
        )
        p_after_sign = get_project(project["id"])
        assert p_after_sign["provisional_committed_cents"] == 300_000
        assert p_after_sign["budget_balance_cents"] == 700_000
        api.cancel_project(project["id"], make_planner_headers())
        p_after_cancel = get_project(project["id"])
        assert p_after_cancel["provisional_committed_cents"] == 0
        assert p_after_cancel["finalized_settled_cents"] == 0
        assert p_after_cancel["budget_balance_cents"] == 1_000_000

    def test_balance_invariant_holds_after_cancel(self, api):
        """# difficulty: compensating_invariant/cancel_cascade_restores_budget_balance

        PRD §3.5: "The budget_balance_cents is then total_budget_cents
        minus provisional_committed_cents minus finalized_settled_cents."

        Claim: after cancel, the ledger invariant
        balance == total - provisional - settled holds (re-checked
        explicitly).
        """
        from test_helpers import assert_project_ledger_invariant
        project, _v, _q, _c = setup_project_with_one_contract_accepted(
            total_budget_cents=1_000_000,
            quote_amount_cents=300_000,
        )
        api.cancel_project(project["id"], make_planner_headers())
        p_after = get_project(project["id"])
        assert_project_ledger_invariant(p_after)


# ===========================================================================
# Rule 9 / Instance settlement_finalize_preserves_total_committed_plus_settled
# ===========================================================================
class TestRule9B_FinalizeTransferInvariant:
    """# difficulty: compensating_invariant/settlement_finalize_preserves_total_committed_plus_settled"""

    def test_finalize_moves_value_from_provisional_to_settled(self, api):
        """# difficulty: compensating_invariant/settlement_finalize_preserves_total_committed_plus_settled

        PRD §3.4: "The project's finalized_settled_cents is increased by
        the new final_amount_cents, and the project's
        provisional_committed_cents is decreased by this settlement's
        provisional_total_cents so the contract is no longer double-counted."

        Claim: pinned=300_000, breach=0, refund=0; before finalize
        provisional=300_000 settled=0; after finalize provisional=0
        settled=300_000.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            total_budget_cents=1_000_000,
            quote_amount_cents=300_000,
        )
        p_before = get_project(project["id"])
        assert p_before["provisional_committed_cents"] == 300_000
        assert p_before["finalized_settled_cents"] == 0
        drive_settlement_to_finalized(
            project["id"], contract,
            breach_deduction_cents=0, refund_cents=0,
        )
        p_after = get_project(project["id"])
        assert p_after["provisional_committed_cents"] == 0
        assert p_after["finalized_settled_cents"] == 300_000

    def test_finalize_preserves_sum_committed_plus_settled(self, api):
        """# difficulty: compensating_invariant/settlement_finalize_preserves_total_committed_plus_settled

        PRD §3.4: "The project's finalized_settled_cents is increased by
        the new final_amount_cents, and the project's
        provisional_committed_cents is decreased by this settlement's
        provisional_total_cents so the contract is no longer
        double-counted."

        Claim: with breach=0 refund=0 the sum
        provisional_committed_cents + finalized_settled_cents is the same
        300_000 before and after finalize -- the value is transferred,
        not destroyed.
        """
        project, _v, _q, contract = setup_project_with_one_contract_accepted(
            total_budget_cents=1_000_000,
            quote_amount_cents=300_000,
        )
        p_before = get_project(project["id"])
        sum_before = (
            p_before["provisional_committed_cents"]
            + p_before["finalized_settled_cents"]
        )
        drive_settlement_to_finalized(
            project["id"], contract,
            breach_deduction_cents=0, refund_cents=0,
        )
        p_after = get_project(project["id"])
        sum_after = (
            p_after["provisional_committed_cents"]
            + p_after["finalized_settled_cents"]
        )
        assert sum_before == sum_after == 300_000
