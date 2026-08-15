"""Replenishment trigger calculations: policy variants and reorder boundary."""
import pytest

from test_helpers import (
    api_client,
    make_plant_operator_headers,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_site,
    create_vessel,
    post_reading,
)
from test_helpers.test_users import TEST_USERS

SM = TEST_USERS["service_manager_headers"]


class TestReorderPolicyVariants:
    def test_target_fill_quantity_on_identical_inventory(
        self, api
    ):
        """PRD §3.2: "Under `TARGET_FILL`, the quantity is `target_fill_pct` divided
        by 100, multiplied by `capacity_tons`, minus `current_inventory_tons` — it
        fills to a fixed capacity percentage regardless of consumption rate."
        PRD §3.2: "If the new reading's `level_pct` is at or below the vessel's
        `reorder_point_pct`, and there is no replenishment order for the vessel in
        `TRIGGERED` or `DISPATCHED` status, the system auto-creates a
        `ReplenishmentOrder` in `TRIGGERED` status, snapshotting the vessel's
        current `replenishment_policy` onto `policy_used` and the triggering
        reading's `id` onto `trigger_reading_id`."

        Design: Difficulty/dual_variant_calc/reorder_target_fill_vs_days_of_cover
        """
        site = create_site(name="Site One", state_code="IA")
        va = create_vessel(
            site["id"],
            name="SILO-A",
            vessel_kind="SILO",
            capacity_tons=100,
            material_name="cement",
            reorder_point_pct=30,
            target_fill_pct=90,
            replenishment_policy="TARGET_FILL",
        )
        post_reading(va["id"], "2026-08-02T00:00:00Z", 25.0, site["id"])

        data, meta = validate_paginated(
            api.list_replenishment_orders(
                SM, params={"vessel_id": va["id"], "status": "TRIGGERED"}
            )
        )
        assert meta["total_count"] == 1
        order = data[0]
        # 90 pct of 100 t minus 25.0 t = 65.0 t
        assert order["order_quantity_tons"] == pytest.approx(65.0, abs=1e-9)
        assert order["policy_used"] == "TARGET_FILL"

    def test_days_of_cover_quantity_on_identical_inventory(self, api):
        """PRD §3.2: "Under `DAYS_OF_COVER`, the quantity is `cover_days` multiplied
        by the vessel's average daily usage in tons, minus
        `current_inventory_tons`."
        PRD §3.2: "If fewer than two readings fall in the window, the usage defaults
        to the vessel's `default_usage_tons`."

        Design: Difficulty/dual_variant_calc/reorder_target_fill_vs_days_of_cover
        """
        site = create_site(name="Site One", state_code="IA")
        vb = create_vessel(
            site["id"],
            name="BIN-B",
            vessel_kind="BIN",
            capacity_tons=100,
            material_name="cement",
            reorder_point_pct=30,
            replenishment_policy="DAYS_OF_COVER",
            cover_days=10,
            default_usage_tons=3.0,
        )
        post_reading(vb["id"], "2026-08-02T00:00:00Z", 25.0, site["id"])

        data, meta = validate_paginated(
            api.list_replenishment_orders(
                SM, params={"vessel_id": vb["id"], "status": "TRIGGERED"}
            )
        )
        assert meta["total_count"] == 1
        order = data[0]
        # 10 days x 3.0 t/day minus 25.0 t = 5.0 t — differs from TARGET_FILL's 65.0
        assert order["order_quantity_tons"] == pytest.approx(5.0, abs=1e-9)
        assert order["policy_used"] == "DAYS_OF_COVER"

    def test_identical_inventory_yields_different_quantities_per_policy(self, api):
        """PRD §3.2: "Under `TARGET_FILL`, the quantity is `target_fill_pct` divided
        by 100, multiplied by `capacity_tons`, minus `current_inventory_tons` — it
        fills to a fixed capacity percentage regardless of consumption rate."
        PRD §3.2: "Under `DAYS_OF_COVER`, the quantity is `cover_days` multiplied
        by the vessel's average daily usage in tons, minus
        `current_inventory_tons`."

        Design: Difficulty/dual_variant_calc/reorder_target_fill_vs_days_of_cover
        """
        site = create_site(name="Site One", state_code="IA")
        va = create_vessel(
            site["id"],
            name="SILO-A",
            vessel_kind="SILO",
            capacity_tons=100,
            material_name="cement",
            reorder_point_pct=30,
            target_fill_pct=90,
            replenishment_policy="TARGET_FILL",
        )
        vb = create_vessel(
            site["id"],
            name="BIN-B",
            vessel_kind="BIN",
            capacity_tons=100,
            material_name="cement",
            reorder_point_pct=30,
            replenishment_policy="DAYS_OF_COVER",
            cover_days=10,
            default_usage_tons=3.0,
        )
        post_reading(va["id"], "2026-08-02T00:00:00Z", 25.0, site["id"])
        post_reading(vb["id"], "2026-08-02T00:00:00Z", 25.0, site["id"])

        qa_data, qa_meta = validate_paginated(
            api.list_replenishment_orders(
                SM, params={"vessel_id": va["id"], "status": "TRIGGERED"}
            )
        )
        qb_data, qb_meta = validate_paginated(
            api.list_replenishment_orders(
                SM, params={"vessel_id": vb["id"], "status": "TRIGGERED"}
            )
        )
        assert qa_meta["total_count"] == 1
        assert qb_meta["total_count"] == 1
        qa = qa_data[0]["order_quantity_tons"]
        qb = qb_data[0]["order_quantity_tons"]
        assert qa == pytest.approx(65.0, abs=1e-9)
        assert qb == pytest.approx(5.0, abs=1e-9)
        assert qa != qb, (
            "Identical inventory must produce different quantities per policy variant"
        )


class TestCalibrationBasisVariants:
    def _setup_vessels(self):
        site = create_site(name="Site Two", state_code="IA")
        vc = create_vessel(
            site["id"],
            name="SILO-C",
            vessel_kind="SILO",
            capacity_tons=100,
            material_name="flour",
            reorder_point_pct=30,
            error_basis="OF_READING",
        )
        vd = create_vessel(
            site["id"],
            name="SILO-D",
            vessel_kind="SILO",
            capacity_tons=100,
            material_name="flour",
            reorder_point_pct=30,
            error_basis="OF_FULL_SCALE",
            full_scale_tons=100,
        )
        tech_res = api_client.create_technician(
            {"name": "Tech Cal One", "weekly_capacity_hours": 40}, SM
        )
        from test_helpers import get_success_data

        tech = get_success_data(tech_res, 201)
        return site, vc, vd, tech

    def test_of_reading_error_pct_and_fail(self, api):
        """PRD §3.4: "Under `OF_READING`, the error is the difference between
        `indicated_tons` and `test_weight_tons`, divided by `test_weight_tons`,
        multiplied by 100 — error expressed relative to the applied test weight."
        PRD §3.4: "The calibration's `result` is `PASS` when the absolute value of
        `error_pct` is at most `tolerance_pct` (the boundary is inclusive) and
        `FAIL` otherwise."

        Design: Difficulty/dual_variant_calc/calibration_of_reading_vs_full_scale
        """
        from test_helpers import make_technician_headers

        site, vc, vd, tech = self._setup_vessels()
        res = api.create_scale_calibration(
            {
                "vessel_id": vc["id"],
                "tested_at": "2026-08-02T00:00:00Z",
                "test_weight_tons": 20.0,
                "indicated_tons": 20.06,
            },
            make_technician_headers(tech["id"]),
        )
        cal = validate_success(res, 201)
        # 0.06/20.0 x 100 = 0.300 > 0.25 -> FAIL
        assert cal["error_pct"] == pytest.approx(0.300, abs=1e-9)
        assert cal["result"] == "FAIL"
        vessel = validate_success(api.get_vessel(vc["id"], SM), 200)
        assert vessel["scale_status"] == "OUT_OF_TOLERANCE"

    def test_of_full_scale_error_pct_and_pass(self, api):
        """PRD §3.4: "Under `OF_FULL_SCALE`, the error is the difference between
        `indicated_tons` and `test_weight_tons`, divided by the vessel's
        `full_scale_tons`, multiplied by 100 — error expressed relative to
        full-scale capacity, so identical weights yield a smaller absolute
        `error_pct` and can flip the pass/fail outcome relative to `OF_READING`."

        Design: Difficulty/dual_variant_calc/calibration_of_reading_vs_full_scale
        """
        from test_helpers import make_technician_headers

        site, vc, vd, tech = self._setup_vessels()
        res = api.create_scale_calibration(
            {
                "vessel_id": vd["id"],
                "tested_at": "2026-08-02T00:00:00Z",
                "test_weight_tons": 20.0,
                "indicated_tons": 20.06,
            },
            make_technician_headers(tech["id"]),
        )
        cal = validate_success(res, 201)
        # 0.06/100 x 100 = 0.060 <= 0.25 -> PASS
        assert cal["error_pct"] == pytest.approx(0.060, abs=1e-9)
        assert cal["result"] == "PASS"
        vessel = validate_success(api.get_vessel(vd["id"], SM), 200)
        assert vessel["scale_status"] == "IN_TOLERANCE"

    def test_same_weights_different_basis_flip_verdict(self, api):
        """PRD §3.4: "Under `OF_FULL_SCALE`, the error is the difference between
        `indicated_tons` and `test_weight_tons`, divided by the vessel's
        `full_scale_tons`, multiplied by 100 — error expressed relative to
        full-scale capacity, so identical weights yield a smaller absolute
        `error_pct` and can flip the pass/fail outcome relative to `OF_READING`."

        Design: Difficulty/dual_variant_calc/calibration_of_reading_vs_full_scale
        """
        from test_helpers import make_technician_headers

        site, vc, vd, tech = self._setup_vessels()
        cal_c = validate_success(
            api.create_scale_calibration(
                {
                    "vessel_id": vc["id"],
                    "tested_at": "2026-08-02T00:00:00Z",
                    "test_weight_tons": 20.0,
                    "indicated_tons": 20.06,
                },
                make_technician_headers(tech["id"]),
            ),
            201,
        )
        cal_d = validate_success(
            api.create_scale_calibration(
                {
                    "vessel_id": vd["id"],
                    "tested_at": "2026-08-02T00:00:00Z",
                    "test_weight_tons": 20.0,
                    "indicated_tons": 20.06,
                },
                make_technician_headers(tech["id"]),
            ),
            201,
        )
        assert cal_c["error_pct"] == pytest.approx(0.300, abs=1e-9)
        assert cal_d["error_pct"] == pytest.approx(0.060, abs=1e-9)
        assert cal_c["result"] == "FAIL"
        assert cal_d["result"] == "PASS"
        assert cal_c["error_pct"] != cal_d["error_pct"]


class TestReorderPointBoundary:
    def test_level_at_reorder_point_triggers_order(self, api):
        """PRD §3.2: "If the new reading's `level_pct` is at or below the vessel's
        `reorder_point_pct`, and there is no replenishment order for the vessel in
        `TRIGGERED` or `DISPATCHED` status, the system auto-creates a
        `ReplenishmentOrder` in `TRIGGERED` status, snapshotting the vessel's
        current `replenishment_policy` onto `policy_used` and the triggering
        reading's `id` onto `trigger_reading_id`."

        Design: Difficulty/boundary_precision_check/reorder_point_inclusive_trigger_boundary
        """
        site = create_site(name="Site Ten", state_code="NE")
        vm = create_vessel(
            site["id"],
            name="SILO-M",
            vessel_kind="SILO",
            capacity_tons=100,
            material_name="wheat",
            reorder_point_pct=30,
            target_fill_pct=90,
        )
        post_reading(vm["id"], "2026-08-02T00:00:00Z", 30.0, site["id"])
        data, meta = validate_paginated(
            api.list_replenishment_orders(SM, params={"vessel_id": vm["id"]})
        )
        # inclusive <= boundary: 30.0 triggers; 90 - 30.0 = 60.0 t
        assert meta["total_count"] == 1
        assert data[0]["order_quantity_tons"] == pytest.approx(60.0, abs=1e-9)

    def test_level_just_above_reorder_point_triggers_nothing(self, api):
        """PRD §3.2: "If the new reading's `level_pct` is at or below the vessel's
        `reorder_point_pct`, and there is no replenishment order for the vessel in
        `TRIGGERED` or `DISPATCHED` status, the system auto-creates a
        `ReplenishmentOrder` in `TRIGGERED` status, snapshotting the vessel's
        current `replenishment_policy` onto `policy_used` and the triggering
        reading's `id` onto `trigger_reading_id`."

        Design: Difficulty/boundary_precision_check/reorder_point_inclusive_trigger_boundary
        """
        site = create_site(name="Site Ten", state_code="NE")
        vn = create_vessel(
            site["id"],
            name="SILO-N",
            vessel_kind="SILO",
            capacity_tons=100,
            material_name="wheat",
            reorder_point_pct=30,
            target_fill_pct=90,
        )
        post_reading(vn["id"], "2026-08-02T00:00:00Z", 30.1, site["id"])
        data, meta = validate_paginated(
            api.list_replenishment_orders(SM, params={"vessel_id": vn["id"]})
        )
        # 30.1 > 30 does not trigger
        assert meta["total_count"] == 0


class TestCalibrationToleranceBoundary:
    def _setup(self):
        from test_helpers import get_success_data

        site = create_site(name="Site Eleven", state_code="NE")
        vessel = create_vessel(
            site["id"],
            name="SILO-O",
            vessel_kind="SILO",
            capacity_tons=100,
            material_name="oats",
            reorder_point_pct=30,
            error_basis="OF_READING",
        )
        tech = get_success_data(
            api_client.create_technician(
                {"name": "Tech Cal Two", "weekly_capacity_hours": 40}, SM
            ),
            201,
        )
        return site, vessel, tech

    def test_error_exactly_at_tolerance_passes(self, api):
        """PRD §2.5: "A calibration passes when the absolute value of `error_pct` is
        at most `tolerance_pct` (the boundary is inclusive); otherwise it fails."

        Design: Difficulty/boundary_precision_check/calibration_tolerance_inclusive_pass_boundary
        """
        from test_helpers import make_technician_headers

        site, vessel, tech = self._setup()
        cal = validate_success(
            api.create_scale_calibration(
                {
                    "vessel_id": vessel["id"],
                    "tested_at": "2026-08-02T00:00:00Z",
                    "test_weight_tons": 20.0,
                    "indicated_tons": 20.05,
                },
                make_technician_headers(tech["id"]),
            ),
            201,
        )
        # 0.05/20.0 x 100 = 0.250 <= 0.25 inclusive -> PASS
        assert cal["error_pct"] == pytest.approx(0.250, abs=1e-9)
        assert cal["result"] == "PASS"

    def test_error_just_above_tolerance_fails(self, api):
        """PRD §2.5: "A calibration passes when the absolute value of `error_pct` is
        at most `tolerance_pct` (the boundary is inclusive); otherwise it fails. A
        pass sets `scale_status` to `IN_TOLERANCE`; a failure sets it to
        `OUT_OF_TOLERANCE`."

        Design: Difficulty/boundary_precision_check/calibration_tolerance_inclusive_pass_boundary
        """
        from test_helpers import make_technician_headers

        site, vessel, tech = self._setup()
        cal = validate_success(
            api.create_scale_calibration(
                {
                    "vessel_id": vessel["id"],
                    "tested_at": "2026-08-03T00:00:00Z",
                    "test_weight_tons": 20.0,
                    "indicated_tons": 20.051,
                },
                make_technician_headers(tech["id"]),
            ),
            201,
        )
        # 0.051/20.0 x 100 = 0.255 > 0.25 -> FAIL
        assert cal["error_pct"] == pytest.approx(0.255, abs=1e-9)
        assert cal["result"] == "FAIL"
        fetched = validate_success(api.get_vessel(vessel["id"], SM), 200)
        assert fetched["scale_status"] == "OUT_OF_TOLERANCE"
