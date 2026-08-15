"""Recovery factor dual variants, dry-volume reconciliation, and byproduct ledger."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    create_completed_run, create_kiln_charge, run_kiln_cycle, stamp_package,
    start_charge, complete_charge,
    get_package, get_run, sell_byproduct, byproduct_inventory_map,
    create_byproduct_sale_payload,
    make_sales_rep_headers, make_grader_headers,
)


def _completed_run_with_packages(specs, scaled_mbf=100, **kwargs):
    return create_completed_run(specs, scaled_mbf=scaled_mbf, **kwargs)


class TestRecoveryDualVariant:
    def _scenario(self):
        """One DF load scaled 100; one package green 58.0; dried to measured 54.1."""
        run, packages = _completed_run_with_packages(
            [{"green_mbf": 58.0, "pieces": 500}], scaled_mbf=100,
            complete_overrides={"chip_tons": 20, "sawdust_tons": 10, "bark_tons": 8},
        )
        pkg_id = packages[0]["id"]
        charge = create_kiln_charge([pkg_id])
        run_kiln_cycle(charge["id"], [
            {"package_id": pkg_id, "exit_moisture_pct": 14.0, "measured_dry_mbf": 54.1},
        ])
        return run, pkg_id

    def test_provisional_recovery_computed_on_green_tally(self, api):
        """PRD Section 3.3: "Third, the run's `output_green_mbf` is computed as the sum of the `green_mbf` of all packages just created, and its provisional recovery is computed immediately: `recovery_pct_provisional` is `output_green_mbf` divided by `input_mbf`, multiplied by 100, rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/recovery_factor_provisional_vs_certified
        """
        run, _pkg_id = self._scenario()
        assert run["input_mbf"] == pytest.approx(100.0, abs=1e-6)
        assert run["output_green_mbf"] == pytest.approx(58.0, abs=1e-6)
        assert run["recovery_pct_provisional"] == pytest.approx(58.0, abs=1e-6), (
            f"round(58.0 / 100 * 100, 2) on green tally, got {run['recovery_pct_provisional']}"
        )

    def test_certified_recovery_computed_on_measured_dry_tally(self, api):
        """PRD Section 3.5: "When the condition first holds and on every subsequent change to the stamped set, the server recomputes `recovery_pct_certified` as the sum of the current `dry_mbf` of the run's packages in those three states, divided by the run's `input_mbf`, multiplied by 100, rounded half-up to 2 decimal places, and bumps the run's `version` with the recompute."
        PRD Section 3.5: "Because certified recovery uses post-shrink dry volumes, it is strictly lower than the provisional figure whenever any shrink has occurred — the gap between the two is the saw floor's honest yield report."

        Design: Difficulty/dual_variant_calc/recovery_factor_provisional_vs_certified
        """
        run, pkg_id = self._scenario()
        stamp_package(pkg_id, inspector_grade="NO_2", action="STAMP")
        after = get_run(run["id"])
        assert after["recovery_pct_certified"] == pytest.approx(54.1, abs=1e-6), (
            f"round(54.1 / 100 * 100, 2) on measured dry tally, got {after['recovery_pct_certified']}"
        )
        assert after["recovery_pct_certified"] != after["recovery_pct_provisional"], (
            "same run input, two valid algorithms, different results"
        )


class TestDryVolumeReconciliation:
    def _in_progress_charge(self):
        """One CEDAR package green 20.0 inside an IN_PROGRESS charge; clock 2026-08-02."""
        run, packages = create_completed_run(
            [{"species": "CEDAR", "green_mbf": 20.0}],
            scaled_mbf=50, price_per_mbf_cents=20000,
            load_overrides={"species": "CEDAR", "log_grade": "SAWLOG_2",
                            "supplier_name": "Cedar Rim LLC"},
        )
        pkg_id = packages[0]["id"]
        charge = create_kiln_charge([pkg_id], chamber="KILN_2", species="CEDAR")
        start_charge(charge["id"], scheduled_start="2026-08-02T00:00:00Z")
        return pkg_id, charge["id"]

    def test_dry_mbf_reads_species_estimate_before_measurement(self, api):
        """PRD Section 3.5: "At the moment a package is created by run completion, its `estimated_dry_mbf` is computed from the green tally using a species shrink constant: `green_mbf` multiplied by one minus the shrink fraction for the package's species, rounded half-up to 3 decimal places."
        PRD Section 3.5: "The shrink fractions are 0.06 for `DOUGLAS_FIR`, 0.07 for `PONDEROSA_PINE`, 0.08 for `HEMLOCK_FIR`, and 0.05 for `CEDAR`."

        Design: Difficulty/dual_variant_calc/dry_volume_estimated_vs_actual_reconciliation
        """
        pkg_id, _charge_id = self._in_progress_charge()
        before = get_package(pkg_id)
        # round(20.0 * (1 - 0.05), 3) = 19.0
        assert before["estimated_dry_mbf"] == pytest.approx(19.0, abs=1e-6)
        assert before["dry_mbf"] == pytest.approx(19.0, abs=1e-6), (
            f"until measured, dry_mbf is the estimate; got {before['dry_mbf']}"
        )
        assert before.get("actual_dry_mbf") is None

    def test_dry_mbf_reconciles_to_measured_actual(self, api):
        """PRD Section 3.5: "The estimate governs from creation until the kiln measures reality: whenever `actual_dry_mbf` has been recorded — at the completion of a charge the package passed — the package's `dry_mbf` is the actual figure; until then, `dry_mbf` is the estimate."

        Design: Difficulty/dual_variant_calc/dry_volume_estimated_vs_actual_reconciliation
        """
        pkg_id, charge_id = self._in_progress_charge()
        complete_charge(charge_id, [
            {"package_id": pkg_id, "exit_moisture_pct": 12.0, "measured_dry_mbf": 18.7},
        ], scheduled_end="2026-08-05T00:00:00Z")
        after = get_package(pkg_id)
        assert after["status"] == "DRY"
        assert after["actual_dry_mbf"] == pytest.approx(18.7, abs=1e-6)
        assert after["dry_mbf"] == pytest.approx(18.7, abs=1e-6), (
            f"measured actual replaces the estimate, got {after['dry_mbf']}"
        )


class TestCertifiedRecoveryCoverage:
    def test_certified_recovery_waits_for_full_stamp_coverage(self, api):
        """PRD Section 3.5: "The certified variant, `recovery_pct_certified`, becomes computable only when every package the run produced has reached `STAMPED`, `ALLOCATED`, or `SHIPPED` — until that moment it is null."

        Design: Corner/calculations/certified_recovery_waits_for_full_stamp_coverage
        """
        run, packages = create_completed_run(
            [{"green_mbf": 30.0, "pieces": 200}, {"green_mbf": 30.0, "pieces": 200}],
        )
        assert run["recovery_pct_provisional"] == pytest.approx(60.0, abs=1e-6)
        p1, p2 = packages[0]["id"], packages[1]["id"]
        charge = create_kiln_charge([p1, p2])
        run_kiln_cycle(charge["id"], [
            {"package_id": p1, "exit_moisture_pct": 14.0, "measured_dry_mbf": 28.0},
            {"package_id": p2, "exit_moisture_pct": 14.0, "measured_dry_mbf": 28.0},
        ])
        stamp_package(p1, inspector_grade="NO_2", action="STAMP")
        half = get_run(run["id"])
        assert half.get("recovery_pct_certified") is None, (
            f"p2 still DRY — input set incomplete, got {half.get('recovery_pct_certified')}"
        )
        stamp_package(p2, inspector_grade="NO_2", action="STAMP")
        full = get_run(run["id"])
        # round((28.0 + 28.0) / 100 * 100, 2) = 56.0 over the dry tallies.
        assert full["recovery_pct_certified"] == pytest.approx(56.0, abs=1e-6)


class TestByproductLedger:
    def _completed_run_with_tons(self):
        run, _packages = create_completed_run(
            [{"green_mbf": 20.0}],
            complete_overrides={"chip_tons": 20, "sawdust_tons": 10, "bark_tons": 8},
        )
        return run

    def test_byproduct_on_hand_and_sale_total(self, api):
        """PRD Section 3.8: "A `SalesRep` records a byproduct sale with the `product` (`CHIP`, `SAWDUST`, or `BARK`), the `volume_tons` sold, the `price_per_ton_cents`, and the `buyer_name`; the sale's `total_cents` is the product of `volume_tons` and `price_per_ton_cents`, rounded half-up to whole cents, and the sale returns 201."
        PRD Section 3.8: "The sale is validated against on-hand inventory: per product, produced tons are the sum of the corresponding tonnage across all `COMPLETED` sawing runs, sold tons are the sum of `volume_tons` across all sales of that product — sales are final and carry no status — and on-hand tons are produced minus sold."

        Design: Corner/calculations/byproduct_on_hand_and_sale_total
        """
        self._completed_run_with_tons()
        sale = sell_byproduct(product="CHIP", volume_tons=7, price_per_ton_cents=9000,
                              buyer_name="PanelBoard Inc")
        assert sale["total_cents"] == 63000, f"round(7 * 9000, 0) = 63000, got {sale['total_cents']}"
        inv = byproduct_inventory_map()
        assert inv["CHIP"]["produced_tons"] == pytest.approx(20, abs=1e-6)
        assert inv["CHIP"]["sold_tons"] == pytest.approx(7, abs=1e-6)
        assert inv["CHIP"]["on_hand_tons"] == pytest.approx(13, abs=1e-6)
        assert inv["SAWDUST"]["on_hand_tons"] == pytest.approx(10, abs=1e-6)
        assert inv["BARK"]["on_hand_tons"] == pytest.approx(8, abs=1e-6)

    def test_byproduct_oversale_rejected(self, api):
        """PRD Section 3.8: "A sale whose `volume_tons` exceeds the product's on-hand tons is rejected with `ERR_INSUFFICIENT_BYPRODUCT` (HTTP 422)."

        Design: Corner/validations/byproduct_oversale_rejected
        """
        self._completed_run_with_tons()
        res = api.create_byproduct_sale(
            create_byproduct_sale_payload(product="SAWDUST", volume_tons=11,
                                          price_per_ton_cents=4000),
            make_sales_rep_headers(),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BYPRODUCT)
        inv = byproduct_inventory_map()
        assert inv["SAWDUST"]["on_hand_tons"] == pytest.approx(10, abs=1e-6), (
            "rejected sale leaves inventory unchanged"
        )
