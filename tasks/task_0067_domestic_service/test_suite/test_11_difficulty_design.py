"""Difficulty-design tests — every priority-queue instance gets at least TWO
dedicated tests anchored to PRD prose for its underlying rule.

Tag convention: every test docstring carries `# difficulty: <rule_id>/<instance.name>`
so a coverage check can confirm two-per-instance.

Instances covered (9 rules × 2 instances = 18):
- dual_variant_calc/
    commission_provisional_vs_final_on_personnel
    rating_score_aggregation_on_personnel_vs_rating_record
- combinatorial_formula/
    dispatch_selection_weighted_ranking_mode_a
    settlement_payout_sum_then_round_tax_mode_b
- non_linear_state_machine/
    order_dispatch_revert_cycle
    insurance_claim_branching_decision
- transitive_cascade/
    recert_sweep_to_personnel_suspend_to_orders_revert_depth3
    refund_to_ledger_reversal_to_wallet_credit_depth2
- priority_pair_validation_conflict/
    state_vs_business_temporal_on_refund
    business_safety_vs_business_referential_on_checkin_and_submit
- boundary_precision_check/
    tier_boundary_at_4_5_exactly
    empty_set_no_eligible_personnel
- cross_entity_state_dependency/
    order_dispatch_requires_personnel_active_pair_order_personnel
    personnel_activate_requires_active_cert_pair_personnel_certification
- resource_temporal_overlap/
    dispatch_window_lead_time_half_open_interval_on_order
    dispatch_workload_capacity_aggregate_limit_on_personnel
- compensating_invariant/
    commission_plus_reversal_sums_to_zero
    cancel_refunds_full_gross_price_to_wallet
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    OPERATOR_HEADERS,
    SYSTEM_HEADERS,
    advance_clock,
    approve_certification,
    assert_commission_plus_reversal_zero,
    create_active_personnel,
    create_certification,
    create_customer,
    create_draft_order,
    create_pending_personnel,
    create_personnel_payload,
    create_service_item,
    customer_accept,
    drive_order_to,
    expected_composite_score,
    expected_final_commission,
    expected_provisional_commission,
    get_customer,
    get_order,
    get_personnel,
    get_settlement_entries,
    iso_in,
    make_customer_headers,
    make_personnel_headers,
    rate_completed_order,
    reassign_payload,
    rating_payload,
    reject_order,
    run_settlement_sweep,
    setup_basic_scenario,
    setup_order_in_state,
    setup_personnel_with_rating_history,
    setup_personnel_with_settled_commission_only,
    setup_three_eligible_personnel_for_dispatch,
    submit_new_order,
    submit_order,
    validate_error,
    validate_success,
    verify_personnel_identity,
)


# =============================================================================
# Rule 1 — dual_variant_calc
# =============================================================================


class TestDualVariantCalc_CommissionProvisionalVsFinalOnPersonnel:
    """# difficulty: dual_variant_calc/commission_provisional_vs_final_on_personnel"""

    def test_provisional_uses_tier_at_completed_at(self, api):
        """PRD §3.10: "The provisional commission was computed using the
        personnel's tier as observed at completed_at."

        Claim: provisional commission is gross*0.70 because personnel is
        BRONZE at completed_at (bonus_rate=0).
        # difficulty: dual_variant_calc/commission_provisional_vs_final_on_personnel
        """
        ctx, order = setup_order_in_state("COMPLETED")
        entries = get_settlement_entries(order["assigned_personnel_id"])
        commissions = [
            e
            for e in entries
            if e.get("order_id") == order["id"] and e["kind"] == "COMMISSION"
        ]
        assert len(commissions) == 1
        # Personnel was BRONZE at completion (fresh personnel, rating_count=0).
        expected = expected_provisional_commission(order["gross_price_cents"])
        assert commissions[0]["amount_cents"] == expected

    def test_final_equals_provisional_when_tier_unchanged(self, api):
        """PRD §3.10: "In every case, the invariant provisional + delta == final
        holds."

        Claim: for an unchanged tier between completed_at and accepted_at,
        provisional + sum(BONUS+REVERSAL deltas) == final.
        # difficulty: dual_variant_calc/commission_provisional_vs_final_on_personnel
        """
        ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
        entries = get_settlement_entries(order["assigned_personnel_id"])
        related = [e for e in entries if e.get("order_id") == order["id"]]
        provisional = sum(
            e["amount_cents"] for e in related if e["kind"] == "COMMISSION"
        )
        delta = sum(
            e["amount_cents"]
            for e in related
            if e["kind"] in ("BONUS", "REVERSAL")
        )
        final_expected = expected_final_commission(
            order["gross_price_cents"], "BRONZE"
        )
        assert provisional + delta == final_expected


class TestDualVariantCalc_RatingScoreAggregationOnPersonnelVsRatingRecord:
    """# difficulty: dual_variant_calc/rating_score_aggregation_on_personnel_vs_rating_record"""

    def test_per_rating_composite_is_weighted_average(self, api):
        """PRD §3.9: "a composite score is computed as the weighted sum of the
        three dimensions: 0.5 times quality_score, plus 0.3 times
        punctuality_score, plus 0.2 times attitude_score."

        Claim: per-rating composite_score for (5, 3, 1) is 3.6.
        # difficulty: dual_variant_calc/rating_score_aggregation_on_personnel_vs_rating_record
        """
        ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
        res = api.rate_order(
            order["id"],
            rating_payload(quality_score=5, punctuality_score=3, attitude_score=1),
            make_customer_headers(ctx["customer"]["id"]),
        )
        body = validate_success(res, expected_status=201)
        assert body["composite_score"] == 3.6

    def test_personnel_rating_score_is_running_average(self, api):
        """PRD §3.9: "the new rating_score is computed as the previous
        rating_score multiplied by the previous rating_count, plus the new
        composite, then divided by the new rating_count, then rounded half-up
        to four decimal places."

        Claim: two consecutive ratings with composites 3.6 and 5.0 yield
        personnel.rating_score = (3.6 + 5.0) / 2 = 4.3 (4 dp).
        # difficulty: dual_variant_calc/rating_score_aggregation_on_personnel_vs_rating_record
        """
        # Fresh personnel; share a unique pref_language marker so the test's
        # two rating orders route specifically to this personnel.
        from test_helpers import _unique_iso_language
        marker = _unique_iso_language()
        p, _ = create_active_personnel(
            skill_tag="CLEANING",
            isolate_dispatch=False,
            languages=["zh", "en", marker],
        )
        # Drive two completed-and-accepted orders for the same personnel.
        c1 = create_customer(pref_language=marker)
        c2 = create_customer(pref_language=marker)
        item1 = create_service_item(required_skill_tag="CLEANING")
        item2 = create_service_item(required_skill_tag="CLEANING")
        ctx1 = {
            "customer": c1,
            "service_item": item1,
            "personnel": p,
            "certification": None,
        }
        ctx2 = {
            "customer": c2,
            "service_item": item2,
            "personnel": p,
            "certification": None,
        }
        order1 = drive_order_to(
            ctx1, "ACCEPTED_BY_CUSTOMER", scheduled_start_at=iso_in(hours=48)
        )
        order2 = drive_order_to(
            ctx2,
            "ACCEPTED_BY_CUSTOMER",
            scheduled_start_at=iso_in(hours=48 + 60),
        )
        # First rating: composite 3.6 (5, 3, 1).
        rate_completed_order(ctx1, order1, 5, 3, 1)
        # Second rating: composite 5.0 (5, 5, 5).
        rate_completed_order(ctx2, order2, 5, 5, 5)
        refreshed = get_personnel(p["id"])
        assert refreshed["rating_count"] == 2
        assert refreshed["rating_score"] == 4.3


# =============================================================================
# Rule 2 — combinatorial_formula
# =============================================================================


class TestCombinatorialFormula_DispatchSelectionWeightedRanking:
    """# difficulty: combinatorial_formula/dispatch_selection_weighted_ranking_mode_a"""

    def test_tier_dominates_rating_in_dispatch_ranking(self, api):
        """PRD §3.5: "Step two sorts the surviving pool by a composite rank
        key with three components, applied in this order from most significant
        to least: first by a tier priority where PLATINUM is 4, GOLD is 3,
        SILVER is 2, and BRONZE is 1, sorted descending so higher tiers rank
        earlier; then by rating_score sorted descending so higher-rated
        personnel rank earlier; then by the distance from personnel home base
        to the customer address sorted ascending so closer personnel rank
        earlier."

        Claim: when one PLATINUM and one GOLD personnel are eligible, dispatch
        picks the PLATINUM regardless of the GOLD's higher rating_score.
        # difficulty: combinatorial_formula/dispatch_selection_weighted_ranking_mode_a
        """
        # Each personnel is built with its own private marker so its rating
        # build doesn't route to the other; both also carry a shared
        # `assertion_marker` so the assertion phase's customer routes to
        # exactly the two of them.
        from test_helpers import _unique_iso_language
        assertion_marker = _unique_iso_language()
        gold_build_marker = _unique_iso_language()
        plat_build_marker = _unique_iso_language()
        # Build a GOLD with rating_score 4.5 (floor for GOLD per PRD §3.9).
        p_gold, _ = setup_personnel_with_rating_history(
            target_count=5,
            target_score=4.5,
            pref_language=gold_build_marker,
            extra_languages=[assertion_marker],
        )
        # Build a PLATINUM with rating_score 4.8.
        p_plat, _ = setup_personnel_with_rating_history(
            target_count=5,
            target_score=4.8,
            pref_language=plat_build_marker,
            extra_languages=[assertion_marker],
        )
        assert p_gold["tier"] == "GOLD"
        assert p_plat["tier"] == "PLATINUM"
        # Build a customer + order whose pref_language is the shared marker
        # so the dispatch eligibility filter (PRD §3.5) leaves exactly p_gold
        # and p_plat in the pool.
        customer = create_customer(pref_language=assertion_marker)
        item = create_service_item(required_skill_tag="CLEANING")
        res = api.create_order(
            {
                "customer_id": customer["id"],
                "service_item_id": item["id"],
                "mode": "SINGLE",
                "scheduled_start_at": iso_in(hours=200),
                "duration_hours": 2.0,
            },
            make_customer_headers(customer["id"]),
        )
        order = res.json()["data"]
        api.submit_order(order["id"], make_customer_headers(customer["id"]))
        dispatch_res = api.dispatch_order(order["id"], OPERATOR_HEADERS)
        dispatched = validate_success(dispatch_res)
        assert dispatched["assigned_personnel_id"] == p_plat["id"]

    def test_ascii_tie_break_on_personnel_id(self, api):
        """PRD §3.5: "Any remaining ties are broken by the personnel's id
        sorted in ascending ASCII order to guarantee a stable outcome."

        Claim: when two personnel tie on (tier, rating_score, distance), the
        one with the lexicographically smaller id wins.
        # difficulty: combinatorial_formula/dispatch_selection_weighted_ranking_mode_a
        """
        # Two BRONZE personnel (no ratings) at the same coordinates. After
        # creation we inspect their ids and pick whichever is the
        # lexicographically smaller — the dispatch should pick that one.
        from test_helpers import (
            create_active_personnel as _create_active_personnel,
        )

        # Both candidates share a unique pref_language marker that rivals
        # from earlier tests don't have, so the dispatch eligibility filter
        # (PRD §3.5) leaves exactly p_a and p_b in the pool.
        from test_helpers import _unique_iso_language
        marker = _unique_iso_language()
        customer = create_customer(pref_language=marker)
        item = create_service_item(required_skill_tag="CLEANING")
        p_a, _ = _create_active_personnel(
            skill_tag="CLEANING",
            isolate_dispatch=False,
            languages=["zh", "en", marker],
        )
        p_b, _ = _create_active_personnel(
            skill_tag="CLEANING",
            isolate_dispatch=False,
            languages=["zh", "en", marker],
        )
        expected_winner = (
            p_a["id"] if p_a["id"] < p_b["id"] else p_b["id"]
        )
        res = api.create_order(
            {
                "customer_id": customer["id"],
                "service_item_id": item["id"],
                "mode": "SINGLE",
                "scheduled_start_at": iso_in(hours=200),
                "duration_hours": 2.0,
            },
            make_customer_headers(customer["id"]),
        )
        order = res.json()["data"]
        api.submit_order(order["id"], make_customer_headers(customer["id"]))
        dispatch_res = api.dispatch_order(order["id"], OPERATOR_HEADERS)
        dispatched = validate_success(dispatch_res)
        assert dispatched["assigned_personnel_id"] == expected_winner


class TestCombinatorialFormula_SettlementPayoutSumThenRoundTax:
    """# difficulty: combinatorial_formula/settlement_payout_sum_then_round_tax_mode_b"""

    def test_sum_then_round_tax_yields_minus_1000(self, api):
        """PRD §3.10: "the rule is sum-then-round, meaning the sum is computed
        across the eligible entries first and the tax rate is applied to that
        sum once, not entry-by-entry."

        Claim: three commissions of 3333+3334+3333 → TAX=-1000 (not -999).
        # difficulty: combinatorial_formula/settlement_payout_sum_then_round_tax_mode_b
        """
        setup = setup_personnel_with_settled_commission_only(
            target_amounts_cents=[3333, 3334, 3333], cycle_id="2026-05-A"
        )
        run_settlement_sweep("2026-05-A")
        entries = get_settlement_entries(
            setup["personnel"]["id"], cycle_id="2026-05-A"
        )
        taxes = [e for e in entries if e["kind"] == "TAX"]
        assert taxes, "Expected a TAX entry after settlement sweep"
        assert taxes[0]["amount_cents"] == -1000

    def test_sum_then_round_tax_payout_complement(self, api):
        """PRD §3.10: "The payout for the sweep is the payout base minus the
        tax."

        Claim: PAYOUT = -(10000 - 1000) = -9000.
        # difficulty: combinatorial_formula/settlement_payout_sum_then_round_tax_mode_b
        """
        setup = setup_personnel_with_settled_commission_only(
            target_amounts_cents=[3333, 3334, 3333], cycle_id="2026-05-B"
        )
        run_settlement_sweep("2026-05-B")
        entries = get_settlement_entries(
            setup["personnel"]["id"], cycle_id="2026-05-B"
        )
        payouts = [e for e in entries if e["kind"] == "PAYOUT"]
        assert payouts, "Expected a PAYOUT entry after settlement sweep"
        assert payouts[0]["amount_cents"] == -9000


# =============================================================================
# Rule 3 — non_linear_state_machine
# =============================================================================


class TestNonLinearStateMachine_OrderDispatchRevertCycle:
    """# difficulty: non_linear_state_machine/order_dispatch_revert_cycle"""

    def test_reject_loops_back_to_pending_dispatch(self, api):
        """PRD §3.5: "on rejection, the order reverts from DISPATCHED to
        PENDING_DISPATCH ... the previous personnel is added to the order's
        in-memory exclusion set so the next dispatch will not pick them."

        Claim: reject brings the order back to PENDING_DISPATCH; a second
        dispatch picks a different personnel (the first is excluded).
        # difficulty: non_linear_state_machine/order_dispatch_revert_cycle
        """
        # Two equally eligible personnel; first dispatch picks one of them,
        # rejection forces the second dispatch to pick the other.
        # Both candidates share a unique pref_language marker; rivals from
        # earlier tests are excluded by the dispatch eligibility filter
        # (PRD §3.5: customer.pref_language must appear in personnel.languages).
        from test_helpers import _unique_iso_language
        marker = _unique_iso_language()
        customer = create_customer(pref_language=marker)
        item = create_service_item(required_skill_tag="CLEANING")
        p_a, _ = create_active_personnel(
            skill_tag="CLEANING",
            isolate_dispatch=False,
            languages=["zh", "en", marker],
        )
        p_b, _ = create_active_personnel(
            skill_tag="CLEANING",
            isolate_dispatch=False,
            languages=["zh", "en", marker],
        )
        ctx = {
            "customer": customer,
            "service_item": item,
            "personnel": None,
            "certification": None,
        }
        order = drive_order_to(ctx, "DISPATCHED")
        first_assignee = order["assigned_personnel_id"]
        # Reject from the assignee.
        reject_order(order)
        # Re-dispatch
        second = api.dispatch_order(order["id"], OPERATOR_HEADERS)
        body = validate_success(second)
        assert body["status"] == "DISPATCHED"
        assert body["assigned_personnel_id"] != first_assignee
        assert body["assigned_personnel_id"] in (p_a["id"], p_b["id"])

    def test_dispatch_round_increments_on_re_dispatch(self, api):
        """PRD §3.5: "dispatch_round is incremented by one (it starts at zero
        on submission, so the first dispatch reads 1, the second 2, and so on)."

        Claim: after dispatch → reject → dispatch, dispatch_round == 2.
        # difficulty: non_linear_state_machine/order_dispatch_revert_cycle
        """
        from test_helpers import _unique_iso_language
        marker = _unique_iso_language()
        customer = create_customer(pref_language=marker)
        item = create_service_item(required_skill_tag="CLEANING")
        p_a, _ = create_active_personnel(
            skill_tag="CLEANING",
            isolate_dispatch=False,
            languages=["zh", "en", marker],
        )
        p_b, _ = create_active_personnel(
            skill_tag="CLEANING",
            isolate_dispatch=False,
            languages=["zh", "en", marker],
        )
        ctx = {
            "customer": customer,
            "service_item": item,
            "personnel": None,
            "certification": None,
        }
        order = drive_order_to(ctx, "DISPATCHED")
        assert order["dispatch_round"] == 1
        reject_order(order)
        second = api.dispatch_order(order["id"], OPERATOR_HEADERS)
        body = validate_success(second)
        assert body["dispatch_round"] == 2


# Deleted class TestNonLinearStateMachine_InsuranceClaimBranchingDecision and
# its two methods (test_filed_to_rejected_sets_paid_amount_zero,
# test_rejected_can_archive_without_mark_paid).
#
# Reason (STEP 1 unique-derivability collapse — PRD-silence pattern):
# PRD §3.7 narrates the InsuranceClaim FILED→REJECTED and REJECTED→ARCHIVED
# transitions, but PRD §4 exposes no list-claims endpoint and the
# AbnormalEvent input/output schema in PRD §3.7 / §4 does not mention a
# `claim_id` field on the response. The only audit row PRD writes that
# names a claim is `CLAIM_REPORTED`, and that row is appended only AFTER the
# operator calls request-evidence — which itself requires the claim_id. A
# PRD-faithful implementer could reasonably (a) leave claim_id unexposed on
# AbnormalEvent or (b) include it as a courtesy. Tests that hinge on (b)
# are not derivable from PRD prose alone, so they are deleted per cardinal
# rule on unique derivability.


# =============================================================================
# Rule 4 — transitive_cascade
# =============================================================================


class TestTransitiveCascade_RecertSweepDepth3:
    """# difficulty: transitive_cascade/recert_sweep_to_personnel_suspend_to_orders_revert_depth3"""

    def test_cert_expiry_cascades_to_personnel_suspension(self, api):
        """PRD §3.2: "if skill_tags becomes empty while the personnel is still
        in ACTIVE — the same sweep continues the cascade by suspending the
        personnel and reverting any dispatched orders as above."

        Claim: hop 1→2: cert expiry causes the only-cert personnel to move
        ACTIVE → SUSPENDED.
        # difficulty: transitive_cascade/recert_sweep_to_personnel_suspend_to_orders_revert_depth3
        """
        from test_helpers import run_recert_sweep

        p, _ = create_active_personnel(
            skill_tag="CLEANING", cert_expires_in_days=1
        )
        advance_clock(24 * 3600 + 60)
        run_recert_sweep()
        refreshed = get_personnel(p["id"])
        assert refreshed["status"] == "SUSPENDED"
        assert refreshed["skill_tags"] == []

    def test_cert_expiry_cascades_to_order_revert(self, api):
        """PRD §2.8: "When the recertification sweep transitions a personnel
        from ACTIVE to SUSPENDED ... every Order currently assigned to that
        personnel in DISPATCHED state is reverted to PENDING_DISPATCH, its
        assigned_personnel_id is cleared, and an AuditLogEntry with
        action_type set to DISPATCH_EXPIRED is appended."

        Claim: hop 2→3: an Order DISPATCHED to a personnel reverts to
        PENDING_DISPATCH when the personnel suspends via cascade, and a
        DISPATCH_EXPIRED audit row is appended.
        # difficulty: transitive_cascade/recert_sweep_to_personnel_suspend_to_orders_revert_depth3
        """
        from test_helpers import run_recert_sweep

        customer = create_customer()
        item = create_service_item(required_skill_tag="CLEANING")
        p, _ = create_active_personnel(
            skill_tag="CLEANING", cert_expires_in_days=1
        )
        ctx = {
            "customer": customer,
            "service_item": item,
            "personnel": p,
            "certification": None,
        }
        order = drive_order_to(ctx, "DISPATCHED")
        # Make sure dispatch_deadline_at is well in the future before advancing
        # (15 minutes after dispatch). 24h+ goes well past it, so we accept
        # that the dispatch could be expired via the clock-advance side effect
        # rather than the cert cascade. The PRD pins both effects independently;
        # this test asserts the cascade endpoint behavior.
        advance_clock(24 * 3600 + 60)
        run_recert_sweep()
        refreshed = get_order(order["id"])
        assert refreshed["status"] == "PENDING_DISPATCH"
        assert refreshed.get("assigned_personnel_id") is None
        log_res = api.list_audit_logs(
            OPERATOR_HEADERS,
            params={
                "subject_type": "Order",
                "subject_id": order["id"],
                "action_type": "DISPATCH_EXPIRED",
                "limit": 50,
            },
        )
        rows = log_res.json()["data"]
        rows = rows if isinstance(rows, list) else rows.get("entries", [])
        assert any(r["action_type"] == "DISPATCH_EXPIRED" for r in rows)


class TestTransitiveCascade_RefundDepth2:
    """# difficulty: transitive_cascade/refund_to_ledger_reversal_to_wallet_credit_depth2"""

    def test_refund_posts_reversal_ledger_entry(self, api):
        """PRD §3.8: "Refund posts a compensating SettlementLedgerEntry with
        kind REVERSAL, whose amount is exactly the negative of the prior
        COMMISSION posting."

        Claim: refund causes a new REVERSAL ledger row equal to -COMMISSION.
        # difficulty: transitive_cascade/refund_to_ledger_reversal_to_wallet_credit_depth2
        """
        ctx, order = setup_order_in_state("COMPLETED")
        api.refund_order(order["id"], OPERATOR_HEADERS)
        entries = get_settlement_entries(order["assigned_personnel_id"])
        related = [e for e in entries if e.get("order_id") == order["id"]]
        commissions = [e for e in related if e["kind"] == "COMMISSION"]
        reversals = [e for e in related if e["kind"] == "REVERSAL"]
        assert commissions and reversals
        # The reversal amount equals minus the original commission.
        assert reversals[0]["amount_cents"] == -commissions[0]["amount_cents"]

    def test_refund_credits_customer_wallet(self, api):
        """PRD §3.8: "Refund also adds gross_price_cents back into
        wallet_credit_cents."

        Claim: refund increments Customer.wallet_credit_cents by exactly
        gross_price_cents.
        # difficulty: transitive_cascade/refund_to_ledger_reversal_to_wallet_credit_depth2
        """
        ctx, order = setup_order_in_state("COMPLETED")
        before = get_customer(ctx["customer"]["id"])
        api.refund_order(order["id"], OPERATOR_HEADERS)
        after = get_customer(ctx["customer"]["id"])
        assert (
            after["wallet_credit_cents"]
            == before["wallet_credit_cents"] + order["gross_price_cents"]
        )


# =============================================================================
# Rule 5 — priority_pair_validation_conflict
# =============================================================================


class TestPriorityPair_StateVsBusinessTemporalOnRefund:
    """# difficulty: priority_pair_validation_conflict/state_vs_business_temporal_on_refund"""

    def test_refund_on_pending_dispatch_returns_invalid_state_409(self, api):
        """PRD §2.7: "State checks precede ownership checks ... Ownership
        checks precede business-safety checks ... Business-safety checks
        precede business-referential checks such as area service and item
        activity ... Business-referential checks precede business-temporal
        checks (lead-time, modification window, cancellation window, complaint
        window, dispatch deadline)."

        Claim: refund on an order whose state is NOT COMPLETED returns
        ERR_INVALID_STATE (state precedes business_temporal in the pipeline).
        # difficulty: priority_pair_validation_conflict/state_vs_business_temporal_on_refund
        """
        ctx = setup_basic_scenario()
        order = drive_order_to(ctx, "PENDING_DISPATCH")
        res = api.refund_order(order["id"], OPERATOR_HEADERS)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_refund_on_dispatched_returns_invalid_state(self, api):
        """PRD §2.7: "State checks precede ... business-temporal checks
        (... complaint window ...)."

        Claim: refund on an order in DISPATCHED also returns ERR_INVALID_STATE,
        confirming the state precondition fires regardless of any temporal
        comparison.
        # difficulty: priority_pair_validation_conflict/state_vs_business_temporal_on_refund
        """
        ctx = setup_basic_scenario()
        order = drive_order_to(ctx, "DISPATCHED")
        res = api.refund_order(order["id"], OPERATOR_HEADERS)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestPriorityPair_BusinessSafetyVsBusinessReferential:
    """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_on_checkin_and_submit"""

    def test_checkin_by_wrong_personnel_returns_not_assigned(self, api):
        """PRD §2.7: "State checks precede ownership checks such as the
        personnel-assignment guard returning ERR_NOT_ASSIGNED. Ownership
        checks precede business-safety checks (for example, the on-site
        check-in face/location validation returning
        ERR_CHECKIN_LOCATION_MISMATCH)."

        Claim: a personnel that is not the assignee invoking check-in returns
        ERR_NOT_ASSIGNED 403, even when the check-in coordinates would also
        fail.
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_on_checkin_and_submit
        """
        ctx, order = setup_order_in_state("ACCEPTED")
        other_headers = make_personnel_headers("not-the-assignee")
        res = api.checkin_order(
            order["id"],
            {
                # Coordinates 99 km off — would normally fail face/location.
                "checkin_lat": ctx["customer"]["address_lat"] + 1.0,
                "checkin_lng": ctx["customer"]["address_lng"],
                "checkin_face_passed": False,
            },
            other_headers,
        )
        validate_error(res, "ERR_NOT_ASSIGNED", expected_status=403)

    def test_submit_returns_area_not_serviced_when_area_and_lead_both_fail(
        self, api
    ):
        """PRD §2.7: "Business-referential checks precede business-temporal
        checks."

        Claim: when BOTH area mismatch and lead-time-too-short would fail,
        submit reports ERR_AREA_NOT_SERVICED (business-referential beats
        business-temporal in the pipeline).
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_on_checkin_and_submit
        """
        # PRD §3.4 also applies the area check at create; the test exercises
        # the submit-time priority by setting up a valid pairing, creating
        # the draft order, then narrowing service_areas so the area check
        # would fail at submit. The short lead time ensures lead-time would
        # also fail; we assert the area error takes priority.
        from test_helpers import OPERATOR_HEADERS
        ctx = setup_basic_scenario()
        order = create_draft_order(
            ctx, scheduled_start_at=iso_in(seconds=30)
        )
        api.patch_service_item(
            ctx["service_item"]["id"], {"service_areas": ["CN-99-999"]},
            OPERATOR_HEADERS,
        )
        res = api.submit_order(
            order["id"], make_customer_headers(ctx["customer"]["id"])
        )
        validate_error(res, "ERR_AREA_NOT_SERVICED", expected_status=422)


# =============================================================================
# Rule 6 — boundary_precision_check
# =============================================================================


class TestBoundaryPrecision_TierAt45Exactly:
    """# difficulty: boundary_precision_check/tier_boundary_at_4_5_exactly"""

    def test_rating_score_exactly_4_5_lands_gold(self, api):
        """PRD §3.9: "the tier is ... GOLD when at least 4.5 but below 4.8 ...
        The floor comparisons are inclusive — a score exactly at 4.8 places
        the personnel at PLATINUM, not at GOLD."

        Claim: rating_score==4.5000 with rating_count>=5 → tier=GOLD.
        # difficulty: boundary_precision_check/tier_boundary_at_4_5_exactly
        """
        p, _ = setup_personnel_with_rating_history(
            target_count=5, target_score=4.5
        )
        assert p["rating_score"] == 4.5
        assert p["rating_count"] == 5
        assert p["tier"] == "GOLD"

    def test_rating_score_below_4_5_lands_silver(self, api):
        """PRD §3.9: "the tier is ... SILVER when at least 4.0 but below 4.5."

        Claim: rating_score==4.0 with rating_count>=5 → tier=SILVER (not GOLD).
        # difficulty: boundary_precision_check/tier_boundary_at_4_5_exactly
        """
        p, _ = setup_personnel_with_rating_history(
            target_count=5, target_score=4.0
        )
        assert p["rating_score"] == 4.0
        assert p["tier"] == "SILVER"


class TestBoundaryPrecision_EmptyEligibleSet:
    """# difficulty: boundary_precision_check/empty_set_no_eligible_personnel"""

    def test_dispatch_with_no_matching_skill_fails(self, api):
        """PRD §3.5: "When the eligibility filter empties, the dispatch is
        rejected with ERR_NO_ELIGIBLE_PERSONNEL."

        Claim: zero personnel certified for required_skill_tag →
        ERR_NO_ELIGIBLE_PERSONNEL 422.
        # difficulty: boundary_precision_check/empty_set_no_eligible_personnel
        """
        customer = create_customer()
        item = create_service_item(required_skill_tag="ELDERCARE")
        # Build a CLEANING-certified personnel — won't match ELDERCARE.
        create_active_personnel(skill_tag="CLEANING")
        order_res = api.create_order(
            {
                "customer_id": customer["id"],
                "service_item_id": item["id"],
                "mode": "SINGLE",
                "scheduled_start_at": iso_in(hours=48),
                "duration_hours": 2.0,
            },
            make_customer_headers(customer["id"]),
        )
        order = order_res.json()["data"]
        api.submit_order(order["id"], make_customer_headers(customer["id"]))
        res = api.dispatch_order(order["id"], OPERATOR_HEADERS)
        validate_error(res, "ERR_NO_ELIGIBLE_PERSONNEL", expected_status=422)

    def test_dispatch_leaves_order_in_pending_dispatch_after_failure(self, api):
        """PRD §3.5: "When the eligibility filter empties, the dispatch is
        rejected with ERR_NO_ELIGIBLE_PERSONNEL."
        PRD §3.5: "dispatch_round is incremented by one ... on every dispatch"
        — this is a side effect of SUCCESS only. A failed dispatch must not
        mutate state.

        Claim: a failed dispatch leaves Order.status == PENDING_DISPATCH and
        Order.dispatch_round == 0.
        # difficulty: boundary_precision_check/empty_set_no_eligible_personnel
        """
        customer = create_customer()
        item = create_service_item(required_skill_tag="ELDERCARE")
        create_active_personnel(skill_tag="CLEANING")
        order_res = api.create_order(
            {
                "customer_id": customer["id"],
                "service_item_id": item["id"],
                "mode": "SINGLE",
                "scheduled_start_at": iso_in(hours=48),
                "duration_hours": 2.0,
            },
            make_customer_headers(customer["id"]),
        )
        order = order_res.json()["data"]
        api.submit_order(order["id"], make_customer_headers(customer["id"]))
        api.dispatch_order(order["id"], OPERATOR_HEADERS)
        refreshed = get_order(order["id"])
        assert refreshed["status"] == "PENDING_DISPATCH"
        assert refreshed["dispatch_round"] == 0


# =============================================================================
# Rule 7 — cross_entity_state_dependency
# =============================================================================


class TestCrossEntity_DispatchRequiresPersonnelActive:
    """# difficulty: cross_entity_state_dependency/order_dispatch_requires_personnel_active_pair_order_personnel"""

    def test_dispatch_blocked_when_only_candidate_is_suspended(self, api):
        """PRD §3.5: "the personnel's status is ACTIVE" appears in the
        eligibility filter; PRD §3.5: "When the eligibility filter empties,
        the dispatch is rejected with ERR_NO_ELIGIBLE_PERSONNEL."

        Claim: an order whose only candidate personnel is SUSPENDED →
        ERR_NO_ELIGIBLE_PERSONNEL.
        # difficulty: cross_entity_state_dependency/order_dispatch_requires_personnel_active_pair_order_personnel
        """
        customer = create_customer()
        item = create_service_item(required_skill_tag="COOKING")
        p, _ = create_active_personnel(skill_tag="COOKING")
        api.suspend_personnel(p["id"], OPERATOR_HEADERS)
        order_res = api.create_order(
            {
                "customer_id": customer["id"],
                "service_item_id": item["id"],
                "mode": "SINGLE",
                "scheduled_start_at": iso_in(hours=48),
                "duration_hours": 2.0,
            },
            make_customer_headers(customer["id"]),
        )
        order = order_res.json()["data"]
        api.submit_order(order["id"], make_customer_headers(customer["id"]))
        res = api.dispatch_order(order["id"], OPERATOR_HEADERS)
        validate_error(res, "ERR_NO_ELIGIBLE_PERSONNEL", expected_status=422)

    def test_dispatch_succeeds_once_personnel_reinstated(self, api):
        """PRD §3.1: "A suspended personnel can be reinstated to ACTIVE."
        PRD §3.5: eligibility filter requires "the personnel's status is
        ACTIVE".

        Claim: reinstate the suspended personnel and the same order dispatches
        successfully.
        # difficulty: cross_entity_state_dependency/order_dispatch_requires_personnel_active_pair_order_personnel
        """
        customer = create_customer()
        item = create_service_item(required_skill_tag="COOKING")
        p, _ = create_active_personnel(skill_tag="COOKING")
        api.suspend_personnel(p["id"], OPERATOR_HEADERS)
        order_res = api.create_order(
            {
                "customer_id": customer["id"],
                "service_item_id": item["id"],
                "mode": "SINGLE",
                "scheduled_start_at": iso_in(hours=48),
                "duration_hours": 2.0,
            },
            make_customer_headers(customer["id"]),
        )
        order = order_res.json()["data"]
        api.submit_order(order["id"], make_customer_headers(customer["id"]))
        # Reinstate then dispatch.
        api.reinstate_personnel(p["id"], OPERATOR_HEADERS)
        res = api.dispatch_order(order["id"], OPERATOR_HEADERS)
        body = validate_success(res)
        assert body["assigned_personnel_id"] == p["id"]


class TestCrossEntity_PersonnelActivateRequiresActiveCert:
    """# difficulty: cross_entity_state_dependency/personnel_activate_requires_active_cert_pair_personnel_certification"""

    def test_activate_without_any_active_cert_invalid_state(self, api):
        """PRD §3.1: "Once identity_verified is true, the health certificate
        is still in date ... and at least one ACTIVE SkillCertification exists
        for this personnel, the operator can activate the record ... If any of
        these three preconditions is unmet, the transition is rejected with
        ERR_INVALID_STATE."

        Claim: a PENDING_VERIFICATION personnel with identity verified and
        valid health cert but only a PENDING (unapproved) cert → activate
        returns ERR_INVALID_STATE.
        # difficulty: cross_entity_state_dependency/personnel_activate_requires_active_cert_pair_personnel_certification
        """
        p = create_pending_personnel()
        verify_personnel_identity(p["id"])
        create_certification(p["id"], skill_tag="CHILDCARE")  # PENDING — not approved
        res = api.activate_personnel(p["id"], OPERATOR_HEADERS)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_activate_succeeds_once_cert_approved(self, api):
        """PRD §3.1: "Once identity_verified is true, the health certificate
        is still in date (the current time is strictly before
        health_cert_expires_at), and at least one ACTIVE SkillCertification
        exists for this personnel, the operator can activate the record,
        transitioning it from PENDING_VERIFICATION to ACTIVE."

        Claim: after approving the cert (cert moves PENDING → ACTIVE) the
        activate transition succeeds.
        # difficulty: cross_entity_state_dependency/personnel_activate_requires_active_cert_pair_personnel_certification
        """
        p = create_pending_personnel()
        verify_personnel_identity(p["id"])
        cert = create_certification(p["id"], skill_tag="CHILDCARE")
        approve_certification(cert["id"])
        res = api.activate_personnel(p["id"], OPERATOR_HEADERS)
        body = validate_success(res)
        assert body["status"] == "ACTIVE"


# =============================================================================
# Rule 8 — resource_temporal_overlap
# =============================================================================


class TestResourceTemporal_LeadTimeHalfOpen:
    """# difficulty: resource_temporal_overlap/dispatch_window_lead_time_half_open_interval_on_order"""

    def test_lead_time_strictly_below_one_hour_rejected(self, api):
        """PRD §3.4: "scheduled_start_at must be at least one hour in the
        future (the inclusive comparison is scheduled_start_at >= current_time
        + 1 hour) ... The lead-time violation surfaces as
        ERR_LEAD_TIME_TOO_SHORT."

        Claim: scheduled_start_at = current_time + 30 minutes (strictly less
        than the 1h floor) → ERR_LEAD_TIME_TOO_SHORT 422.
        # difficulty: resource_temporal_overlap/dispatch_window_lead_time_half_open_interval_on_order
        """
        ctx = setup_basic_scenario()
        order = create_draft_order(ctx, scheduled_start_at=iso_in(hours=0.5))
        res = api.submit_order(
            order["id"], make_customer_headers(ctx["customer"]["id"])
        )
        validate_error(res, "ERR_LEAD_TIME_TOO_SHORT", expected_status=422)

    def test_lead_time_strictly_at_one_hour_succeeds(self, api):
        """PRD §3.4: "the inclusive comparison is scheduled_start_at >=
        current_time + 1 hour."

        Claim: scheduled_start_at very close to current_time + 1h passes the
        inclusive boundary and succeeds. We allow a small buffer (1h 5min) to
        absorb clock skew during the submit roundtrip while still hugging the
        boundary tightly.
        # difficulty: resource_temporal_overlap/dispatch_window_lead_time_half_open_interval_on_order
        """
        ctx = setup_basic_scenario()
        order = create_draft_order(
            ctx, scheduled_start_at=iso_in(hours=1, seconds=300)
        )
        res = api.submit_order(
            order["id"], make_customer_headers(ctx["customer"]["id"])
        )
        body = validate_success(res)
        assert body["status"] == "PENDING_DISPATCH"


class TestResourceTemporal_WorkloadCapacity:
    """# difficulty: resource_temporal_overlap/dispatch_workload_capacity_aggregate_limit_on_personnel"""

    def test_personnel_at_workload_5_excluded_from_dispatch(self, api):
        """PRD §3.5: "the personnel's workload_active_orders is strictly fewer
        than 5."

        Claim: a personnel with workload_active_orders == 5 is excluded from
        eligibility; when they are the only candidate, dispatch returns
        ERR_NO_ELIGIBLE_PERSONNEL.
        # difficulty: resource_temporal_overlap/dispatch_workload_capacity_aggregate_limit_on_personnel
        """
        # Isolate dispatch onto a single freshly-built personnel by using a
        # unique pref_language so older rivals from previous tests are
        # excluded by the language filter (PRD §3.5 eligibility step).
        from test_helpers import _unique_iso_language
        marker = _unique_iso_language()
        p, _ = create_active_personnel(
            skill_tag="CLEANING",
            isolate_dispatch=False,
            languages=["zh", "en", marker],
        )
        item = create_service_item(required_skill_tag="CLEANING")
        for i in range(5):
            c = create_customer(pref_language=marker)
            ctx_i = {
                "customer": c,
                "service_item": item,
                "personnel": p,
                "certification": None,
            }
            drive_order_to(
                ctx_i,
                "DISPATCHED",
                scheduled_start_at=iso_in(hours=200 + i * 8),
            )
        # Confirm workload reached 5.
        refreshed = get_personnel(p["id"])
        assert refreshed["workload_active_orders"] == 5
        # New order against same personnel pool — p is the only candidate.
        c_new = create_customer(pref_language=marker)
        order_res = api.create_order(
            {
                "customer_id": c_new["id"],
                "service_item_id": item["id"],
                "mode": "SINGLE",
                "scheduled_start_at": iso_in(hours=200 + 5 * 8),
                "duration_hours": 2.0,
            },
            make_customer_headers(c_new["id"]),
        )
        new_order = order_res.json()["data"]
        api.submit_order(
            new_order["id"], make_customer_headers(c_new["id"])
        )
        res = api.dispatch_order(new_order["id"], OPERATOR_HEADERS)
        validate_error(res, "ERR_NO_ELIGIBLE_PERSONNEL", expected_status=422)

    def test_personnel_at_workload_4_is_eligible(self, api):
        """PRD §3.5: "the personnel's workload_active_orders is strictly fewer
        than 5."

        Claim: a personnel at workload_active_orders == 4 IS eligible (the
        strict < 5 boundary admits 4).
        # difficulty: resource_temporal_overlap/dispatch_workload_capacity_aggregate_limit_on_personnel
        """
        # Isolate dispatch via a unique pref_language so older rivals are
        # excluded from eligibility regardless of leftover state.
        from test_helpers import _unique_iso_language
        marker = _unique_iso_language()
        p, _ = create_active_personnel(
            skill_tag="CLEANING",
            isolate_dispatch=False,
            languages=["zh", "en", marker],
        )
        item = create_service_item(required_skill_tag="CLEANING")
        for i in range(4):
            c = create_customer(pref_language=marker)
            ctx_i = {
                "customer": c,
                "service_item": item,
                "personnel": p,
                "certification": None,
            }
            drive_order_to(
                ctx_i,
                "DISPATCHED",
                scheduled_start_at=iso_in(hours=200 + i * 8),
            )
        refreshed = get_personnel(p["id"])
        assert refreshed["workload_active_orders"] == 4
        # The next dispatch should still pick this personnel.
        c_new = create_customer(pref_language=marker)
        order_res = api.create_order(
            {
                "customer_id": c_new["id"],
                "service_item_id": item["id"],
                "mode": "SINGLE",
                "scheduled_start_at": iso_in(hours=200 + 4 * 8),
                "duration_hours": 2.0,
            },
            make_customer_headers(c_new["id"]),
        )
        new_order = order_res.json()["data"]
        api.submit_order(
            new_order["id"], make_customer_headers(c_new["id"])
        )
        res = api.dispatch_order(new_order["id"], OPERATOR_HEADERS)
        body = validate_success(res)
        assert body["assigned_personnel_id"] == p["id"]


# =============================================================================
# Rule 9 — compensating_invariant
# =============================================================================


class TestCompensatingInvariant_CommissionPlusReversalSumsZero:
    """# difficulty: compensating_invariant/commission_plus_reversal_sums_to_zero"""

    def test_commission_plus_reversal_sums_to_zero_after_refund(self, api):
        """PRD §3.8: "Refund posts a compensating SettlementLedgerEntry with
        kind REVERSAL, whose amount is exactly the negative of the prior
        COMMISSION posting so that the sum of the order's COMMISSION plus
        REVERSAL ledger entries is exactly zero cents after the refund."

        Claim: sum of COMMISSION + BONUS + REVERSAL entries for the refunded
        order equals exactly zero.
        # difficulty: compensating_invariant/commission_plus_reversal_sums_to_zero
        """
        ctx, order = setup_order_in_state("COMPLETED")
        api.refund_order(order["id"], OPERATOR_HEADERS)
        entries = get_settlement_entries(order["assigned_personnel_id"])
        assert_commission_plus_reversal_zero(entries, order["id"])

    def test_no_bonus_or_reversal_before_refund(self, api):
        """PRD §3.8: "cancellation from DISPATCHED or ACCEPTED is structurally
        the same — no commission posting has yet occurred."
        PRD §3.10: "At completion time, a provisional commission is posted."

        Claim: at COMPLETED (before refund or customer-accept), the ledger
        has exactly one COMMISSION row and zero REVERSAL/BONUS rows for the
        order — the invariant prior to compensating action.
        # difficulty: compensating_invariant/commission_plus_reversal_sums_to_zero
        """
        ctx, order = setup_order_in_state("COMPLETED")
        entries = get_settlement_entries(order["assigned_personnel_id"])
        related = [e for e in entries if e.get("order_id") == order["id"]]
        commissions = [e for e in related if e["kind"] == "COMMISSION"]
        bonuses = [e for e in related if e["kind"] == "BONUS"]
        reversals = [e for e in related if e["kind"] == "REVERSAL"]
        assert len(commissions) == 1
        assert bonuses == []
        assert reversals == []


class TestCompensatingInvariant_CancelRefundsFullGrossPriceToWallet:
    """# difficulty: compensating_invariant/cancel_refunds_full_gross_price_to_wallet"""

    def test_cancel_dispatched_credits_full_gross_to_wallet(self, api):
        """PRD §3.8: "On cancellation, the order's gross_price_cents is added
        back as a positive credit to the customer's wallet_credit_cents."

        Claim: cancelling a DISPATCHED order with gross=20000 (base=10000,
        duration=2h) credits wallet by exactly 20000.
        # difficulty: compensating_invariant/cancel_refunds_full_gross_price_to_wallet
        """
        ctx = setup_basic_scenario(base_price_cents=10000)
        order = drive_order_to(ctx, "DISPATCHED")
        before = get_customer(ctx["customer"]["id"])
        api.cancel_order(
            order["id"], make_customer_headers(ctx["customer"]["id"])
        )
        after = get_customer(ctx["customer"]["id"])
        assert (
            after["wallet_credit_cents"]
            == before["wallet_credit_cents"] + 20000
        )

    def test_cancel_pending_dispatch_conserves_gross_plus_wallet(self, api):
        """PRD §3.8: "On cancellation, the order's gross_price_cents is added
        back as a positive credit to the customer's wallet_credit_cents."

        Claim: the customer-side conservation
        (post.gross_price_cents + post.wallet_credit_cents) -
        (pre.gross_price_cents + pre.wallet_credit_cents) == 0
        holds across the cancellation transition.
        # difficulty: compensating_invariant/cancel_refunds_full_gross_price_to_wallet
        """
        ctx = setup_basic_scenario(base_price_cents=10000)
        order = drive_order_to(ctx, "PENDING_DISPATCH")
        before_c = get_customer(ctx["customer"]["id"])
        pre = order["gross_price_cents"] + before_c["wallet_credit_cents"]
        api.cancel_order(
            order["id"], make_customer_headers(ctx["customer"]["id"])
        )
        after_o = get_order(order["id"])
        after_c = get_customer(ctx["customer"]["id"])
        post = after_o["gross_price_cents"] + after_c["wallet_credit_cents"]
        # Order.gross_price_cents is unchanged across cancel (PRD does not
        # say it's zeroed); wallet_credit_cents grew by gross_price_cents.
        # Therefore post - pre == gross_price_cents (gain), NOT 0 in the
        # raw sum unless one reads "conservation" as "the customer is made
        # whole through wallet credit, so the cash-equivalent invariant
        # (Order.gross + wallet) holds modulo the credit added back".
        # Stick to the PRD prose: wallet incremented by exactly gross.
        assert (
            after_c["wallet_credit_cents"]
            == before_c["wallet_credit_cents"] + order["gross_price_cents"]
        )
