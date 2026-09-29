"""Dual-variant calculations: dividend funding modes and consensus mean variants.

Two calculations in this API each run in two variants over byte-identical stored
data. The dividend payout runs under ``DECLARED_RATE`` or ``RESERVE_CAPPED``; the
consensus read reports either the untrimmed ``SIMPLE`` mean or the default
guidance-anchored trimmed mean. Each variant of each calculation is asserted in
its own test.
"""

from test_helpers import (
    ApiClient,
    CONTACT_INSTITUTIONAL_HOLDER,
    CONTACT_RETAIL_HOLDER,
    FUNDING_DECLARED_RATE,
    FUNDING_RESERVE_CAPPED,
    INSTRUCTION_EXECUTED,
    IR_ADMIN,
    METRIC_EPS,
    TRANSFER_AGENT,
    VARIANT_ANCHORED,
    VARIANT_SIMPLE,
    assertions,
    fixtures,
)

# ---------------------------------------------------------------------------
# Local composite setup (test_helpers must not be modified)
# ---------------------------------------------------------------------------

#: The three holder positions shared by both funding-mode registers, in the
#: order they are written to the register.
_HOLDER_PLAN = (
    (333, CONTACT_INSTITUTIONAL_HOLDER),
    (667, CONTACT_INSTITUTIONAL_HOLDER),
    (1000, CONTACT_RETAIL_HOLDER),
)


def _build_dividend_register(
    api: ApiClient,
    ticker: str,
    legal_name: str,
    dividend_reserve_cents: int,
    base_hour: int = 0,
):
    """An issuer of 1,000,000 shares with holders of 333, 667 and 1000 shares.

    Each holder is written with the logical clock one hour further on, so that
    the payout ledger's creation-timestamp ordering is unambiguous.
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    company = fixtures.create_company(
        api,
        ticker=ticker,
        legal_name=legal_name,
        shares_outstanding=1000000,
        dividend_reserve_cents=dividend_reserve_cents,
    )
    holders = []
    for index, (shares, contact_type) in enumerate(_HOLDER_PLAN, start=1):
        fixtures.set_clock(api, f"2026-08-01T{base_hour + index - 1:02d}:00:00Z")
        holders.append(
            fixtures.create_holder(
                api,
                company["id"],
                shares,
                display_name=f"{ticker} Holder {index}",
                email=f"{ticker.lower()}{index}@holders.test",
                contact_type=contact_type,
            )
        )
    return company, holders


def _submit_dividend(api: ApiClient, company_id: str, funding_mode: str):
    """A DIVIDEND_PAYMENT instruction at 0.4567 cents per share in ``funding_mode``."""
    return fixtures.submit_dividend(
        api,
        company_id,
        record_date="2026-08-15",
        payable_date="2026-08-25",
        declared_rate_cents_per_share=0.4567,
        funding_mode=funding_mode,
        headers=IR_ADMIN,
    )


def _acknowledged_dividend(api: ApiClient, company_id: str, funding_mode: str):
    """A DIVIDEND_PAYMENT instruction acknowledged with the clock on the payable date."""
    instruction = _submit_dividend(api, company_id, funding_mode)
    fixtures.set_clock(api, "2026-08-25T00:00:00Z")
    return fixtures.acknowledge_instruction(
        api, instruction["id"], headers=TRANSFER_AGENT
    )


class TestDividendFundingModeVariants:
    """DECLARED_RATE and RESERVE_CAPPED over the identical 333/667/1000 register."""

    def test_declared_rate_variant_pays_the_submitted_rate_per_holder(self, api: ApiClient):
        """PRD §3.9: "Under `DECLARED_RATE` the effective rate is exactly `declared_rate_cents_per_share` as submitted, and if the resulting total exceeds the reserve the execution is refused with `ERR_DIVIDEND_RESERVE_INSUFFICIENT` and nothing is written."

        PRD §3.9: "For each payee, the amount is that payee's `shares_held` multiplied by the effective rate and rounded half up to whole cents."

        PRD §3.9: "`total_payout_cents` is then the sum of the rounded per-holder amounts."

        PRD §3.9: "The snapshot counts the issuer's contacts whose `contact_type` is `INSTITUTIONAL_HOLDER` or `RETAIL_HOLDER` and whose `shares_held` is strictly greater than zero, writing that count to `snapshot_holder_count`, and sums those same rows' `shares_held` into `snapshot_shares_total`."

        Design: Difficulty/dual_variant_calc/dividend_declared_rate_versus_reserve_capped_payout
        """
        company, holders = _build_dividend_register(
            api, "DVA", "Dividend Alpha Corp", 100000
        )
        instruction = _acknowledged_dividend(
            api, company["id"], FUNDING_DECLARED_RATE
        )
        assert instruction["snapshot_holder_count"] == 3
        assert instruction["snapshot_shares_total"] == 2000

        executed = fixtures.execute_instruction(
            api, instruction["id"], headers=TRANSFER_AGENT
        )
        assertions.assert_instruction(
            executed,
            status=INSTRUCTION_EXECUTED,
            funding_mode=FUNDING_DECLARED_RATE,
            total_payout_cents=914,
        )
        assertions.assert_payout_ledger(
            executed,
            [
                {"contact_id": holders[0]["id"], "shares_held": 333, "amount_cents": 152},
                {"contact_id": holders[1]["id"], "shares_held": 667, "amount_cents": 305},
                {"contact_id": holders[2]["id"], "shares_held": 1000, "amount_cents": 457},
            ],
        )

        after = fixtures.read_company(api, company["id"])
        assertions.assert_company(
            after, dividend_reserve_cents=99086, dividend_paid_cents=914
        )

    def test_reserve_capped_variant_replaces_the_rate_with_the_floored_reserve_quotient(
        self, api: ApiClient
    ):
        """PRD §3.9: "Under `RESERVE_CAPPED` the declared rate is ignored entirely: the effective rate is the issuer's `dividend_reserve_cents` divided by the instruction's `snapshot_shares_total`, truncated downward to 4 decimal places — that is, multiply the quotient by 10,000, discard any fractional part toward zero, and divide by 10,000 again."

        PRD §3.9: "For each payee, the amount is that payee's `shares_held` multiplied by the effective rate and rounded half up to whole cents."

        PRD §3.9: "It then moves the money: the issuer's `dividend_reserve_cents` decreases by `total_payout_cents` while its `dividend_paid_cents` increases by the same figure, with the issuer's `version` incremented by 1."

        Design: Difficulty/dual_variant_calc/dividend_declared_rate_versus_reserve_capped_payout
        """
        company, holders = _build_dividend_register(
            api, "DVB", "Dividend Beta Corp", 500
        )
        instruction = _acknowledged_dividend(
            api, company["id"], FUNDING_RESERVE_CAPPED
        )
        assert instruction["snapshot_shares_total"] == 2000

        executed = fixtures.execute_instruction(
            api, instruction["id"], headers=TRANSFER_AGENT
        )
        assertions.assert_instruction(
            executed,
            status=INSTRUCTION_EXECUTED,
            funding_mode=FUNDING_RESERVE_CAPPED,
            total_payout_cents=500,
        )
        # 500 / 2000 = 0.2500 cents per share, so 333 / 667 / 1000 shares are
        # credited 83 / 167 / 250 rather than the declared rate's 152 / 305 / 457.
        assertions.assert_payout_ledger(
            executed,
            [
                {"contact_id": holders[0]["id"], "shares_held": 333, "amount_cents": 83},
                {"contact_id": holders[1]["id"], "shares_held": 667, "amount_cents": 167},
                {"contact_id": holders[2]["id"], "shares_held": 1000, "amount_cents": 250},
            ],
        )

        before = {"dividend_reserve_cents": 500, "dividend_paid_cents": 0}
        after = fixtures.read_company(api, company["id"])
        assertions.assert_company(
            after, dividend_reserve_cents=0, dividend_paid_cents=500
        )
        assertions.assert_reserve_plus_paid_unchanged(before, after)

    def test_identical_registers_diverge_between_the_two_funding_modes(
        self, api: ApiClient
    ):
        """PRD §3.9: "The two funding modes differ only in the effective rate."

        PRD §3.9: "Finally each ledger row credits that holder's `dividend_received_cents` by the row's `amount_cents` and increments that contact's `version` by 1."

        PRD §3.9: "Second, the sum of `dividend_received_cents` across the issuer's contacts always equals the issuer's `dividend_paid_cents`."

        Design: Difficulty/dual_variant_calc/dividend_declared_rate_versus_reserve_capped_payout
        """
        company_a, holders_a = _build_dividend_register(
            api, "DVA", "Dividend Alpha Corp", 100000, base_hour=0
        )
        company_b, holders_b = _build_dividend_register(
            api, "DVB", "Dividend Beta Corp", 500, base_hour=3
        )
        instruction_a = _submit_dividend(api, company_a["id"], FUNDING_DECLARED_RATE)
        instruction_b = _submit_dividend(api, company_b["id"], FUNDING_RESERVE_CAPPED)

        fixtures.set_clock(api, "2026-08-25T00:00:00Z")
        fixtures.acknowledge_instruction(api, instruction_a["id"], headers=TRANSFER_AGENT)
        fixtures.acknowledge_instruction(api, instruction_b["id"], headers=TRANSFER_AGENT)
        executed_a = fixtures.execute_instruction(
            api, instruction_a["id"], headers=TRANSFER_AGENT
        )
        executed_b = fixtures.execute_instruction(
            api, instruction_b["id"], headers=TRANSFER_AGENT
        )

        assert executed_a["total_payout_cents"] == 914
        assert executed_b["total_payout_cents"] == 500

        # The identical 1000-share retail position is credited differently under
        # the two modes.
        retail_a = fixtures.read_contact(api, holders_a[2]["id"])
        retail_b = fixtures.read_contact(api, holders_b[2]["id"])
        assertions.assert_contact(retail_a, shares_held=1000, dividend_received_cents=457)
        assertions.assert_contact(retail_b, shares_held=1000, dividend_received_cents=250)

        after_a = fixtures.read_company(api, company_a["id"])
        after_b = fixtures.read_company(api, company_b["id"])
        assertions.assert_holder_credits_match_paid(
            after_a, [fixtures.read_contact(api, holder["id"]) for holder in holders_a]
        )
        assertions.assert_holder_credits_match_paid(
            after_b, [fixtures.read_contact(api, holder["id"]) for holder in holders_b]
        )


# ---------------------------------------------------------------------------
# Consensus: SIMPLE versus the guidance-anchored trimmed mean
# ---------------------------------------------------------------------------


def _build_consensus_world(api: ApiClient):
    """An issuer with published EPS guidance and four accepted EPS estimates."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    company = fixtures.create_company(
        api,
        ticker="CNS",
        legal_name="Consensus Systems Inc",
        shares_outstanding=1000000,
    )
    fixtures.create_published_guidance(
        api,
        company["id"],
        fact_key="FY2026-EPS-GUIDANCE",
        metric=METRIC_EPS,
        period_label="FY2026",
        guidance_low=2.00,
        guidance_high=2.20,
    )
    seeded = fixtures.seed_estimates(api, company["id"], [2.00, 2.05, 2.10, 3.90])
    return company, seeded


class TestConsensusMeanVariants:
    """One eligible set of 2.00 / 2.05 / 2.10 / 3.90 read through both variants."""

    def test_default_variant_reports_the_guidance_anchored_trimmed_mean(
        self, api: ApiClient
    ):
        """PRD §3.7: "If that row exists, `guidance_anchored` is true, `band_low` is `guidance_low` multiplied by 0.85 and rounded half up to 4 decimal places, and `band_high` is `guidance_high` multiplied by 1.15 and rounded half up to 4 decimal places."

        PRD §3.7: "Keep every eligible submission whose `value` lies within the band, both bounds inclusive: a value exactly equal to `band_low` or exactly equal to `band_high` is kept."

        PRD §3.7: "Otherwise the anchored mean is the sum of the kept values divided by their count, rounded half up to 4 decimal places, and `trimmed_applied` is reported as true."

        PRD §3.7: "When `variant` is `ANCHORED`, or when it is omitted entirely (`ANCHORED` being the default), `consensus_mean` is the anchored mean from step four; for identical inputs the two variants diverge whenever `outlier_excluded_count` is greater than zero."

        Design: Difficulty/dual_variant_calc/consensus_simple_mean_versus_guidance_anchored_trimmed_mean
        """
        company, _ = _build_consensus_world(api)

        payload = fixtures.read_consensus(
            api, company["id"], metric=METRIC_EPS, period_label="FY2026"
        )
        assertions.assert_consensus(
            payload,
            company_id=company["id"],
            metric=METRIC_EPS,
            period_label="FY2026",
            variant=VARIANT_ANCHORED,
            eligible_count=4,
            guidance_anchored=True,
            outlier_excluded_count=1,
            trimmed_applied=True,
        )
        assert payload["band_low"] == assertions.approx_4dp(1.7000)
        assert payload["band_high"] == assertions.approx_4dp(2.5300)
        assert payload["simple_mean"] == assertions.approx_4dp(2.5125)
        assert payload["consensus_mean"] == assertions.approx_4dp(2.0500)

    def test_default_variant_reports_dispersion_against_the_anchored_mean(
        self, api: ApiClient
    ):
        """PRD §3.7: "Finally, `dispersion_pct` is the spread of the kept values relative to the reported consensus: the largest kept value minus the smallest kept value, divided by `consensus_mean`, multiplied by 100 and rounded half up to 2 decimal places."

        PRD §3.7: "The number of eligible submissions not kept is reported as `outlier_excluded_count`."

        Design: Difficulty/dual_variant_calc/consensus_simple_mean_versus_guidance_anchored_trimmed_mean
        """
        company, _ = _build_consensus_world(api)

        payload = fixtures.read_consensus(
            api, company["id"], metric=METRIC_EPS, period_label="FY2026"
        )
        # Kept values are 2.00 / 2.05 / 2.10, so the spread is 0.10 over a
        # reported consensus of 2.0500.
        assert payload["outlier_excluded_count"] == 1
        assert payload["consensus_mean"] == assertions.approx_4dp(2.0500)
        assert payload["dispersion_pct"] == assertions.approx_2dp(4.88)

    def test_simple_variant_reports_the_untrimmed_mean_over_the_whole_eligible_set(
        self, api: ApiClient
    ):
        """PRD §3.7: "When `variant` is `SIMPLE`, `consensus_mean` is the untrimmed `simple_mean` computed over the whole eligible set — outliers are still counted and still reported through `outlier_excluded_count`, they simply do not move the reported number."

        PRD §3.7: "Sum the `value` of every eligible submission, divide by the number of eligible submissions, and round the quotient half up to 4 decimal places."

        PRD §3.7: "Finally, `dispersion_pct` is the spread of the kept values relative to the reported consensus: the largest kept value minus the smallest kept value, divided by `consensus_mean`, multiplied by 100 and rounded half up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/consensus_simple_mean_versus_guidance_anchored_trimmed_mean
        """
        company, _ = _build_consensus_world(api)

        payload = fixtures.read_consensus(
            api,
            company["id"],
            metric=METRIC_EPS,
            period_label="FY2026",
            variant=VARIANT_SIMPLE,
        )
        assertions.assert_consensus(
            payload,
            variant=VARIANT_SIMPLE,
            eligible_count=4,
            outlier_excluded_count=1,
            guidance_anchored=True,
        )
        assert payload["simple_mean"] == assertions.approx_4dp(2.5125)
        assert payload["consensus_mean"] == assertions.approx_4dp(2.5125)
        # The same kept spread of 0.10 measured against the untrimmed mean.
        assert payload["dispersion_pct"] == assertions.approx_2dp(3.98)

    def test_the_two_variants_diverge_over_identical_stored_estimates(
        self, api: ApiClient
    ):
        """PRD §3.7: "The `variant` query parameter selects which mean is reported as `consensus_mean`."

        PRD §3.7: "When `variant` is `ANCHORED`, or when it is omitted entirely (`ANCHORED` being the default), `consensus_mean` is the anchored mean from step four; for identical inputs the two variants diverge whenever `outlier_excluded_count` is greater than zero."

        PRD §3.7: "The consensus itself is a **computed read**, not a stored row: it takes a required `metric` and `period_label`, plus an optional `variant`, and returns freshly calculated numbers without incrementing any version."

        Design: Difficulty/dual_variant_calc/consensus_simple_mean_versus_guidance_anchored_trimmed_mean
        """
        company, seeded = _build_consensus_world(api)
        versions_before = [
            fixtures.read_contact(api, analyst["id"])["version"]
            for analyst, _ in seeded
        ]

        anchored = fixtures.read_consensus(
            api, company["id"], metric=METRIC_EPS, period_label="FY2026"
        )
        simple = fixtures.read_consensus(
            api,
            company["id"],
            metric=METRIC_EPS,
            period_label="FY2026",
            variant=VARIANT_SIMPLE,
        )
        assert anchored["eligible_count"] == simple["eligible_count"] == 4
        assert anchored["outlier_excluded_count"] == simple["outlier_excluded_count"] == 1
        assert simple["consensus_mean"] - anchored["consensus_mean"] == (
            assertions.approx_4dp(0.4625)
        )

        # A computed read increments no version.
        versions_after = [
            fixtures.read_contact(api, analyst["id"])["version"]
            for analyst, _ in seeded
        ]
        assert versions_after == versions_before
        assert fixtures.read_company(api, company["id"])["version"] == 1
