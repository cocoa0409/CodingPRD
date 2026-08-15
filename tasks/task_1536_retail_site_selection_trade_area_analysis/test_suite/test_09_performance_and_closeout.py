"""Post-opening performance measurement: variance thresholds, miss cascades,
recovery, period sequencing, and close-out capital release (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_performance_snapshot,
    create_measuring_site,
    create_open_site,
    create_performance_snapshot_payload,
    create_qualified_market,
    create_site,
    create_underperforming_site,
    finalize_snapshot,
    record_snapshot,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]

# ANALOG roster netting exactly 1,200,000,000 (expected period sales
# 100,000,000 after the /12).
NET_1_2B_STORES = (("N1", "STANDARD", 1100000000), ("N2", "STANDARD", 1300000000))


class TestSnapshotMissCascade:
    """Two consecutive -2000 bp misses drive OPEN -> MEASURING ->
    UNDERPERFORMING; the forecast actualizes at the first finalize."""

    def test_first_finalize_actualizes_and_marks_miss(self, api):
        """PRD §3.9: "`expected_sales_cents` is the site's `ACTUALIZED`
        forecast's `net_annual_sales_cents` divided by twelve, rounded half-up
        to whole cents. `variance_bp` is the difference between
        `actual_sales_cents` and the expectation, multiplied by 10,000, divided
        by the expectation, rounded half-up to integer basis points."
        PRD §3.9: "The site's first `FINALIZED` snapshot moves it from `OPEN`
        to `MEASURING` and moves its `COMMITTEE_LOCKED` forecast to
        `ACTUALIZED`."
        PRD §3.9: "A variance of −2,000 basis points or worse — the boundary
        is inclusive, so exactly −2,000 counts — is a miss, and anything better
        resets the site's `consecutive_miss_count` to zero, while each miss
        increments it by one."

        Design: Difficulty/transitive_cascade/snapshot_miss_underperformance_cascade
        """
        ctx = create_open_site(stores=NET_1_2B_STORES)
        snap = record_snapshot(ctx["site"]["id"], 1, 80000000)
        finalized = finalize_snapshot(snap["id"])
        assert_performance_snapshot(finalized)
        # Forecast net 1,200,000,000 / 12 = 100,000,000 expected.
        assert finalized["expected_sales_cents"] == 100000000
        # (80000000 - 100000000) * 10000 / 100000000 = -2000 (a miss).
        assert finalized["variance_bp"] == -2000
        assert finalized["snapshot_status"] == "FINALIZED"
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["site_status"] == "MEASURING"
        assert site["consecutive_miss_count"] == 1
        forecast = validate_success(
            api.get_sales_forecast(ctx["forecast"]["id"], MANAGER)
        )
        assert forecast["forecast_status"] == "ACTUALIZED"

    def test_second_consecutive_miss_flips_underperforming(self, api):
        """PRD §3.9: "When the miss counter reaches two on a `MEASURING` site,
        the site degrades to `UNDERPERFORMING` — note it remains counted in the
        market's `open_store_count` while underperforming."
        PRD §2.9: "`open_store_count` is the number of the market's existing
        stores in `OPERATING` status plus the number of the market's sites in
        `OPEN`, `MEASURING`, or `UNDERPERFORMING` status."

        Design: Difficulty/transitive_cascade/snapshot_miss_underperformance_cascade
        """
        ctx = create_measuring_site(actual_sales_cents=80000000)
        snap2 = record_snapshot(ctx["site"]["id"], 2, 80000000)
        finalized2 = finalize_snapshot(snap2["id"])
        assert finalized2["variance_bp"] == -2000
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["consecutive_miss_count"] == 2
        assert site["site_status"] == "UNDERPERFORMING"
        market = validate_success(api.get_market(ctx["market"]["id"], ADMIN))
        # 2 OPERATING stores + this UNDERPERFORMING site.
        assert market["open_store_count"] == 3


class TestPerformanceRecovery:
    def test_performance_recovery_resets_miss_count(self, api):
        """PRD §3.9: "And recovery is symmetric: a `FINALIZED` snapshot whose
        variance is better than −2,000 basis points on an `UNDERPERFORMING`
        site restores it to `MEASURING`, the counter having reset to zero."

        Design: Corner/calculations/performance_recovery_resets_miss_count
        """
        ctx = create_underperforming_site()
        assert ctx["site"]["site_status"] == "UNDERPERFORMING"
        snap3 = record_snapshot(ctx["site"]["id"], 3, 100000000)
        finalized3 = finalize_snapshot(snap3["id"])
        assert finalized3["variance_bp"] == 0, (
            "actual equals the 100,000,000 expectation"
        )
        site = validate_success(api.get_site(ctx["site"]["id"], MANAGER))
        assert site["consecutive_miss_count"] == 0
        assert site["site_status"] == "MEASURING"


class TestSnapshotGates:
    def test_error_period_gap_on_first_snapshot(self, api):
        """PRD §3.9: "Periods are strictly sequential: the `period_index` must
        equal the site's current count of `FINALIZED` snapshots plus one, with
        no gaps and no replays, else `ERR_PERIOD_GAP`."

        Design: Corner/errors/error_period_gap_on_first_snapshot
        """
        ctx = create_open_site()
        resp = api.create_performance_snapshot(
            create_performance_snapshot_payload(site_id=ctx["site"]["id"],
                                                period_index=2),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_GAP)

    def test_error_site_not_open_for_snapshot(self, api):
        """PRD §3.9: "A `RealEstateManager` records a snapshot for a site in
        `OPEN`, `MEASURING`, or `UNDERPERFORMING` — any other stage is rejected
        with `ERR_SITE_NOT_OPEN`"

        Design: Corner/errors/error_site_not_open_for_snapshot
        """
        market = create_qualified_market(name="Metro E8")
        site = create_site(market["id"])
        resp = api.create_performance_snapshot(
            create_performance_snapshot_payload(site_id=site["id"]),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_OPEN)


class TestCloseOut:
    def test_closeout_from_measuring_releases_capital(self, api):
        """PRD §3.9: "When a store's story ends, the manager closes the site
        out: from `MEASURING` or `UNDERPERFORMING` the site moves to the
        terminal `CLOSED_OUT`, the market's `open_store_count` is decremented,
        the market's `committed_capex_cents` is reduced by the site's
        `build_cost_cents` as the capital is released, and the de-saturation
        check of §2.9 runs — a `SATURATED` market below target returns to
        `QUALIFIED`."

        Design: Corner/state_machines/closeout_from_measuring_releases_capital
        """
        ctx = create_measuring_site(actual_sales_cents=100000000)
        assert ctx["site"]["site_status"] == "MEASURING"
        closed = validate_success(api.close_out_site(ctx["site"]["id"], MANAGER))
        assert closed["site_status"] == "CLOSED_OUT"
        market = validate_success(api.get_market(ctx["market"]["id"], ADMIN))
        # The site drops out; the two OPERATING existing stores remain.
        assert market["open_store_count"] == 2
        assert market["committed_capex_cents"] == 0, (
            "500000000 released at close-out"
        )
