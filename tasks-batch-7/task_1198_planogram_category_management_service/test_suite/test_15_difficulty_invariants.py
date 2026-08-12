"""Difficulty: compensating_invariant — single active planogram per (cat, variant); crew capacity conserved."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_category_payload,
    create_planogram_payload,
    create_product_payload,
    create_reset_assignment_payload,
    create_reset_crew_payload,
    create_reset_project_payload,
    create_retailer_payload,
    create_store_payload,
    create_supplier_payload,
    make_category_captain_headers,
    setup_approved_planogram,
    validate_success,
)


def _bootstrap_retailer_category_supplier_product(api):
    retailer = validate_success(
        api.create_retailer(create_retailer_payload(name="R"), TEST_USERS["platform_admin_headers"]),
        expected_status=201,
    )
    rid = retailer["id"]
    cat = validate_success(
        api.create_category(
            rid,
            create_category_payload(code="C", role="ROUTINE", annual_sales_cents=100_000, total_linear_feet=10),
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
        api.create_product(
            rid,
            create_product_payload(cid, sid, sku="P1", width_in=6, unit_cost_cents=100, weekly_demand_units=100),
            TEST_USERS["category_manager_headers"],
        ),
        expected_status=201,
    )
    validate_success(api.list_product_cut_in(rid, p1["id"], TEST_USERS["category_manager_headers"]))
    return retailer, cat, supplier, p1


def _build_approved_pg(api, rid, cid, sid, p1_id, *, name, facings):
    pg = validate_success(
        api.create_planogram(rid, cid, create_planogram_payload(name=name, variant="BASE"), TEST_USERS["category_manager_headers"]),
        expected_status=201,
    )
    pgid = pg["id"]
    validate_success(
        api.create_planogram_line(
            rid, cid, pgid,
            {"product_id": p1_id, "position_index": 1, "facings": facings, "capacity_units": 50 if facings == 5 else 80},
            TEST_USERS["category_manager_headers"],
        ),
        expected_status=201,
    )
    captain_headers = make_category_captain_headers(sid)
    validate_success(api.submit_planogram(rid, cid, pgid, captain_headers))
    validate_success(api.approve_planogram(rid, cid, pgid, TEST_USERS["category_manager_headers"]))
    return pgid


class TestSingleActivePerVariantInvariant:
    def test_activation_supersede_conserves_single_active(self, api):
        """PRD §3.5: "no other planogram may currently be `ACTIVE` for the same
        category and `variant`, else `ERR_DUPLICATE_ACTIVE_VARIANT`."
        PRD §3.5: "The previously `ACTIVE` planogram of the same category and
        variant — if one exists — automatically becomes `SUPERSEDED`"."

        Design: Difficulty/compensating_invariant/planogram_activation_supersede_conserves_single_active_per_variant
        """
        retailer, category, supplier, p1 = _bootstrap_retailer_category_supplier_product(api)
        rid, cid, sid, p1_id = retailer["id"], category["id"], supplier["id"], p1["id"]
        pga = _build_approved_pg(api, rid, cid, sid, p1_id, name="PG_A", facings=5)
        cat_v1 = validate_success(api.get_category(rid, cid, TEST_USERS["category_manager_headers"]))["version"]
        validate_success(
            api.activate_planogram(rid, cid, pga, {"expected_category_version": cat_v1}, TEST_USERS["category_manager_headers"])
        )
        pgb = _build_approved_pg(api, rid, cid, sid, p1_id, name="PG_B", facings=8)
        cat_v2 = validate_success(api.get_category(rid, cid, TEST_USERS["category_manager_headers"]))["version"]
        validate_success(
            api.activate_planogram(rid, cid, pgb, {"expected_category_version": cat_v2}, TEST_USERS["category_manager_headers"])
        )
        pga_now = validate_success(api.get_planogram(rid, cid, pga, TEST_USERS["category_manager_headers"]))
        pgb_now = validate_success(api.get_planogram(rid, cid, pgb, TEST_USERS["category_manager_headers"]))
        assert pgb_now["status"] == "ACTIVE"
        assert pga_now["status"] == "SUPERSEDED"

    def test_active_count_per_category_variant_is_one(self, api):
        """PRD §3.5: "no other planogram may currently be `ACTIVE` for the
        same category and `variant`, else `ERR_DUPLICATE_ACTIVE_VARIANT`."

        Design: Difficulty/compensating_invariant/planogram_activation_supersede_conserves_single_active_per_variant
        """
        retailer, category, supplier, p1 = _bootstrap_retailer_category_supplier_product(api)
        rid, cid, sid, p1_id = retailer["id"], category["id"], supplier["id"], p1["id"]
        pga = _build_approved_pg(api, rid, cid, sid, p1_id, name="PG_A", facings=5)
        cat_v1 = validate_success(api.get_category(rid, cid, TEST_USERS["category_manager_headers"]))["version"]
        validate_success(
            api.activate_planogram(rid, cid, pga, {"expected_category_version": cat_v1}, TEST_USERS["category_manager_headers"])
        )
        pgb = _build_approved_pg(api, rid, cid, sid, p1_id, name="PG_B", facings=8)
        cat_v2 = validate_success(api.get_category(rid, cid, TEST_USERS["category_manager_headers"]))["version"]
        validate_success(
            api.activate_planogram(rid, cid, pgb, {"expected_category_version": cat_v2}, TEST_USERS["category_manager_headers"])
        )
        # Count ACTIVE planograms for (cid, BASE)
        resp = api.list_planograms(rid, cid, TEST_USERS["category_manager_headers"], params={"variant": "BASE", "status": "ACTIVE"})
        data = validate_success(resp)
        items = data if isinstance(data, list) else data.get("data", [])
        active_count = sum(1 for p in items if p.get("status") == "ACTIVE" and p.get("variant") == "BASE")
        assert active_count == 1


class TestResetAssignmentReleaseConservesCapacity:
    def _setup_in_progress_project_with_assignment(self, api):
        """Drive RP to IN_PROGRESS with one ASSIGNED assignment on a cap=2 crew."""
        retailer, category, supplier, product, pg, line = setup_approved_planogram(
            product_overrides={"weekly_demand_units": 100}
        )
        rid, cid, pgid = retailer["id"], category["id"], pg["id"]
        store = validate_success(
            api.create_store(rid, create_store_payload(store_code="ST1", cluster="BASE"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        crew = validate_success(
            api.create_reset_crew(rid, create_reset_crew_payload(name="Crew", max_concurrent_projects=2), TEST_USERS["reset_coordinator_headers"]),
            expected_status=201,
        )
        rp = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pgid, store["id"], scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T12:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        rpid, rp_v = rp["id"], rp["version"]
        ra = validate_success(
            api.create_reset_assignment(
                rid, cid, rpid,
                create_reset_assignment_payload(crew["id"], assigned_start="2026-06-01T10:00:00Z", assigned_end="2026-06-01T12:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        raid = ra["id"]
        validate_success(
            api.schedule_reset_project(
                rid, cid, rpid, {"expected_reset_project_version": rp_v}, TEST_USERS["reset_coordinator_headers"]
            )
        )
        # Advance clock past scheduled_start → SCHEDULED → IN_PROGRESS
        validate_success(
            api.set_current_utc(rid, {"to_iso8601": "2026-06-01T10:30:00Z"}, TEST_USERS["platform_admin_headers"])
        )
        return rid, cid, rpid, raid, crew["id"]

    def test_complete_releases_assigned_assignments(self, api):
        """PRD §3.9: "Completion moves the project to `COMPLETED` and releases
        every `ASSIGNED` assignment on it to `RELEASED`."

        Design: Difficulty/compensating_invariant/reset_assignment_release_conserves_crew_capacity
        """
        rid, cid, rpid, raid, crew_id = self._setup_in_progress_project_with_assignment(api)
        validate_success(
            api.complete_reset_project(rid, cid, rpid, TEST_USERS["reset_coordinator_headers"])
        )
        rp_now = validate_success(api.get_reset_project(rid, cid, rpid, TEST_USERS["reset_coordinator_headers"]))
        ra_now = validate_success(api.get_reset_assignment(rid, cid, rpid, raid, TEST_USERS["reset_coordinator_headers"]))
        assert rp_now["status"] == "COMPLETED"
        assert ra_now["status"] == "RELEASED"

    def test_crew_assigned_count_zero_after_completion(self, api):
        """PRD §3.9: "Completion moves the project to `COMPLETED` and releases
        every `ASSIGNED` assignment on it to `RELEASED`."
        PRD §3.9: "at no instant may the count of `ASSIGNED` assignments
        sitting on a crew exceed that crew's `max_concurrent_projects`."

        Design: Difficulty/compensating_invariant/reset_assignment_release_conserves_crew_capacity
        """
        rid, cid, rpid, raid, crew_id = self._setup_in_progress_project_with_assignment(api)
        validate_success(
            api.complete_reset_project(rid, cid, rpid, TEST_USERS["reset_coordinator_headers"])
        )
        # After completion, the crew has zero ASSIGNED assignments.
        # Use the flat /reset-assignments endpoint filtered by crew_id+status.
        resp = api.flat_list_reset_assignments(
            TEST_USERS["reset_coordinator_headers"],
            params={"crew_id": crew_id, "status": "ASSIGNED"},
        )
        data = validate_success(resp)
        items = data if isinstance(data, list) else data.get("data", [])
        remaining = [a for a in items if a.get("status") == "ASSIGNED"]
        assert len(remaining) == 0, f"Expected 0 ASSIGNED assignments after completion, got {remaining!r}"
