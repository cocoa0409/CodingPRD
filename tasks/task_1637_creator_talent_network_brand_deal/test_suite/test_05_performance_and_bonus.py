"""Performance reporting, bonus tiers, and the engagement kicker (PRD §3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_performance_report,
    create_performance_report_payload,
    finalize_report_payload,
    get_deal,
    make_active_deal,
    validate_error,
    validate_success,
)

TM = TEST_USERS["talent_manager_headers"]
BM = TEST_USERS["brand_manager_headers"]


def _submit_report(api, deal_id, **overrides):
    """Submit a report with the deal's current version (OCC, PRD §2.7)."""
    version = get_deal(deal_id)["version"]
    return api.create_performance_report(
        deal_id, create_performance_report_payload(version, **overrides), BM
    )


class TestBonusDualVariant:
    def test_provisional_bonus_on_raw_metrics(self, api):
        """PRD §3.7: "The submission itself computes `provisional_bonus_cents`
        on the raw metrics — the optimistic PROVISIONAL variant of the bonus,
        which prices unaudited, possibly bot-inflated views."
        PRD §3.7: "failing that, at least 1,000,000 views pays 100,000
        cents"
        PRD §3.7: "When that rate reaches at least 400 basis points, the
        tier bonus is multiplied by 1.25 and rounded half up to whole cents"

        1,000,000 raw views -> tier 2 (100,000); 45,000 engagements ->
        450bps -> kicker: 100,000 x 1.25 = 125,000.

        Design: Difficulty/dual_variant_calc/bonus_provisional_vs_final_audit_adjusted
        """
        ns = make_active_deal(brief_overrides={"usage_rights_days": 45})
        report = validate_success(
            _submit_report(api, ns.deal_id, views=1000000, likes=30000,
                           comments=10000, shares=5000),
            201,
        )
        assert_performance_report(report)
        assert report["provisional_bonus_cents"] == 125000
        assert report["status"] == "REPORTED"
        assert report.get("final_bonus_cents") is None, (
            "PRD §3.7: final_bonus_cents is null until finalization"
        )

    def test_final_bonus_on_audited_metrics(self, api):
        """PRD §3.7: "The report moves from `REPORTED` to terminal `FINAL`,
        the FINAL bonus variant runs the identical tier-and-kicker formula on
        `audited_views` and `audited_engagements`, and the result lands on
        `final_bonus_cents`, which is null until this moment. When the audit
        discounts views across a tier boundary, the FINAL figure lands below
        the PROVISIONAL one."
        PRD §3.7: "Finalization also recomputes the deal's
        `bonus_accrued_cents`: the sum of `final_bonus_cents` across the
        deal's `FINAL` reports that have not yet been billed on a non-`VOID`
        invoice"

        Audited 600,000 views drops a tier (25,000); 24,000 audited
        engagements is exactly 400bps -> kicker: 25,000 x 1.25 = 31,250.

        Design: Difficulty/dual_variant_calc/bonus_provisional_vs_final_audit_adjusted
        """
        ns = make_active_deal(brief_overrides={"usage_rights_days": 45})
        report = validate_success(
            _submit_report(api, ns.deal_id, views=1000000, likes=30000,
                           comments=10000, shares=5000),
            201,
        )
        finalized = validate_success(api.finalize_performance_report(
            report["id"],
            finalize_report_payload(audited_views=600000,
                                    audited_engagements=24000),
            BM,
        ))
        assert finalized["status"] == "FINAL"
        assert finalized["provisional_bonus_cents"] == 125000
        assert finalized["final_bonus_cents"] == 31250, (
            "audit-adjusted FINAL variant lands below the optimistic "
            "PROVISIONAL variant"
        )
        deal = get_deal(ns.deal_id)
        assert deal["bonus_accrued_cents"] == 31250


class TestBonusTierBoundary:
    def test_views_999999_stays_tier1(self, api):
        """PRD §3.7: "failing that, at least 250,000 views pays 25,000
        cents; below every tier it pays zero."
        PRD §3.7: "The view tier pays the highest qualifying tier only,
        never cumulatively"

        999,999 views (< 1,000,000) pays the 25,000-cent tier; 1,000 likes on
        999,999 views is a 10bps engagement rate, below the 400bps kicker, so
        the tier bonus stands unchanged.

        Design: Difficulty/boundary_precision_check/bonus_tier_boundary_exact_million
        """
        ns = make_active_deal()
        report = validate_success(
            _submit_report(api, ns.deal_id, views=999999, likes=1000,
                           comments=0, shares=0),
            201,
        )
        assert report["provisional_bonus_cents"] == 25000, (
            "999,999 views stays in tier 1"
        )

    def test_views_exactly_1000000_qualifies_tier2(self, api):
        """PRD §3.7: "failing that, at least 1,000,000 views pays 100,000
        cents"
        PRD §3.7: "the window including its start instant and excluding its
        end"

        Exactly 1,000,000 views qualifies tier 2 (>= boundary). The second
        report's period starts exactly when the first ends, so neither
        supersedes the other.

        Design: Difficulty/boundary_precision_check/bonus_tier_boundary_exact_million
        """
        ns = make_active_deal()
        r1 = validate_success(
            _submit_report(api, ns.deal_id, views=999999, likes=1000,
                           comments=0, shares=0,
                           period_start="2026-08-01T00:00:00Z",
                           period_end="2026-08-15T00:00:00Z"),
            201,
        )
        r2 = validate_success(
            _submit_report(api, ns.deal_id, views=1000000, likes=1000,
                           comments=0, shares=0,
                           period_start="2026-08-15T00:00:00Z",
                           period_end="2026-09-01T00:00:00Z"),
            201,
        )
        assert r2["provisional_bonus_cents"] == 100000, (
            "exactly 1,000,000 views qualifies tier 2"
        )
        reports = validate_success(
            api.list_deal_performance_reports(ns.deal_id, BM)
        )
        by_id = {r["id"]: r for r in reports}
        assert by_id[r1["id"]]["status"] == "REPORTED", (
            "adjacent periods (end-exclusive) do not overlap, so no supersede"
        )
        assert by_id[r2["id"]]["status"] == "REPORTED"


class TestBonusFloorAndKicker:
    def test_bonus_zero_below_first_tier(self, api):
        """PRD §3.7: "below every tier it pays zero."

        249,999 views (one below tier 1) earns exactly 0 even with maximal
        engagement — the kicker multiplies a zero tier.

        Design: Corner/calculations/bonus_zero_below_first_tier
        """
        ns = make_active_deal()
        report = validate_success(
            _submit_report(api, ns.deal_id, views=249999, likes=50000,
                           comments=0, shares=0),
            201,
        )
        assert report["provisional_bonus_cents"] == 0

    def test_engagement_kicker_exact_400bps(self, api):
        """PRD §3.7: "The engagement rate in basis points is zero when the
        measured view count is zero, and otherwise is the sum of likes,
        comments, and shares multiplied by ten thousand and divided by the
        view count, rounded half down to a whole basis point. When that rate
        reaches at least 400 basis points, the tier bonus is multiplied by
        1.25 and rounded half up to whole cents; otherwise the tier bonus
        stands unchanged."

        12,000 engagements on 300,000 views is exactly 400bps -> 31,250;
        11,980 is 399.33bps, which rounds half down to 399bps -> 25,000.

        Design: Corner/calculations/engagement_kicker_exact_400bps
        """
        ns = make_active_deal()
        r1 = validate_success(
            _submit_report(api, ns.deal_id, views=300000, likes=12000,
                           comments=0, shares=0,
                           period_start="2026-08-01T00:00:00Z",
                           period_end="2026-08-15T00:00:00Z"),
            201,
        )
        assert r1["provisional_bonus_cents"] == 31250, (
            "exactly 400bps applies the 1.25 kicker to the 25,000 tier"
        )
        r2 = validate_success(
            _submit_report(api, ns.deal_id, views=300000, likes=11980,
                           comments=0, shares=0,
                           period_start="2026-08-15T00:00:00Z",
                           period_end="2026-09-01T00:00:00Z"),
            201,
        )
        assert r2["provisional_bonus_cents"] == 25000, (
            "399bps (rounded half down) leaves the tier bonus unchanged"
        )


class TestReportPeriodRules:
    def test_duplicate_final_report_period_rejected(self, api):
        """PRD §3.7: "A new report whose window overlaps — any intersection
        at all — a `FINAL` report of the same deal is rejected with
        `ERR_DUPLICATE_REPORT_PERIOD`."

        Design: Corner/validations/duplicate_final_report_period_rejected
        """
        ns = make_active_deal()
        r1 = validate_success(
            _submit_report(api, ns.deal_id, views=100000, likes=1000),
            201,
        )
        validate_success(api.finalize_performance_report(
            r1["id"], finalize_report_payload(100000, 1000), BM))
        res = _submit_report(api, ns.deal_id, views=50000, likes=500,
                             period_start="2026-08-10T00:00:00Z",
                             period_end="2026-08-20T00:00:00Z")
        validate_error(res, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD, 422)

    def test_report_submit_stale_deal_version_rejected(self, api):
        """PRD §2.7: "Submitting a performance report requires
        `expected_deal_version` on the same terms: submission supersedes any
        `REPORTED` report with an overlapping period, so a stale writer would
        supersede reports it never observed. A mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/report_submit_stale_deal_version_rejected
        """
        ns = make_active_deal()
        stale_version = ns.deal["version"]
        r1 = validate_success(
            api.create_performance_report(
                ns.deal_id,
                create_performance_report_payload(stale_version,
                                                  views=100000, likes=1000),
                BM,
            ),
            201,
        )
        # The first submission bumped the deal version; reusing it is stale.
        res = api.create_performance_report(
            ns.deal_id,
            create_performance_report_payload(
                stale_version, views=200000, likes=2000,
                period_start="2026-08-05T00:00:00Z",
                period_end="2026-08-20T00:00:00Z"),
            BM,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)
        reports = validate_success(
            api.list_deal_performance_reports(ns.deal_id, BM)
        )
        by_id = {r["id"]: r for r in reports}
        assert by_id[r1["id"]]["status"] == "REPORTED", (
            "the stale write did not supersede the existing report"
        )

    def test_report_supersede_on_overlap(self, api):
        """PRD §3.7: "A new report whose window overlaps a still-`REPORTED`
        report of the same deal supersedes it: the prior report moves to
        terminal `SUPERSEDED` and its `version` advances."

        Design: Corner/cross_cutting_layers/report_supersede_on_overlap
        """
        ns = make_active_deal()
        r1 = validate_success(
            _submit_report(api, ns.deal_id, views=100000, likes=1000,
                           period_start="2026-08-01T00:00:00Z",
                           period_end="2026-08-15T00:00:00Z"),
            201,
        )
        r2 = validate_success(
            _submit_report(api, ns.deal_id, views=200000, likes=2000,
                           period_start="2026-08-10T00:00:00Z",
                           period_end="2026-08-20T00:00:00Z"),
            201,
        )
        reports = validate_success(
            api.list_deal_performance_reports(ns.deal_id, BM)
        )
        by_id = {r["id"]: r for r in reports}
        assert by_id[r1["id"]]["status"] == "SUPERSEDED"
        assert by_id[r2["id"]]["status"] == "REPORTED"
