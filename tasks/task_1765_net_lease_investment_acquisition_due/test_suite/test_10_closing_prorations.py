"""Closing-statement issuance: per-line proration rounding, the half-open
interval split at the closing date, and proration immutability."""
from test_helpers import (
    ApiErrorId,
    assert_proration,
    create_deal,
    issue_statement,
    issue_statement_payload,
    proration_line,
    setup_clear_to_close,
    validate_paginated,
    validate_success,
)


def _prorations_by_type(api, deal_id, stmt_id, escrow_headers):
    data, _meta = validate_paginated(api.list_prorations(
        deal_id, stmt_id, escrow_headers, params={"limit": 100}))
    return {line["line_type"]: line for line in data}


class TestProrationNestedRounding:
    def _setup_and_issue_three_line_statement(self, api, escrow_headers):
        ctx = setup_clear_to_close(deal_name="ProrationDeal",
                                   target_close_date="2026-09-20T00:00:00Z",
                                   purchase_price_cents=25000000,
                                   earnest_money_cents=500000,
                                   lease_rent_cents=1200000,
                                   lease_type="ABSOLUTE_NET",
                                   lease_commencement="2018-06-01T00:00:00Z",
                                   lease_expiration="2035-12-01T00:00:00Z")
        deal_id = ctx["deal"]["id"]
        lease_id = ctx["lease"]["id"]
        stmt_id = ctx["statement"]["id"]
        inputs = [
            proration_line("BASE_RENT", lease_id, 1200000,
                           "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"),
            proration_line("TAX", lease_id, 365000,
                           "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z"),
            proration_line("INSURANCE", lease_id, 100001,
                           "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z"),
        ]
        issued = issue_statement(deal_id, stmt_id, "2026-09-15T00:00:00Z",
                                 proration_inputs=inputs)
        return ctx, issued

    def test_per_line_rounding_and_direction(
            self, api, escrow_headers):
        """PRD §3.11: "The line amount is the `annual_amount_cents`
        multiplied by buyer days and divided by 365, rounded half up per
        line."
        PRD §3.11: "The `direction` is `BUYER_CREDIT` for `BASE_RENT` and
        `CAM` lines — rent pre-paid by the tenant to the seller through the
        period end — and `SELLER_CREDIT` for the other line types."

        Design: Difficulty/combinatorial_formula/proration_nested_rounding_mode_b_round_per_line_then_sum
        """
        ctx, issued = self._setup_and_issue_three_line_statement(
            api, escrow_headers)
        assert issued["status"] == "ISSUED"
        lines = _prorations_by_type(api, ctx["deal"]["id"],
                                    ctx["statement"]["id"], escrow_headers)
        # BASE_RENT: buyer days 16 (closing 09-15) -> 1,200,000*16/365.
        assert lines["BASE_RENT"]["prorated_cents"] == 52603
        assert lines["BASE_RENT"]["direction"] == "BUYER_CREDIT"
        # TAX: buyer days 108 -> 365,000*108/365 = 108,000 exactly.
        assert lines["TAX"]["prorated_cents"] == 108000
        assert lines["TAX"]["direction"] == "SELLER_CREDIT"
        # INSURANCE: 100,001*108/365 = 29,589.0684 -> 29,589 per line.
        assert lines["INSURANCE"]["prorated_cents"] == 29589
        assert lines["INSURANCE"]["direction"] == "SELLER_CREDIT"
        for line in lines.values():
            assert_proration(line)

    def test_total_round_per_line_then_sum_and_cash_to_close(
            self, api, escrow_headers):
        """PRD §3.11: "The rounding order is pinned — round each line first,
        then sum; summing exact values and rounding once at the end produces
        different cents and is forbidden."
        PRD §3.11: "The `cash_to_close_cents` composes in a pinned layered
        order: start from the `psa_price_cents`; subtract the financing
        application's `loan_amount_cents` (zero when there is no financing);
        add the `total_prorations_cents`, which may be negative; add the
        `assumption_fee_cents` (zero for a new loan or no financing); and
        finally subtract the `earnest_money_cents`."

        Design: Difficulty/combinatorial_formula/proration_nested_rounding_mode_b_round_per_line_then_sum
        """
        ctx, issued = self._setup_and_issue_three_line_statement(
            api, escrow_headers)
        # 52,603 - 108,000 - 29,589 = -84,986 (round per line, then sum).
        assert issued["total_prorations_cents"] == -84986
        # 25,000,000 - 0 + (-84,986) + 0 - 500,000 = 24,415,014.
        assert issued["cash_to_close_cents"] == 24415014
        assert issued["provisional"] is True


class TestProrationHalfOpenInterval:
    def _setup_and_issue(self, api, closing_date):
        ctx = setup_clear_to_close(deal_name="HalfOpenDeal",
                                   target_close_date="2026-09-05T00:00:00Z",
                                   purchase_price_cents=25000000,
                                   earnest_money_cents=500000,
                                   lease_rent_cents=1200000,
                                   lease_expiration="2036-01-01T00:00:00Z",
                                   dd_period_days=25)
        lease_id = ctx["lease"]["id"]
        inputs = [proration_line("BASE_RENT", lease_id, 1200000,
                                 "2026-09-01T00:00:00Z",
                                 "2026-10-01T00:00:00Z")]
        issued = issue_statement(ctx["deal"]["id"], ctx["statement"]["id"],
                                 closing_date, proration_inputs=inputs)
        return ctx, issued

    def test_closing_on_period_start_gives_zero_seller_days(
            self, api, escrow_headers):
        """PRD §3.11: "Seller days are the days from `period_start` up to the
        earlier of `period_end` and the `closing_date`, floored at zero;
        buyer days are the period length minus seller days."
        PRD §3.11: "Each line's `prorated_cents` uses the ACT/365 day-count
        convention over the half-open interval from `period_start`
        (inclusive) to `period_end` (exclusive)."

        Design: Difficulty/resource_temporal_overlap/proration_period_half_open_interval_split_at_closing_date
        """
        ctx, issued = self._setup_and_issue(api, "2026-09-01T00:00:00Z")
        lines = _prorations_by_type(api, ctx["deal"]["id"],
                                    ctx["statement"]["id"], escrow_headers)
        rent = lines["BASE_RENT"]
        # Closing on the first day of the period: seller days 0, buyer days
        # 30 -> round_half_up(1,200,000*30/365) = 98,630.
        assert rent["prorated_cents"] == 98630
        assert rent["direction"] == "BUYER_CREDIT", (
            "The empty seller interval does not flip the direction")

    def test_closing_at_period_end_gives_zero_buyer_amount(
            self, api, escrow_headers):
        """PRD §3.11: "Seller days are the days from `period_start` up to the
        earlier of `period_end` and the `closing_date`, floored at zero;
        buyer days are the period length minus seller days."
        PRD §3.11: "The line amount is the `annual_amount_cents` multiplied
        by buyer days and divided by 365, rounded half up per line."

        Design: Difficulty/resource_temporal_overlap/proration_period_half_open_interval_split_at_closing_date
        """
        ctx, issued = self._setup_and_issue(api, "2026-10-01T00:00:00Z")
        lines = _prorations_by_type(api, ctx["deal"]["id"],
                                    ctx["statement"]["id"], escrow_headers)
        rent = lines["BASE_RENT"]
        # Closing at period_end (exclusive bound): buyer days 0 -> 0 cents.
        assert rent["prorated_cents"] == 0
        assert rent["direction"] == "BUYER_CREDIT"


class TestProrationImmutability:
    def test_proration_immutable_no_update_endpoint(self, api,
                                                    escrow_headers,
                                                    analyst_headers):
        """PRD §2.4: "Proration lines are immutable once created —
        corrections happen exclusively through true-up adjustments on the
        owning statement — so a `Proration` carries only `id` and
        `created_at`; both `updated_at` and `version` are absent from that
        resource."
        PRD §3.10: "On success the deal's posture and status become
        `CLEAR_TO_CLOSE` and the system issues the provisional closing
        statement in `DRAFT` with computed prorations"

        Design: Corner/entities/proration_immutable_no_update_endpoint
        """
        # Statements exist only after certification.
        fresh = create_deal(deal_name="ImmutDeal",
                            purchase_price_cents=10000000,
                            earnest_money_cents=100000)
        stmts, meta = validate_paginated(api.list_closing_statements(
            fresh["id"], escrow_headers))
        assert stmts == [] and meta["total_count"] == 0

        ctx = setup_clear_to_close(deal_name="ImmutDeal2")
        deal_id = ctx["deal"]["id"]
        stmt_id = ctx["statement"]["id"]
        issue_statement(deal_id, stmt_id, lease_id=ctx["lease"]["id"])
        lines, _meta = validate_paginated(api.list_prorations(
            deal_id, stmt_id, escrow_headers))
        assert lines, "Issuance must create one Proration per input line"
        for line in lines:
            assert_proration(line)

        # The PRD declares no mutating route for proration lines.
        line_id = lines[0]["id"]
        path = (f"/acquisition-deals/deals/{deal_id}/closing-statements/"
                f"{stmt_id}/prorations/{line_id}")
        for method in ("PUT", "PATCH", "DELETE"):
            resp = api._request(method, path,
                                {"prorated_cents": 1}, escrow_headers)
            assert resp.status_code in (404, 405), (
                f"{method} {path} must not be a mutating route, got "
                f"{resp.status_code}")
