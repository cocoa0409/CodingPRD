"""Temporal-overlap rules: half-open lease intervals (adjacency allowed) vs
closed inspector windows (adjacency conflicts)."""
import test_helpers as th
from test_helpers import (
    ApiErrorId,
    api_client,
    create_inspection_payload,
    create_jurisdiction,
    create_property,
    create_tenancy,
    create_unit,
    make_manager_admin_headers,
    make_property_manager_headers,
    validate_error,
    validate_success,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


class TestTenancyLeaseOverlapHalfOpen:
    def _unit_with_first_lease(self):
        jur = create_jurisdiction(interest_required=False, annual_interest_rate_bp=0)
        prop = create_property(jur["id"])
        unit = create_unit(prop["id"])
        ten1 = create_tenancy(unit["id"], tenant_display_name="T One",
                              lease_start_on="2026-01-01", lease_end_on="2027-01-01")
        return unit, ten1

    def test_adjacent_lease_allowed(self):
        """PRD §3.2: "The lease period is a half-open interval that includes
        the start date and excludes the end date: two tenancies on the same
        unit whose intervals merely touch — one ending on the day the next
        begins — are adjacent and allowed, while any genuine overlap is
        rejected with `ERR_UNIT_OCCUPANCY_OVERLAP`."

        [2026-01-01, 2027-01-01) then [2027-01-01, 2028-01-01): created (201).

        Design: Difficulty/resource_temporal_overlap/tenancy_lease_overlap_half_open_adjacency
        """
        unit, _ten1 = self._unit_with_first_lease()
        resp = api_client.create_tenancy(
            {"unit_id": unit["id"], "tenant_display_name": "T Two",
             "lease_start_on": "2027-01-01", "lease_end_on": "2028-01-01",
             "monthly_rent_cents": 150_000, "deposit_cents": 200_000,
             "keys_issued": 2, "fobs_issued": 1},
            PM,
        )
        ten2 = validate_success(resp, expected_status=201)
        assert ten2["unit_id"] == unit["id"]

    def test_interior_overlap_rejected(self):
        """PRD §3.2: "two tenancies on the same unit whose intervals merely
        touch — one ending on the day the next begins — are adjacent and
        allowed, while any genuine overlap is rejected with
        `ERR_UNIT_OCCUPANCY_OVERLAP`."

        [2026-06-01, 2027-06-01) overlaps [2026-01-01, 2027-01-01) in the
        interior: rejected 409.

        Design: Difficulty/resource_temporal_overlap/tenancy_lease_overlap_half_open_adjacency
        """
        unit, _ten1 = self._unit_with_first_lease()
        resp = api_client.create_tenancy(
            {"unit_id": unit["id"], "tenant_display_name": "T Three",
             "lease_start_on": "2026-06-01", "lease_end_on": "2027-06-01",
             "monthly_rent_cents": 150_000, "deposit_cents": 200_000,
             "keys_issued": 2, "fobs_issued": 1},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_OCCUPANCY_OVERLAP)


class TestInspectorWindowClosedInterval:
    def _two_tenancies_and_first_window(self):
        jur = create_jurisdiction(interest_required=False, annual_interest_rate_bp=0)
        prop = create_property(jur["id"])
        unit_a = create_unit(prop["id"], unit_number="1A")
        unit_b = create_unit(prop["id"], unit_number="1B")
        ten_a = create_tenancy(unit_a["id"], tenant_display_name="T A",
                               lease_start_on="2026-01-05", lease_end_on="2027-01-05")
        ten_b = create_tenancy(unit_b["id"], tenant_display_name="T B",
                               lease_start_on="2026-01-05", lease_end_on="2027-01-05")
        resp = api_client.create_inspection(
            create_inspection_payload(
                tenancy_id=ten_a["id"], kind="MOVE_IN",
                inspector_user_id="insp-1",
                scheduled_start_at="2026-01-05T09:00:00Z",
                scheduled_end_at="2026-01-05T10:00:00Z"),
            PM,
        )
        mi_a = validate_success(resp, expected_status=201)
        return ten_a, ten_b, mi_a

    def test_touching_windows_conflict(self):
        """PRD §3.2: "Inspector calendars are protected: the windows of an
        inspector's `DRAFT` inspections are closed intervals that must not
        touch or overlap, so a new window conflicts — and is rejected with
        `ERR_INSPECTOR_SCHEDULE_CONFLICT` — whenever the new start falls at or
        before an existing window's end while that existing window's start
        falls at or before the new end; mere adjacency at an endpoint
        therefore already counts as a conflict."

        insp-1 holds DRAFT 09:00-10:00; a second DRAFT for insp-1 starting
        exactly at 10:00 conflicts.

        Design: Difficulty/resource_temporal_overlap/inspector_window_closed_interval_adjacency_conflicts
        """
        _ten_a, ten_b, _mi_a = self._two_tenancies_and_first_window()
        resp = api_client.create_inspection(
            create_inspection_payload(
                tenancy_id=ten_b["id"], kind="MOVE_IN",
                inspector_user_id="insp-1",
                scheduled_start_at="2026-01-05T10:00:00Z",
                scheduled_end_at="2026-01-05T11:00:00Z"),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT)

    def test_same_window_other_inspector_allowed(self):
        """PRD §3.2: "the windows of an inspector's `DRAFT` inspections are
        closed intervals that must not touch or overlap" — the constraint
        ranges over one inspector's own windows.

        The identical window for a different inspector (insp-2) is created
        (201, DRAFT).

        Design: Difficulty/resource_temporal_overlap/inspector_window_closed_interval_adjacency_conflicts
        """
        _ten_a, ten_b, _mi_a = self._two_tenancies_and_first_window()
        resp = api_client.create_inspection(
            create_inspection_payload(
                tenancy_id=ten_b["id"], kind="MOVE_IN",
                inspector_user_id="insp-2",
                scheduled_start_at="2026-01-05T10:00:00Z",
                scheduled_end_at="2026-01-05T11:00:00Z"),
            PM,
        )
        mi_b = validate_success(resp, expected_status=201)
        assert mi_b["status"] == "DRAFT"
        assert mi_b["inspector_user_id"] == "insp-2"
