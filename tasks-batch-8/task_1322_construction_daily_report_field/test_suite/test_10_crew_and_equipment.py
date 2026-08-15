"""Manpower band boundaries, equipment capacity, register filters, immediacy."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_crew_entry,
    api_client,
    create_equipment_entry_payload,
    get_report,
    make_active_project,
    make_report,
    make_work_area,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_SUPT = TEST_USERS["superintendent_headers"]


class TestManpowerBandBoundaries:
    def test_exactly_eight_and_twelve_hours_hit_band_edges(self, api):
        """PRD section 3.3: "a worker logging exactly eight hours accrues zero
        overtime, and a worker logging exactly twelve hours accrues exactly four
        overtime hours and zero double time." and "Report totals aggregate
        active lines only. `total_workers` sums `worker_count` over `ACTIVE`
        crew entries, and `manhours_regular`, `manhours_ot`, and `manhours_dt`
        sum the per-line band figures over `ACTIVE` rows".

        Design: Difficulty/boundary_precision_check/ot_boundary_exactly_eight_and_twelve_hours
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        report = make_report(project["id"])

        ce1 = add_crew_entry(report["id"], area["id"], worker_count=3,
                             hours_per_worker=8.0, work_performed="framing")
        assert ce1["regular_hours"] == pytest.approx(24.00, abs=1e-9)
        assert ce1["ot_hours"] == pytest.approx(0.00, abs=1e-9), \
            "8.0 exactly is all regular; OT starts strictly above 8"
        assert ce1["dt_hours"] == pytest.approx(0.00, abs=1e-9)

        ce2 = add_crew_entry(report["id"], area["id"], trade="Electric",
                             worker_count=2, hours_per_worker=12.0,
                             work_performed="overtime pull")
        assert ce2["regular_hours"] == pytest.approx(16.00, abs=1e-9)
        assert ce2["ot_hours"] == pytest.approx(8.00, abs=1e-9), \
            "12.0 exactly caps the OT band at 4 per worker"
        assert ce2["dt_hours"] == pytest.approx(0.00, abs=1e-9), \
            "DT starts strictly above 12"

        totals = get_report(report["id"])
        assert totals["total_workers"] == 5
        assert totals["manhours_regular"] == pytest.approx(40.00, abs=1e-9)
        assert totals["manhours_ot"] == pytest.approx(8.00, abs=1e-9)
        assert totals["manhours_dt"] == pytest.approx(0.00, abs=1e-9)

    def test_just_past_the_band_edges(self, api):
        """PRD section 3.3: "Its `ot_hours` are `worker_count` multiplied by the
        smaller of (the excess of `hours_per_worker` above eight, never below
        zero) and four — overtime covers only the band strictly above eight
        hours and up to twelve. Its `dt_hours` are `worker_count` multiplied by
        the excess of `hours_per_worker` above twelve, never below zero".

        Design: Difficulty/boundary_precision_check/ot_boundary_exactly_eight_and_twelve_hours
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        report = make_report(project["id"])

        ce1 = add_crew_entry(report["id"], area["id"], worker_count=1,
                             hours_per_worker=8.5)
        assert ce1["regular_hours"] == pytest.approx(8.00, abs=1e-9)
        assert ce1["ot_hours"] == pytest.approx(0.50, abs=1e-9)
        assert ce1["dt_hours"] == pytest.approx(0.00, abs=1e-9)

        ce2 = add_crew_entry(report["id"], area["id"], worker_count=1,
                             hours_per_worker=12.5)
        assert ce2["regular_hours"] == pytest.approx(8.00, abs=1e-9)
        assert ce2["ot_hours"] == pytest.approx(4.00, abs=1e-9)
        assert ce2["dt_hours"] == pytest.approx(0.50, abs=1e-9)

        totals = get_report(report["id"])
        assert totals["total_workers"] == 2
        assert totals["manhours_regular"] == pytest.approx(16.00, abs=1e-9)
        assert totals["manhours_ot"] == pytest.approx(4.50, abs=1e-9)
        assert totals["manhours_dt"] == pytest.approx(0.50, abs=1e-9)


class TestEquipmentCapacity:
    def test_capacity_equality_allowed_one_cent_over_rejected(self, api):
        """PRD section 3.3: "the sum of `hours_used` and `hours_idle` must not
        exceed twenty-four hours per unit multiplied by `unit_count`, with
        equality allowed — a breach is rejected with
        `ERR_EQUIPMENT_CAPACITY_EXCEEDED`."

        Design: Corner/validations/equipment_capacity_boundary_exact
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        report = make_report(project["id"])

        ok = validate_success(api_client.create_equipment_entry(
            create_equipment_entry_payload(report["id"], area["id"],
                                           unit_count=2, hours_used=24,
                                           hours_idle=24),
            _SUPT), 201)
        assert ok["id"], "48.00 hours on 2 units (cap 48) is allowed"

        over = api_client.create_equipment_entry(
            create_equipment_entry_payload(report["id"], area["id"],
                                           unit_count=2, hours_used=24,
                                           hours_idle=24.01),
            _SUPT)
        validate_error(over, ApiErrorId.ERR_EQUIPMENT_CAPACITY_EXCEEDED)
        assert over.status_code == 422


class TestRegisterFilters:
    def test_crew_entries_filter_by_report_and_area(self, api):
        """PRD section 3.3: "Both registers can be listed filtered by
        `report_id`, `work_area_id`, and `status`."

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        project = make_active_project()
        a1 = make_work_area(project["id"])
        a2 = make_work_area(project["id"])
        r1 = make_report(project["id"], report_date="2026-08-04")
        r2 = make_report(project["id"], report_date="2026-08-05")

        add_crew_entry(r1["id"], a1["id"], worker_count=1)
        add_crew_entry(r2["id"], a1["id"], worker_count=2)
        add_crew_entry(r2["id"], a2["id"], worker_count=3)

        by_report, meta_r = validate_paginated(api_client.list_crew_entries(
            _SUPT, params={"report_id": r2["id"]}))
        assert len(by_report) == 2 and meta_r["total_count"] == 2

        by_area, meta_a = validate_paginated(api_client.list_crew_entries(
            _SUPT, params={"work_area_id": a1["id"]}))
        assert len(by_area) == 2 and meta_a["total_count"] == 2

        by_both, meta_b = validate_paginated(api_client.list_crew_entries(
            _SUPT, params={"report_id": r2["id"], "work_area_id": a2["id"]}))
        assert len(by_both) == 1 and meta_b["total_count"] == 1
        assert by_both[0]["worker_count"] == 3


class TestImmediateConsistency:
    def test_child_write_visible_in_response_and_immediate_read(self, api):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in
        the data field." PRD section 2.6: "Almost every child-entry write or
        transition on a report — crew, equipment, weather, delay, safety,
        incident, media, delivery, and quantity activity, distribution sends,
        and the report's own lifecycle transitions — advances the parent
        report's `version` by one and refreshes its `updated_at`."

        Design: Corner/consistency_model/immediate_consistency_same_request_response
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        report = make_report(project["id"])
        version_before = report["version"]

        entry = validate_success(api_client.create_crew_entry(
            {"report_id": report["id"], "work_area_id": area["id"],
             "subcontractor": "S", "trade": "T", "worker_count": 2,
             "hours_per_worker": 10, "work_performed": "w"},
            _SUPT), 201)
        # The create response already carries the computed band split.
        assert entry["regular_hours"] == pytest.approx(16.00, abs=1e-9)
        assert entry["ot_hours"] == pytest.approx(4.00, abs=1e-9)

        after = get_report(report["id"])
        assert after["total_workers"] == 2
        assert after["manhours_regular"] == pytest.approx(16.00, abs=1e-9)
        assert after["manhours_ot"] == pytest.approx(4.00, abs=1e-9)
        assert after["version"] == version_before + 1, \
            "the child write advances the parent report's version by one"
