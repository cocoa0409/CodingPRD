"""HQLA valuation: dual-variant divergence and pinned rounding order.

Difficulty instances: hqla_baseline_vs_stress_haircut_divergence,
hqla_per_asset_floor_then_sum_rounding_order.
Corner instance: asset_reprice_updates_hqla_summary.
"""
from test_helpers import (
    make_asset,
    make_scenario,
    reprice_asset_payload,
    validate_success,
)


def _inventory(api, ops_headers):
    """Two LEVEL_2B at 1000002 cents each plus one LEVEL_1 at 500000."""
    make_asset(asset_class="LEVEL_2B", reference="B1", market_value_cents=1_000_002)
    make_asset(asset_class="LEVEL_2B", reference="B2", market_value_cents=1_000_002)
    make_asset(asset_class="LEVEL_1", reference="C1", market_value_cents=500_000)


class TestHqlaDualVariant:
    def test_hqla_baseline_vs_stress_divergence(self, api, officer_headers):
        """PRD §3.3: "Two variants exist. The BASELINE variant applies the class
        haircut alone, with no add-on. The STRESS variant adds the referencing
        scenario's `level2_addon_bps` to the haircut of `LEVEL_2A` and
        `LEVEL_2B` assets only, so the same inventory values strictly lower
        whenever a Level 2 asset exists and the add-on is positive. A computed
        read returns both totals — `baseline_total_cents` and
        `stress_total_cents` — along with the `asset_count`, evaluated over
        exactly the `UNENCUMBERED` inventory under the scenario passed as
        `scenario_id`."

        Design: Difficulty/dual_variant_calc/hqla_baseline_vs_stress_haircut_divergence
        """
        make_scenario(name="Base", tier="BASELINE", level2_addon_bps=0)
        severe = make_scenario(
            name="Severe", tier="SEVERE", deposit_runoff_pct=25,
            wholesale_renewal_pct=0, level2_addon_bps=1000,
        )
        _inventory(api, None)

        data = validate_success(api.get_hqla_summary(severe["id"], officer_headers))
        # BASELINE: floor(1000002 * 0.75) = 750001 twice + 500000 = 2000002.
        assert data["baseline_total_cents"] == 2_000_002, (
            f"baseline total must be 2000002, got {data['baseline_total_cents']}"
        )
        # STRESS (addon 1000 -> 3500 bps on LEVEL_2B): floor(1000002 * 0.65) = 650001
        # twice + 500000 = 1800002.
        assert data["stress_total_cents"] == 1_800_002, (
            f"stress total must be 1800002, got {data['stress_total_cents']}"
        )
        assert data["asset_count"] == 3, f"asset_count must be 3, got {data['asset_count']}"
        assert data["baseline_total_cents"] != data["stress_total_cents"], (
            "identical inventory must value lower under the STRESS variant when a "
            "LEVEL_2 asset exists and the add-on is positive"
        )

    def test_hqla_divergence_vanishes_without_addon(self, api, officer_headers):
        """PRD §3.3: "The STRESS variant adds the referencing scenario's
        `level2_addon_bps` to the haircut of `LEVEL_2A` and `LEVEL_2B` assets
        only, so the same inventory values strictly lower whenever a Level 2
        asset exists and the add-on is positive."
        PRD §3.3: "The BASELINE variant applies the class haircut alone, with
        no add-on."

        Design: Difficulty/dual_variant_calc/hqla_baseline_vs_stress_haircut_divergence
        """
        base = make_scenario(name="Base", tier="BASELINE", level2_addon_bps=0)
        _inventory(api, None)
        data = validate_success(api.get_hqla_summary(base["id"], officer_headers))
        # With a zero add-on the variants coincide; LEVEL_2B floors still apply.
        assert data["baseline_total_cents"] == 2_000_002
        assert data["stress_total_cents"] == 2_000_002, (
            f"zero add-on means the variants coincide, got stress {data['stress_total_cents']}"
        )


class TestHqlaRoundingOrder:
    def test_hqla_per_asset_floor_then_sum(self, api, officer_headers, analyst_headers):
        """PRD §2.6: "Where a calculation aggregates per-item values, the floor
        is applied per item before summing — the rounding order is pinned,
        because flooring items individually and then summing produces a
        different total than summing first and flooring once."
        PRD §3.3: "Per asset, the adjusted value is the market value multiplied
        by the difference between ten thousand and the applicable total haircut
        in basis points, divided by ten thousand, and rounded down to whole
        cents — floored per asset before any summing begins."

        Design: Difficulty/combinatorial_formula/hqla_per_asset_floor_then_sum_rounding_order
        """
        base = make_scenario(name="Base", tier="BASELINE", level2_addon_bps=0)
        _inventory(api, None)
        data = validate_success(api.get_hqla_summary(base["id"], analyst_headers))
        # Per-asset floor: floor(1000002 * 7500 / 10000) = 750001 per LEVEL_2B;
        # 750001 + 750001 + 500000 = 2000002. Sum-then-floor (the rejected
        # order) would give 2000003.
        assert data["baseline_total_cents"] == 2_000_002, (
            f"per-asset floor then sum must give 2000002, got {data['baseline_total_cents']}"
        )
        assert data["baseline_total_cents"] != 2_000_003, (
            "sum-then-floor (2000003) is the rejected rounding order"
        )
        assert data["stress_total_cents"] == 2_000_002, (
            "BASELINE scenario has a zero add-on so the variants coincide"
        )

    def test_hqla_per_asset_floor_single_odd_cent_asset(self, api, officer_headers):
        """PRD §3.3: "Per asset, the adjusted value is the market value
        multiplied by the difference between ten thousand and the applicable
        total haircut in basis points, divided by ten thousand, and rounded
        down to whole cents — floored per asset before any summing begins."
        PRD §3.3: "zero for `LEVEL_1`, 1500 basis points (fifteen percent) for
        `LEVEL_2A`, and 2500 basis points (twenty-five percent) for `LEVEL_2B`".

        Design: Difficulty/combinatorial_formula/hqla_per_asset_floor_then_sum_rounding_order
        """
        base = make_scenario(name="Base", tier="BASELINE", level2_addon_bps=0)
        # One LEVEL_2B at an odd cent count: floor(1000001 * 7500 / 10000)
        # = floor(750000.75) = 750000 — the fractional cent is dropped by the
        # per-asset floor, never rounded half-up.
        make_asset(asset_class="LEVEL_2B", reference="D1", market_value_cents=1_000_001)
        # One LEVEL_2A at 1500 bps: floor(2000001 * 8500 / 10000)
        # = floor(1700000.85) = 1700000.
        make_asset(asset_class="LEVEL_2A", reference="D2", market_value_cents=2_000_001)
        data = validate_success(api.get_hqla_summary(base["id"], officer_headers))
        assert data["asset_count"] == 2
        assert data["baseline_total_cents"] == 2_450_000, (
            f"per-asset floors 750000 + 1700000 must total 2450000, "
            f"got {data['baseline_total_cents']}"
        )


class TestHqlaRepriceReconciliation:
    def test_asset_reprice_updates_hqla_summary(self, api, ops_headers, analyst_headers):
        """PRD §3.3: "Market repricing by `TreasuryOps` replaces an asset's
        `market_value_cents`, bumps the asset's `version` by one, and feeds all
        future haircut computations."

        Design: Corner/calculations/asset_reprice_updates_hqla_summary
        """
        base = make_scenario(name="Base", tier="BASELINE", level2_addon_bps=0)
        asset = make_asset(asset_class="LEVEL_2B", reference="B1", market_value_cents=1_000_000)

        first = validate_success(api.get_hqla_summary(base["id"], analyst_headers))
        assert first["baseline_total_cents"] == 750_000, (
            f"floor(1000000 * 0.75) = 750000, got {first['baseline_total_cents']}"
        )

        resp = api.reprice_liquid_asset(
            asset["id"], reprice_asset_payload(market_value_cents=2_000_000), ops_headers,
        )
        validate_success(resp)

        second = validate_success(api.get_hqla_summary(base["id"], analyst_headers))
        assert second["baseline_total_cents"] == 1_500_000, (
            f"floor(2000000 * 0.75) = 1500000 must be visible immediately, "
            f"got {second['baseline_total_cents']}"
        )
