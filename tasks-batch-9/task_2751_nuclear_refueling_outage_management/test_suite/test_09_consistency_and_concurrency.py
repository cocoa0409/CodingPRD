"""Consistency model: a write's own response already carries every computed
figure, and a cascade's effects are readable on the very next request."""

import pytest

from test_helpers import (
    AlaraPosture,
    CLOCK_EPOCH,
    DoseDirection,
    DoseReason,
    HoldPointType,
    OutageStatus,
    RwpStatus,
    StartupTestStatus,
    StationUnit,
    WorkOrderType,
    api_client,
    given_approved_core_load_pattern,
    given_approved_work_order,
    given_draft_rwp,
    given_outage,
    given_rad_area,
    make_outage_director_headers,
    make_rad_protection_manager_headers,
    make_rad_protection_planner_headers,
    make_reactor_engineer_headers,
    make_regulatory_affairs_headers,
    make_station_admin_headers,
    read_outage,
    read_rwp,
    set_clock,
    validate_paginated,
    validate_success,
)


class TestReviewResponseCarriesItsComputedIndices:
    def test_the_closing_write_returns_the_finished_figures_and_the_read_adds_nothing(self):
        """The review request supplies only actual duration and cost, yet its own
        response already carries all six performance figures; the follow-up read
        returns the identical numbers rather than a value that settled later.

        PRD 4: "Creating a new resource returns HTTP 201 with the created resource
        in `data`; every other successful operation, including every state
        transition and every read, returns HTTP 200 with the affected resource — or
        the requested collection — in `data`."

        PRD 3.9: "The rounding order is pinned: each variance percentage is rounded
        to two decimal places first, each rounded percentage is then multiplied by
        its weight, the three products are summed without intermediate rounding,
        and the single subtraction of that sum from 100 is rounded half up to two
        decimal places once at the end."

        Design: Corner/consistency_model/the_post_outage_review_response_already_carries_its_computed_indices
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        given_approved_core_load_pattern(
            outage["id"],
            cycle_length_mwd_mtu=18000,
            fresh_assembly_count=88,
            discharge_assembly_count=80,
        )
        work_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="Reactor coolant pump seal",
            estimated_hours=20,
            estimated_cost_usd=60000,
            estimated_dose_mrem=0,
        )
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
        validate_success(
            api_client.commence_execution(outage["id"], make_outage_director_headers())
        )
        startup_test = validate_success(
            api_client.create_startup_test(
                outage["id"],
                {
                    "test_code": "RCS-HEATUP",
                    "sequence_index": 1,
                    "hold_point_type": HoldPointType.STATION,
                    "predicted_reactivity_pcm": 500,
                },
                make_reactor_engineer_headers("re-alpha"),
            ),
            201,
        )
        validate_success(
            api_client.defer_work_order(
                work_order["id"], "Removed from outage scope", make_outage_director_headers()
            )
        )
        validate_success(
            api_client.authorize_startup(outage["id"], make_outage_director_headers())
        )
        satisfied = validate_success(
            api_client.satisfy_startup_test(
                startup_test["id"], 500, make_regulatory_affairs_headers("ra-1")
            )
        )
        assert satisfied["status"] == StartupTestStatus.SATISFIED
        assert read_outage(outage["id"])["status"] == OutageStatus.ONLINE

        reviewed = validate_success(
            api_client.post_outage_review(
                outage["id"],
                {
                    "actual_duration_hours": 780,
                    "actual_cost_usd": 42000000,
                    "review_notes": "Two shifts lost to emergent valve work",
                },
                make_outage_director_headers(),
            )
        )
        assert reviewed["status"] == OutageStatus.REVIEWED
        assert reviewed["approved_emergent_hours"] == pytest.approx(0.00, abs=0.01)
        assert reviewed["duration_variance_pct"] == pytest.approx(8.33, abs=0.01)
        assert reviewed["dose_variance_pct"] == pytest.approx(-100.00, abs=0.01)
        assert reviewed["cost_variance_pct"] == pytest.approx(5.00, abs=0.01)
        assert reviewed["outage_performance_index"] == pytest.approx(94.84, abs=0.01)
        assert reviewed["adjusted_performance_index"] == pytest.approx(94.84, abs=0.01), (
            "with no approved emergent hours the two variants coincide"
        )

        on_read = validate_success(
            api_client.get_outage(outage["id"], make_station_admin_headers())
        )
        assert on_read["status"] == OutageStatus.REVIEWED
        assert on_read["outage_performance_index"] == pytest.approx(
            reviewed["outage_performance_index"], abs=0.01
        )
        assert on_read["adjusted_performance_index"] == pytest.approx(
            reviewed["adjusted_performance_index"], abs=0.01
        )
        assert on_read["actual_duration_hours"] == pytest.approx(780.00, abs=0.01)
        assert on_read["actual_cost_usd"] == pytest.approx(42000000.00, abs=0.01)


class TestCascadeEffectsAreVisibleImmediately:
    def test_one_approval_settles_the_ledger_the_posture_and_the_sibling_permit(self):
        """A single approval writes a ledger row, two derived outage figures, a
        posture change and a hold on a sibling permit. Each is read exactly once,
        immediately afterwards, and each already carries its final value.

        PRD 2.9: "Cascades are ordered and total."

        PRD 3.7: "Hop four is conditional: if the posture moved out of `NORMAL`
        during this very request, then every permit of the same outage that is in
        `DRAFT` and whose `committed_dose_mrem` exceeds 200 mrem moves `DRAFT →
        HELD_FOR_ALARA`, processed in ascending `created_at` order, each such
        permit's own `version` incrementing by 1."

        Design: Corner/consistency_model/cascade_results_are_visible_on_the_first_read_after_the_write
        """
        set_clock(CLOCK_EPOCH)
        first_area = given_rad_area(
            station_unit=StationUnit.UNIT_1,
            area_code="CTMT-EL471",
            dose_rate_mrem_per_hr=25,
            occupancy_limit_workers=10,
            survey_buffer_hours=2,
        )
        second_area = given_rad_area(
            station_unit=StationUnit.UNIT_1,
            area_code="CTMT-EL500",
            dose_rate_mrem_per_hr=25,
            occupancy_limit_workers=10,
            survey_buffer_hours=2,
        )
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
            dose_budget_total_mrem=900,
            cost_budget_usd=40000000,
        )
        given_approved_core_load_pattern(
            outage["id"],
            cycle_length_mwd_mtu=18000,
            fresh_assembly_count=88,
            discharge_assembly_count=80,
        )
        first_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Survey A",
            estimated_hours=60,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            requires_rad_work=True,
        )
        second_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Survey B",
            estimated_hours=60,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            requires_rad_work=True,
        )
        permit_a = given_draft_rwp(
            first_order["id"],
            first_area["id"],
            worker_count=5,
            shielding_factor=0,
            planned_start_offset_hours=0,
            planned_duration_hours=5,
        )
        permit_b = given_draft_rwp(
            second_order["id"],
            second_area["id"],
            worker_count=4,
            shielding_factor=0,
            planned_start_offset_hours=0,
            planned_duration_hours=3,
        )
        assert permit_a["committed_dose_mrem"] == pytest.approx(750.00, abs=0.01)
        assert permit_a["alara_review_required"] is True
        assert permit_b["committed_dose_mrem"] == pytest.approx(360.00, abs=0.01)
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))

        approved = validate_success(
            api_client.approve_rwp(
                permit_a["id"],
                make_rad_protection_manager_headers(),
                alara_review_reference="ALARA-2026-0142",
            )
        )
        assert approved["status"] == RwpStatus.APPROVED
        assert approved["committed_dose_mrem"] == pytest.approx(750.00, abs=0.01)

        after = read_outage(outage["id"])
        assert after["dose_committed_mrem"] == pytest.approx(750.00, abs=0.01)
        assert after["dose_budget_remaining_mrem"] == pytest.approx(150.00, abs=0.01)
        assert after["alara_posture"] == AlaraPosture.RESTRICTED

        assert read_rwp(permit_b["id"])["status"] == RwpStatus.HELD_FOR_ALARA, (
            "the conditional hop had already run inside the approve request"
        )

        rows, meta = validate_paginated(
            api_client.list_dose_transactions(
                permit_a["id"], make_rad_protection_planner_headers()
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["direction"] == DoseDirection.COMMIT
        assert rows[0]["amount_mrem"] == pytest.approx(750.00, abs=0.01)
        assert rows[0]["reason"] == DoseReason.RWP_APPROVED
