"""Insurer postings, tiered commission, satisfaction cascades, and reversal (PRD §2.6, §2.9, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_recovery_posting,
    assert_settlement_split_identity,
    create_pending_posting,
    factories,
    find_notice,
    get_case,
    get_lien,
    get_posting,
    get_settlement,
    setup_accepted_settlement,
    setup_pending_posting,
    setup_posted_recovery,
    validate_error,
    validate_paginated,
    validate_success,
)

SPEC = TEST_USERS["specialist_headers"]
ACCT = TEST_USERS["accountant_headers"]
ERO = TEST_USERS["estate_officer_headers"]


class TestPostingCascade:
    def test_post_computes_commission_and_satisfies_lien(self, api):
        """PRD §3.5: "The lien's `outstanding_cents` is reduced by the `gross_recovery_cents`. When that reduction drives the lien's outstanding balance to exactly zero, the lien — whether `FILED` or `AMENDED` — becomes `SATISFIED`"
        PRD §3.5: "The three tier products are summed and the result is rounded half-up once — at post time, per posting, per the ordering rule of §2.6 — yielding `commission_cents`; `net_to_state_cents` is then the `gross_recovery_cents` less `commission_cents`."

        Design: Difficulty/transitive_cascade/posting_post_cascade_depth3plus
        """
        ctx = setup_posted_recovery(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        posting = ctx["posting"]
        assert_recovery_posting(posting)
        assert posting["status"] == "POSTED"
        # 10% of 100000 + 7.5% of 100000 = 17500; net = 200000 - 17500.
        assert posting["commission_cents"] == 17500
        assert posting["net_to_state_cents"] == 182500
        lien = ctx["lien"]
        assert lien["outstanding_cents"] == 0
        assert lien["status"] == "SATISFIED"

    def test_post_resolves_case_disburses_settlement_and_queues_notice(self, api):
        """PRD §3.5: "a case standing at `SETTLEMENT_PENDING` is in turn resolved, moving to `RESOLVED` with its `total_recovered_cents` recomputed as the sum of `gross_recovery_cents` over the case's `POSTED` postings, and a `CASE_RESOLUTION_NOTICE` is queued to the member per §2.11. The first posting to reach `POSTED` on a settlement also moves that settlement from `ACCEPTED` to `DISBURSED`."
        PRD §2.11: "Each notice is created in `QUEUED` status, and its `due_date` is the creation calendar date plus thirty days — the member-communication deadline."

        Design: Difficulty/transitive_cascade/posting_post_cascade_depth3plus
        """
        ctx = setup_posted_recovery(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        case = ctx["case"]
        assert case["status"] == "RESOLVED"
        assert case["total_recovered_cents"] == 200000
        assert ctx["settlement"]["status"] == "DISBURSED"
        notice = find_notice("CASE_RESOLUTION_NOTICE", case_id=case["id"])
        assert notice["status"] == "QUEUED"
        # Created at the default clock 2026-08-01; deadline is +30 days.
        assert notice["due_date"] == "2026-08-31"
        assert notice["member_id"] == ctx["member"]["id"]
        assert notice["estate_case_id"] is None


class TestPerPostingRoundingThenSum:
    def test_each_posting_commission_rounded_half_up(self, api):
        """PRD §2.6: "Contractor commission carries one further ordering rule: each posting's commission is rounded half-up to integer cents at post time, and every period or per-case total is the sum of those per-posting rounded commissions — never a rounding applied to the sum of unrounded values. The two orders disagree on fractional-cent inputs, so the pinned order is part of the contract."

        Design: Difficulty/combinatorial_formula/commission_per_posting_rounding_then_sum
        """
        # Postings 100020 and 100060: tier-2 components are 20*0.075=1.5 and
        # 60*0.075=4.5; half-up per posting yields 10002 and 10005.
        ctx = setup_accepted_settlement(claims=[("2026-01-10", 200080)])
        p1 = create_pending_posting(ctx["settlement"]["id"], 100020)
        p2 = create_pending_posting(ctx["settlement"]["id"], 100060)
        posted1 = validate_success(api.post_posting(p1["id"], ACCT), 200)
        posted2 = validate_success(api.post_posting(p2["id"], ACCT), 200)
        assert posted1["commission_cents"] == 10002, (
            f"100000*0.10 + 20*0.075 = 10001.5 rounds half-up to 10002, got {posted1['commission_cents']}"
        )
        assert posted2["commission_cents"] == 10005, (
            f"100000*0.10 + 60*0.075 = 10004.5 rounds half-up to 10005, got {posted2['commission_cents']}"
        )

    def test_case_summary_sums_per_posting_rounded_commissions(self, api):
        """PRD §3.5: "For reconciliation, an accounting summary read on a case reports `total_recovered_cents` (the sum of `gross_recovery_cents` over the case's `POSTED` postings), `total_commission_cents` (the sum of `commission_cents` over those same postings), `total_net_to_state_cents` (the first total less the second), and `posting_count` (the number of `POSTED` postings contributing)."
        PRD §2.6: "every period or per-case total is the sum of those per-posting rounded commissions — never a rounding applied to the sum of unrounded values."

        Design: Difficulty/combinatorial_formula/commission_per_posting_rounding_then_sum
        """
        ctx = setup_accepted_settlement(claims=[("2026-01-10", 200080)])
        p1 = create_pending_posting(ctx["settlement"]["id"], 100020)
        p2 = create_pending_posting(ctx["settlement"]["id"], 100060)
        validate_success(api.post_posting(p1["id"], ACCT), 200)
        validate_success(api.post_posting(p2["id"], ACCT), 200)
        summary = validate_success(
            api.get_accounting_summary(ctx["case"]["id"], ACCT), 200
        )
        assert summary["total_recovered_cents"] == 200080
        # Sum of rounded per-posting commissions: 10002 + 10005 = 20007,
        # one cent more than the 20006 an aggregate-round order would give.
        assert summary["total_commission_cents"] == 20007
        assert summary["total_net_to_state_cents"] == 180073
        assert summary["posting_count"] == 2


class TestCommissionTiers:
    def test_commission_tier_boundary_and_straddle(self, api):
        """PRD §3.5: "Posting computes the contractor's commission on the check, in tiers: ten percent of the portion of `gross_recovery_cents` up to and including 100,000 cents (one thousand dollars); seven and a half percent of the portion above 100,000 cents, up to a further 100,000 cents of width; and five percent of any portion above 200,000 cents."

        Design: Corner/calculations/commission_tier_boundary_and_straddle
        """
        # Posting exactly at the tier-1 cap: no tier-2 spillover.
        ctx_a = setup_posted_recovery(
            posting_amount=100000, claims=[("2026-01-10", 100000)]
        )
        posting_a = ctx_a["posting"]
        assert posting_a["commission_cents"] == 10000, (
            f"A 100000 posting sits exactly at the tier-1 cap, got {posting_a['commission_cents']}"
        )
        assert posting_a["net_to_state_cents"] == 90000
        # Posting straddling all three tiers: 10000 + 7500 + 2500.
        ctx_b = setup_posted_recovery(
            posting_amount=250000, claims=[("2026-01-10", 250000)]
        )
        posting_b = ctx_b["posting"]
        assert posting_b["commission_cents"] == 20000, (
            f"250000 straddles all three tiers: 10000+7500+2500, got {posting_b['commission_cents']}"
        )
        assert posting_b["net_to_state_cents"] == 230000


class TestPostingStateRules:
    def test_double_post_rejected_without_double_application(self, api):
        """PRD §3.5: "A posting in `PENDING` moves to `POSTED`, provided the current calendar date is on or before the `sol_date` of the posting's settlement's case; past that date the lazy expiry cascade of §2.5 fires and the post is rejected with `ERR_SOL_EXPIRED`."

        Design: Corner/state_machines/posting_double_post_returns_invalid_state
        """
        ctx = setup_posted_recovery(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        resp = api.post_posting(ctx["posting"]["id"], ACCT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_lien(ctx["lien"]["id"])["outstanding_cents"] == 0, (
            "A rejected second post must not reduce the lien again"
        )

    def test_posting_above_settlement_recovery_rejected(self, api):
        """PRD §3.5: "Installments are allowed: several postings may accumulate against one settlement, but the cumulative `gross_recovery_cents` of non-`REVERSED` postings on a settlement must never exceed that settlement's `state_recovery_cents`; a recording that would cross the line is rejected with `ERR_POSTING_EXCEEDS_RECOVERY` (HTTP 409)."

        Design: Corner/validations/posting_above_recovery_rejected
        """
        # REIMBURSEMENT recovery on a 100000 lien: 100000.
        ctx = setup_accepted_settlement(claims=[("2026-01-10", 100000)])
        assert ctx["settlement"]["state_recovery_cents"] == 100000
        resp = api.create_posting(
            ctx["settlement"]["id"],
            factories.posting_payload(gross_recovery_cents=100001),
            ACCT,
        )
        validate_error(resp, ApiErrorId.ERR_POSTING_EXCEEDS_RECOVERY)
        data, meta = validate_paginated(
            api.list_postings(SPEC, params={"settlement_id": ctx["settlement"]["id"]})
        )
        assert data == [] and meta["total_count"] == 0

    def test_estate_officer_cannot_post_recovery(self, api):
        """PRD §2.1: "A request whose role is valid but not listed among the endpoint's authorized roles is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: the post endpoint is authorized for RecoveryAccountant only.

        Design: Corner/rbac/estate_officer_cannot_post_recovery_forbidden
        """
        ctx = setup_pending_posting(
            posting_amount=100000, claims=[("2026-01-10", 100000)]
        )
        resp = api.post_posting(ctx["posting"]["id"], ERO)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_posting(ctx["posting"]["id"])["status"] == "PENDING"


class TestAccountingSummary:
    def test_accounting_summary_reflects_posted_postings(self, api):
        """PRD §3.5: "For reconciliation, an accounting summary read on a case reports `total_recovered_cents` (the sum of `gross_recovery_cents` over the case's `POSTED` postings), `total_commission_cents` (the sum of `commission_cents` over those same postings), `total_net_to_state_cents` (the first total less the second), and `posting_count` (the number of `POSTED` postings contributing). `PENDING` and `REVERSED` postings are excluded from every figure."

        Design: Corner/endpoints/accounting_summary_computed_read
        """
        ctx = setup_posted_recovery(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        summary = validate_success(
            api.get_accounting_summary(ctx["case"]["id"], ACCT), 200
        )
        assert summary["total_recovered_cents"] == 200000
        assert summary["total_commission_cents"] == 17500
        assert summary["total_net_to_state_cents"] == 182500
        assert summary["posting_count"] == 1


class TestImmediateConsistency:
    def test_post_response_and_followup_read_are_immediately_consistent(self, api):
        """PRD §2.9: "Derived balances — the case's `total_paid_claims_cents` and `total_recovered_cents`, the lien's `outstanding_cents`, the estate's `claim_outstanding_cents` — are recomputed from their underlying records on every contributing mutation, so the values a client reads always reflect the complete claim, posting, payment, and waiver history."

        Design: Corner/consistency_model/immediate_visibility_after_post
        """
        ctx = setup_pending_posting(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        posted = validate_success(api.post_posting(ctx["posting"]["id"], ACCT), 200)
        assert posted["commission_cents"] == 17500
        assert posted["net_to_state_cents"] == 182500
        lien = get_lien(ctx["lien"]["id"])
        assert lien["outstanding_cents"] == 0, (
            "The lien read immediately after the post must reflect the payment"
        )


class TestReversal:
    def test_reverse_restores_lien_outstanding_exactly(self, api):
        """PRD §3.5: "Reversing moves the posting to `REVERSED` and unwinds its effects: the lien's `outstanding_cents` is increased by the `gross_recovery_cents`, excluding the posting from the posted set; if the lien had been `SATISFIED`, it reverts to `FILED`, and a case that had been `RESOLVED` reverts to `SETTLEMENT_PENDING`; if no `POSTED` postings remain on the settlement, the settlement falls back from `DISBURSED` to `ACCEPTED`; and the case's `total_recovered_cents` is recomputed without the reversed posting."

        Design: Difficulty/compensating_invariant/lien_outstanding_post_reverse_conservation
        """
        ctx = setup_posted_recovery(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        assert ctx["lien"]["outstanding_cents"] == 0
        reversed_posting = validate_success(
            api.reverse_posting(ctx["posting"]["id"], ACCT), 200
        )
        assert reversed_posting["status"] == "REVERSED"
        lien = get_lien(ctx["lien"]["id"])
        # Conservation: outstanding == amount - sum(POSTED) = 200000 - 0.
        assert lien["outstanding_cents"] == 200000, (
            f"Reversal must restore the balance with zero drift, got {lien['outstanding_cents']}"
        )
        assert lien["outstanding_cents"] == lien["lien_amount_cents"]

    def test_reverse_rewinds_lien_case_and_settlement_states(self, api):
        """PRD §3.5: "if the lien had been `SATISFIED`, it reverts to `FILED`, and a case that had been `RESOLVED` reverts to `SETTLEMENT_PENDING`; if no `POSTED` postings remain on the settlement, the settlement falls back from `DISBURSED` to `ACCEPTED`"

        Design: Difficulty/compensating_invariant/lien_outstanding_post_reverse_conservation
        """
        ctx = setup_posted_recovery(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        validate_success(api.reverse_posting(ctx["posting"]["id"], ACCT), 200)
        assert get_lien(ctx["lien"]["id"])["status"] == "FILED"
        assert get_case(ctx["case"]["id"])["status"] == "SETTLEMENT_PENDING"
        assert get_settlement(ctx["settlement"]["id"])["status"] == "ACCEPTED"

    def test_total_recovered_reconciles_to_zero_after_reverse(self, api):
        """PRD §3.5: "and the case's `total_recovered_cents` is recomputed without the reversed posting."

        Design: Corner/cross_cutting_complexity_layers/derived_total_recovered_reconciles_after_reverse
        """
        ctx = setup_pending_posting(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        case_id = ctx["case"]["id"]
        assert get_case(case_id)["total_recovered_cents"] == 0
        validate_success(api.post_posting(ctx["posting"]["id"], ACCT), 200)
        assert get_case(case_id)["total_recovered_cents"] == 200000
        validate_success(api.reverse_posting(ctx["posting"]["id"], ACCT), 200)
        assert get_case(case_id)["total_recovered_cents"] == 0, (
            "The derived total must track the POSTED set with no drift"
        )


class TestSettlementSplitIdentity:
    def test_settlement_split_fields_unchanged_through_post_and_reverse(self, api):
        """PRD §3.4: "Under both variants, the member's `member_net_cents` is the `gross_amount_cents` less `fee_amount_cents`, less `litigation_costs_cents`, less `state_recovery_cents`."
        PRD §3.5: "Reversing moves the posting to `REVERSED` and unwinds its effects"

        Design: Difficulty/compensating_invariant/settlement_split_identity_conserved
        """
        ctx = setup_posted_recovery(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        validate_success(api.reverse_posting(ctx["posting"]["id"], ACCT), 200)
        settlement = get_settlement(ctx["settlement"]["id"])
        assert settlement["fee_amount_cents"] == 250000
        assert settlement["cost_share_cents"] == 0, (
            "cost_share_cents is zero under REIMBURSEMENT"
        )
        assert settlement["state_recovery_cents"] == 200000
        assert settlement["member_net_cents"] == 450000

    def test_settlement_split_partitions_gross(self, api):
        """PRD §3.4: "Under both variants, the member's `member_net_cents` is the `gross_amount_cents` less `fee_amount_cents`, less `litigation_costs_cents`, less `state_recovery_cents`."

        Design: Difficulty/compensating_invariant/settlement_split_identity_conserved
        """
        ctx = setup_posted_recovery(
            posting_amount=200000, claims=[("2026-01-10", 200000)]
        )
        validate_success(api.reverse_posting(ctx["posting"]["id"], ACCT), 200)
        settlement = get_settlement(ctx["settlement"]["id"])
        assert_settlement_split_identity(settlement)
        assert settlement["gross_amount_cents"] == 1000000
