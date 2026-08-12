"""Pooled-fund accounting: budget variants, contribution receipt gating,
refund protocol, withdrawal cascade, and the tier-minimum fiscal rule
(PRD §2.6, §2.9, §3.1-§3.3).
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_cycle,
    approve_and_release_payout,
    assert_contribution,
    create_contribution_payload,
    get_ledger,
    get_success_data,
    make_finance_headers,
    make_member_headers,
    setup_award,
    setup_nomination_phase,
    setup_pooling,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _pledge(api, ctx, member_index, amount_cents):
    """Raw pledge call as the owning member (may fail under test)."""
    member = ctx["members"][member_index]
    membership = ctx["memberships"][member_index]
    return api.create_contribution(
        create_contribution_payload(ctx["cycle"]["id"], membership["id"], amount_cents),
        make_member_headers(member["id"]),
    )


class TestBudgetVariants:
    def test_budget_provisional_counts_pledges_final_does_not(self, api):
        """PRD §2.6: "The provisional variant, `grant_budget_provisional_cents`,
        builds its base from received funds plus outstanding pledges, so it
        reads at least as high as the final variant whenever pledges remain
        outstanding; it is the planning figure and is recomputed on every
        financial mutation in any phase. The final variant,
        `grant_budget_final_cents`, builds its base from received funds only".
        PRD §2.6: "The fee on a base is the base multiplied by the cycle's
        `admin_fee_percent` and divided by one hundred, rounded half up to
        whole cents."

        With 100000 received and 100000 pledged at fee 5 and reserve 0:
        provisional base 200000 -> 200000 - 10000 = 190000; final base
        100000 -> 100000 - 5000 = 95000.

        Design: Difficulty/dual_variant_calc/budget_provisional_vs_final_diverge
        """
        ctx = setup_pooling(
            "Circle DV",
            num_members=2,
            funding=[(0, 100000, True), (1, 100000, False)],
        )
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["grant_budget_provisional_cents"] == 190000, (
            f"provisional budget must include the pledge, got {ledger['grant_budget_provisional_cents']}"
        )
        assert ledger["grant_budget_final_cents"] == 95000, (
            f"final budget must exclude the pledge, got {ledger['grant_budget_final_cents']}"
        )

    def test_budget_divergence_leaves_pool_and_pledge_state(self, api):
        """PRD §2.6: "`pooled_balance_cents` is what remains of received funds
        after subtracting the refunded total, the released total, and the
        transferred administration fee, then adding rollover funds carried in
        and subtracting rollover funds carried out."
        PRD §2.6: "`pledged_outstanding_cents` sums `amount_cents` over
        contributions in `PLEDGED`".

        Design: Difficulty/dual_variant_calc/budget_provisional_vs_final_diverge
        """
        ctx = setup_pooling(
            "Circle DV2",
            num_members=2,
            funding=[(0, 100000, True), (1, 100000, False)],
        )
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["pooled_balance_cents"] == 100000
        assert ledger["pledged_outstanding_cents"] == 100000
        pledged = get_success_data(api.get_contribution(ctx["contributions"][1]["id"], ADMIN))
        assert_contribution(pledged)
        assert pledged["status"] == "PLEDGED"


class TestTierMinimum:
    def test_contribution_below_tier_minimum_rejected_boundary(self, api):
        """PRD §3.3: "the amount must meet the tier minimum — `STANDARD`
        memberships pledge at least the circle's `standard_minimum_cents`,
        `LEADER` memberships at least `leader_minimum_cents`, and a shortfall
        fails with `ERR_BELOW_TIER_MINIMUM`."

        Design: Corner/validations/contribution_below_tier_minimum_rejected
        """
        ctx = setup_pooling("Circle VA3", num_members=1)
        resp = _pledge(api, ctx, 0, 99999)
        validate_error(resp, ApiErrorId.ERR_BELOW_TIER_MINIMUM)

        ok = validate_success(_pledge(api, ctx, 0, 100000), expected_status=201)
        assert ok["status"] == "PLEDGED", "exactly the minimum is accepted (inclusive boundary)"

    def test_phase_gate_beats_tier_minimum(self, api):
        """PRD §2.9: "Only then do state checks run, in this order: the target
        entity's from-state validity (`ERR_INVALID_STATE`), the cycle-phase gate
        (`ERR_CYCLE_PHASE`), and the membership-active gate
        (`ERR_MEMBERSHIP_NOT_ACTIVE`)."
        PRD §2.9: "Business rules come last, in this relative order:
        segregation of duties on payout approval; the temporal windows (voting
        window, refund window); uniqueness constraints; calendar overlap rules;
        capacity and counter limits; referenced-entity state (nonprofit
        standing, completed site visits, interim-report acceptance); ballot
        reference and points-budget rules; and finally the fiscal thresholds
        (tier minimums, the vetting score gate, and the refund underfunding
        guard)."

        A pledge in NOMINATION phase that is also below the tier minimum must
        surface the phase gate.

        Design: Difficulty/priority_pair_validation_conflict/cycle_phase_beats_tier_minimum
        """
        ctx = setup_nomination_phase(
            "Circle PP1", num_members=2, funding=((0, 100000, True),)
        )
        resp = _pledge(api, ctx, 1, 50000)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code}"
        err = validate_error(resp, ApiErrorId.ERR_CYCLE_PHASE)
        assert err["error_id"] != ApiErrorId.ERR_BELOW_TIER_MINIMUM

    def test_tier_minimum_fires_when_phase_valid(self, api):
        """PRD §3.3: "Three gates apply, after the ownership check against the
        membership: the cycle must be in `POOLING` (otherwise
        `ERR_CYCLE_PHASE`), the membership must be `ACTIVE` (otherwise
        `ERR_MEMBERSHIP_NOT_ACTIVE`), and the amount must meet the tier minimum
        — `STANDARD` memberships pledge at least the circle's
        `standard_minimum_cents`, `LEADER` memberships at least
        `leader_minimum_cents`, and a shortfall fails with
        `ERR_BELOW_TIER_MINIMUM`."

        With the phase gate satisfied (POOLING), the same 50000 pledge reaches
        the fiscal check — the companion half of the priority pair.

        Design: Difficulty/priority_pair_validation_conflict/cycle_phase_beats_tier_minimum
        """
        ctx = setup_pooling("Circle PP1B", num_members=2)
        resp = _pledge(api, ctx, 1, 50000)
        validate_error(resp, ApiErrorId.ERR_BELOW_TIER_MINIMUM)


class TestContributionReceipt:
    def test_receive_requires_pooling_phase(self, api):
        """PRD §3.3: "Recording receipt is a `CircleAdmin` action and likewise
        requires the cycle to still be in `POOLING` (`ERR_CYCLE_PHASE`) and the
        contribution to be in `PLEDGED` (`ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/contribution_receive_requires_pooling_phase
        """
        ctx = setup_nomination_phase(
            "Circle CE2",
            num_members=2,
            funding=((0, 100000, True), (1, 100000, False)),
        )
        pledged = ctx["contributions"][1]
        resp = api.receive_contribution(pledged["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CYCLE_PHASE)

    def test_receive_rejected_leaves_contribution_and_totals_unchanged(self, api):
        """PRD §3.3: "Recording receipt is a `CircleAdmin` action and likewise
        requires the cycle to still be in `POOLING` (`ERR_CYCLE_PHASE`) and the
        contribution to be in `PLEDGED` (`ERR_INVALID_STATE`)."
        PRD §2.6: "`received_total_cents` is the sum of `amount_cents` over the
        cycle's contributions in `RECEIVED`".

        Design: Difficulty/cross_entity_state_dependency/contribution_receive_requires_pooling_phase
        """
        ctx = setup_nomination_phase(
            "Circle CE2B",
            num_members=2,
            funding=((0, 100000, True), (1, 100000, False)),
        )
        pledged = ctx["contributions"][1]
        validate_error(api.receive_contribution(pledged["id"], ADMIN), ApiErrorId.ERR_CYCLE_PHASE)
        after = get_success_data(api.get_contribution(pledged["id"], ADMIN))
        assert after["status"] == "PLEDGED", "the rejected receipt must not move the contribution"
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["received_total_cents"] == 100000

    def test_ledger_reflects_receive_immediately(self, api):
        """PRD §2.6: "Each giving cycle maintains a family of derived ledger
        figures that the server recomputes immediately on every financial
        mutation; clients never write them."
        PRD §3.3: "Receipt moves the contribution `PLEDGED` → `RECEIVED`,
        stamps `received_at` from the logical clock, adds the amount to
        `received_total_cents`, subtracts it from `pledged_outstanding_cents`,
        and recomputes `pooled_balance_cents` together with both grant-budget
        variants (the final variant freezes only once `budget_locked` is set
        at the award lock)."

        Design: Corner/consistency_model/ledger_reflects_receive_immediately
        """
        ctx = setup_pooling("Circle CM1", num_members=1, funding=[(0, 100000, False)])
        contribution = ctx["contributions"][0]
        received = validate_success(api.receive_contribution(contribution["id"], ADMIN))
        assert received["status"] == "RECEIVED", "the receive response itself shows the new state"
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["received_total_cents"] == 100000
        assert ledger["pooled_balance_cents"] == 100000


class TestRefundProtocol:
    def test_receive_then_refund_conserves_pooled_balance(self, api):
        """PRD §3.3: "An approved refund subtracts the amount from
        `received_total_cents`, adds it to `refunded_total_cents`, and
        recomputes the pooled balance and the provisional budget; the final
        budget does not move once `budget_locked` is set."
        PRD §2.6: "`pooled_balance_cents` is what remains of received funds
        after subtracting the refunded total, the released total, and the
        transferred administration fee, then adding rollover funds carried in
        and subtracting rollover funds carried out."

        Design: Difficulty/compensating_invariant/receive_refund_pooled_conservation
        """
        ctx = setup_pooling("Circle CI1", num_members=1, funding=[(0, 100000, False)])
        contribution = ctx["contributions"][0]
        validate_success(api.receive_contribution(contribution["id"], ADMIN))
        mid = get_ledger(ctx["cycle"]["id"])
        assert mid["pooled_balance_cents"] == 100000, "receive puts the funds in the pool"

        member = ctx["members"][0]
        validate_success(
            api.request_refund(contribution["id"], make_member_headers(member["id"]))
        )
        validate_success(api.approve_refund(contribution["id"], ADMIN))
        end = get_ledger(ctx["cycle"]["id"])
        assert end["pooled_balance_cents"] == 0, (
            "forward receive + compensating refund conserve the pooled balance"
        )

    def test_refund_moves_totals_and_terminates_contribution(self, api):
        """PRD §3.3: "An approved refund subtracts the amount from
        `received_total_cents`, adds it to `refunded_total_cents`, and
        recomputes the pooled balance and the provisional budget; the final
        budget does not move once `budget_locked` is set."
        PRD §3.3: "`REFUNDED` and `VOIDED` are the terminal states, and
        `VOIDED` is reachable only through the withdrawal cascade of §3.2."

        Design: Difficulty/compensating_invariant/receive_refund_pooled_conservation
        """
        ctx = setup_pooling("Circle CI1B", num_members=1, funding=[(0, 100000, False)])
        contribution = ctx["contributions"][0]
        validate_success(api.receive_contribution(contribution["id"], ADMIN))
        member = ctx["members"][0]
        validate_success(
            api.request_refund(contribution["id"], make_member_headers(member["id"]))
        )
        refunded = validate_success(api.approve_refund(contribution["id"], ADMIN))
        assert refunded["status"] == "REFUNDED"
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["received_total_cents"] == 0
        assert ledger["refunded_total_cents"] == 100000
        assert ledger["pooled_balance_cents"] == 0

    def test_refund_request_on_refunded_contribution_rejected(self, api):
        """PRD §3.3: "The request is valid only from `RECEIVED`
        (`ERR_INVALID_STATE`) and only while the cycle's phase is one of
        `POOLING`, `NOMINATION`, `VETTING`, `VOTING`, or `AWARD`".
        PRD §3.3: "`REFUNDED` and `VOIDED` are the terminal states".

        Design: Corner/state_machines/refund_request_on_refunded_contribution_rejected
        """
        ctx = setup_pooling("Circle SM2", num_members=1, funding=[(0, 100000, False)])
        contribution = ctx["contributions"][0]
        member = ctx["members"][0]
        validate_success(api.receive_contribution(contribution["id"], ADMIN))
        validate_success(
            api.request_refund(contribution["id"], make_member_headers(member["id"]))
        )
        validate_success(api.approve_refund(contribution["id"], ADMIN))

        resp = api.request_refund(contribution["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_contribution(contribution["id"], ADMIN))
        assert after["status"] == "REFUNDED"

    def test_refund_request_after_window_rejected(self, api):
        """PRD §3.3: "The request is valid only from `RECEIVED`
        (`ERR_INVALID_STATE`) and only while the cycle's phase is one of
        `POOLING`, `NOMINATION`, `VETTING`, `VOTING`, or `AWARD`; once the cycle
        has moved past `AWARD`, or before pooling has begun, the request fails
        with `ERR_REFUND_WINDOW_CLOSED`."

        Design: Corner/validations/refund_request_after_window_rejected
        """
        ctx = setup_award("Circle VA2", num_members=1)
        approve_and_release_payout(ctx, ctx["payouts"][0])
        advance_cycle(ctx["cycle"]["id"])  # AWARD -> REPORTING
        contribution = ctx["contributions"][0]
        member = ctx["members"][0]
        resp = api.request_refund(contribution["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_REFUND_WINDOW_CLOSED)
        after = get_success_data(api.get_contribution(contribution["id"], ADMIN))
        assert after["status"] == "RECEIVED"

    def test_refund_underfunding_awards_rejected(self, api):
        """PRD §3.3: "Approval moves `REFUND_REQUESTED` → `REFUNDED`, but only
        if the pool remains funded afterward: the pooled balance minus the
        refunded `amount_cents` must still be at least the sum of `amount_cents`
        over the cycle's payouts in `SCHEDULED` or `APPROVED`, or the approval
        fails with `ERR_REFUND_UNDERFUNDS_AWARDS`."

        Pool 95000, obligations 95000 (T1 66500 + T2 28500), refund 100000:
        95000 - 100000 < 95000, so the approval is blocked.

        Design: Corner/errors/refund_underfunding_awards_rejected
        """
        ctx = setup_award("Circle ER12", num_members=1)
        contribution = ctx["contributions"][0]
        member = ctx["members"][0]
        validate_success(
            api.request_refund(contribution["id"], make_member_headers(member["id"]))
        )
        resp = api.approve_refund(contribution["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_REFUND_UNDERFUNDS_AWARDS)
        after = get_success_data(api.get_contribution(contribution["id"], ADMIN))
        assert after["status"] == "REFUND_REQUESTED", "the request stands; only approval is blocked"
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["pooled_balance_cents"] == 95000


class TestWithdrawalCascade:
    def test_withdraw_voids_pledged_contribution(self, api):
        """PRD §3.2: "A member may withdraw their own membership from either
        `ACTIVE` or `RENEWAL_DUE`; the membership ends in `WITHDRAWN`, and the
        withdrawal cascades: every contribution of that membership still in
        `PLEDGED` is voided to `VOIDED`, each voided contribution's
        `amount_cents` is subtracted from the cycle's
        `pledged_outstanding_cents`, the provisional grant budget is
        recomputed, and the circle's `active_member_count` is recomputed."

        Design: Difficulty/transitive_cascade/withdraw_voids_pledge_recomputes_provisional_budget
        """
        ctx = setup_pooling(
            "Circle TC2",
            num_members=2,
            funding=[(0, 100000, True), (1, 100000, False)],
        )
        member2 = ctx["members"][1]
        membership2 = ctx["memberships"][1]
        withdrawn = validate_success(
            api.withdraw_membership(membership2["id"], make_member_headers(member2["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN", "hop 1: membership withdrawn"
        contribution = get_success_data(
            api.get_contribution(ctx["contributions"][1]["id"], ADMIN)
        )
        assert contribution["status"] == "VOIDED", (
            "hop 2: the pledge is voided by the withdrawal cascade"
        )

    def test_withdraw_recomputes_provisional_budget_only(self, api):
        """PRD §3.2: "the withdrawal cascades: every contribution of that
        membership still in `PLEDGED` is voided to `VOIDED`, each voided
        contribution's `amount_cents` is subtracted from the cycle's
        `pledged_outstanding_cents`, the provisional grant budget is
        recomputed, and the circle's `active_member_count` is recomputed."
        PRD §2.6: "The final variant, `grant_budget_final_cents`, builds its
        base from received funds only".

        Before: provisional 190000 (received 100000 + pledged 100000, fee 5%).
        After the void: pledged 0, provisional 95000; final was already 95000.

        Design: Difficulty/transitive_cascade/withdraw_voids_pledge_recomputes_provisional_budget
        """
        ctx = setup_pooling(
            "Circle TC2B",
            num_members=2,
            funding=[(0, 100000, True), (1, 100000, False)],
        )
        before = get_ledger(ctx["cycle"]["id"])
        assert before["grant_budget_provisional_cents"] == 190000

        member2 = ctx["members"][1]
        membership2 = ctx["memberships"][1]
        validate_success(
            api.withdraw_membership(membership2["id"], make_member_headers(member2["id"]))
        )
        after = get_ledger(ctx["cycle"]["id"])
        assert after["pledged_outstanding_cents"] == 0
        assert after["grant_budget_provisional_cents"] == 95000
        assert after["grant_budget_final_cents"] == 95000


class TestReceiptRoleGate:
    def test_finance_officer_cannot_receive_contribution(self, api):
        """PRD §3.3: "Recording receipt is a `CircleAdmin` action and likewise
        requires the cycle to still be in `POOLING` (`ERR_CYCLE_PHASE`) and the
        contribution to be in `PLEDGED` (`ERR_INVALID_STATE`)."
        PRD §2.1: "Each write endpoint restricts which roles may invoke it
        (Section 4); a caller whose role is not listed for that endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/finance_officer_cannot_receive_contribution_forbidden
        """
        ctx = setup_pooling("Circle RB2", num_members=1, funding=[(0, 100000, False)])
        contribution = ctx["contributions"][0]
        resp = api.receive_contribution(contribution["id"], make_finance_headers("fin-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_contribution(contribution["id"], ADMIN))
        assert after["status"] == "PLEDGED"
