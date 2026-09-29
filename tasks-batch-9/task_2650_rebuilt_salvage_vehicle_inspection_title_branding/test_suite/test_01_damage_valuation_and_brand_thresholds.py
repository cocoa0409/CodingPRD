"""Damage-to-value valuation, the basis variant that picks the denominator, and the
salvage-brand threshold that decides whether a wreck is branded at all.

Two carrier evaluations carrying byte-identical money can end up on opposite sides of
the statutory brand, either because the basis code shrank the denominator or because
the ratio landed one ten-thousandth away from the threshold.
"""

import pytest

from test_helpers import (
    BRAND_SEVERITY,
    assert_damage_ratio_precision,
    assert_damage_report,
    assert_title_record,
    file_damage_report,
    issue_salvage_title,
    read_damage_report,
    read_title,
    read_vehicle,
    register_vehicle,
)


class TestDamageBasisVariant:
    """The same repair estimate and actual cash value under the two basis codes."""

    def test_gross_estimate_basis_leaves_a_seventy_four_percent_wreck_unbranded(self):
        """A gross-basis evaluation divides by the actual cash value alone and earns no brand.

        PRD: "In either case `damage_ratio` is `repair_estimate_cents` divided by the chosen denominator, rounded half up to four decimal places."

        Design: Difficulty/dual_variant_calc/damage_basis_variant_flips_recommended_brand_on_identical_damage
        """
        vehicle = register_vehicle()
        report = file_damage_report(
            vehicle["id"],
            basis_code="GROSS_ESTIMATE",
            acv_cents=1_000_000,
            repair_estimate_cents=740_000,
            damage_type="COLLISION",
            odometer_reading_miles=64_000,
            report_effective_at="2026-07-15T00:00:00Z",
            total_loss_declared=True,
        )

        assert_damage_report(report)
        assert_damage_ratio_precision(report["damage_ratio"])
        assert report["damage_ratio"] == pytest.approx(0.7400, abs=1e-6), (
            f"740000 over 1000000 must publish 0.7400, got {report['damage_ratio']}"
        )
        assert report["recommended_brand_code"] == "NONE", (
            "a 0.7400 ratio sits below the salvage threshold, so the recommendation must be "
            f"NONE, got {report['recommended_brand_code']}"
        )
        assert report["basis_code"] == "GROSS_ESTIMATE", (
            f"the filed basis must be preserved, got {report['basis_code']}"
        )
        reread = read_damage_report(report["id"])
        assert reread["damage_ratio"] == pytest.approx(0.7400, abs=1e-6), (
            f"the published ratio must survive a re-read, got {reread['damage_ratio']}"
        )
        assert reread["recommended_brand_code"] == "NONE", (
            f"the recommendation must survive a re-read, got {reread['recommended_brand_code']}"
        )

    def test_net_of_salvage_basis_brands_the_identical_damage_salvage(self):
        """Retained salvage value shrinks the denominator and pushes the same damage over the line.

        PRD: "Under the net-of-salvage basis, declared as `NET_OF_SALVAGE`, the denominator is `acv_cents` reduced by `salvage_retention_cents`; because that denominator is smaller, the same repair estimate and the same actual cash value produce a strictly higher ratio, and a vehicle that would have earned no brand at all under the gross basis can be branded `SALVAGE` under the net basis with no change whatsoever in the underlying damage."

        Design: Difficulty/dual_variant_calc/damage_basis_variant_flips_recommended_brand_on_identical_damage
        """
        gross_vehicle = register_vehicle()
        net_vehicle = register_vehicle()
        gross_report = file_damage_report(
            gross_vehicle["id"],
            basis_code="GROSS_ESTIMATE",
            acv_cents=1_000_000,
            repair_estimate_cents=740_000,
            damage_type="COLLISION",
            odometer_reading_miles=64_000,
            report_effective_at="2026-07-15T00:00:00Z",
            total_loss_declared=True,
        )
        net_report = file_damage_report(
            net_vehicle["id"],
            basis_code="NET_OF_SALVAGE",
            acv_cents=1_000_000,
            repair_estimate_cents=740_000,
            salvage_retention_cents=100_000,
            damage_type="COLLISION",
            odometer_reading_miles=64_000,
            report_effective_at="2026-07-15T00:00:00Z",
            total_loss_declared=True,
        )

        assert_damage_report(net_report)
        assert_damage_ratio_precision(net_report["damage_ratio"])
        assert net_report["damage_ratio"] == pytest.approx(0.8222, abs=1e-6), (
            "740000 over a denominator of 1000000 less 100000 must publish 0.8222, got "
            f"{net_report['damage_ratio']}"
        )
        assert net_report["recommended_brand_code"] == "SALVAGE", (
            "a 0.8222 ratio is at or above the salvage threshold, so the recommendation must be "
            f"SALVAGE, got {net_report['recommended_brand_code']}"
        )
        assert net_report["salvage_retention_cents"] == 100_000, (
            f"the retained salvage value must be recorded, got {net_report['salvage_retention_cents']}"
        )
        assert gross_report["acv_cents"] == net_report["acv_cents"], (
            "the two evaluations must carry identical actual cash values"
        )
        assert gross_report["repair_estimate_cents"] == net_report["repair_estimate_cents"], (
            "the two evaluations must carry identical repair estimates"
        )
        assert gross_report["recommended_brand_code"] == "NONE", (
            "the gross-basis sibling on identical money must stay unbranded, got "
            f"{gross_report['recommended_brand_code']}"
        )
        assert net_report["damage_ratio"] > gross_report["damage_ratio"], (
            f"the net basis must produce the strictly higher ratio: {net_report['damage_ratio']} "
            f"is not above {gross_report['damage_ratio']}"
        )

    def test_gross_estimate_basis_ignores_the_retained_salvage_value_entirely(self):
        """A retention figure filed alongside a gross-basis evaluation changes nothing.

        PRD: "Under the gross-estimate basis, declared as `GROSS_ESTIMATE`, the denominator is `acv_cents` alone and `salvage_retention_cents` is ignored entirely."

        Design: Difficulty/dual_variant_calc/damage_basis_variant_flips_recommended_brand_on_identical_damage
        """
        vehicle = register_vehicle()
        report = file_damage_report(
            vehicle["id"],
            basis_code="GROSS_ESTIMATE",
            acv_cents=1_000_000,
            repair_estimate_cents=740_000,
            salvage_retention_cents=100_000,
            damage_type="COLLISION",
            odometer_reading_miles=64_000,
            report_effective_at="2026-07-15T00:00:00Z",
            total_loss_declared=True,
        )

        assert report["damage_ratio"] == pytest.approx(0.7400, abs=1e-6), (
            "the gross basis must divide by the actual cash value alone and publish 0.7400, got "
            f"{report['damage_ratio']}"
        )
        assert report["recommended_brand_code"] == "NONE", (
            "ignoring the retention keeps the recommendation at NONE, got "
            f"{report['recommended_brand_code']}"
        )
        assert report["salvage_retention_cents"] == 100_000, (
            "the retention is still recorded on the filed document, got "
            f"{report['salvage_retention_cents']}"
        )
        assert report["damage_ratio"] != pytest.approx(0.8222, abs=1e-6), (
            "the gross basis must not use the reduced denominator, got "
            f"{report['damage_ratio']}"
        )


class TestSalvageThresholdBoundary:
    """The salvage threshold at four-decimal precision, from both sides."""

    def test_ratio_of_exactly_the_salvage_threshold_brands_the_title_salvage(self):
        """A ratio landing exactly on the threshold brands, and the brand reaches the title.

        PRD: "All three thresholds are inclusive — a depth of exactly 46 centimetres brands `FLOOD`, a ratio of exactly 1.20 brands `NON_REPAIRABLE`, and a ratio of exactly 0.75 brands `SALVAGE`."

        Design: Difficulty/boundary_precision_check/damage_ratio_exactly_at_salvage_threshold_brands_but_one_ten_thousandth_below_does_not
        """
        vehicle = register_vehicle()
        report = file_damage_report(
            vehicle["id"],
            basis_code="GROSS_ESTIMATE",
            acv_cents=1_000_000,
            repair_estimate_cents=750_000,
            damage_type="COLLISION",
            odometer_reading_miles=64_000,
            report_effective_at="2026-07-20T00:00:00Z",
            total_loss_declared=True,
        )

        assert_damage_ratio_precision(report["damage_ratio"])
        assert report["damage_ratio"] == pytest.approx(0.7500, abs=1e-6), (
            f"750000 over 1000000 must publish 0.7500, got {report['damage_ratio']}"
        )
        assert report["recommended_brand_code"] == "SALVAGE", (
            "a ratio of exactly 0.7500 must brand SALVAGE, got "
            f"{report['recommended_brand_code']}"
        )

        title = issue_salvage_title(vehicle["id"], report["id"], owner_name="Ada Reyes")
        assert_title_record(title)
        assert title["brand_code"] == "SALVAGE", (
            f"the title must take the recommended brand, got {title['brand_code']}"
        )
        assert title["brand_severity"] == BRAND_SEVERITY["SALVAGE"], (
            f"a SALVAGE title publishes severity {BRAND_SEVERITY['SALVAGE']}, got "
            f"{title['brand_severity']}"
        )
        assert title["is_current"] is True, "the first title on a vehicle is the current one"
        assert title["transfer_sequence"] == 0, (
            f"the first title ever issued carries sequence 0, got {title['transfer_sequence']}"
        )

        subject = read_vehicle(vehicle["id"])
        assert subject["active_brand_code"] == "SALVAGE", (
            "the vehicle's active brand follows its current title, got "
            f"{subject['active_brand_code']}"
        )
        assert "SALVAGE" in subject["brand_history"], (
            f"the brand history must record SALVAGE, got {subject['brand_history']}"
        )

    def test_ratio_one_ten_thousandth_below_the_threshold_earns_no_brand(self):
        """One ten-thousandth short of the threshold leaves the title and the vehicle unbranded.

        PRD: "Rung three: otherwise, if `damage_ratio` is at least 0.75, the recommendation is `SALVAGE`."

        Design: Difficulty/boundary_precision_check/damage_ratio_exactly_at_salvage_threshold_brands_but_one_ten_thousandth_below_does_not
        """
        vehicle = register_vehicle()
        report = file_damage_report(
            vehicle["id"],
            basis_code="GROSS_ESTIMATE",
            acv_cents=1_000_000,
            repair_estimate_cents=749_900,
            damage_type="COLLISION",
            odometer_reading_miles=64_000,
            report_effective_at="2026-07-20T00:00:00Z",
            total_loss_declared=True,
        )

        assert_damage_ratio_precision(report["damage_ratio"])
        assert report["damage_ratio"] == pytest.approx(0.7499, abs=1e-6), (
            f"749900 over 1000000 must publish 0.7499, got {report['damage_ratio']}"
        )
        assert report["recommended_brand_code"] == "NONE", (
            "a ratio of 0.7499 is below the salvage threshold, so the recommendation must be "
            f"NONE, got {report['recommended_brand_code']}"
        )

        title = issue_salvage_title(vehicle["id"], report["id"], owner_name="Ben Ortiz")
        assert_title_record(title)
        assert title["brand_code"] == "NONE", (
            f"an unbranded recommendation must mint an unbranded title, got {title['brand_code']}"
        )
        assert title["brand_severity"] == BRAND_SEVERITY["NONE"], (
            f"an unbranded title publishes severity 0, got {title['brand_severity']}"
        )
        assert read_title(title["id"])["brand_code"] == "NONE", (
            "the unbranded brand must survive a re-read of the title"
        )

        subject = read_vehicle(vehicle["id"])
        assert subject["active_brand_code"] == "NONE", (
            f"the vehicle must stay unbranded, got {subject['active_brand_code']}"
        )
        assert subject["brand_history"] == [], (
            f"an unbranded chain records no history, got {subject['brand_history']}"
        )
