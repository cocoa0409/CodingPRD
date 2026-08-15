"""Funding concentration measurement and its breach detection pipeline.

Difficulty instance: funding_limit_value_equal_does_not_breach.
Corner instances: top_counterparty_tiebreak_by_counterparty_name,
breach_dedupe_suppresses_duplicate_open_breach.
"""
from test_helpers import (
    assert_limit_breach,
    create_board_limit_payload,
    make_board_limit,
    make_funding_source,
    validate_paginated,
    validate_success,
)


class TestFundingLimitBoundary:
    def test_funding_limit_value_equal_does_not_breach(self, api, officer_headers):
        """PRD §3.7: "`ABOVE_BREACHES` breaches only when the observed value is
        strictly above the limit; `BELOW_BREACHES` breaches only when strictly
        below; an observed value exactly equal to the limit never breaches
        under either direction."
        PRD §3.5: "The response reports `total_funding_cents`, the sum of every
        balance on record, and `wholesale_reliance_bps`: the combined balance
        of the three wholesale channels times ten thousand, divided by total
        funding, and rounded down to whole basis points".

        Design: Difficulty/boundary_precision_check/funding_limit_value_equal_does_not_breach
        """
        make_board_limit(subject="WHOLESALE_RELIANCE_PCT", direction="ABOVE_BREACHES",
                         limit_value=4000, severity="BOARD")
        make_funding_source(counterparty_name="RetailA", channel="RETAIL_DEPOSIT",
                            balance_cents=6_000_000_000)
        make_funding_source(counterparty_name="W1", channel="WHOLESALE_UNSECURED",
                            balance_cents=4_000_000_000, matures_in_days=20)

        first = validate_success(api.run_funding_evaluation(officer_headers))
        # floor(4000000000 * 10000 / 10000000000) = 4000 exactly — equal to the
        # limit, so no breach under the pinned strictness.
        assert first["wholesale_reliance_bps"] == 4000, (
            f"wholesale share must be exactly 4000 bps, got {first['wholesale_reliance_bps']}"
        )
        assert first["breaches_created"] == 0, (
            f"value == limit must not breach, got {first['breaches_created']} breaches"
        )

    def test_funding_limit_value_plus_one_breaches(self, api, officer_headers):
        """PRD §3.7: "`ABOVE_BREACHES` breaches only when the observed value is
        strictly above the limit".
        PRD §3.5: "the evaluation immediately runs breach detection against
        every board limit on `WHOLESALE_RELIANCE_PCT` and
        `TOP_COUNTERPARTY_PCT`, and the response's `breaches_created` counts
        how many new breaches were raised."

        Design: Difficulty/boundary_precision_check/funding_limit_value_equal_does_not_breach
        """
        limit = make_board_limit(subject="WHOLESALE_RELIANCE_PCT", direction="ABOVE_BREACHES",
                                 limit_value=4000, severity="BOARD")
        make_funding_source(counterparty_name="RetailA", channel="RETAIL_DEPOSIT",
                            balance_cents=6_000_000_000)
        make_funding_source(counterparty_name="W1", channel="WHOLESALE_UNSECURED",
                            balance_cents=4_000_000_000, matures_in_days=20)
        make_funding_source(counterparty_name="W2", channel="WHOLESALE_SECURED",
                            balance_cents=1_000_000_000, matures_in_days=8)

        evaluation = validate_success(api.run_funding_evaluation(officer_headers))
        # floor(5000000000 * 10000 / 11000000000) = 4545 > 4000 -> breaches.
        assert evaluation["wholesale_reliance_bps"] == 4545, (
            f"wholesale share must be 4545 bps, got {evaluation['wholesale_reliance_bps']}"
        )
        assert evaluation["breaches_created"] == 1, (
            f"4545 > 4000 must raise exactly one breach, got {evaluation['breaches_created']}"
        )
        breaches, _meta = validate_paginated(api.list_limit_breaches(limit["id"], officer_headers))
        assert len(breaches) == 1
        assert_limit_breach(breaches[0])
        assert breaches[0]["detected_value"] == 4545
        assert breaches[0]["status"] == "OPEN"
        assert breaches[0]["source_type"] == "FUNDING_EVALUATION"


class TestTopCounterpartyTiebreak:
    def test_top_counterparty_tiebreak_by_name(self, api, officer_headers):
        """PRD §3.5: "Counterparty concentration groups balances by
        `counterparty_name`; `top_counterparty_bps` is the largest such share,
        each counterparty's share floored the same way, and
        `top_counterparty_name` names the counterparty holding it, with ties
        broken by ascending lexicographic order of the name."

        Design: Corner/calculations/top_counterparty_tiebreak_by_counterparty_name
        """
        make_funding_source(counterparty_name="Beta", channel="WHOLESALE_UNSECURED",
                            balance_cents=1_000_000_000, matures_in_days=5)
        make_funding_source(counterparty_name="Alpha", channel="WHOLESALE_SECURED",
                            balance_cents=1_000_000_000, matures_in_days=6)
        # Retail joins the tie: per PRD §3.5 the share grouping spans every
        # counterparty, so a 2x retail balance would hold the top outright and
        # no tie would exist to break.
        make_funding_source(counterparty_name="Retail", channel="RETAIL_DEPOSIT",
                            balance_cents=1_000_000_000)
        evaluation = validate_success(api.run_funding_evaluation(officer_headers))
        # floor(1000000000 * 10000 / 3000000000) = 3333 for Alpha, Beta, Retail.
        assert evaluation["top_counterparty_bps"] == 3333, (
            f"top share must be 3333 bps, got {evaluation['top_counterparty_bps']}"
        )
        assert evaluation["top_counterparty_name"] == "Alpha", (
            f"lexicographic tie-break must pick Alpha, got {evaluation['top_counterparty_name']!r}"
        )
        assert evaluation["breaches_created"] == 0, "no limits are configured"


class TestBreachDedupe:
    def test_breach_dedupe_suppresses_duplicate_open_breach(self, api, officer_headers):
        """PRD §3.7: "Detection also deduplicates per limit: when a breach for
        the same limit already stands `OPEN`, `ACKNOWLEDGED`, or `ESCALATED`,
        no new breach is created, so only `REMEDIATED` history may coexist with
        a fresh breach."

        Design: Corner/calculations/breach_dedupe_suppresses_duplicate_open_breach
        """
        limit = make_board_limit(subject="WHOLESALE_RELIANCE_PCT", direction="ABOVE_BREACHES",
                                 limit_value=4000, severity="BOARD")
        make_funding_source(counterparty_name="RetailA", channel="RETAIL_DEPOSIT",
                            balance_cents=6_000_000_000)
        make_funding_source(counterparty_name="W1", channel="WHOLESALE_UNSECURED",
                            balance_cents=4_000_000_000, matures_in_days=20)
        make_funding_source(counterparty_name="W2", channel="WHOLESALE_SECURED",
                            balance_cents=1_000_000_000, matures_in_days=8)

        first = validate_success(api.run_funding_evaluation(officer_headers))
        assert first["breaches_created"] == 1

        limit_now = validate_success(api.get_board_limit(limit["id"], officer_headers))
        assert limit_now["limit_value"] == 4000

        second = validate_success(api.run_funding_evaluation(officer_headers))
        assert second["wholesale_reliance_bps"] == 4545, (
            f"the limit is still violated at 4545 bps, got {second['wholesale_reliance_bps']}"
        )
        assert second["breaches_created"] == 0, (
            f"the standing OPEN breach must suppress a duplicate, got {second['breaches_created']}"
        )
        breaches, meta = validate_paginated(api.list_limit_breaches(limit["id"], officer_headers))
        assert len(breaches) == 1, f"exactly one breach may stand on the limit, got {len(breaches)}"
