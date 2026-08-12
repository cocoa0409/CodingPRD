"""Difficulty: boundary_precision_check — dos boundary at exactly 3.0; reset window adjacency."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_category_payload,
    create_planogram_payload,
    create_product_payload,
    create_reset_project_payload,
    create_retailer_payload,
    create_store_payload,
    create_supplier_payload,
    make_category_captain_headers,
    validate_error,
    validate_success,
)


class TestDosUnderstockBoundary:
    def _setup_two_products_at_boundary(self, api):
        """Return (rid, cid, pgid, pa_id, pb_id): category + planogram + two LISTED products
        with weekly_demand=70 (=10/day)."""
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), TEST_USERS["platform_admin_headers"]),
            expected_status=201,
        )
        rid = retailer["id"]
        cat = validate_success(
            api.create_category(
                rid,
                create_category_payload(code="C", role="ROUTINE", annual_sales_cents=100_000, total_linear_feet=20),
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        cid = cat["id"]
        supplier = validate_success(
            api.create_supplier(rid, create_supplier_payload(name="S"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        sid = supplier["id"]
        pa = validate_success(
            api.create_product(rid, create_product_payload(cid, sid, sku="PA", width_in=6, unit_cost_cents=100, weekly_demand_units=70), TEST_USERS["category_manager_headers"]),
            expected_status=201,
        )
        pb = validate_success(
            api.create_product(rid, create_product_payload(cid, sid, sku="PB", width_in=6, unit_cost_cents=100, weekly_demand_units=70), TEST_USERS["category_manager_headers"]),
            expected_status=201,
        )
        validate_success(api.list_product_cut_in(rid, pa["id"], TEST_USERS["category_manager_headers"]))
        validate_success(api.list_product_cut_in(rid, pb["id"], TEST_USERS["category_manager_headers"]))
        pg = validate_success(
            api.create_planogram(rid, cid, create_planogram_payload(name="PG", variant="BASE"), TEST_USERS["category_manager_headers"]),
            expected_status=201,
        )
        return rid, cid, pg["id"], pa["id"], pb["id"]

    def test_dos_exactly_3_is_ok(self, api):
        """PRD §3.4: "a line at exactly 3.0 days is `OK`, and so is a line at
        exactly 21.0 days."
        PRD §3.4: "A line lasting strictly less than 3.0 days is flagged
        `UNDERSTOCK`."

        Design: Difficulty/boundary_precision_check/dos_understock_boundary_at_exactly_3_days
        """
        rid, cid, pgid, pa_id, _ = self._setup_two_products_at_boundary(api)
        # capacity=30, daily demand=10 → dos = 30/10 = 3.0 → OK (boundary inclusive)
        resp = api.create_planogram_line(
            rid, cid, pgid,
            {"product_id": pa_id, "position_index": 1, "facings": 3, "capacity_units": 30},
            TEST_USERS["category_manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["days_of_supply"] == pytest.approx(3.0, abs=0.001)
        assert data["dos_flag"] == "OK"

    def test_dos_just_below_3_is_understock(self, api):
        """PRD §3.4: "A line lasting strictly less than 3.0 days is flagged
        `UNDERSTOCK`."

        Design: Difficulty/boundary_precision_check/dos_understock_boundary_at_exactly_3_days
        """
        rid, cid, pgid, _, pb_id = self._setup_two_products_at_boundary(api)
        # capacity=29, daily=10 → dos=2.9 → strictly below 3.0 → UNDERSTOCK
        resp = api.create_planogram_line(
            rid, cid, pgid,
            {"product_id": pb_id, "position_index": 2, "facings": 3, "capacity_units": 29},
            TEST_USERS["category_manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["days_of_supply"] == pytest.approx(2.9, abs=0.001)
        assert data["dos_flag"] == "UNDERSTOCK"


class TestResetWindowAdjacency:
    def _setup_approved_planogram_store(self, api):
        """Category + supplier + P1 LISTED + planogram APPROVED + store.
        Returns (rid, cid, pgid, stid)."""
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), TEST_USERS["platform_admin_headers"]),
            expected_status=201,
        )
        rid = retailer["id"]
        cat = validate_success(
            api.create_category(
                rid,
                create_category_payload(code="C", role="ROUTINE", annual_sales_cents=100_000, total_linear_feet=20),
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        cid = cat["id"]
        supplier = validate_success(
            api.create_supplier(rid, create_supplier_payload(name="S"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        sid = supplier["id"]
        p1 = validate_success(
            api.create_product(rid, create_product_payload(cid, sid, sku="P1", width_in=6, unit_cost_cents=100, weekly_demand_units=100), TEST_USERS["category_manager_headers"]),
            expected_status=201,
        )
        validate_success(api.list_product_cut_in(rid, p1["id"], TEST_USERS["category_manager_headers"]))
        store = validate_success(
            api.create_store(rid, create_store_payload(store_code="ST1", cluster="BASE"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        pg = validate_success(
            api.create_planogram(rid, cid, create_planogram_payload(name="PG1", variant="BASE"), TEST_USERS["category_manager_headers"]),
            expected_status=201,
        )
        pgid = pg["id"]
        validate_success(
            api.create_planogram_line(
                rid, cid, pgid,
                {"product_id": p1["id"], "position_index": 1, "facings": 5, "capacity_units": 50},
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        captain_headers = make_category_captain_headers(sid)
        validate_success(api.submit_planogram(rid, cid, pgid, captain_headers))
        validate_success(api.approve_planogram(rid, cid, pgid, TEST_USERS["category_manager_headers"]))
        return rid, cid, pgid, store["id"]

    def test_back_to_back_reset_windows_do_not_conflict(self, api):
        """PRD §3.9: "Overlap arithmetic is half-open — a project whose
        `scheduled_start` equals another's `scheduled_end` runs back-to-back
        without conflict"."

        Design: Difficulty/boundary_precision_check/reset_window_back_to_back_vs_overlapping
        """
        rid, cid, pgid, stid = self._setup_approved_planogram_store(api)
        # RP1 [10:00, 12:00) SCHEDULED
        rp1 = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pgid, stid, scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T12:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        validate_success(
            api.schedule_reset_project(
                rid, cid, rp1["id"], {"expected_reset_project_version": rp1["version"]}, TEST_USERS["reset_coordinator_headers"]
            )
        )
        # RP2 [12:00, 14:00) — adjacent; back-to-back must schedule
        rp2 = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pgid, stid, scheduled_start="2026-06-01T12:00:00Z", scheduled_end="2026-06-01T14:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        resp = api.schedule_reset_project(
            rid, cid, rp2["id"], {"expected_reset_project_version": rp2["version"]}, TEST_USERS["reset_coordinator_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "SCHEDULED"

    def test_overlapping_reset_window_rejected(self, api):
        """PRD §3.9: "any violation of these window rules is rejected with
        `ERR_RESET_WINDOW_CONFLICT`."

        Design: Difficulty/boundary_precision_check/reset_window_back_to_back_vs_overlapping
        """
        rid, cid, pgid, stid = self._setup_approved_planogram_store(api)
        # RP1 [10:00, 12:00) SCHEDULED
        rp1 = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pgid, stid, scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T12:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        validate_success(
            api.schedule_reset_project(
                rid, cid, rp1["id"], {"expected_reset_project_version": rp1["version"]}, TEST_USERS["reset_coordinator_headers"]
            )
        )
        # RP3 [11:59, 14:00) — overlaps by 1 minute
        rp3 = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pgid, stid, scheduled_start="2026-06-01T11:59:00Z", scheduled_end="2026-06-01T14:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        resp = api.schedule_reset_project(
            rid, cid, rp3["id"], {"expected_reset_project_version": rp3["version"]}, TEST_USERS["reset_coordinator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_RESET_WINDOW_CONFLICT)
