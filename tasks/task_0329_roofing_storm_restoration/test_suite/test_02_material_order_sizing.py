"""Material-order sizing: the non-linear MIN_BUNDLES / ceil / *1.15 / *3 bundle
formula, the *80lb weight, and the tiered freight schedule.

Queue A: combinatorial_formula (material sizing instance).
Queue B (calculations section): material_sizing_min_bundles_floor (MIN_BUNDLES
floor case, tier-1 freight).

NOTE on the difficulty instance material_sizing_nonlinear_min_ceil_tier: its
bundles (69) and total_weight_lbs (5520) are uniquely derivable from PRD §3.4
and are asserted here. The instance's freight_cents literal (21500) is NOT
PRD-derivable — PRD §3.4 yields 12500 + ceil((5520-4000)/1000)*3000 =
12500 + 2*3000 = 18500 — so this file asserts the PRD-faithful 18500 freight,
the value a PRD-only implementer uniquely arrives at.
"""
from test_helpers import (
    validate_success, TEST_USERS, setup_contracted_job,
    create_material_order_payload,
)

PM = TEST_USERS["production_manager_headers"]

SHINGLE_20 = [{"trade": "SHINGLE", "squares": 20, "unit_price_cents": 18000, "waste_factor_pct": 0.15}]
SHINGLE_2 = [{"trade": "SHINGLE", "squares": 2, "unit_price_cents": 18000, "waste_factor_pct": 0.15}]


class TestMaterialOrderSizing:
    def test_bundles_and_weight_from_shingle_squares(self, api):
        """PRD §3.4: "The bundle count `bundles` is then the effective shingle
        squares multiplied by one plus the shingle waste allowance of 0.15,
        multiplied by 3 bundles per square, that product rounded up to the next
        whole bundle, and finally floored at a minimum of 12 bundles — whichever
        of the computed count and 12 is larger is the bundle count."

        Design: Difficulty/combinatorial_formula/material_sizing_nonlinear_min_ceil_tier
        """
        job_id, _ = setup_contracted_job(line_items=SHINGLE_20)
        mo = validate_success(api.create_material_order(
            create_material_order_payload(job_id=job_id), PM), expected_status=201)
        # ceil(20 * 1.15 * 3) = ceil(69.0) = 69 (above the 12 floor).
        assert mo["bundles"] == 69
        # 69 * 80 lbs.
        assert mo["total_weight_lbs"] == 5520

    def test_freight_tier_for_heavy_order(self, api):
        """PRD §3.4: "If it exceeds 4000, freight is 12500 plus 3000 for each
        whole 1000 pounds (or part thereof) above 4000 — that is, the weight
        above 4000 divided by 1000, rounded up to a whole number, multiplied by
        3000, added to the 12500 base."

        Design: Difficulty/combinatorial_formula/material_sizing_nonlinear_min_ceil_tier
        """
        job_id, _ = setup_contracted_job(line_items=SHINGLE_20)
        mo = validate_success(api.create_material_order(
            create_material_order_payload(job_id=job_id), PM), expected_status=201)
        # weight 5520 > 4000: 12500 + ceil((5520-4000)/1000)*3000 = 12500 + 2*3000 = 18500.
        assert mo["total_weight_lbs"] == 5520
        assert mo["freight_cents"] == 18500

    def test_min_bundles_floor_and_tier1_freight(self, api):
        """PRD §3.4: "rounded up to the next whole bundle, and finally floored at
        a minimum of 12 bundles — whichever of the computed count and 12 is
        larger is the bundle count."

        Design: Corner/calculations/material_sizing_min_bundles_floor
        """
        job_id, _ = setup_contracted_job(line_items=SHINGLE_2)
        mo = validate_success(api.create_material_order(
            create_material_order_payload(job_id=job_id), PM), expected_status=201)
        # ceil(2 * 1.15 * 3) = ceil(6.9) = 7, floored up to MIN_BUNDLES = 12.
        assert mo["bundles"] == 12
        assert mo["total_weight_lbs"] == 960
        # weight 960 <= 2000: tier-1 freight 7500.
        assert mo["freight_cents"] == 7500
