"""Batch calculations: dose rounding, yield, BUD, waste tolerance (PRD §3.4, §3.5)."""
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    assert_batch_mass_invariant,
    create_drug,
    create_patient,
    fixtures,
    place_order,
    validate_error,
    validate_paginated,
    validate_success,
)

COMPLETION_INSTANT = datetime(2026, 8, 1, tzinfo=timezone.utc)  # PRD §2.6 default clock


def _instant(iso_ts: str) -> datetime:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def _four_verified_orders(doses=(2.6, 2.4, 2.5, 12.5)):
    prescriber, _ = fixtures.make_prescriber()
    pharmacist, _ = fixtures.make_pharmacist()
    drug = create_drug(name="DrugR")
    orders = []
    for i, dose in enumerate(doses):
        patient = create_patient(full_name=f"Pat R{i + 1}")
        order = place_order(patient, drug, prescriber, route="IV",
                            ordered_dose_mg=dose)
        orders.append(fixtures.verify_order(order["id"], pharmacist))
    return pharmacist, drug, orders


class TestDoseRoundingPerComponentThenSum:
    def test_each_order_final_dose_rounded_to_its_step(self, api):
        """PRD §3.4: "The step size depends on the raw value: below 1 the step is 0.1; from 1 up to and including 10 the step is 0.5; above 10 the step is 1.0. Rounding to a step means dividing the raw value by its step, rounding that quotient half-up to a whole number, and multiplying back by the step. The `final_dose_ml` of an order is the step-rounded value of `renal_adjusted_dose_mg` divided by the drug's `concentration_mg_per_ml`."

        Design: Difficulty/combinatorial_formula/dose_rounding_per_component_then_sum
        """
        _, _, orders = _four_verified_orders()
        expected_ml = [0.3, 0.2, 0.3, 1.5]
        for order, expected in zip(orders, expected_ml):
            assert order["final_dose_ml"] == pytest.approx(expected, abs=1e-9)

    def test_batch_demand_sums_per_component_rounded_volumes(self, api):
        """PRD §3.4: "Wherever several component volumes feed an aggregate — the batch demand calculation is the case that matters — each component volume is rounded to its step first and only then summed. Summing first and rounding the total is explicitly not the policy and yields different results; implementations must round-then-sum."
        PRD §3.5: "Second, `vials_used` is `demand_ml` divided by the batch drug's `vial_size_ml`, rounded up to a whole vial."

        Design: Difficulty/combinatorial_formula/dose_rounding_per_component_then_sum
        """
        _, _, orders = _four_verified_orders()
        batch_ns = fixtures.setup_batch([o["id"] for o in orders],
                                        start_session=True)
        batch = batch_ns.batch
        # per-component: 0.3 + 0.2 + 0.3 + 1.5 == 2.3; sum-then-round would give 2.0
        assert batch["demand_ml"] == pytest.approx(2.3, abs=1e-9)
        assert batch["vials_used"] == 1  # ceil(2.3 / 10)


class TestBeyondUseDatingVariants:
    def _setup_completed_two_drug_batch(self, api, pharmacist_headers):
        prescriber, _ = fixtures.make_prescriber()
        pharmacist, _ = fixtures.make_pharmacist()
        patient = create_patient()
        drug_s = create_drug(name="DrugS plain")
        drug_t = create_drug(name="DrugT stable", has_stability_data=True,
                             stability_hours_refrigerated=720)
        order_s = place_order(patient, drug_s, prescriber, route="IV",
                              ordered_dose_mg=100.0)
        order_t = place_order(patient, drug_t, prescriber, route="IV",
                              ordered_dose_mg=100.0)
        order_s = fixtures.verify_order(order_s["id"], pharmacist)
        order_t = fixtures.verify_order(order_t["id"], pharmacist)
        batch_ns = fixtures.setup_batch_in_progress(
            [order_s["id"], order_t["id"]], usp_risk_level="LOW",
            documents_stability_source=True,
        )
        fixtures.complete_batch(batch_ns, [10.0, 10.0], waste_ml=0.0,
                                storage_condition="REFRIGERATED")
        preps_s, _ = validate_paginated(
            api.list_preparations(pharmacist_headers,
                                  params={"order_id": order_s["id"]})
        )
        preps_t, _ = validate_paginated(
            api.list_preparations(pharmacist_headers,
                                  params={"order_id": order_t["id"]})
        )
        return preps_s[0], preps_t[0]

    def test_default_table_variant_uses_usp_hours(self, api, pharmacist_headers):
        """PRD §3.5: "The base table is keyed by the batch's `usp_risk_level` and the preparation's `storage_condition`, in whole hours: a `LOW`-risk preparation keeps 48 hours at `ROOM`, 336 hours `REFRIGERATED`, and 1080 hours `FROZEN`"
        PRD §3.5: "The resulting `bud_expiry` is the completion timestamp (read from the logical clock) plus the beyond-use hours, stored as an ISO 8601 UTC instant, and it remains null until completion computes it."

        Design: Difficulty/dual_variant_calc/bud_default_table_vs_stability_extended
        """
        prep_s, _ = self._setup_completed_two_drug_batch(api, pharmacist_headers)
        # LOW / REFRIGERATED -> 336 h from the 2026-08-01T00:00:00Z completion
        assert _instant(prep_s["bud_expiry"]) == COMPLETION_INSTANT + timedelta(hours=336)

    def test_stability_extended_variant_capped_at_720_hours(self, api, pharmacist_headers):
        """PRD §3.5: "The stability-extended variant applies only when the drug's `has_stability_data` is true, the batch's `documents_stability_source` is true, and the drug's stability hours for the chosen storage condition are not null; in that case the beyond-use hours are the drug's stability hours for that condition, capped at 720 hours — so identical completion times yield a later expiry under the extended variant than under the table variant."

        Design: Difficulty/dual_variant_calc/bud_default_table_vs_stability_extended
        """
        prep_s, prep_t = self._setup_completed_two_drug_batch(api, pharmacist_headers)
        # stability_hours_refrigerated 720, capped at 720 -> 720 h from completion
        assert _instant(prep_t["bud_expiry"]) == COMPLETION_INSTANT + timedelta(hours=720)
        assert _instant(prep_t["bud_expiry"]) > _instant(prep_s["bud_expiry"])


class TestWasteToleranceReleaseGate:
    def test_overage_above_small_tier_tolerance_blocks_release(self, api, pharmacist_headers):
        """PRD §3.5: "QA release additionally gates on waste: the batch's `overage_pct` must not exceed the tolerance of its size tier — 60 percent for SMALL, 30 percent for MEDIUM, 10 percent for LARGE — otherwise the release is rejected with `ERR_WASTE_TOLERANCE_EXCEEDED`."
        PRD §3.5: "Sixth, the batch's size tier is read off the run's drawn volume: below 25 mL the batch is SMALL with a 60 percent waste tolerance; from 25 mL up to and including 100 mL it is MEDIUM with a 30 percent tolerance; above 100 mL it is LARGE with a 10 percent tolerance."

        Design: Corner/calculations/waste_tolerance_release_gate
        """
        pharmacist, _, orders = _four_verified_orders()
        batch_ns = fixtures.setup_batch_in_progress([o["id"] for o in orders])
        completed = fixtures.complete_batch(
            batch_ns, [0.3, 0.2, 0.3, 1.5], waste_ml=7.7,
            storage_condition="REFRIGERATED",
        )
        # drawn 10 mL (SMALL tier); overage 7.7 / 10 * 100 == 77.0 > 60
        assert completed["overage_pct"] == pytest.approx(77.0, abs=0.005)
        resp = api.qa_release_batch(
            batch_ns.batch["id"], fixtures.make_pharmacist_headers(pharmacist["id"])
        )
        validate_error(resp, "ERR_WASTE_TOLERANCE_EXCEEDED", 422)
        fetched = validate_success(
            api.get_batch(batch_ns.batch["id"], pharmacist_headers), 200
        )
        assert fetched["status"] == "QA_REVIEW"
        assert fetched["overage_pct"] == pytest.approx(77.0, abs=0.005)
