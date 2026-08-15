"""Trustee fee assessment: dual variants, tiered formula, period tiling,
segregation of duties, post/reverse compensation, objection window
(PRD §2.9, §3.6)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_beneficiary_headers,
    make_ops_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    EXEC,
    MANAGER,
    OFFICER,
    OPS,
    buy_holding,
    create_fee,
    create_posted_fee,
    get_trust,
    setup_funded_trust,
)

Q3 = {"period_start": "2026-07-01", "period_end": "2026-09-30"}


def _funded_trust(api, principal=200000000, income=0, name="Fee Trust"):
    return setup_funded_trust(
        principal_cents=principal, income_cents=income, trust_name=name
    )["trust"]


class TestFeeVariants:
    def _trust_with_repriced_holdings(self, api):
        """Four equity holdings of 500,000.00 each bought at creation prices
        (create-time priced_at inside Q3), then repriced to 60000 cents/unit
        at 2026-10-05; logical clock at 2026-10-10."""
        trust = _funded_trust(api, principal=200000000, name="Fee Variant Trust")
        holdings = [
            buy_holding(trust["id"], "EQUITY", ticker, 1000, 50000)
            for ticker in ("AAA", "BBB", "CCC", "DDD")
        ]
        for h in holdings:
            assert api.update_price(
                h["id"], {"unit_price_cents": 60000, "priced_at": "2026-10-05T00:00:00Z"},
                MANAGER,
            ).status_code == 200
        assert api.set_clock({"to_iso8601": "2026-10-10T00:00:00Z"}, EXEC).status_code == 200
        return trust

    def test_provisional_uses_current_market_value(self, api):
        """PRD §3.6: "A PROVISIONAL assessment is an estimate for disclosure
        and planning: its `base_market_value_cents` is the trust's
        `total_market_value_cents` at calculation time, at current prices."
        PRD §3.6: "Dividing the annual fee by four and rounding half up to
        whole cents gives the quarterly amount; the `assessed_fee_cents` is
        that quarterly amount floored at a minimum quarterly fee of 125,000
        cents — twelve hundred fifty dollars."

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_quarter_base
        """
        trust = self._trust_with_repriced_holdings(api)
        prov = create_fee(trust["id"], variant="PROVISIONAL", **Q3)
        # current TMV = 2,400,000.00 -> annual 21,000.00 -> quarterly 5,250.00
        assert prov["base_market_value_cents"] == 240000000
        assert prov["assessed_fee_cents"] == 512500

    def test_final_uses_as_of_period_end_prices_and_variants_coexist(self, api):
        """PRD §3.6: "A FINAL assessment is authoritative for a closed period:
        each holding is repriced at the latest price observation whose
        `priced_at` falls on or before the end of `period_end` (the creation
        price counts as an observation), the base is the sum of those as-of
        market values plus the currently posted income and principal cash
        balances, and identical holdings can therefore yield a different fee
        between the two variants."
        PRD §3.6: "`income_portion_cents` is the assessed fee multiplied by
        one half, rounded half up, and `principal_portion_cents` is whatever
        remains of the assessed fee, so the two portions always sum back to
        the assessed fee."
        PRD §3.6: "PROVISIONAL rows do not participate in the tiling rule."

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_quarter_base
        """
        trust = self._trust_with_repriced_holdings(api)
        prov = create_fee(trust["id"], variant="PROVISIONAL", **Q3)
        fin = create_fee(trust["id"], variant="FINAL", **Q3)
        # as-of 2026-09-30 TMV = 2,000,000.00 -> annual 17,500.00 -> 4,375.00
        assert fin["base_market_value_cents"] == 200000000
        assert fin["assessed_fee_cents"] == 437500
        assert fin["income_portion_cents"] == 218750
        assert fin["principal_portion_cents"] == 218750
        assert prov["id"] != fin["id"], "PROVISIONAL and FINAL for one period coexist"


class TestTieredFeeAndFloor:
    def test_mid_tier_base_fee_and_even_split(self, api):
        """PRD §3.6: "The first tier charges one percent on the portion of
        the base up to one million dollars — 100,000,000 cents. The second
        tier charges three-quarters of one percent on the portion above one
        million dollars, up to a two-million-dollar span. The third tier
        charges one-half of one percent on any portion above three million
        dollars. The sum of the three tiers is the `annual_fee_cents`.
        Dividing the annual fee by four and rounding half up to whole cents
        gives the quarterly amount."
        PRD §3.6: "`income_portion_cents` is the assessed fee multiplied by
        one half, rounded half up, and `principal_portion_cents` is whatever
        remains of the assessed fee, so the two portions always sum back to
        the assessed fee."

        Design: Difficulty/combinatorial_formula/trustee_fee_tiered_min_split
        """
        trust = _funded_trust(api, principal=200000000, name="Fee Tier Trust")
        fee = create_fee(trust["id"], variant="FINAL", **Q3)
        assert fee["base_market_value_cents"] == 200000000
        assert fee["annual_fee_cents"] == 1750000
        assert fee["assessed_fee_cents"] == 437500
        assert fee["income_portion_cents"] == 218750
        assert fee["principal_portion_cents"] == 218750

    def test_min_quarterly_fee_floor_at_low_base(self, api):
        """PRD §3.6: "Dividing the annual fee by four and rounding half up to
        whole cents gives the quarterly amount; the `assessed_fee_cents` is
        that quarterly amount floored at a minimum quarterly fee of 125,000
        cents — twelve hundred fifty dollars."

        Design: Difficulty/combinatorial_formula/trustee_fee_tiered_min_split
        """
        trust = _funded_trust(api, principal=10000000, name="Fee Floor Trust")
        fee = create_fee(trust["id"], variant="FINAL", **Q3)
        # raw quarterly = round(100,000 * 0.01 / 4) = 25,000 < floor 125,000
        assert fee["assessed_fee_cents"] == 125000
        assert fee["income_portion_cents"] == 62500
        assert fee["principal_portion_cents"] == 62500


class TestFeePeriodTiling:
    def _trust_with_q3_final(self, api):
        trust = _funded_trust(api, principal=200000000, name="Tile Trust")
        a1 = create_fee(trust["id"], variant="FINAL", **Q3)
        return trust, a1

    def test_contiguous_final_period_accepted(self, api):
        """PRD §3.6: "FINAL periods must tile with no gap and no overlap: the
        `period_start` of a new FINAL assessment must be exactly one day after
        the `period_end` of the latest non-REVERSED FINAL assessment for the
        trust, otherwise `ERR_FEE_PERIOD_NOT_CONTIGUOUS`."

        Design: Difficulty/resource_temporal_overlap/fee_period_gap_free_tiling
        """
        trust, _ = self._trust_with_q3_final(api)
        a2 = create_fee(trust["id"], variant="FINAL",
                        period_start="2026-10-01", period_end="2026-12-31")
        assert a2["status"] == "CALCULATED"

    def test_gap_and_overlap_starts_rejected(self, api):
        """PRD §3.6: "FINAL periods must tile with no gap and no overlap: the
        `period_start` of a new FINAL assessment must be exactly one day after
        the `period_end` of the latest non-REVERSED FINAL assessment for the
        trust, otherwise `ERR_FEE_PERIOD_NOT_CONTIGUOUS`; PROVISIONAL rows do
        not participate in the tiling rule."

        Design: Difficulty/resource_temporal_overlap/fee_period_gap_free_tiling
        """
        trust, _ = self._trust_with_q3_final(api)
        gap = api.create_fee_assessment(
            {"trust_id": trust["id"], "period_start": "2026-10-02",
             "period_end": "2026-12-31", "variant": "FINAL"},
            OPS,
        )
        validate_error(gap, ApiErrorId.ERR_FEE_PERIOD_NOT_CONTIGUOUS)
        overlap = api.create_fee_assessment(
            {"trust_id": trust["id"], "period_start": "2026-09-15",
             "period_end": "2026-10-15", "variant": "FINAL"},
            OPS,
        )
        validate_error(overlap, ApiErrorId.ERR_FEE_PERIOD_NOT_CONTIGUOUS)

        # A PROVISIONAL assessment is not subject to the tiling rule.
        prov = create_fee(trust["id"], variant="PROVISIONAL",
                          period_start="2026-10-02", period_end="2026-12-31")
        assert prov["status"] == "CALCULATED"


class TestFeeSegregationOfDuties:
    def test_discloser_cannot_post(self, api):
        """PRD §2.9: "The operator who discloses a trustee fee may not post
        that same fee; the TaxSpecialist who prepares a filing may not approve
        its review; and the operator who initiates a trust termination may not
        approve its final accounting. Each pairing is enforced by comparing
        `X-User-ID` against the recorded first-half actor —
        `disclosed_by_user_id`, `prepared_by_user_id`, and
        `initiated_by_user_id` respectively — and a match is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_fee_discloser_cannot_post
        """
        trust = _funded_trust(api, principal=200000000, name="SoD Fee")
        fee = create_fee(trust["id"], variant="FINAL", **Q3)
        assert api.disclose_fee(fee["id"], make_ops_headers("ops_same")).status_code == 200
        resp = api.post_fee(fee["id"], make_ops_headers("ops_same"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_different_operator_posts_successfully(self, api):
        """PRD §3.6: "Posting moves DISCLOSED → POSTED and is
        segregation-controlled: the poster's `X-User-ID` must differ from
        `disclosed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_fee_discloser_cannot_post
        """
        # Income funding is required so the posted fee's income portion fits
        # within available income (PRD §3.6 funds check on posting).
        trust = _funded_trust(api, principal=200000000, income=1000000,
                              name="SoD Fee Other")
        fee = create_fee(trust["id"], variant="FINAL", **Q3)
        assert api.disclose_fee(fee["id"], make_ops_headers("ops_same")).status_code == 200
        api.post_fee(fee["id"], make_ops_headers("ops_same"))  # rejected
        posted = validate_success(api.post_fee(fee["id"], make_ops_headers("ops_other")))
        assert posted["status"] == "POSTED"


class TestFeePostAndReverse:
    def test_post_debits_both_buckets(self, api):
        """PRD §3.6: "A successful post appends two ledger rows — a FEE row in
        the INCOME bucket for the negative of the income portion and a FEE row
        in the PRINCIPAL bucket for the negative of the principal portion,
        both sourced to FEE_ASSESSMENT — recomputes the trust's balances and
        available amounts."

        Design: Corner/state_machines/fee_post_then_reverse_restores_balances
        """
        trust = _funded_trust(api, principal=200000000, income=1000000,
                              name="Reverse Trust")
        create_posted_fee(trust["id"], variant="FINAL", **Q3)
        # FINAL base (PRD §3.6) = as-of holdings (none) + currently posted
        # cash (201,000,000) -> annual 1,757,500 -> quarterly 439,375 ->
        # income portion round-half-up(219,687.5) = 219,688, principal
        # portion 219,687.
        after = get_trust(trust["id"])
        assert after["income_balance_cents"] == 780312
        assert after["principal_balance_cents"] == 199780313

    def test_reverse_restores_balances_exactly(self, api):
        """PRD §3.6: "Finally, a `TrustExecutive` may reverse a POSTED
        assessment, moving POSTED → REVERSED with a `reason`: offsetting
        ADJUSTMENT rows are appended — the income portion added back to INCOME
        and the principal portion added back to PRINCIPAL — so the net effect
        of posting followed by reversal on every balance is exactly zero, and
        the trust's `version` increments."

        Design: Corner/state_machines/fee_post_then_reverse_restores_balances
        """
        trust = _funded_trust(api, principal=200000000, income=1000000,
                              name="Reverse Exact")
        fee = create_posted_fee(trust["id"], variant="FINAL", **Q3)
        reversed_fee = validate_success(
            api.reverse_fee(fee["id"], {"reason": "billing error"}, EXEC)
        )
        assert reversed_fee["status"] == "REVERSED"

        after = get_trust(trust["id"])
        assert after["income_balance_cents"] == 1000000
        assert after["principal_balance_cents"] == 200000000

        rows, meta = validate_paginated(
            api.list_ledger_entries(OPS, params={"trust_id": trust["id"],
                                                 "entry_kind": "ADJUSTMENT"})
        )
        assert meta["total_count"] == 2
        by_bucket = {r["bucket"]: r["amount_cents"] for r in rows}
        # Reversal rows mirror the posted portions: 219,688 / 219,687 (base
        # includes both posted cash balances, PRD §3.6).
        assert by_bucket == {"INCOME": 219688, "PRINCIPAL": 219687}


class TestObjectionWindow:
    def _disclosed_fee_and_delivered_statement(self, api):
        """Both the fee DISCLOSED and the statement DELIVERED at clock
        2026-09-01T00:00:00Z (default clock advanced once)."""
        ctx = setup_funded_trust(
            principal_cents=200000000,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            trust_name="Window Obj",
        )
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        assert api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, EXEC).status_code == 200
        fee = create_fee(trust["id"], variant="FINAL", **Q3)
        assert api.disclose_fee(fee["id"], make_ops_headers("ops_disc")).status_code == 200
        resp = api.create_annual_statement(
            {"trust_id": trust["id"], "fiscal_year": 2026}, OFFICER
        )
        stmt = get_success_data(resp)
        assert api.finalize_statement(stmt["id"], OFFICER).status_code == 200
        assert api.deliver_statement(stmt["id"], OFFICER).status_code == 200
        return trust, ben, fee, stmt

    def test_fee_dispute_at_exactly_thirty_days_succeeds(self, api):
        """PRD §2.9: "Two beneficiary objection windows run for thirty days,
        measured against the logical clock and inclusive of the thirtieth day.
        A beneficiary may dispute a disclosed fee while the clock is no later
        than thirty days after `disclosed_at`, and may dispute a delivered
        annual statement while the clock is no later than thirty days after
        `delivered_at`. A dispute arriving after the window closes is rejected
        with `ERR_OBJECTION_WINDOW_EXPIRED`."

        Design: Corner/validations/objection_window_exact_edge_and_expired
        """
        trust, ben, fee, _ = self._disclosed_fee_and_delivered_statement(api)
        assert api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, EXEC).status_code == 200
        disputed = validate_success(
            api.dispute_fee(fee["id"], {"dispute_reason": "fee too high"},
                            make_beneficiary_headers(ben["id"]))
        )
        assert disputed["status"] == "DISPUTED"

    def test_statement_dispute_at_thirty_one_days_rejected(self, api):
        """PRD §2.9: "Two beneficiary objection windows run for thirty days,
        measured against the logical clock and inclusive of the thirtieth day.
        A beneficiary may dispute a disclosed fee while the clock is no later
        than thirty days after `disclosed_at`, and may dispute a delivered
        annual statement while the clock is no later than thirty days after
        `delivered_at`. A dispute arriving after the window closes is rejected
        with `ERR_OBJECTION_WINDOW_EXPIRED`."

        Design: Corner/validations/objection_window_exact_edge_and_expired
        """
        trust, ben, _, stmt = self._disclosed_fee_and_delivered_statement(api)
        assert api.set_clock({"to_iso8601": "2026-10-02T00:00:00Z"}, EXEC).status_code == 200
        resp = api.dispute_statement(stmt["id"], {"dispute_reason": "late objection"},
                                     make_beneficiary_headers(ben["id"]))
        validate_error(resp, ApiErrorId.ERR_OBJECTION_WINDOW_EXPIRED)
        current = validate_success(api.get_annual_statement(stmt["id"], OFFICER))
        assert current["status"] == "DELIVERED"
