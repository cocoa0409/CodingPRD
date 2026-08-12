"""Difficulty: resource_temporal_overlap — store geometric overlap; crew aggregate capacity."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_reset_assignment_payload,
    create_reset_crew_payload,
    create_reset_project_payload,
    create_store_payload,
    setup_approved_planogram,
    validate_error,
    validate_success,
)


class TestStoreGeometricOverlap:
    def _setup_one_scheduled_project(self, api):
        """One APPROVED planogram, one store, one SCHEDULED RP [10:00, 12:00).
        Returns (rid, cid, pgid, stid, rp1_id)."""
        retailer, category, supplier, product, pg, line = setup_approved_planogram(
            product_overrides={"weekly_demand_units": 100}
        )
        rid, cid, pgid = retailer["id"], category["id"], pg["id"]
        store = validate_success(
            api.create_store(rid, create_store_payload(store_code="ST1", cluster="BASE"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        rp1 = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pgid, store["id"], scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T12:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        validate_success(
            api.schedule_reset_project(
                rid, cid, rp1["id"], {"expected_reset_project_version": rp1["version"]}, TEST_USERS["reset_coordinator_headers"]
            )
        )
        return rid, cid, pgid, store["id"], rp1["id"]

    def test_overlapping_window_rejected(self, api):
        """PRD §3.9: "no overlap with any other project at the same store that
        is currently `SCHEDULED` or `IN_PROGRESS`. ... any violation of these
        window rules is rejected with `ERR_RESET_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/store_reset_window_geometric_overlap
        """
        rid, cid, pgid, stid, _ = self._setup_one_scheduled_project(api)
        rp2 = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pgid, stid, scheduled_start="2026-06-01T11:00:00Z", scheduled_end="2026-06-01T13:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        resp = api.schedule_reset_project(
            rid, cid, rp2["id"], {"expected_reset_project_version": rp2["version"]}, TEST_USERS["reset_coordinator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_RESET_WINDOW_CONFLICT)

    def test_fully_contained_window_rejected(self, api):
        """PRD §3.9: "no overlap with any other project at the same store that
        is currently `SCHEDULED` or `IN_PROGRESS`."

        Design: Difficulty/resource_temporal_overlap/store_reset_window_geometric_overlap
        """
        rid, cid, pgid, stid, _ = self._setup_one_scheduled_project(api)
        # Fully-contained window [10:30, 11:30) inside existing [10:00, 12:00)
        rp2 = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pgid, stid, scheduled_start="2026-06-01T10:30:00Z", scheduled_end="2026-06-01T11:30:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        resp = api.schedule_reset_project(
            rid, cid, rp2["id"], {"expected_reset_project_version": rp2["version"]}, TEST_USERS["reset_coordinator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_RESET_WINDOW_CONFLICT)


class TestCrewAggregateCapacity:
    def _setup_two_scheduled_projects(self, api):
        """Two SCHEDULED projects on DIFFERENT stores, each on the same approved planogram,
        with crew cap=1 already assigned to RP1. Returns (rid, cid, pgid, crew_id, rp1_id, rp2_id)."""
        retailer, category, supplier, product, pg, line = setup_approved_planogram(
            product_overrides={"weekly_demand_units": 100}
        )
        rid, cid, pgid = retailer["id"], category["id"], pg["id"]
        st1 = validate_success(
            api.create_store(rid, create_store_payload(store_code="ST1", cluster="BASE"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        st2 = validate_success(
            api.create_store(rid, create_store_payload(store_code="ST2", cluster="BASE"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        crew = validate_success(
            api.create_reset_crew(rid, create_reset_crew_payload(name="Crew", max_concurrent_projects=1), TEST_USERS["reset_coordinator_headers"]),
            expected_status=201,
        )
        rp1 = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pgid, st1["id"], scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T12:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        validate_success(
            api.schedule_reset_project(
                rid, cid, rp1["id"], {"expected_reset_project_version": rp1["version"]}, TEST_USERS["reset_coordinator_headers"]
            )
        )
        validate_success(
            api.create_reset_assignment(
                rid, cid, rp1["id"],
                create_reset_assignment_payload(crew["id"], assigned_start="2026-06-01T10:00:00Z", assigned_end="2026-06-01T12:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        rp2 = validate_success(
            api.create_reset_project(
                rid, cid,
                create_reset_project_payload(pgid, st2["id"], scheduled_start="2026-06-01T11:00:00Z", scheduled_end="2026-06-01T13:00:00Z"),
                TEST_USERS["reset_coordinator_headers"],
            ),
            expected_status=201,
        )
        validate_success(
            api.schedule_reset_project(
                rid, cid, rp2["id"], {"expected_reset_project_version": rp2["version"]}, TEST_USERS["reset_coordinator_headers"]
            )
        )
        return rid, cid, rp1["id"], rp2["id"], crew["id"]

    def test_crew_capacity_exceeded_rejected(self, api):
        """PRD §3.9: "at no instant may the count of `ASSIGNED` assignments
        sitting on a crew exceed that crew's `max_concurrent_projects`. ...
        all reported as `ERR_CREW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/crew_assignment_aggregate_capacity_overlap
        """
        rid, cid, rp1, rp2, crew_id = self._setup_two_scheduled_projects(api)
        # Crew already has one ASSIGNED in [10:00, 12:00); max_concurrent_projects=1.
        # New assignment [11:00, 13:00) overlaps in time → capacity exceeded.
        resp = api.create_reset_assignment(
            rid, cid, rp2,
            create_reset_assignment_payload(crew_id, assigned_start="2026-06-01T11:00:00Z", assigned_end="2026-06-01T13:00:00Z"),
            TEST_USERS["reset_coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CREW_OVERLAP)

    def test_crew_capacity_overlap_even_when_stores_differ(self, api):
        """PRD §3.9: "the assigned window must lie entirely inside its
        project's scheduled window; it must not overlap — again using
        half-open arithmetic, so back-to-back assignments are fine — any other
        `ASSIGNED` assignment belonging to the same crew; and at no instant
        may the count of `ASSIGNED` assignments sitting on a crew exceed that
        crew's `max_concurrent_projects`."

        Design: Difficulty/resource_temporal_overlap/crew_assignment_aggregate_capacity_overlap
        """
        # Variant: even though the two RPs are on different stores (so no
        # geometric RP-window conflict), the crew's aggregate capacity still
        # blocks the second assignment.
        rid, cid, rp1, rp2, crew_id = self._setup_two_scheduled_projects(api)
        # Try assigning the same crew to RP2 inside its [11:00, 13:00) window —
        # the crew capacity is exceeded at the overlap instant.
        resp = api.create_reset_assignment(
            rid, cid, rp2,
            create_reset_assignment_payload(crew_id, assigned_start="2026-06-01T11:30:00Z", assigned_end="2026-06-01T12:30:00Z"),
            TEST_USERS["reset_coordinator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CREW_OVERLAP)
