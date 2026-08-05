"""Payout math: dual-variant estimate, tiered contingency fee, pro-rata waterfall."""
from test_helpers import get_success_data, TEST_USERS
from test_helpers import fixtures as fx

PM = TEST_USERS["program_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _file_submit_review(api, consumer, program_id, claimed,
                        bstart="2026-01-01T00:00:00Z", bend="2026-02-01T00:00:00Z"):
    """File a claim, attach + verify one document, submit, start review.
    Leaves the claim in UNDER_REVIEW, eligible."""
    claim = fx.create_claim(api, consumer, program_id, claimed_amount_cents=claimed,
                           benefit_period_start=bstart, benefit_period_end=bend)
    doc = fx.add_document(api, claim, consumer)
    fx.submit_claim(api, claim, consumer)
    fx.verify_document(api, doc["id"])
    fx.start_review(api, claim["id"])
    return claim


class TestProvisionalVsFinalDiverge:
    """Difficulty dual_variant_calc — provisional (advertised-based) diverges from
    final (fund-clamped) once the shared fund is partly depleted."""

    def _setup_depleted_second_claim(self, api):
        fx.set_clock(api)
        program = fx.create_open_program(
            api, fund_total_cents=30000, advertised_amount_cents=20000,
            per_claim_cap_cents=25000, eligibility_min_purchase_cents=5000)
        pid = program["id"]
        ca_consumer = fx.register_verified_consumer(api)
        ca = _file_submit_review(api, ca_consumer, pid, 25000)
        fx.approve_claim(api, ca["id"], pid)  # debits 20000 -> fund_remaining 10000
        cb_consumer = fx.register_verified_consumer(api)
        cb = _file_submit_review(api, cb_consumer, pid, 25000)
        fx.approve_claim(api, cb["id"], pid)  # final clamped to remaining 10000
        return get_success_data(api.get_claim(cb["id"], ADMIN))

    def test_provisional_and_final_diverge(self, api):
        """PRD §3.3: "The provisional estimate is deliberately optimistic: it is
        the smallest of the consumer's `claimed_amount_cents`, the program's
        headline `advertised_amount_cents`, and the program's `per_claim_cap_cents`."
        PRD §3.5: "The `final_payout_cents` is the smallest of the claim's
        `provisional_payout_cents`, the program's `per_claim_cap_cents`, and the
        program's live `fund_remaining_cents` — this last clamp is what makes the
        final figure diverge from the provisional estimate once the fund is partly
        depleted."

        Design: Difficulty/dual_variant_calc/claim_payout_provisional_vs_final_diverge
        """
        cb = self._setup_depleted_second_claim(api)
        assert cb["provisional_payout_cents"] == 20000
        assert cb["final_payout_cents"] == 10000
        assert cb["provisional_payout_cents"] != cb["final_payout_cents"]

    def test_net_payout_reflects_fund_clamped_gross(self, api):
        """PRD §3.5: "The `net_payout_cents` is the `final_payout_cents` minus the
        `contingency_fee_cents`, evaluated in that pinned order — gross first, then
        fee, then the subtraction."

        Design: Difficulty/dual_variant_calc/claim_payout_provisional_vs_final_diverge
        """
        cb = self._setup_depleted_second_claim(api)
        # gross 10000 -> tier2 20% -> 2000 -> verified discount -> 1800; net 8200
        assert cb["final_payout_cents"] == 10000
        assert cb["net_payout_cents"] == 8200


class TestContingencyFeeCombinatorial:
    """Difficulty combinatorial_formula — tier selection + clamp + verified discount."""

    def test_verified_consumer_tier2_discounted_fee(self, api):
        """PRD §3.9: "a gross of at least 10,000 cents but below 50,000 cents takes
        20 percent". PRD §3.9: "if the recipient consumer's `identity_status` is
        `VERIFIED`, the clamped fee is reduced by ten percent — multiplied by the
        remaining ninety percent and rounded half up to a whole cent".

        Design: Difficulty/combinatorial_formula/contingency_fee_tier_select_clamp_discount
        """
        fx.set_clock(api)
        program = fx.create_open_program(
            api, fund_total_cents=100000, advertised_amount_cents=20000,
            per_claim_cap_cents=30000, eligibility_min_purchase_cents=5000)
        consumer = fx.register_verified_consumer(api)
        claim = _file_submit_review(api, consumer, program["id"], 25000)
        fx.approve_claim(api, claim["id"], program["id"])
        data = get_success_data(api.get_claim(claim["id"], ADMIN))
        assert data["final_payout_cents"] == 20000
        assert data["contingency_fee_cents"] == 3600
        assert data["net_payout_cents"] == 16400

    def test_unverified_consumer_keeps_undiscounted_fee(self, api):
        """PRD §3.9: "otherwise the clamped value stands as the fee. ... the
        discount is applied after the clamp and gross-cap, never before."

        Design: Difficulty/combinatorial_formula/contingency_fee_tier_select_clamp_discount
        """
        fx.set_clock(api)
        program = fx.create_open_program(
            api, fund_total_cents=100000, advertised_amount_cents=20000,
            per_claim_cap_cents=30000, eligibility_min_purchase_cents=5000)
        consumer = fx.register_consumer(api)  # UNVERIFIED; optimistic risk 20 < 50
        claim = _file_submit_review(api, consumer, program["id"], 25000)
        fx.approve_claim(api, claim["id"], program["id"])
        data = get_success_data(api.get_claim(claim["id"], ADMIN))
        # gross 20000 -> tier2 20% -> 4000 -> clamp 4000 -> no discount
        assert data["final_payout_cents"] == 20000
        assert data["contingency_fee_cents"] == 4000
        assert data["net_payout_cents"] == 16000


class TestFeeTierBoundary:
    """Difficulty boundary_precision_check — gross at the 10000-cent tier edge."""

    def test_gross_exactly_10000_selects_tier2(self, api):
        """PRD §3.9: "a gross of at least 10,000 cents but below 50,000 cents takes
        20 percent (so a gross of exactly 10,000 cents lands in this middle tier)".

        Design: Difficulty/boundary_precision_check/fee_tier_boundary_gross_exactly_10000_selects_tier2
        """
        fx.set_clock(api)
        program = fx.create_open_program(
            api, fund_total_cents=100000, advertised_amount_cents=10000,
            per_claim_cap_cents=10000, eligibility_min_purchase_cents=5000)
        consumer = fx.register_verified_consumer(api)
        claim = _file_submit_review(api, consumer, program["id"], 15000)
        fx.approve_claim(api, claim["id"], program["id"])
        data = get_success_data(api.get_claim(claim["id"], ADMIN))
        assert data["final_payout_cents"] == 10000
        assert data["contingency_fee_cents"] == 1800  # tier2 20% of 10000 = 2000, *0.9
        assert data["net_payout_cents"] == 8200

    def test_gross_9999_selects_tier1(self, api):
        """PRD §3.9: "a gross below 10,000 cents takes a rate of 15 percent".

        Design: Difficulty/boundary_precision_check/fee_tier_boundary_gross_exactly_10000_selects_tier2
        """
        fx.set_clock(api)
        program = fx.create_open_program(
            api, fund_total_cents=100000, advertised_amount_cents=9999,
            per_claim_cap_cents=9999, eligibility_min_purchase_cents=5000)
        consumer = fx.register_verified_consumer(api)
        claim = _file_submit_review(api, consumer, program["id"], 15000)
        fx.approve_claim(api, claim["id"], program["id"])
        data = get_success_data(api.get_claim(claim["id"], ADMIN))
        # gross 9999 < 10000 -> tier1 15% -> round_half_up(1499.85)=1500 -> *0.9=1350
        assert data["final_payout_cents"] == 9999
        assert data["contingency_fee_cents"] == 1350
        assert data["net_payout_cents"] == 8649


class TestProRataSettlement:
    """Difficulty combinatorial_formula — floor-then-distribute-remainder waterfall."""

    def _settle(self, api):
        fx.set_clock(api)
        program = fx.create_open_program(
            api, category="CLASS_ACTION", distribution_method="PRO_RATA",
            fund_total_cents=100000, advertised_amount_cents=60000,
            per_claim_cap_cents=60000, eligibility_min_purchase_cents=5000)
        pid = program["id"]
        claims = []
        for claimed in (50000, 30000, 20001):  # created in this order (created_at ASC)
            consumer = fx.register_verified_consumer(api)
            claim = _file_submit_review(api, consumer, pid, claimed)
            fx.approve_claim(api, claim["id"], pid)  # PRO_RATA: no payout yet
            claims.append(claim["id"])
        get_success_data(api.close_program(pid, PM))  # runs the waterfall settlement
        return pid, [get_success_data(api.get_claim(cid, ADMIN)) for cid in claims]

    def test_floor_then_remainder_gives_exact_shares(self, api):
        """PRD §3.8: "Then take the floor of each raw share down to a whole cent —
        flooring every claim **first**, before any remainder is handled. ...
        Distribute the remainder one cent at a time, giving a single extra cent to
        each claim in `created_at` ascending order in one pass".

        Design: Difficulty/combinatorial_formula/pro_rata_settlement_floor_then_distribute_remainder
        """
        _, (ca, cb, cc) = self._settle(api)
        assert ca["final_payout_cents"] == 50000
        assert cb["final_payout_cents"] == 30000
        assert cc["final_payout_cents"] == 20000

    def test_pool_fully_allocated(self, api):
        """PRD §3.8: "Sum those floored shares and subtract from the pool to get
        the leftover whole cents (the remainder). ... The system never sums the
        shares and rounds once at the end."

        Design: Difficulty/combinatorial_formula/pro_rata_settlement_floor_then_distribute_remainder
        """
        pid, (ca, cb, cc) = self._settle(api)
        total = (ca["final_payout_cents"] + cb["final_payout_cents"]
                 + cc["final_payout_cents"])
        assert total == 100000
        assert get_success_data(api.get_program(pid, PM))["fund_remaining_cents"] == 0
