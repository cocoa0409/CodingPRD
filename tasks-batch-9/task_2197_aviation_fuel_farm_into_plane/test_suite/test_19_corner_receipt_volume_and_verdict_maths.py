"""Corner behaviour of the two computations that stand between a supplier's ticket and the ledger:
the six-step volume correction with its density bands, and the all-pass laboratory verdict."""
import pytest

from test_helpers import (
    validate_success, get_success_data, fixtures as fx,
)

PIPELINE = dict(delivery_mode="PIPELINE", supplier_name="Refinery One",
                meter_ticket_gross_liters=12_000.0, tank_opening_gauge_liters=0.0,
                tank_closing_gauge_liters=10_000.0)


def _parcel(density, temperature_c=25.0, water=0.0):
    return dict(PIPELINE, temperature_c=temperature_c,
                certificate_density_kg_per_m3=density, measured_water_liters=water)


class TestReceiptNetVolumeCorners:
    def test_the_two_density_band_edges_are_inclusive_lower_bounds(self, api):
        """PRD §3.2: "**First**, a thermal expansion coefficient is selected by density band from the
        certificate density: 0.000850 when the certificate density is at least 800.0 kilograms per cubic
        metre, otherwise 0.000900 when it is at least 780.0, otherwise 0.000950."
        PRD §3.2: "**Second**, the volume correction factor is one minus the coefficient multiplied by
        the parcel temperature less the 15-degree reference temperature, and this factor is rounded half
        up to five decimal places *before* it multiplies anything."
        PRD §3.2: "**Fourth**, the corrected volume is the governing gross multiplied by the correction
        factor, rounded half up to two decimals."

        Design: Corner/calculations/density_exactly_at_both_band_edges
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0)
        tank_id = env["tank"]["id"]

        heavy_edge = fx.record_receipt(tank_id, **_parcel(800.0))
        mid_edge = fx.record_receipt(tank_id, **_parcel(780.0))
        just_under_heavy = fx.record_receipt(tank_id, **_parcel(799.99))
        just_under_mid = fx.record_receipt(tank_id, **_parcel(779.99))

        assert heavy_edge["net_volume_liters"] == pytest.approx(9915.00, abs=0.005), \
            "alpha 0.000850 over a 10 degree lift gives a factor of 0.99150"
        assert mid_edge["net_volume_liters"] == pytest.approx(9910.00, abs=0.005), \
            "alpha 0.000900 gives 0.99100"
        assert just_under_heavy["net_volume_liters"] == pytest.approx(9910.00, abs=0.005), \
            "799.99 has not reached the heavy band, so it falls to the middle one"
        assert just_under_mid["net_volume_liters"] == pytest.approx(9905.00, abs=0.005), \
            "779.99 falls all the way to alpha 0.000950"

    def test_at_the_reference_temperature_only_the_water_moves_the_net(self, api):
        """PRD §3.2: "**Fifth**, the water deduction cap is one half of one percent of the *governing
        gross* — not of the corrected volume — rounded half up to two decimals, and the deduction
        actually applied is the smaller of the measured water volume and that cap."
        PRD §3.2: "**Sixth**, `net_volume_liters` is the corrected volume less the applied deduction,
        rounded half up to two decimals again."
        PRD §3.2: "**Third**, two gross bases are derived: the gauge delta, being the closing gauge
        reading less the opening gauge reading rounded half up to two decimals, and the meter gross,
        being the supplier ticket figure as printed."

        Design: Corner/calculations/temperature_exactly_at_the_reference
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0)
        tank_id = env["tank"]["id"]

        light = fx.record_receipt(tank_id, **_parcel(760.0, temperature_c=15.0, water=50.0))
        heavy = fx.record_receipt(tank_id, **_parcel(840.0, temperature_c=15.0, water=50.0))
        dry = fx.record_receipt(tank_id, **_parcel(840.0, temperature_c=15.0, water=0.0))

        assert light["net_volume_liters"] == pytest.approx(9950.00, abs=0.005), \
            "a factor of exactly 1.00000 leaves the 10,000.00 gauge delta alone, less 50.00 of water"
        assert heavy["net_volume_liters"] == pytest.approx(9950.00, abs=0.005), \
            "the band no longer matters once the parcel is at the reference temperature"
        assert dry["net_volume_liters"] == pytest.approx(10000.00, abs=0.005)
        assert light["advisory_net_volume_liters"] == pytest.approx(11950.00, abs=0.005), \
            "the advisory basis is the 12,000.00 meter ticket, capped at 60.00 of water"

    def test_the_receipt_arithmetic_reads_its_own_certificate_and_never_reruns(self, api):
        """PRD §3.2: "A `FarmOperator` records an inbound parcel the moment it lands, and the arithmetic
        performed at that instant is frozen forever: the volumes computed on creation are never
        recomputed, and they are exactly what a later release verdict adds to the tank ledger."
        PRD §3.2: "**First**, a thermal expansion coefficient is selected by density band from the
        certificate density: 0.000850 when the certificate density is at least 800.0 kilograms per cubic
        metre, otherwise 0.000900 when it is at least 780.0, otherwise 0.000950."
        PRD §3.3: "On success the receipt's `released_at_utc` is stamped from the logical clock and its
        `released_by_user_id` from the acting identifier; the receipt's net volume enters the tank
        ledger, which recomputes the tank's `book_volume_liters`, `reserved_volume_liters` and
        `available_volume_liters`; the farm's permit-day throughput counter is recomputed; and the farm's
        posture is recomputed, which may land on `RESTRICTED` the moment permit utilisation reaches the
        90 percent boundary."

        Design: Corner/calculations/net_volume_is_frozen_at_creation
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0,
                                               density_kg_per_m3=850.0)
        tank_id = env["tank"]["id"]

        receipt = fx.record_receipt(tank_id, **_parcel(780.0))
        assert receipt["net_volume_liters"] == pytest.approx(9910.00, abs=0.005), \
            "the certificate's 780.0 selects alpha 0.000900; the tank's own 850.0 is irrelevant here"

        sample = fx.draw_receipt_sample(receipt["id"])
        fx.post_results(sample["id"], fx.INSPECTOR_A, observed_density_kg_per_m3=780.0)
        released = fx.sign_verdict(receipt["id"], "RELEASE", fx.INSPECTOR_B)
        assert released["status"] == "RELEASED"
        assert released["net_volume_liters"] == pytest.approx(9910.00, abs=0.005)

        fx.set_clock("2026-08-20T06:00:00Z")
        reread = validate_success(api.get_fuel_receipt(receipt["id"], fx.OPERATOR))
        assert reread["net_volume_liters"] == pytest.approx(9910.00, abs=0.005), \
            "nothing after creation ever recomputes the parcel"
        assert reread["advisory_net_volume_liters"] == \
            pytest.approx(11892.00, abs=0.005)
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(9910.00, abs=0.005)


class TestSampleVerdictCorners:
    def test_conductivity_fails_on_both_sides_of_its_inclusive_band(self, api):
        """PRD §3.2: "The conductivity fails when it falls outside the inclusive band from 50 to 600
        picosiemens per metre, so both 50 and 600 pass."
        PRD §3.2: "The `verdict` is `PASS` when nothing failed and `FAIL` otherwise."
        PRD §3.2: "The verdict computation is a strict all-pass gate over the metrics that were actually
        posted; a null metric is skipped entirely and cannot fail."

        Design: Corner/calculations/conductivity_is_a_two_sided_inclusive_band
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0)
        tank_id = env["tank"]["id"]

        verdicts = {}
        for conductivity in (50.0, 49.9, 600.0):
            receipt = fx.record_receipt(tank_id, **_parcel(795.0))
            sample = fx.draw_receipt_sample(receipt["id"])
            verdicts[conductivity] = fx.post_results(
                sample["id"], fx.INSPECTOR_A, conductivity_ps_per_m=conductivity)

        assert verdicts[50.0]["verdict"] == "PASS"
        assert verdicts[50.0]["failed_metrics"] == []
        assert verdicts[600.0]["verdict"] == "PASS", "the upper edge is inclusive too"
        assert verdicts[600.0]["failed_metrics"] == []
        assert verdicts[49.9]["verdict"] == "FAIL"
        assert verdicts[49.9]["failed_metrics"] == ["conductivity_ps_per_m"], \
            "a tenth below the floor is as fatal as a reading above the ceiling"

    def test_receipt_qc_density_is_judged_against_the_certificate_not_the_tank(self, api):
        """PRD §3.2: "The observed density fails when its absolute difference from the comparison
        density exceeds 3.0 kilograms per cubic metre, where the comparison density is the parent
        receipt's `certificate_density_kg_per_m3` for a `RECEIPT_QC` sample and the parent tank's
        `density_kg_per_m3` otherwise."
        PRD §3.2: "It creates a quality sample whose `sample_purpose` is `RECEIPT_QC`, whose `status` is
        `DRAWN`, and whose `fuel_receipt_id` points back at this receipt, stamps the receipt's
        `sampled_by_user_id` with the acting identifier, and raises the receipt's `version` by one."

        Design: Corner/calculations/density_tolerance_uses_the_receipt_certificate_for_receipt_qc
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0,
                                               density_kg_per_m3=790.0)
        receipt = fx.record_receipt(env["tank"]["id"], **_parcel(795.0))
        sample = fx.draw_receipt_sample(receipt["id"])
        assert sample["sample_purpose"] == "RECEIPT_QC"
        assert sample["fuel_receipt_id"] == receipt["id"]

        tested = fx.post_results(sample["id"], fx.INSPECTOR_A,
                                 observed_density_kg_per_m3=798.0)

        assert tested["verdict"] == "PASS", \
            "3.0 against the certificate's 795.0 is inside tolerance; 8.0 against the tank's 790.0 " \
            "would not have been"
        assert tested["failed_metrics"] == []
        assert tested["status"] == "TESTED"

    def test_failed_metrics_come_back_in_the_pinned_order(self, api):
        """PRD §3.2: "The names of the failing metrics are collected into `failed_metrics` in a fixed
        order — water reaction rating first, then particulate, then conductivity, then observed density,
        then flash point — regardless of the order they appeared in the payload."
        PRD §3.2: "The water reaction rating fails when it exceeds 1."
        PRD §3.2: "The flash point fails when it is below 38.0 degrees Celsius, so exactly 38.0
        passes."

        Design: Corner/calculations/failed_metrics_ordering_is_canonical_not_insertion
        """
        env = fx.setup_farm_with_released_tank(opening_volume_liters=0.0)
        receipt = fx.record_receipt(env["tank"]["id"], **_parcel(795.0))
        sample = fx.draw_receipt_sample(receipt["id"])

        reversed_payload = {"flash_point_c": 30.0, "observed_density_kg_per_m3": 795.0,
                            "conductivity_ps_per_m": 120.0, "particulate_mg_per_l": 0.5,
                            "water_reaction_rating": 3}
        tested = get_success_data(api.post_test_results(sample["id"], reversed_payload,
                                                        fx.INSPECTOR_A))

        assert tested["verdict"] == "FAIL"
        assert tested["failed_metrics"] == ["water_reaction_rating", "flash_point_c"], \
            "the payload named the flash point first and the rating last"
