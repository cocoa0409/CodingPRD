"""Settlement lifecycle: authority-tier boundaries, exposure and reserve
gates, optimistic concurrency on offer creation, the counter/expiry loop, and
the acceptance cascade through reserve exhaustion and carrier analytics."""
from test_helpers import (
    ApiErrorId,
    assert_settlement,
    create_salvage_payload,
    create_settlement_payload,
    get_carrier,
    get_claim,
    get_success_data,
    set_clock,
    setup_claim_offered,
    setup_claim_paid,
    setup_claim_under_review,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
ADJUSTER2 = TEST_USERS["adjuster2_headers"]
MANAGER = TEST_USERS["manager_headers"]
SALVAGE = TEST_USERS["salvage_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestAuthorityTierBoundary:
    def test_offer_at_exact_max_auto_settle_is_tier_1(self, api):
        """PRD §3.6: "Creating the offer computes its `authority_tier_required`: an amount no more than the carrier's `max_auto_settle_cents` requires `TIER_1` (adjuster-level) authority; otherwise an amount no more than 10,000,000 cents requires `TIER_2` (manager) authority; anything larger requires `TIER_3` (FinanceController) authority. Boundaries are inclusive at every rung — an offer of exactly `max_auto_settle_cents` stays `TIER_1`."

        Design: Difficulty/boundary_precision_check/settlement_authority_tier_at_exact_cap
        """
        ctx = setup_claim_offered(
            amount_cents=50_000,
            carrier_over={"max_auto_settle_cents": 50_000},
            shipment_over={"declared_value_cents": 50_000},
            claim_over={"claimed_amount_cents": 50_000},
        )
        settlement = ctx["settlement"]
        assert_settlement(settlement)
        # amount 50_000 == carrier.max_auto_settle_cents 50_000 -> stays TIER_1.
        assert settlement["authority_tier_required"] == "TIER_1"

    def test_offer_one_cent_above_max_auto_settle_is_tier_2(self, api):
        """PRD §3.6: "Creating the offer computes its `authority_tier_required`: an amount no more than the carrier's `max_auto_settle_cents` requires `TIER_1` (adjuster-level) authority; otherwise an amount no more than 10,000,000 cents requires `TIER_2` (manager) authority; anything larger requires `TIER_3` (FinanceController) authority. Boundaries are inclusive at every rung — an offer of exactly `max_auto_settle_cents` stays `TIER_1`."

        Design: Difficulty/boundary_precision_check/settlement_authority_tier_at_exact_cap
        """
        ctx = setup_claim_offered(
            amount_cents=50_001,
            carrier_over={"max_auto_settle_cents": 50_000},
            shipment_over={"declared_value_cents": 60_000},
            claim_over={"claimed_amount_cents": 60_000},
        )
        assert ctx["settlement"]["authority_tier_required"] == "TIER_2"


class TestAcceptanceGates:
    def test_accept_above_current_net_exposure_rejected(self, api):
        """PRD §3.6: "A `ClaimsManager` or `FinanceController` accepts an offer only when the claim is `OFFERED` (otherwise `ERR_CLAIM_INVALID_STATE`), the settlement is `OFFERED` (otherwise `ERR_SETTLEMENT_INVALID_STATE`), the amount does not exceed the claim's current `net_exposure_cents` (otherwise `ERR_SETTLEMENT_EXCEEDS_NET_EXPOSURE`), the actor's authority is at least the offer's `authority_tier_required` — tiers are cumulative, so `TIER_3` satisfies `TIER_2` and `TIER_1` requirements — with a shortfall producing `ERR_AUTHORITY_TIER_INSUFFICIENT`, the actor is neither the user who extended the offer nor the adjuster who performed the assessment (a same-user overlap is `ERR_SEGREGATION_OF_DUTIES_VIOLATION`), and the claim's `reserve_amount_cents` covers the full amount (otherwise `ERR_RESERVE_INSUFFICIENT`)."

        Design: Corner/errors/error_settlement_exceeds_net_exposure
        """
        # Offer of 40_000 is created while net exposure is 40_000; a salvage
        # credit of 10_000 then reduces net exposure to 30_000, so the 40_000
        # offer exceeds the claim's current net exposure at accept time. The
        # reserve (40_000) still covers the amount, and the acceptor is a
        # fresh manager identity — only the exposure check can fail.
        ctx = setup_claim_offered(amount_cents=40_000, reserve_amount_cents=40_000)
        claim_id = ctx["claim"]["id"]
        get_success_data(
            api.schedule_salvage(
                claim_id,
                create_salvage_payload(
                    gross_proceeds_cents=10_000,
                    handling_cost_cents=0,
                    scheduled_at="2026-06-11T00:00:00Z",
                ),
                SALVAGE,
            )
        )
        # The claim is OFFERED (an executable state per §3.5), so the §2.7
        # clock sweep executes the due disposition exactly as if a coordinator
        # had executed it by hand.
        set_clock("2026-06-12T00:00:00Z")
        assert get_claim(claim_id)["net_exposure_cents"] == 30_000
        resp = api.accept_settlement(claim_id, ctx["settlement"]["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_NET_EXPOSURE)

    def test_offer_with_stale_claim_version_rejected(self, api):
        """PRD §2.6: "If that value does not match the claim's current `version` — because another writer has since advanced it, for example by posting an assessment, executing a salvage credit, or posting a reserve, all of which legitimately alter the claim's exposure figures and bump its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The three guarded operations are: extending a settlement offer on a claim under review, declining a claim under review, and opening an appeal on a declined claim."

        Design: Corner/errors/error_stale_version_on_occ_endpoint
        """
        # Claim stays UNDER_REVIEW; a reserve post advances the claim version
        # after the client read it, so the offer creation carries a stale
        # expected_claim_version.
        ctx = setup_claim_under_review(
            shipment_over={"declared_value_cents": 50_000},
            claim_over={"claimed_amount_cents": 30_000},
        )
        claim_id = ctx["claim"]["id"]
        stale_version = ctx["claim"]["version"]
        get_success_data(
            api.post_reserve(claim_id, {"amount_cents": 5_000}, FINANCE)
        )
        resp = api.create_settlement(
            claim_id,
            create_settlement_payload(20_000, stale_version),
            ADJUSTER2,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestCounterAndExpiryLoop:
    def test_counter_returns_claim_to_under_review_for_next_round(self, api):
        """PRD §3.6: "A `ClaimsAdjuster` may counter it: the settlement becomes `COUNTERED`, the claim returns from `OFFERED` to `UNDER_REVIEW` where a fresh offer — the next `round_number` — may be extended, and the claim's `version` increments."
        PRD §3.6: "Each new offer bears a `round_number`, 1-indexed and unique per claim, incremented with every offer cycle, and records in `offered_by_role` which side proposed it — `ADJUSTER`, `MANAGER`, or `CARRIER`."

        Design: Difficulty/non_linear_state_machine/settlement_counter_loop_and_expiry_branch
        """
        ctx = setup_claim_offered(amount_cents=40_000)
        claim_id = ctx["claim"]["id"]
        countered = validate_success(
            api.counter_settlement(claim_id, ctx["settlement"]["id"], ADJUSTER2), 200
        )
        assert countered["state"] == "COUNTERED"
        assert get_claim(claim_id)["filing_status"] == "UNDER_REVIEW"
        version = get_claim(claim_id)["version"]
        second = validate_success(
            api.create_settlement(
                claim_id, create_settlement_payload(38_000, version), ADJUSTER2
            ),
            201,
        )
        assert second["state"] == "OFFERED"
        assert second["round_number"] == 2
        assert get_claim(claim_id)["filing_status"] == "OFFERED"

    def test_offer_expires_after_fourteen_days_returning_claim(self, api):
        """PRD §2.7: "Third, offer expiry: a settlement still `OFFERED` more than 14 days after its creation transitions to `EXPIRED` and returns its claim to `UNDER_REVIEW`."
        PRD §3.6: "Finally, per §2.7, an offer left standing more than 14 days past its creation expires on its own: the settlement becomes `EXPIRED` and the claim falls back to `UNDER_REVIEW` without any operator action."

        Design: Difficulty/non_linear_state_machine/settlement_counter_loop_and_expiry_branch
        """
        ctx = setup_claim_offered(amount_cents=40_000)
        claim_id = ctx["claim"]["id"]
        # Offer created at the 2026-06-10 logical instant; advance 21 days.
        set_clock("2026-07-01T00:00:00Z")
        settlement = validate_success(
            api.get_settlement(claim_id, ctx["settlement"]["id"], CLERK), 200
        )
        assert settlement["state"] == "EXPIRED"
        assert get_claim(claim_id)["filing_status"] == "UNDER_REVIEW"


class TestAcceptanceCascade:
    def test_full_acceptance_pays_claim_and_exhausts_reserve(self, api):
        """PRD §3.6: "On acceptance the settlement becomes `ACCEPTED` with `approved_by_user_id` recording who accepted; the claim's `settlement_amount_cents` is fixed to the accepted amount; if the amount equals the net exposure the claim becomes `PAID` with `payment_status` `PAID_IN_FULL`, and if it falls short the claim becomes `CLOSED_WITH_PAYMENT` with `payment_status` `PARTIAL`; the active reserve is exhausted — moved to `EXHAUSTED` with `released_at` stamped and the claim's reserve figure zeroed; the carrier's `claims_paid_count` increases by one and `claim_ratio_bp` is recomputed; `OFFER_ACCEPTED` and `PAID_OUT` events are appended; and the claim's `version` increments."

        Design: Difficulty/transitive_cascade/settlement_accept_cascade_depth3
        """
        # FULL_VALUE carrier, declared 50_000, claimed 40_000 -> net exposure
        # 40_000; offer equals net exposure exactly.
        ctx = setup_claim_paid(amount_cents=40_000, reserve_amount_cents=40_000)
        settlement = ctx["settlement"]
        assert_settlement(settlement)
        assert settlement["state"] == "ACCEPTED"
        assert settlement["approved_by_user_id"] is not None
        claim = ctx["claim"]
        assert claim["filing_status"] == "PAID"
        assert claim["payment_status"] == "PAID_IN_FULL"
        assert claim["settlement_amount_cents"] == 40_000
        assert claim["reserve_amount_cents"] == 0
        reserve = validate_success(
            api.get_reserve(claim["id"], ctx["reserve"]["id"], CLERK), 200
        )
        assert reserve["state"] == "EXHAUSTED"
        assert reserve["released_at"] is not None

    def test_acceptance_updates_carrier_paid_count_and_events(self, api):
        """PRD §3.6: "On acceptance the settlement becomes `ACCEPTED` with `approved_by_user_id` recording who accepted; the claim's `settlement_amount_cents` is fixed to the accepted amount; if the amount equals the net exposure the claim becomes `PAID` with `payment_status` `PAID_IN_FULL`, and if it falls short the claim becomes `CLOSED_WITH_PAYMENT` with `payment_status` `PARTIAL`; the active reserve is exhausted — moved to `EXHAUSTED` with `released_at` stamped and the claim's reserve figure zeroed; the carrier's `claims_paid_count` increases by one and `claim_ratio_bp` is recomputed; `OFFER_ACCEPTED` and `PAID_OUT` events are appended; and the claim's `version` increments."
        PRD §3.9: "Per carrier, `claims_filed_count` counts claims that ever entered `SUBMITTED` — established from the event stream, counting only the first `FILED` event per claim so that a resubmission after withdrawal never double-counts — while `claims_paid_count` counts claims currently in `PAID` or `CLOSED_WITH_PAYMENT`; `claim_ratio_bp` is the paid count multiplied by 10,000 and divided by the filed count, with a denominator of zero treated as one so that a carrier with no filings reports a ratio of zero, rounded half-up to whole basis points."

        Design: Difficulty/transitive_cascade/settlement_accept_cascade_depth3
        """
        ctx = setup_claim_paid(amount_cents=40_000, reserve_amount_cents=40_000)
        carrier = get_carrier(ctx["carrier"]["id"])
        assert carrier["claims_paid_count"] == 1
        # 1 paid of 1 ever-filed -> round(1 * 10000 / 1) = 10000 bp.
        assert carrier["claim_ratio_bp"] == 10_000
        events, _meta = validate_paginated(
            api.list_claim_events(ctx["claim"]["id"], CLERK)
        )
        kinds = {e["event_kind"] for e in events}
        assert "OFFER_ACCEPTED" in kinds
        assert "PAID_OUT" in kinds


class TestSalvageSettlementConservation:
    def test_salvage_credit_offsets_settlement_without_double_count(self, api):
        """PRD §3.5: "A claim's `net_exposure_cents` is the thread that ties this section together: it is always the claim's `computed_liability_cents` minus its accumulated `salvage_credit_cents`, floored at zero, and it is recomputed on every assessment and on every salvage posting."
        PRD §3.6: "On acceptance the settlement becomes `ACCEPTED` with `approved_by_user_id` recording who accepted; the claim's `settlement_amount_cents` is fixed to the accepted amount; if the amount equals the net exposure the claim becomes `PAID` with `payment_status` `PAID_IN_FULL`, and if it falls short the claim becomes `CLOSED_WITH_PAYMENT` with `payment_status` `PARTIAL`; the active reserve is exhausted — moved to `EXHAUSTED` with `released_at` stamped and the claim's reserve figure zeroed; the carrier's `claims_paid_count` increases by one and `claim_ratio_bp` is recomputed; `OFFER_ACCEPTED` and `PAID_OUT` events are appended; and the claim's `version` increments."

        Design: Difficulty/compensating_invariant/claim_net_exposure_conserved_under_salvage_and_settlement
        """
        ctx = setup_claim_under_review()  # computed liability 40_000
        claim_id = ctx["claim"]["id"]
        get_success_data(
            api.schedule_salvage(
                claim_id,
                create_salvage_payload(
                    gross_proceeds_cents=12_000,
                    handling_cost_cents=2_000,
                    scheduled_at="2026-06-11T00:00:00Z",
                ),
                SALVAGE,
            )
        )
        # The claim is UNDER_REVIEW (an executable state per §3.5), so the
        # §2.7 clock sweep executes the due disposition exactly as if a
        # coordinator had executed it by hand.
        set_clock("2026-06-12T00:00:00Z")
        get_success_data(api.post_reserve(claim_id, {"amount_cents": 30_000}, FINANCE))
        version = get_claim(claim_id)["version"]
        settlement = validate_success(
            api.create_settlement(
                claim_id, create_settlement_payload(30_000, version), ADJUSTER2
            ),
            201,
        )
        validate_success(api.accept_settlement(claim_id, settlement["id"], MANAGER), 200)
        claim = get_claim(claim_id)
        assert claim["computed_liability_cents"] == 40_000
        assert claim["salvage_credit_cents"] == 10_000
        assert claim["settlement_amount_cents"] == 30_000
        # Conservation: the settled amount plus the salvage credit reconstructs
        # the computed liability exactly — no double-counting of the credit.
        assert (
            claim["settlement_amount_cents"] + claim["salvage_credit_cents"]
            == claim["computed_liability_cents"]
        )
        assert claim["filing_status"] == "PAID"
        assert claim["reserve_amount_cents"] == 0

    def test_partial_settlement_lands_closed_with_payment(self, api):
        """PRD §3.6: "On acceptance the settlement becomes `ACCEPTED` with `approved_by_user_id` recording who accepted; the claim's `settlement_amount_cents` is fixed to the accepted amount; if the amount equals the net exposure the claim becomes `PAID` with `payment_status` `PAID_IN_FULL`, and if it falls short the claim becomes `CLOSED_WITH_PAYMENT` with `payment_status` `PARTIAL`; the active reserve is exhausted — moved to `EXHAUSTED` with `released_at` stamped and the claim's reserve figure zeroed; the carrier's `claims_paid_count` increases by one and `claim_ratio_bp` is recomputed; `OFFER_ACCEPTED` and `PAID_OUT` events are appended; and the claim's `version` increments."

        Design: Difficulty/compensating_invariant/claim_net_exposure_conserved_under_salvage_and_settlement
        """
        ctx = setup_claim_under_review()  # net exposure 40_000
        claim_id = ctx["claim"]["id"]
        get_success_data(
            api.schedule_salvage(
                claim_id,
                create_salvage_payload(
                    gross_proceeds_cents=12_000,
                    handling_cost_cents=2_000,
                    scheduled_at="2026-06-11T00:00:00Z",
                ),
                SALVAGE,
            )
        )
        # The claim is UNDER_REVIEW (an executable state per §3.5), so the
        # §2.7 clock sweep executes the due disposition exactly as if a
        # coordinator had executed it by hand.
        set_clock("2026-06-12T00:00:00Z")
        # Net exposure is now 30_000; settle below it at 20_000.
        get_success_data(api.post_reserve(claim_id, {"amount_cents": 30_000}, FINANCE))
        version = get_claim(claim_id)["version"]
        settlement = validate_success(
            api.create_settlement(
                claim_id, create_settlement_payload(20_000, version), ADJUSTER2
            ),
            201,
        )
        validate_success(api.accept_settlement(claim_id, settlement["id"], MANAGER), 200)
        claim = get_claim(claim_id)
        assert claim["filing_status"] == "CLOSED_WITH_PAYMENT"
        assert claim["payment_status"] == "PARTIAL"
        assert claim["settlement_amount_cents"] == 20_000


class TestTerminalStateLockdown:
    def test_withdraw_paid_claim_rejected(self, api):
        """PRD §3.3: "Withdrawal is the clerk's escape hatch, available from `DRAFT`, `SUBMITTED`, or `ACKNOWLEDGED` (any other state is `ERR_CLAIM_INVALID_STATE`) and landing in the terminal `WITHDRAWN`."

        Design: Corner/state_machines/claim_terminal_state_lockdown_paid
        """
        ctx = setup_claim_paid(amount_cents=40_000, reserve_amount_cents=40_000)
        assert ctx["claim"]["filing_status"] == "PAID"
        resp = api.withdraw_claim(ctx["claim"]["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)
