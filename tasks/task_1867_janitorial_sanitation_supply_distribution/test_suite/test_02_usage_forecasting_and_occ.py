"""Usage capture, dual-variant forecasting, replenishment boundary, and the
forecast-profile optimistic concurrency control."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_forecast_profile,
    create_forecast_profile,
    create_usage_record,
    recompute_profile,
    setup_facility_with_product,
    setup_profile_with_usage,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


def _setup_dual_variant_scenario(api):
    """One POSTED record of 90 units (June) and one SUBMITTED record of 180
    units (July); profile with horizon 30, safety stock 5, on-hand 20."""
    facility, product = setup_facility_with_product(
        facility_name="Fac A", base_price_cents=1200)
    create_usage_record(facility, product, quantity_used=90,
                        period_start="2026-06-01T00:00:00Z",
                        period_end="2026-06-30T00:00:00Z", post=True)
    create_usage_record(facility, product, quantity_used=180,
                        period_start="2026-07-01T00:00:00Z",
                        period_end="2026-07-31T00:00:00Z",
                        source="AUTO_DISPENSER")
    profile = create_forecast_profile(facility, product, horizon_days=30,
                                      safety_stock=5, current_on_hand=20)
    return facility, product, profile


class TestDualVariantForecast:
    def test_usage_forecast_final_counts_posted_only(self, api):
        """PRD: "Under the `FINAL` variant only `POSTED` records count, giving
        the audited view"
        PRD: "The `avg_daily_usage` is the sum of `quantity_used` across
        included records divided by 90 — the divisor is always 90 regardless of
        how much of the window the records actually cover — rounded half up to
        four decimal places. From that average the engine derives
        `reorder_point` as the average daily usage multiplied by the 7-day lead
        time, rounded up to the next whole unit, plus `safety_stock`;
        `recommended_qty` as the larger of zero and the horizon demand (the
        average daily usage multiplied by `horizon_days`, rounded up to whole
        units) minus `current_on_hand`"
        PRD: "The recompute stamps `variant_used` with the variant just run"

        Design: Difficulty/dual_variant_calc/usage_forecast_provisional_vs_final
        """
        _facility, _product, profile = _setup_dual_variant_scenario(api)
        data = validate_success(
            api.recompute_forecast_profile(profile["id"], "FINAL", ADMIN))
        assert data["variant_used"] == "FINAL"
        assert data["avg_daily_usage"] == 1.0, (
            f"FINAL average is 90/90 = 1.0, got {data['avg_daily_usage']}")
        assert data["reorder_point"] == 12, (
            "ceil(1.0 * 7) + 5 = 12")
        assert data["recommended_qty"] == 10, (
            "max(0, ceil(1.0 * 30) - 20) = 10")
        assert data["replenishment_recommended"] is False, (
            "20 <= 12 is false")

    def test_usage_forecast_provisional_includes_submitted(self, api):
        """PRD: "under `PROVISIONAL` both `SUBMITTED` and `POSTED` records
        count, giving the operator's forward-looking view, so identical raw
        data yields a smaller `FINAL` average whenever unposted records exist."
        PRD: "The `avg_daily_usage` is the sum of `quantity_used` across
        included records divided by 90 — the divisor is always 90 regardless of
        how much of the window the records actually cover — rounded half up to
        four decimal places."
        PRD: "`replenishment_recommended`, which is true whenever
        `current_on_hand` is less than or equal to `reorder_point` — equality
        triggers the recommendation."

        Design: Difficulty/dual_variant_calc/usage_forecast_provisional_vs_final
        """
        _facility, _product, profile = _setup_dual_variant_scenario(api)
        data = validate_success(
            api.recompute_forecast_profile(profile["id"], "PROVISIONAL",
                                           ADMIN))
        assert data["variant_used"] == "PROVISIONAL"
        assert data["avg_daily_usage"] == 3.0, (
            f"PROVISIONAL average is 270/90 = 3.0, got {data['avg_daily_usage']}")
        assert data["reorder_point"] == 26, "ceil(3.0 * 7) + 5 = 26"
        assert data["recommended_qty"] == 70, (
            "max(0, ceil(3.0 * 30) - 20) = 70")
        assert data["replenishment_recommended"] is True, "20 <= 26 is true"


class TestReplenishmentBoundary:
    def test_replenishment_triggers_at_equality(self, api):
        """PRD: "`replenishment_recommended`, which is true whenever
        `current_on_hand` is less than or equal to `reorder_point` — equality
        triggers the recommendation."
        PRD: "From that average the engine derives `reorder_point` as the
        average daily usage multiplied by the 7-day lead time, rounded up to
        the next whole unit, plus `safety_stock`"

        Design: Difficulty/boundary_precision_check/replenishment_triggers_at_equality
        """
        _facility, _product, profile = setup_profile_with_usage(
            quantity_posted=90, safety_stock=0, current_on_hand=7)
        data = validate_success(
            api.recompute_forecast_profile(profile["id"], "FINAL", ADMIN))
        assert data["reorder_point"] == 7, "ceil(1.0 * 7) + 0 = 7"
        assert data["replenishment_recommended"] is True, (
            "7 <= 7: equality triggers the recommendation")

    def test_replenishment_not_triggered_one_unit_above(self, api):
        """PRD: "`replenishment_recommended`, which is true whenever
        `current_on_hand` is less than or equal to `reorder_point` — equality
        triggers the recommendation."
        PRD: "A `DistributorAdmin` may patch any of those three tunables, but
        only under the optimistic-concurrency rule of §2.8: the request must
        carry `expected_forecast_profile_version` matching the profile's
        current `version`"

        Design: Difficulty/boundary_precision_check/replenishment_triggers_at_equality
        """
        _facility, _product, profile = setup_profile_with_usage(
            quantity_posted=90, safety_stock=0, current_on_hand=7)
        recomputed = validate_success(
            api.recompute_forecast_profile(profile["id"], "FINAL", ADMIN))
        assert recomputed["reorder_point"] == 7
        patched = validate_success(api.patch_forecast_profile(
            profile["id"],
            {"current_on_hand": 8,
             "expected_forecast_profile_version": recomputed["version"]},
            ADMIN))
        assert patched["current_on_hand"] == 8
        data = validate_success(
            api.recompute_forecast_profile(profile["id"], "FINAL", ADMIN))
        assert data["reorder_point"] == 7
        assert data["replenishment_recommended"] is False, (
            "8 <= 7 is false")


class TestForecastProfileOcc:
    def test_occ_stale_patch_returns_412(self, api):
        """PRD: "A request to that endpoint must carry
        `expected_forecast_profile_version`, a non-optional input field holding
        the `version` of the ForecastProfile the client last observed. If
        another writer has advanced the profile's `version` since that
        observation, the update is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD: "a stale value draws `ERR_STALE_VERSION`, and a successful patch
        increments the `version`."

        Design: Corner/cross_cutting_layers/occ_stale_patch_returns_412
        """
        _facility, _product, profile = setup_profile_with_usage(
            quantity_posted=90, current_on_hand=10)
        observed_version = profile["version"]

        first = validate_success(api.patch_forecast_profile(
            profile["id"],
            {"safety_stock": 3,
             "expected_forecast_profile_version": observed_version},
            ADMIN))
        assert first["version"] == observed_version + 1, (
            "A successful patch increments the version")
        assert first["safety_stock"] == 3

        resp = api.patch_forecast_profile(
            profile["id"],
            {"safety_stock": 9,
             "expected_forecast_profile_version": observed_version},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        after = validate_success(
            api.get_forecast_profile(profile["id"], ADMIN))
        assert after["safety_stock"] == 3, (
            "The stale patch leaves the first writer's value in place")
        assert after["version"] == observed_version + 1
