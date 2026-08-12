"""Difficulty: transitive_cascade — planogram activate cascade; audit fail cascade."""
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
    setup_active_planogram,
    setup_submitted_audit,
    validate_success,
)


def _build_planogram_with_state(api, rid, cid, sid, products, *, name, facings, target_state):
    """Build a planogram with one line and walk to APPROVED or ACTIVE."""
    pg = validate_success(
        api.create_planogram(rid, cid, create_planogram_payload(name=name, variant="BASE"), TEST_USERS["category_manager_headers"]),
        expected_status=201,
    )
    pgid = pg["id"]
    p1_id = products["P1"]["id"]
    validate_success(
        api.create_planogram_line(
            rid, cid, pgid,
            {"product_id": p1_id, "position_index": 1, "facings": facings, "capacity_units": 100},
            TEST_USERS["category_manager_headers"],
        ),
        expected_status=201,
    )
    captain_headers = make_category_captain_headers(sid)
    validate_success(api.submit_planogram(rid, cid, pgid, captain_headers))
    validate_success(api.approve_planogram(rid, cid, pgid, TEST_USERS["category_manager_headers"]))
    if target_state == "ACTIVE":
        cat_now = validate_success(api.get_category(rid, cid, TEST_USERS["category_manager_headers"]))
        validate_success(
            api.activate_planogram(rid, cid, pgid, {"expected_category_version": cat_now["version"]}, TEST_USERS["category_manager_headers"])
        )
    return pgid


def _bootstrap_retailer_category_supplier_product(api):
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
        api.create_product(
            rid,
            create_product_payload(cid, sid, sku="P1", width_in=6, unit_cost_cents=100, weekly_demand_units=100),
            TEST_USERS["category_manager_headers"],
        ),
        expected_status=201,
    )
    validate_success(api.list_product_cut_in(rid, p1["id"], TEST_USERS["category_manager_headers"]))
    return retailer, cat, supplier, {"P1": p1}


class TestPlanogramActivateCascade:
    def _setup_cascade_scenario(self, api):
        """PG_A ACTIVE; ResetProject SCHEDULED on PG_A with ASSIGNED crew; PG_B APPROVED."""
        retailer, category, supplier, products = _bootstrap_retailer_category_supplier_product(api)
        rid, cid, sid = retailer["id"], category["id"], supplier["id"]
        store = validate_success(
            api.create_store(rid, create_store_payload(store_code="ST1", cluster="BASE"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        crew = validate_success(
            api.create_reset_crew(rid, create_reset_crew_payload(name="Crew1", max_concurrent_projects=2), TEST_USERS["reset_coordinator_headers"]),
            expected_status=201,
        )
        pga = _build_planogram_with_state(api, rid, cid, sid, products, name="PG_A", facings=5, target_state="ACTIVE")
        rp = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pga, store["id"], scheduled_start="2026-06-01T08:00:00Z", scheduled_end="2026-06-01T16:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        rpid, rp_v = rp["id"], rp["version"]
        ra = validate_success(
            api.create_reset_assignment(
                rid, cid, rpid,
                create_reset_assignment_payload(crew["id"], assigned_start="2026-06-01T09:00:00Z", assigned_end="2026-06-01T12:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        validate_success(
            api.schedule_reset_project(rid, cid, rpid, {"expected_reset_project_version": rp_v}, TEST_USERS["reset_coordinator_headers"])
        )
        pgb = _build_planogram_with_state(api, rid, cid, sid, products, name="PG_B", facings=8, target_state="APPROVED")
        return retailer, category, supplier, store, crew, pga, pgb, rpid, ra["id"]

    def test_activate_cancels_scheduled_reset_project(self, api):
        """PRD §3.5: "any reset project still referencing the superseded
        planogram in `PROPOSED` or `SCHEDULED` status is moved to `CANCELLED`."

        Design: Difficulty/transitive_cascade/planogram_activate_cascade_to_reset_assignment_release
        """
        retailer, category, supplier, store, crew, pga, pgb, rpid, raid = self._setup_cascade_scenario(api)
        rid, cid = retailer["id"], category["id"]
        cat_now = validate_success(api.get_category(rid, cid, TEST_USERS["category_manager_headers"]))
        validate_success(
            api.activate_planogram(rid, cid, pgb, {"expected_category_version": cat_now["version"]}, TEST_USERS["category_manager_headers"])
        )
        pga_now = validate_success(api.get_planogram(rid, cid, pga, TEST_USERS["category_manager_headers"]))
        pgb_now = validate_success(api.get_planogram(rid, cid, pgb, TEST_USERS["category_manager_headers"]))
        rp_now = validate_success(api.get_reset_project(rid, cid, rpid, TEST_USERS["reset_coordinator_headers"]))
        assert pgb_now["status"] == "ACTIVE"
        assert pga_now["status"] == "SUPERSEDED"
        assert rp_now["status"] == "CANCELLED"

    def test_activate_cascade_releases_assigned_assignments(self, api):
        """PRD §3.5: "every `ASSIGNED` crew assignment under those cancelled
        projects is released to `RELEASED` — a depth-two cascade that keeps
        labor commitments honest against a layout that no longer exists."

        Design: Difficulty/transitive_cascade/planogram_activate_cascade_to_reset_assignment_release
        """
        retailer, category, supplier, store, crew, pga, pgb, rpid, raid = self._setup_cascade_scenario(api)
        rid, cid = retailer["id"], category["id"]
        cat_now = validate_success(api.get_category(rid, cid, TEST_USERS["category_manager_headers"]))
        validate_success(
            api.activate_planogram(rid, cid, pgb, {"expected_category_version": cat_now["version"]}, TEST_USERS["category_manager_headers"])
        )
        ra_now = validate_success(
            api.get_reset_assignment(rid, cid, rpid, raid, TEST_USERS["reset_coordinator_headers"])
        )
        assert ra_now["status"] == "RELEASED"


class TestAuditFailCascade:
    def _setup_audit_with_low_score(self, api, matched: int, total_facings: int):
        """ACTIVE planogram with `total_facings` facings; audit submitted.
        Returns (rid, cid, sid_retailer, pgid, stid, aid) ready to score."""
        retailer, category, supplier, product, pg, store, audit = setup_submitted_audit(
            product_overrides={"weekly_demand_units": 100},
            line_overrides={"facings": total_facings, "capacity_units": total_facings * 10, "position_index": 1},
            retailer_overrides={"compliance_threshold_pct": 85},
        )
        return retailer, category, supplier, pg, store, audit

    def test_audit_fail_creates_proposed_reset_project(self, api):
        """PRD §3.7: "When the outcome is `FAIL` and the audited planogram is
        still `ACTIVE`, the platform automatically creates a new reset project
        in `PROPOSED` status for the store, the planogram's category, and that
        planogram, carrying a fourteen-day window that starts tomorrow"."

        Design: Difficulty/transitive_cascade/audit_fail_cascade_to_reset_project_creation
        """
        # PG total_facings=10; matched=3 → score = floor(30) = 30 → FAIL (threshold 85).
        retailer, category, supplier, pg, store, audit = self._setup_audit_with_low_score(api, 3, 10)
        rid, cid, stid, pgid = retailer["id"], category["id"], store["id"], pg["id"]
        aid = audit["id"]
        resp = api.score_audit(rid, stid, aid, {"matched_facings": 3}, TEST_USERS["audit_reviewer_headers"])
        data = validate_success(resp)
        assert data["compliance_outcome"] == "FAIL"
        # Cascade: a new PROPOSED reset project must exist referencing this planogram+store
        projects_resp = api.list_reset_projects(rid, cid, TEST_USERS["reset_coordinator_headers"])
        projects_data = validate_success(projects_resp)
        project_list = projects_data if isinstance(projects_data, list) else projects_data.get("data", [])
        assert isinstance(project_list, list)
        matches = [
            p for p in project_list
            if p.get("planogram_id") == pgid and p.get("store_id") == stid and p.get("status") == "PROPOSED"
        ]
        assert len(matches) >= 1, (
            f"Expected at least one PROPOSED ResetProject for (store={stid}, planogram={pgid}); "
            f"got {project_list!r}"
        )

    def test_audit_fail_cascade_reset_project_references_planogram_category(self, api):
        """PRD §3.7: "the platform automatically creates a new reset project in
        `PROPOSED` status for the store, the planogram's category, and that
        planogram"."

        Design: Difficulty/transitive_cascade/audit_fail_cascade_to_reset_project_creation
        """
        # PG total_facings=10; matched=1 → score = floor(10) = 10 → FAIL (threshold 85).
        retailer, category, supplier, pg, store, audit = self._setup_audit_with_low_score(api, 1, 10)
        rid, cid, stid, pgid = retailer["id"], category["id"], store["id"], pg["id"]
        aid = audit["id"]
        resp = api.score_audit(rid, stid, aid, {"matched_facings": 1}, TEST_USERS["audit_reviewer_headers"])
        data = validate_success(resp)
        assert data["compliance_outcome"] == "FAIL"
        projects_resp = api.list_reset_projects(rid, cid, TEST_USERS["reset_coordinator_headers"])
        projects_data = validate_success(projects_resp)
        project_list = projects_data if isinstance(projects_data, list) else projects_data.get("data", [])
        matches = [
            p for p in project_list
            if p.get("planogram_id") == pgid and p.get("category_id") == cid and p.get("status") == "PROPOSED"
        ]
        assert len(matches) >= 1
