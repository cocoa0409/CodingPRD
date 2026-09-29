"""Re-entering a state node does not reproduce its outgoing edges: the tank's orthogonal
quality dimension blocks a repeat return to service, and a receipt's second re-test round
consumes the re-test budget."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures as fx,
    make_inspector_headers,
)

INSPECTOR_D = make_inspector_headers("qi-dave")


def _isolated_released_tank(api):
    """Farm with one in-service truck and a tank taken ON_TEST -> RELEASED -> ISOLATED once."""
    env = fx.setup_fuel_farm(permit_overrides={"max_daily_throughput_liters": 400000.0})
    env["truck"] = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                     turnaround_buffer_minutes=15,
                                     differential_pressure_kpa=10.0)
    env["tank"] = fx.make_released_tank(
        env["farm"]["id"], capacity_liters=5_000_000.0, safe_fill_liters=4_000_000.0,
        density_kg_per_m3=795.0, opening_volume_liters=1_000_000.0)
    fx.isolate_tank(env["tank"]["id"], "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")
    return env


class TestTankIsolatedNodeVisitedTwice:
    def test_second_visit_to_isolated_cannot_return_to_service_after_quarantine(self, api):
        """PRD §3.4: "Returning `ISOLATED → IN_SERVICE` requires that the tank's `quality_status`
        is not `QUARANTINED` and that its `water_bottom_mm` is strictly below 25.0 millimetres — at
        25.0 or above the return is refused with `ERR_WATER_BOTTOM_EXCEEDED`."
        PRD §3.4: "A tank may perfectly well be `RELEASED` on quality while `ISOLATED` on service,
        and the two dimensions must be tracked and reported separately."
        PRD §3.4: "Isolating a tank, `IN_SERVICE → ISOLATED`, requires an isolation window supplied
        as `isolation_window_start_utc` and `isolation_window_end_utc`, and it competes for a scarce
        resource: **a farm may have at most one tank isolated over any given instant.**"

        Design: Difficulty/non_linear_state_machine/tank_isolated_to_in_service_blocked_on_second_visit_by_quality_dimension
        """
        env = _isolated_released_tank(api)
        tank_id = env["tank"]["id"]

        # first visit to ISOLATED: the return to service is legal
        back = validate_success(api.change_tank_service_status(
            tank_id, {"to_status": "IN_SERVICE"}, fx.OPERATOR))
        assert back["service_status"] == "IN_SERVICE"
        assert back["quality_status"] == "RELEASED"

        # second visit to ISOLATED, with the quality dimension moved underneath it
        fx.isolate_tank(tank_id, "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")
        validate_success(api.quarantine_tank(
            tank_id, fx.INSPECTOR_A, {"reason": "routine surveillance sample off-spec"}))

        validate_error(api.change_tank_service_status(
            tank_id, {"to_status": "IN_SERVICE"}, fx.OPERATOR),
            ApiErrorId.ERR_INVALID_TANK_STATE, 409)

        blocked = fx.read_tank(tank_id)
        assert blocked["service_status"] == "ISOLATED", \
            "the rejected request leaves the service dimension exactly where it was"
        assert blocked["quality_status"] == "QUARANTINED"
        assert blocked["available_volume_liters"] == pytest.approx(0.00, abs=0.005)
        assert fx.read_farm(env["farm"]["id"])["posture"] == "RESTRICTED"

    def test_recovery_needs_a_full_requalification_loop_on_the_quality_dimension(self, api):
        """PRD §3.4: "Recovery runs the other way: drawing a fresh periodic tank QA sample moves
        `QUARANTINED → ON_TEST`, which is permitted only when no receipt targeting the tank is still
        `QUARANTINED`."
        PRD §3.4: "Signing a tank's quality release, `ON_TEST → RELEASED`, is a `QualityInspector`
        action requiring three things: a periodic tank QA sample exists for this tank whose
        `sample_purpose` is `PERIODIC_TANK_QA`, whose `status` is `TESTED`, whose `verdict` is
        `PASS`, and whose `created_at` is the latest of any sample for this tank; the acting
        identifier differs from that sample's `drawn_by_user_id`, since an inspector may not release
        a tank on the strength of a sample they drew themselves; and the tank's `water_bottom_mm` is
        strictly below 25.0."
        PRD §3.4: "The return clears both isolation window fields to null and recomputes
        availability and posture, again raising both versions."

        Design: Difficulty/non_linear_state_machine/tank_isolated_to_in_service_blocked_on_second_visit_by_quality_dimension
        """
        env = _isolated_released_tank(api)
        tank_id = env["tank"]["id"]
        validate_success(api.change_tank_service_status(
            tank_id, {"to_status": "IN_SERVICE"}, fx.OPERATOR))
        fx.isolate_tank(tank_id, "2026-08-10T06:00:00Z", "2026-08-10T10:00:00Z")
        validate_success(api.quarantine_tank(tank_id, fx.INSPECTOR_A, {"reason": "off-spec"}))

        sample = fx.draw_tank_sample(tank_id, fx.INSPECTOR_C)
        on_test = fx.read_tank(tank_id)
        assert on_test["quality_status"] == "ON_TEST", \
            "drawing a fresh periodic tank QA sample is what leaves QUARANTINED"
        fx.post_results(sample["id"], fx.INSPECTOR_C, particulate_mg_per_l=0.4,
                        conductivity_ps_per_m=130.0, observed_density_kg_per_m3=795.0,
                        flash_point_c=43.0)
        released = fx.release_tank_quality(tank_id, INSPECTOR_D)
        assert released["quality_status"] == "RELEASED"
        assert released["service_status"] == "ISOLATED"
        assert fx.read_farm(env["farm"]["id"])["posture"] == "OPEN"

        final = validate_success(api.change_tank_service_status(
            tank_id, {"to_status": "IN_SERVICE"}, fx.OPERATOR))
        assert final["service_status"] == "IN_SERVICE"
        assert final["isolation_window_start_utc"] is None
        assert final["isolation_window_end_utc"] is None
        assert final["available_volume_liters"] == pytest.approx(999500.00, abs=0.005)
        assert final["book_volume_liters"] == pytest.approx(1000000.00, abs=0.005), \
            "nothing in the whole isolation/quarantine cycle moved the ledger"


class TestReceiptRetestBudget:
    @staticmethod
    def _quarantined_once(api):
        env = fx.setup_farm_with_released_tank(
            permit_overrides={"max_daily_throughput_liters": 400000.0})
        fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                          turnaround_buffer_minutes=15, differential_pressure_kpa=10.0)
        receipt = fx.make_quarantined_receipt(
            env["tank"]["id"], metrics={"particulate_mg_per_l": 2.5,
                                        "conductivity_ps_per_m": 150.0,
                                        "flash_point_c": 41.0},
            delivery_mode="TRUCK", supplier_name="Refinery One",
            meter_ticket_gross_liters=30120.0, tank_opening_gauge_liters=100.0,
            tank_closing_gauge_liters=30100.0, temperature_c=25.0,
            certificate_density_kg_per_m3=795.0, measured_water_liters=200.0)
        assert receipt["status"] == "QUARANTINED"
        # The first pass through SAMPLED is the original receipt QC draw, not a re-test:
        # PRD §3.2 opens a RECORDED receipt with retest_round zero and PRD §3.3 raises it
        # only on the QUARANTINED -> SAMPLED re-sample.
        assert receipt["retest_round"] == 0
        env["receipt"] = receipt
        return env

    @staticmethod
    def _failing_retest_round(api, receipt_id, expected_round):
        """Run one QUARANTINED -> SAMPLED -> UNDER_TEST -> QUARANTINED re-test round."""
        sample = fx.draw_receipt_sample(receipt_id, fx.INSPECTOR_A)
        reread = validate_success(api.get_fuel_receipt(receipt_id, fx.OPERATOR))
        assert reread["status"] == "SAMPLED", "the SAMPLED node is entered again"
        assert reread["retest_round"] == expected_round
        fx.post_results(sample["id"], fx.INSPECTOR_A, particulate_mg_per_l=2.5,
                        conductivity_ps_per_m=150.0, observed_density_kg_per_m3=795.0,
                        flash_point_c=41.0)
        return sample

    def test_third_sampling_attempt_from_the_same_state_hits_the_retest_ceiling(self, api):
        """PRD §3.3: "A `QualityInspector` may open a re-test round, moving
        `QUARANTINED → SAMPLED`, which is permitted only while the receipt's `retest_round` is at
        most 1 — so a parcel may be re-sampled at most twice, and a third attempt on a receipt
        already at a `retest_round` of 2 is rejected with `ERR_RETEST_LIMIT_REACHED` — and only
        while the farm is not `FROZEN`."
        PRD §3.3: "A re-sample raises `retest_round` by one, creates a fresh `RECEIPT_QC` sample in
        `DRAWN`, re-stamps `sampled_by_user_id`, and raises the receipt's `version` by one."
        PRD §3.2: "The particulate figure fails when it exceeds 1.0 milligrams per litre, so
        exactly 1.0 passes."

        Design: Difficulty/non_linear_state_machine/receipt_sampled_node_revisited_then_retest_budget_exhausted
        """
        env = self._quarantined_once(api)
        receipt_id = env["receipt"]["id"]

        # first re-test round: retest_round 0 -> 1
        second = self._failing_retest_round(api, receipt_id, 1)
        sample = validate_success(api.get_quality_sample(second["id"], fx.INSPECTOR_A))
        assert sample["verdict"] == "FAIL"
        assert sample["failed_metrics"] == ["particulate_mg_per_l"]

        again = fx.sign_verdict(receipt_id, "QUARANTINE", fx.INSPECTOR_B)
        assert again["status"] == "QUARANTINED"
        assert again["retest_round"] == 1

        # second re-test round: retest_round 1 -> 2, which is the last one allowed
        self._failing_retest_round(api, receipt_id, 2)
        again = fx.sign_verdict(receipt_id, "QUARANTINE", fx.INSPECTOR_B)
        assert again["status"] == "QUARANTINED"
        assert again["retest_round"] == 2

        # a third attempt on a receipt already at a retest_round of 2 is refused
        validate_error(api.create_receipt_sample(receipt_id, fx.INSPECTOR_A),
                       ApiErrorId.ERR_RETEST_LIMIT_REACHED, 409)

    def test_rejection_is_the_only_remaining_successor_and_conserves_the_ledger(self, api):
        """PRD §3.3: "Alternatively a `FarmOperator` may give up on the parcel and return it to the
        supplier, moving `QUARANTINED → REJECTED` with an optional `reason`."
        PRD §3.3: "Rejection is the conservation case: no ledger volume is added and the farm's
        `active_permit_throughput_used_liters` is left exactly as it was, because only receipts that
        actually reached `RELEASED` ever counted toward the permit day."
        PRD §3.2: "**Sixth**, `net_volume_liters` is the corrected volume less the applied
        deduction, rounded half up to two decimals again."

        Design: Difficulty/non_linear_state_machine/receipt_sampled_node_revisited_then_retest_budget_exhausted
        """
        env = self._quarantined_once(api)
        receipt_id = env["receipt"]["id"]
        self._failing_retest_round(api, receipt_id, 1)
        fx.sign_verdict(receipt_id, "QUARANTINE", fx.INSPECTOR_B)
        self._failing_retest_round(api, receipt_id, 2)
        fx.sign_verdict(receipt_id, "QUARANTINE", fx.INSPECTOR_B)
        validate_error(api.create_receipt_sample(receipt_id, fx.INSPECTOR_A),
                       ApiErrorId.ERR_RETEST_LIMIT_REACHED, 409)

        rejected = validate_success(api.reject_fuel_receipt(
            receipt_id, fx.OPERATOR, {"reason": "off-spec on two consecutive rounds"}))
        assert rejected["status"] == "REJECTED"
        assert rejected["net_volume_liters"] == pytest.approx(29698.32, abs=0.005)

        tank = fx.read_tank(env["tank"]["id"])
        assert tank["book_volume_liters"] == pytest.approx(1000000.00, abs=0.005), \
            "a rejected parcel never entered the ledger"
        farm = fx.read_farm(env["farm"]["id"])
        assert farm["active_permit_throughput_used_liters"] == pytest.approx(0.00, abs=0.005)
