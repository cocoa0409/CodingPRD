"""Cancellation effectiveness: the clock sweep cascade, premium-return
arithmetic (pro-rata vs short-rate), and the ledger lines it posts.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_no_return_entries,
    cancel_policy_effective,
)
from test_helpers import fixtures as fx

OFFICER = TEST_USERS["compliance_officer_headers"]


class TestClockSweepCascade:
    def test_sweep_flips_policy_and_case(self, api):
        """PRD §3.4: "When the current clock date reaches the case's
        `scheduled_effective_date` with the case in `NOTICE_SENT` and every
        notice for the case in `MAILED` or `DELIVERY_CONFIRMED`, the clock
        sweep moves the case `NOTICE_SENT → EFFECTIVE` and the policy
        `CANCEL_PENDING → CANCELLED`, stamps the policy's
        `cancellation_effective_date` with the scheduled date, posts the
        return-premium ledger line, and increments the `cancellation_count` of
        the regulatory report for the pinned profile and the month containing
        the scheduled date — auto-creating the `OPEN` report row if none
        exists yet."

        Design: Difficulty/transitive_cascade/clock_sweep_cancellation_to_report_cascade
        """
        bundle = cancel_policy_effective(
            "CO",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-15",
            mailed_on_date="2026-08-01",
            premium_cents=36500,
            policy_number="P-SW-1",
        )
        assert bundle["policy"]["status"] == "CANCELLED"
        assert bundle["policy"]["cancellation_effective_date"] == "2026-08-15"
        assert bundle["case"]["status"] == "EFFECTIVE"

    def test_sweep_posts_return_entry_and_increments_report(self, api):
        """PRD §3.4: "When the current clock date reaches the case's
        `scheduled_effective_date` with the case in `NOTICE_SENT` and every
        notice for the case in `MAILED` or `DELIVERY_CONFIRMED`, the clock
        sweep moves the case `NOTICE_SENT → EFFECTIVE` and the policy
        `CANCEL_PENDING → CANCELLED`, stamps the policy's
        `cancellation_effective_date` with the scheduled date, posts the
        return-premium ledger line, and increments the `cancellation_count` of
        the regulatory report for the pinned profile and the month containing
        the scheduled date — auto-creating the `OPEN` report row if none
        exists yet."

        Design: Difficulty/transitive_cascade/clock_sweep_cancellation_to_report_cascade
        """
        bundle = cancel_policy_effective(
            "CO",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-15",
            mailed_on_date="2026-08-01",
            premium_cents=36500,
            policy_number="P-SW-1",
        )
        # Elapsed 226 days of a 365-day term: unearned = 36500 * 139 / 365.
        returns = [
            e for e in fx.policy_ledger(bundle["policy"]["id"])
            if e["entry_kind"] == "RETURN_PRO_RATA"
        ]
        assert len(returns) == 1 and returns[0]["amount_cents"] == -13900, (
            f"expected one RETURN_PRO_RATA of -13900, got {returns}"
        )

        report = fx.find_report(bundle["profile"]["id"], "2026-08")
        assert report["status"] == "OPEN"
        assert report["cancellation_count"] == 1


class TestReturnPremiumVariants:
    def test_pro_rata_returns_full_unearned_premium(self, api):
        """PRD §3.3: "`SHORT_RATE` applies only when the ground is
        `INSURED_REQUEST` and the profile's `short_rate_penalty_pct` is greater
        than zero; `PRO_RATA` applies to every insurer-initiated ground, and to
        insured-requested cancellations in states whose penalty fraction is
        0.0."
        PRD §3.4: "The unearned premium is the `total_premium_cents`
        multiplied by the share of the term remaining — term length minus
        elapsed days, divided by term length — rounded half-up to a whole
        cent. Under `PRO_RATA`, that unearned figure is the refund."

        Design: Difficulty/dual_variant_calc/return_premium_pro_rata_vs_short_rate_same_inputs
        """
        bundle = cancel_policy_effective(
            "CA",
            request_clock="2026-06-01T00:00:00Z",
            scheduled_effective_date="2026-07-02",
            mailed_on_date="2026-06-01",
            ground_code="INSURED_REQUEST",
            premium_cents=120000,
            profile_over={"short_rate_penalty_pct": 0.0},
            policy_number="P-CA-1",
        )
        case = bundle["case"]
        assert case["status"] == "EFFECTIVE"
        assert case["return_method"] == "PRO_RATA"
        # Elapsed 182 days of 365: unearned = round_half_up(120000 * 183 / 365).
        assert case["return_premium_cents"] == 60164

        returns = [
            e for e in fx.policy_ledger(bundle["policy"]["id"])
            if e["entry_kind"] == "RETURN_PRO_RATA"
        ]
        assert len(returns) == 1 and returns[0]["amount_cents"] == -60164

    def test_short_rate_withholds_penalty_fraction(self, api):
        """PRD §3.3: "`SHORT_RATE` applies only when the ground is
        `INSURED_REQUEST` and the profile's `short_rate_penalty_pct` is greater
        than zero; `PRO_RATA` applies to every insurer-initiated ground, and to
        insured-requested cancellations in states whose penalty fraction is
        0.0."
        PRD §3.4: "Under `SHORT_RATE`, the unearned figure is multiplied by
        one minus the profile's `short_rate_penalty_pct`, and the product is
        rounded half-up to a whole cent a second time." Identical economics
        under the two methods diverge: "Identical inputs under `SHORT_RATE`
        always yield a strictly smaller refund than under `PRO_RATA`, so the
        pinned `return_method` matters to the cent."

        Design: Difficulty/dual_variant_calc/return_premium_pro_rata_vs_short_rate_same_inputs
        """
        bundle = cancel_policy_effective(
            "TX",
            request_clock="2026-06-01T00:00:00Z",
            scheduled_effective_date="2026-07-02",
            mailed_on_date="2026-06-01",
            ground_code="INSURED_REQUEST",
            premium_cents=120000,
            profile_over={"short_rate_penalty_pct": 0.10},
            policy_number="P-TX-1",
        )
        case = bundle["case"]
        assert case["status"] == "EFFECTIVE"
        assert case["return_method"] == "SHORT_RATE"
        # Same economics as the pro-rata variant (60164 unearned):
        # round_half_up(60164 * 0.9) = 54148 — strictly smaller.
        assert case["return_premium_cents"] == 54148
        assert case["return_premium_cents"] < 60164

        returns = [
            e for e in fx.policy_ledger(bundle["policy"]["id"])
            if e["entry_kind"] == "RETURN_SHORT_RATE"
        ]
        assert len(returns) == 1 and returns[0]["amount_cents"] == -54148


class TestDoubleRoundingOrder:
    def test_short_rate_result_reflects_pinned_rounding_order(self, api):
        """PRD §3.4: "The two roundings are mandatory and must occur in
        exactly this order — first the unearned premium, then the penalty;
        collapsing the arithmetic into a single rounding at the end is
        forbidden." Term 2026-03-01..2027-03-01, premium 73000, effective
        2026-06-15: unearned = round_half_up(73000 * 259 / 365) = 51800, then
        round_half_up(51800 * 0.75) = 38850.

        Design: Difficulty/combinatorial_formula/return_premium_double_rounding_order_pinned
        """
        bundle = cancel_policy_effective(
            "NM",
            request_clock="2026-05-20T00:00:00Z",
            scheduled_effective_date="2026-06-15",
            mailed_on_date="2026-05-20",
            ground_code="INSURED_REQUEST",
            premium_cents=73000,
            term_start="2026-03-01",
            term_end="2027-03-01",
            profile_over={"short_rate_penalty_pct": 0.25, "other_grounds_notice_days": 20},
            policy_number="P-SR-1",
        )
        case = bundle["case"]
        assert case["status"] == "EFFECTIVE"
        assert case["return_method"] == "SHORT_RATE"
        assert case["return_premium_cents"] == 38850

    def test_short_rate_ledger_entry_matches_finalized_amount(self, api):
        """PRD §2.9: "A cancellation that reaches effectiveness posts a
        `RETURN_PRO_RATA` or `RETURN_SHORT_RATE` entry — chosen by the case's
        pinned `return_method` — with a negative amount equal to the finalized
        `return_premium_cents`."

        Design: Difficulty/combinatorial_formula/return_premium_double_rounding_order_pinned
        """
        bundle = cancel_policy_effective(
            "NM",
            request_clock="2026-05-20T00:00:00Z",
            scheduled_effective_date="2026-06-15",
            mailed_on_date="2026-05-20",
            ground_code="INSURED_REQUEST",
            premium_cents=73000,
            term_start="2026-03-01",
            term_end="2027-03-01",
            profile_over={"short_rate_penalty_pct": 0.25, "other_grounds_notice_days": 20},
            policy_number="P-SR-1",
        )
        assert bundle["policy"]["status"] == "CANCELLED"
        returns = [
            e for e in fx.policy_ledger(bundle["policy"]["id"])
            if e["entry_kind"] == "RETURN_SHORT_RATE"
        ]
        assert len(returns) == 1 and returns[0]["amount_cents"] == -38850, (
            f"ledger must carry the finalized short-rate refund, got {returns}"
        )


class TestProRataKnownInputs:
    def test_return_premium_pro_rata_correct_result(self, api):
        """PRD §3.4: "The unearned premium is the `total_premium_cents`
        multiplied by the share of the term remaining — term length minus
        elapsed days, divided by term length — rounded half-up to a whole
        cent. Under `PRO_RATA`, that unearned figure is the refund." Term
        2026-01-01..2027-01-01, premium 36500, effective 2026-08-15: elapsed
        226, unearned = round_half_up(36500 * 139 / 365) = 13900.

        Design: Corner/calculations/return_premium_pro_rata_correct_result
        """
        bundle = cancel_policy_effective(
            "OK",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-15",
            mailed_on_date="2026-08-01",
            premium_cents=36500,
            policy_number="P-OK-1",
        )
        case = bundle["case"]
        assert case["return_method"] == "PRO_RATA"
        assert case["return_premium_cents"] == 13900
        assert bundle["policy"]["cancellation_effective_date"] == "2026-08-15"


class TestImmediateConsistency:
    def test_cascade_visible_in_immediately_following_reads(self, api):
        """PRD §2.4: "Advancing the clock is what makes time-borne rules
        execute. Each advance runs four scheduled sweeps in its wake: the
        cancellation effectiveness sweep, which moves eligible policies from
        `CANCEL_PENDING` to `CANCELLED`; the policy expiry sweep, which moves
        nonrenewed policies from `NONRENEWAL_PENDING` to `EXPIRED`; the
        reinstatement expiry sweep, which retires reinstatement requests whose
        windows have closed; and the lapse sweep, which recomputes the
        `lapse_flag` on cancelled policies." After the clock call returns, the
        policy, the case, and the ledger all reflect the cascade.

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_read
        """
        bundle = cancel_policy_effective(
            "FM",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-20",
            mailed_on_date="2026-08-01",
            premium_cents=36500,
            policy_number="P-FM-1",
        )
        policy = fx.get_policy(bundle["policy"]["id"])
        case = fx.get_cancellation_case(bundle["case"]["id"])
        ledger = fx.policy_ledger(bundle["policy"]["id"])

        assert policy["status"] == "CANCELLED"
        assert policy["cancellation_effective_date"] == "2026-08-20"
        assert case["status"] == "EFFECTIVE"

        by_kind = {}
        for entry in ledger:
            by_kind.setdefault(entry["entry_kind"], []).append(entry)
        assert any(e["amount_cents"] == 36500 for e in by_kind.get("WRITTEN", []))
        # Elapsed 231 days: unearned = round_half_up(36500 * 134 / 365) = 13400.
        assert any(e["amount_cents"] == -13400 for e in by_kind.get("RETURN_PRO_RATA", []))
