"""Two interval conventions: a symmetric point buffer and a closed coverage range."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import IDDE_HEADERS, INSPECTOR_HEADERS


def _screen(outfall_id, observed_at):
    """A no-flow dry-weather screening, so no indicator is consulted."""
    return api_client.create_observation(
        outfall_id,
        factories.screening_payload(
            observed_at,
            dry_weather_flow_present=False,
            indicator_bacteria_mpn=None,
            indicator_surfactant_mg_per_l=None,
            indicator_ammonia_mg_per_l=None,
        ),
        IDDE_HEADERS,
    )


class TestScreeningBufferIsSymmetric:
    """Fourteen days in both directions, with the boundary itself allowed."""

    @pytest.fixture
    def screened_outfall(self):
        """OF-01 with one no-flow screening on 2026-08-01, the clock a month on."""
        program = fx.setup_active_program(
            outfall_codes=("OF-01",),
            outfall_overrides={
                "receiving_water": "Mill Creek",
                "drainage_area_acres": 45.00,
                "priority_tier": "HIGH",
                "baseline_concentration_mg_per_l": 0.45,
                "design_runoff_kl": 20000,
                "sweeping_capacity_lane_miles_per_month": 40.00,
            },
        )
        fx.set_clock("2026-09-01T00:00:00Z")
        outfall = program["outfalls"]["OF-01"]
        first = validate_success(_screen(outfall["id"], "2026-08-01T08:00:00Z"), 201)
        return {"term_id": program["term_id"], "outfall": outfall, "first": first}

    def test_01_exactly_fourteen_days_later_is_accepted(self, screened_outfall):
        """The boundary is inclusive, and a no-flow visit reads CLEAR.

        PRD: "The dry-weather screening buffer is symmetric and open. Two
        dry-weather screenings at the same outfall must be separated by at least 14
        days, measured in both directions from `observed_at`: exactly 14 days apart
        is accepted, 13 days and 23 hours apart in either direction is refused with
        `ERR_SCREENING_INTERVAL_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/screening_interval_is_a_symmetric_fourteen_day_buffer_around_each_observation
        """
        second = validate_success(
            _screen(screened_outfall["outfall"]["id"], "2026-08-15T08:00:00Z"), 201
        )

        assert screened_outfall["first"]["screening_result"] == "CLEAR", (
            "no flow short-circuits the indicator logic"
        )
        assert second["screening_result"] == "CLEAR", "the second visit is clear too"

        outfall = fx.read_outfall(screened_outfall["outfall"]["id"])
        assert outfall["screening_count"] == 2, "both screenings are counted"
        assert outfall["last_screened_at"] == "2026-08-15T08:00:00Z", (
            "the later visit instant is stamped"
        )

    def test_02_one_hour_short_of_fourteen_days_is_refused(self, screened_outfall):
        """13 days and 23 hours after the second visit is inside the buffer.

        PRD: "Two dry-weather screenings at the same outfall must be separated by at
        least 14 days, measured in both directions from `observed_at`: exactly 14
        days apart is accepted, 13 days and 23 hours apart in either direction is
        refused with `ERR_SCREENING_INTERVAL_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/screening_interval_is_a_symmetric_fourteen_day_buffer_around_each_observation
        """
        outfall_id = screened_outfall["outfall"]["id"]
        validate_success(_screen(outfall_id, "2026-08-15T08:00:00Z"), 201)

        response = _screen(outfall_id, "2026-08-29T07:00:00Z")

        validate_error(response, ApiErrorId.ERR_SCREENING_INTERVAL_VIOLATION.value, 409)

        outfall = fx.read_outfall(outfall_id)
        assert outfall["screening_count"] == 2, (
            "the refused screening created no observation"
        )
        assert outfall["last_screened_at"] == "2026-08-15T08:00:00Z", (
            "the refused screening stamped nothing"
        )

    def test_03_a_back_dated_screening_inside_the_buffer_is_refused_too(
        self, screened_outfall
    ):
        """Five days before an existing visit is just as close as five days after.

        PRD: "Because the test is symmetric, back-dating a screening into the buffer
        of a screening already recorded later is refused too."

        Design: Difficulty/resource_temporal_overlap/screening_interval_is_a_symmetric_fourteen_day_buffer_around_each_observation
        """
        outfall_id = screened_outfall["outfall"]["id"]
        validate_success(_screen(outfall_id, "2026-08-15T08:00:00Z"), 201)

        response = _screen(outfall_id, "2026-08-10T08:00:00Z")

        validate_error(response, ApiErrorId.ERR_SCREENING_INTERVAL_VIOLATION.value, 409)

        observations, meta = validate_paginated(
            api_client.list_outfall_observations(
                outfall_id, IDDE_HEADERS, {"observation_type": "DRY_WEATHER_SCREENING"}
            )
        )
        assert meta["total_count"] == 2, (
            f"only the two accepted screenings may exist, got {meta['total_count']}"
        )
        assert all(o["screening_result"] == "CLEAR" for o in observations), (
            "every stored screening was a no-flow visit"
        )

    def test_04_the_third_visit_at_the_boundary_is_accepted(self, screened_outfall):
        """Exactly 14 days after the second visit clears both neighbours.

        PRD: "A `CLEAR` result moves `screening_status` from `NOT_SCREENED` to
        `CLEAR`."

        Design: Difficulty/resource_temporal_overlap/screening_interval_is_a_symmetric_fourteen_day_buffer_around_each_observation
        """
        outfall_id = screened_outfall["outfall"]["id"]
        validate_success(_screen(outfall_id, "2026-08-15T08:00:00Z"), 201)
        _screen(outfall_id, "2026-08-29T07:00:00Z")
        _screen(outfall_id, "2026-08-10T08:00:00Z")

        third = validate_success(_screen(outfall_id, "2026-08-29T08:00:00Z"), 201)
        assert third["screening_result"] == "CLEAR", "the third visit is clear"

        outfall = fx.read_outfall(outfall_id)
        assert outfall["screening_count"] == 3, "three screenings were accepted in all"
        assert outfall["last_screened_at"] == "2026-08-29T08:00:00Z", (
            "the latest accepted visit is stamped"
        )
        assert outfall["screening_status"] == "CLEAR", "no suspect result was recorded"
        assert outfall["open_case_count"] == 0, "no case was opened by a clear result"


class TestInspectionCoverageIsAClosedInterval:
    """Touching endpoints conflict, and the scope is type plus subject."""

    @pytest.fixture
    def inspected_site(self):
        """SITE-H covered for 2026-06-01..2026-06-15, plus one recorded facility."""
        program = fx.setup_active_program()
        site = fx.setup_site_with_approved_plan(
            program["term_id"],
            esc_plan_reference="ESC-H-1",
            site_name="SITE-H",
            operator_name="Hartley Grading",
            disturbed_acres=3.40,
        )
        facility = fx.setup_facility_with_agreement(
            site["id"],
            recorded_at="2026-05-01T00:00:00Z",
            inspection_interval_months=12,
            facility_type="INFILTRATION_TRENCH",
            design_capacity_cf=3100,
            service_area_acres=3.40,
        )
        first = fx.create_esc_inspection(
            site["id"], "2026-06-01", "2026-06-15", rainfall_trigger=False
        )
        return {
            "term_id": program["term_id"],
            "site": site,
            "facility": facility,
            "first": first,
        }

    def test_05_a_period_start_on_the_stored_period_end_conflicts(self, inspected_site):
        """Sharing the closing day is already an overlap.

        PRD: "An inspection's coverage period is a closed interval bounded by
        `period_start` and `period_end` inclusive, and two inspections of the same
        `inspection_type` on the same subject may not overlap. Touching endpoints
        count as an overlap: a `period_start` equal to another inspection's
        `period_end` is a conflict, reported as `ERR_INSPECTION_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/inspection_coverage_periods_are_closed_intervals_that_conflict_when_they_touch
        """
        response = api_client.create_inspection(
            factories.esc_inspection_payload(
                inspected_site["site"]["id"],
                "2026-06-15",
                "2026-06-20",
                rainfall_trigger=False,
            ),
            INSPECTOR_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_INSPECTION_PERIOD_OVERLAP.value, 409)

    def test_06_a_period_end_on_the_stored_period_start_conflicts_symmetrically(
        self, inspected_site
    ):
        """Touching the opening day from below is rejected the same way.

        PRD: "Touching endpoints count as an overlap: a `period_start` equal to
        another inspection's `period_end` is a conflict, reported as
        `ERR_INSPECTION_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/inspection_coverage_periods_are_closed_intervals_that_conflict_when_they_touch
        """
        response = api_client.create_inspection(
            factories.esc_inspection_payload(
                inspected_site["site"]["id"],
                "2026-05-25",
                "2026-06-01",
                rainfall_trigger=False,
            ),
            INSPECTOR_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_INSPECTION_PERIOD_OVERLAP.value, 409)

    def test_07_a_one_day_gap_is_free(self, inspected_site):
        """2026-06-16 starts the day after the stored period closes.

        PRD: "A new inspection has `status` `DRAFT`, an empty `findings` list, all
        three severity counters and `deficiency_score` at 0, `escalation_triggered`
        false, and `finalized_at` and `finalized_by_user_id` null."

        Design: Difficulty/resource_temporal_overlap/inspection_coverage_periods_are_closed_intervals_that_conflict_when_they_touch
        """
        second = validate_success(
            api_client.create_inspection(
                factories.esc_inspection_payload(
                    inspected_site["site"]["id"],
                    "2026-06-16",
                    "2026-06-20",
                    rainfall_trigger=False,
                ),
                INSPECTOR_HEADERS,
            ),
            201,
        )

        assert second["status"] == "DRAFT", "a new inspection starts in DRAFT"
        assert second["deficiency_score"] == 0, "no score exists before finalization"
        assert second["escalation_triggered"] is False, "nothing has escalated yet"

    def test_08_the_same_window_is_free_for_the_other_type_and_subject(
        self, inspected_site
    ):
        """A maintenance inspection may cover the identical dates.

        PRD: "two inspections of the same `inspection_type` on the same subject may
        not overlap."

        Design: Difficulty/resource_temporal_overlap/inspection_coverage_periods_are_closed_intervals_that_conflict_when_they_touch
        """
        maintenance = validate_success(
            api_client.create_inspection(
                factories.maintenance_inspection_payload(
                    inspected_site["facility"]["id"],
                    "2026-06-01",
                    "2026-06-15",
                    rainfall_trigger=False,
                ),
                INSPECTOR_HEADERS,
            ),
            201,
        )

        assert maintenance["inspection_type"] == "POST_CONSTRUCTION_MAINTENANCE", (
            "the second row is a maintenance inspection"
        )
        assert (
            maintenance["post_construction_facility_id"]
            == inspected_site["facility"]["id"]
        ), "it is scoped to the facility, not the site"

    def test_09_only_the_accepted_rows_are_stored_against_the_site(self, inspected_site):
        """Two conflicts and two acceptances leave the site with two inspections.

        PRD: "Nothing is persisted when a request is rejected — no partial writes,
        no counter increments, no cascades."

        Design: Difficulty/resource_temporal_overlap/inspection_coverage_periods_are_closed_intervals_that_conflict_when_they_touch
        """
        site_id = inspected_site["site"]["id"]
        api_client.create_inspection(
            factories.esc_inspection_payload(
                site_id, "2026-06-15", "2026-06-20", rainfall_trigger=False
            ),
            INSPECTOR_HEADERS,
        )
        api_client.create_inspection(
            factories.esc_inspection_payload(
                site_id, "2026-05-25", "2026-06-01", rainfall_trigger=False
            ),
            INSPECTOR_HEADERS,
        )
        validate_success(
            api_client.create_inspection(
                factories.esc_inspection_payload(
                    site_id, "2026-06-16", "2026-06-20", rainfall_trigger=False
                ),
                INSPECTOR_HEADERS,
            ),
            201,
        )
        validate_success(
            api_client.create_inspection(
                factories.maintenance_inspection_payload(
                    inspected_site["facility"]["id"],
                    "2026-06-01",
                    "2026-06-15",
                    rainfall_trigger=False,
                ),
                INSPECTOR_HEADERS,
            ),
            201,
        )

        _, meta = validate_paginated(
            api_client.list_inspections(
                INSPECTOR_HEADERS, {"construction_site_id": site_id}
            )
        )
        assert meta["total_count"] == 2, (
            "only the two accepted erosion-control inspections belong to the site, "
            f"got {meta['total_count']}"
        )

        first = fx.read_inspection(inspected_site["first"]["id"])
        assert first["status"] == "DRAFT", "the stored inspection is untouched"
