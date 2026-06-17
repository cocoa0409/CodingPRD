"""Crew and equipment booking conflicts: half-open crew overlap, buffered
equipment overlap, adjacency, FK validation, window ordering. Covers §3.8.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_project, create_crew, create_equipment, book_crew,
    create_crew_assignment_payload,
    TEST_USERS,
)

PM = TEST_USERS["project_manager_headers"]


class TestCrewOverlap:
    def test_overlapping_crew_window_rejected(self, api):
        """PRD §3.8: "A new assignment for a given crew_id is rejected with
        ERR_CREW_DOUBLE_BOOKED (HTTP 409) when its half-open window overlaps the
        window of any existing BOOKED assignment for the same crew; because the
        intervals are half-open, two windows that merely touch - one ending exactly
        when the next begins - do not overlap and are allowed."

        Design: Difficulty/resource_temporal_overlap/crew_plain_half_open_overlap
        """
        crew = create_crew(crew_name="C6")
        p1 = create_project(site_name="Crew P1")
        book_crew(p1["id"], crew["id"], "2026-07-01T10:00:00Z", "2026-07-01T14:00:00Z")
        p2 = create_project(site_name="Crew P2")
        # [13:00,15:00) overlaps the existing [10:00,14:00).
        res = api.create_crew_assignment(
            p2["id"],
            create_crew_assignment_payload(crew["id"], "2026-07-01T13:00:00Z", "2026-07-01T15:00:00Z"),
            PM)
        validate_error(res, "ERR_CREW_DOUBLE_BOOKED")

    def test_disjoint_crew_window_allowed(self, api):
        """PRD §3.8: "A new assignment for a given crew_id is rejected with
        ERR_CREW_DOUBLE_BOOKED (HTTP 409) when its half-open window overlaps the
        window of any existing BOOKED assignment for the same crew"

        Design: Difficulty/resource_temporal_overlap/crew_plain_half_open_overlap
        """
        crew = create_crew(crew_name="C6b")
        p1 = create_project(site_name="Crew P3")
        book_crew(p1["id"], crew["id"], "2026-07-01T10:00:00Z", "2026-07-01T14:00:00Z")
        p2 = create_project(site_name="Crew P4")
        # A fully disjoint, later window [16:00,18:00) does not overlap [10:00,14:00).
        ca = validate_success(api.create_crew_assignment(
            p2["id"],
            create_crew_assignment_payload(crew["id"], "2026-07-01T16:00:00Z", "2026-07-01T18:00:00Z"),
            PM), 201)
        assert ca["status"] == "BOOKED"

    def test_adjacent_crew_window_allowed(self, api):
        """PRD §3.8: "because the intervals are half-open, two windows that merely
        touch - one ending exactly when the next begins - do not overlap and are
        allowed."

        Design: Corner/validations/crew_adjacent_window_not_overlap_succeeds
        """
        crew = create_crew(crew_name="Adj")
        p1 = create_project(site_name="AdjP1")
        book_crew(p1["id"], crew["id"], "2026-07-01T10:00:00Z", "2026-07-01T14:00:00Z")
        p2 = create_project(site_name="AdjP2")
        # [14:00,16:00) is exactly adjacent to [10:00,14:00) -> allowed.
        res = api.create_crew_assignment(
            p2["id"],
            create_crew_assignment_payload(crew["id"], "2026-07-01T14:00:00Z", "2026-07-01T16:00:00Z"),
            PM)
        ca = validate_success(res, 201)
        assert ca["status"] == "BOOKED"


class TestEquipmentOverlap:
    def test_buffered_equipment_window_rejected(self, api):
        """PRD §3.8: "A new assignment for a given equipment_id is rejected with
        ERR_EQUIPMENT_DOUBLE_BOOKED (HTTP 409) when its window, after each existing
        equipment booking is expanded by a two-hour cleandown buffer on each side,
        falls inside that buffered span."
        PRD §3.8: "Concretely, an existing booking running from its start to its
        end is treated as occupying from two hours before its start up to two hours
        after its end; a new window that touches that buffered edge exactly does
        not collide, but a window that reaches inside it does."

        Design: Difficulty/resource_temporal_overlap/equipment_buffered_interval_overlap
        """
        crew_a = create_crew(crew_name="C7", skill="PAVING")
        crew_b = create_crew(crew_name="C8", skill="PAVING")
        eq = create_equipment(asset_name="Pump-1", asset_type="PUMP_TRUCK")
        p1 = create_project(site_name="Eq P1")
        book_crew(p1["id"], crew_a["id"], "2026-07-01T10:00:00Z", "2026-07-01T12:00:00Z",
                  equipment_id=eq["id"])
        p2 = create_project(site_name="Eq P2")
        # Existing [10:00,12:00) buffered to [08:00,14:00); new [13:00,15:00) is inside it.
        res = api.create_crew_assignment(
            p2["id"],
            create_crew_assignment_payload(
                crew_b["id"], "2026-07-01T13:00:00Z", "2026-07-01T15:00:00Z",
                equipment_id=eq["id"]),
            PM)
        validate_error(res, "ERR_EQUIPMENT_DOUBLE_BOOKED")

    def test_equipment_window_touching_buffered_edge_allowed(self, api):
        """PRD §3.8: "a new window that touches that buffered edge exactly does not
        collide, but a window that reaches inside it does."

        Design: Difficulty/resource_temporal_overlap/equipment_buffered_interval_overlap
        """
        crew_a = create_crew(crew_name="C7b", skill="PAVING")
        crew_b = create_crew(crew_name="C8b", skill="PAVING")
        eq = create_equipment(asset_name="Pump-2", asset_type="PUMP_TRUCK")
        p1 = create_project(site_name="Eq P3")
        book_crew(p1["id"], crew_a["id"], "2026-07-01T10:00:00Z", "2026-07-01T12:00:00Z",
                  equipment_id=eq["id"])
        p2 = create_project(site_name="Eq P4")
        # Existing [10:00,12:00) buffered to [08:00,14:00); a new [14:00,16:00) touches
        # the buffered edge exactly and is therefore allowed.
        ca = validate_success(api.create_crew_assignment(
            p2["id"],
            create_crew_assignment_payload(
                crew_b["id"], "2026-07-01T14:00:00Z", "2026-07-01T16:00:00Z",
                equipment_id=eq["id"]),
            PM), 201)
        assert ca["status"] == "BOOKED"


class TestBookingValidation:
    def test_fk_not_found_on_missing_crew(self, api):
        """PRD §2.5: "When a body foreign key points at a resource that does not
        exist, the request is rejected with ERR_FK_NOT_FOUND (HTTP 404)."

        Design: Corner/validations/fk_not_found_on_crew_assignment
        """
        proj = create_project(site_name="Fk")
        res = api.create_crew_assignment(
            proj["id"],
            create_crew_assignment_payload(
                "00000000-0000-4000-8000-0000000000ff",
                "2026-07-01T10:00:00Z", "2026-07-01T12:00:00Z"),
            PM)
        validate_error(res, "ERR_FK_NOT_FOUND")

    def test_invalid_window_order_rejected(self, api):
        """PRD §3.8: "a booking window defined by window_start and window_end, where
        window_end must be strictly after window_start."

        Design: Corner/errors/invalid_window_order_returns_invalid_request
        """
        crew = create_crew(crew_name="Bad")
        proj = create_project(site_name="BadW")
        res = api.create_crew_assignment(
            proj["id"],
            create_crew_assignment_payload(crew["id"], "2026-07-01T14:00:00Z", "2026-07-01T10:00:00Z"),
            PM)
        validate_error(res, "ERR_INVALID_REQUEST")


def test_list_crew_assignments_filtered_by_crew_id(api):
    """PRD §4 (endpoint): GET /crew-assignments "List crew assignments filtered by
    crew or equipment".
    PRD §3.8: "A ProjectManager books a crew onto a project by creating a
    CrewAssignment, supplying the crew_id of the crew"

    Design: Corner/endpoints/list_crew_assignments_filtered_by_crew_id
    """
    crew = create_crew(crew_name="Filt")
    proj = create_project(site_name="FiltP")
    book_crew(proj["id"], crew["id"], "2026-07-01T10:00:00Z", "2026-07-01T12:00:00Z")
    data, meta = validate_paginated(api.list_crew_assignments(PM, params={"crew_id": crew["id"]}))
    assert meta["total_count"] == 1
