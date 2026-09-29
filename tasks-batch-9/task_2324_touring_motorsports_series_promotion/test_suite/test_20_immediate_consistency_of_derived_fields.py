"""Derived fields are readable the instant the write that produced them returns.

Nothing in this API is eventually consistent. A write that computes a score, a
timeline offset, a requirement floor or a posture reports the computed value in
its own response body, and a follow-up read of the same row — or of the parent
that aggregates it — agrees field for field with no refresh step in between.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import ApiClient
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as helpers
from test_helpers import validate_success

#: A heavy rig: at or above the 9000 lb threshold that lifts the fence floor.
HEAVY_RIG_WEIGHT_LBS = 9500

#: One complete 500-mile block plus a remainder, so the haul penalty is 5 points.
HAUL_MILES_ONE_BLOCK = 600

#: Duration of the single competition segment used throughout this module.
COMPETITION_MINUTES = 40


def _second_market_kwargs() -> Dict[str, Any]:
    """Venue, booking and timing overrides that put a stop in another market."""
    return {
        "venue_name": C.SECOND_VENUE_NAME,
        "market_code": C.SECOND_VENUE_MARKET_CODE,
        "city": C.SECOND_VENUE_CITY,
        "state_code": C.SECOND_VENUE_STATE_CODE,
        "tour_date": C.SECOND_TOUR_DATE,
        "load_in_start_utc": C.SECOND_LOAD_IN_START_UTC,
        "tear_down_end_utc": C.SECOND_TEAR_DOWN_END_UTC,
        "doors_open_utc": C.SECOND_DOORS_OPEN_UTC,
        "show_start_utc": C.SECOND_SHOW_START_UTC,
    }


def _heavy_entry(api: ApiClient, stop_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """Enter one heavy rig in the stop and return the create response body."""
    competitor = helpers.create_competitor(api, vehicle_class="HEAVY")
    return validate_success(
        api.create_vehicle_entry(
            F.make_vehicle_entry_payload(
                competitor["competitor_id"],
                stop_id,
                vehicle_weight_lbs=HEAVY_RIG_WEIGHT_LBS,
                haul_distance_miles=HAUL_MILES_ONE_BLOCK,
            ),
            headers=headers,
        ),
        201,
    )


class TestDerivedFieldsAreVisibleImmediately:
    """Every computed field is in the write's own response and survives a re-read."""

    def test_entry_creation_reports_the_readiness_score_it_just_computed(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.3: "The haul penalty is common to both variants: 5 points are
        deducted for every complete block of 500 road miles in the entry's own
        `haul_distance_miles`, where the number of blocks is the mileage divided by
        500 and rounded down to a whole number."

        Design: Corner/consistency_model/corner_consistency_every_derived_field_is_visible_in_the_same_response
        """
        state = helpers.stop_with_show_timing(api)
        expected_score = A.expected_readiness_score(
            HAUL_MILES_ONE_BLOCK, schedule_penalty_applies=False
        )
        assert expected_score == 95

        created = _heavy_entry(api, state["stop_id"], promoter_headers)

        # The create response already carries the score and the variant that
        # produced it, plus the bay the weight-based selector chose.
        A.assert_readiness_score(created, expected_score, "PRE_STAGING")
        assert created["logistics_state"] == "ENTERED"
        assert created["tech_status"] == "TECH_PENDING"
        assert created["staging_bay_index"] == C.DEFAULT_VENUE_STAGING_BAY_COUNT

        # A follow-up read of the same row agrees, with no recompute step.
        fetched = helpers.fetch_entry(api, created["id"])
        A.assert_readiness_score(fetched, expected_score, "PRE_STAGING")
        assert fetched["staging_bay_index"] == created["staging_bay_index"]
        assert fetched["version"] == created["version"]

    def test_segment_creation_reports_its_offsets_and_the_stop_aggregate_agrees(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.4: "Each insert also refreshes the stop's
        `competition_segment_count`, which is the number of the stop's segments whose
        `segment_type` is `COMPETITION`, and recomputes the posture — which matters
        because a stop with zero competition segments is held at `RESTRICTED` and
        cannot open sales."

        Design: Corner/consistency_model/corner_consistency_every_derived_field_is_visible_in_the_same_response
        """
        state = helpers.stop_with_show_timing(api)

        created = validate_success(
            api.create_show_segment(
                state["stop_id"],
                F.make_show_segment_payload(
                    segment_type="COMPETITION",
                    title="Heat Races",
                    run_order_position=1,
                    duration_minutes=COMPETITION_MINUTES,
                ),
                headers=promoter_headers,
            ),
            201,
        )

        assert created["reset_gap_minutes"] == 0
        assert created["start_offset_minutes"] == 0
        assert created["end_offset_minutes"] == COMPETITION_MINUTES

        fetched = validate_success(
            api.get_show_segment(created["id"], headers=promoter_headers)
        )
        assert fetched["start_offset_minutes"] == created["start_offset_minutes"]
        assert fetched["end_offset_minutes"] == created["end_offset_minutes"]
        assert fetched["reset_gap_minutes"] == created["reset_gap_minutes"]

        # The parent's aggregate is already caught up.
        stop = helpers.fetch_stop(api, state["stop_id"])
        assert stop["competition_segment_count"] == 1
        assert stop["run_order_end_offset_minutes"] == COMPETITION_MINUTES

    def test_safety_plan_creation_reports_the_requirement_floors_it_just_computed(
        self,
        api: ApiClient,
        promoter_headers: Dict[str, str],
        safety_author_headers: Dict[str, str],
    ) -> None:
        """PRD §3.5: "Creation records the caller in `authored_by_user_id`, opens the
        plan in `state` `DRAFT`, and immediately computes the requirement floors."

        Design: Corner/consistency_model/corner_consistency_every_derived_field_is_visible_in_the_same_response
        """
        state = helpers.stop_with_show_timing(api)
        _heavy_entry(api, state["stop_id"], promoter_headers)

        expected_floors = A.expected_safety_requirements(
            expected_attendance=0,
            live_entry_count=1,
            heavy_rig_present=True,
            floor_type=C.DEFAULT_VENUE_FLOOR_TYPE,
        )
        assert expected_floors["required_catch_fence_height_ft"] == 8
        assert expected_floors["required_barrier_linear_feet"] == 1200

        created = validate_success(
            api.create_safety_plan(
                state["stop_id"],
                F.make_safety_plan_payload(
                    barrier_linear_feet=1200,
                    catch_fence_height_ft=8,
                    medical_als_staff_count=1,
                    medical_bls_staff_count=2,
                    ambulance_count=1,
                    emergency_access_lanes=1,
                ),
                headers=safety_author_headers,
            ),
            201,
        )

        assert created["state"] == "DRAFT"
        A.assert_safety_requirements(created, expected_floors)
        A.assert_safety_cost(created)
        assert created["safety_cost_cents"] == A.expected_safety_cost_cents(1, 2, 1, 1200)

        # A follow-up read agrees on every one of the six floors and the bill.
        fetched = helpers.fetch_safety_plan(api, created["id"])
        A.assert_safety_requirements(fetched, expected_floors)
        assert fetched["safety_cost_cents"] == created["safety_cost_cents"]
        assert fetched["version"] == created["version"]

    def test_heavy_rig_lifts_the_fence_floor_reported_by_the_create_response(
        self,
        api: ApiClient,
        promoter_headers: Dict[str, str],
        safety_author_headers: Dict[str, str],
    ) -> None:
        """PRD §3.5: "`required_catch_fence_height_ft` is 8 feet when a heavy rig is
        present among the live entries and 6 feet otherwise."

        Design: Corner/consistency_model/corner_consistency_every_derived_field_is_visible_in_the_same_response
        """
        without_rig = helpers.stop_with_show_timing(api)
        light_plan = validate_success(
            api.create_safety_plan(
                without_rig["stop_id"],
                F.make_safety_plan_payload(),
                headers=safety_author_headers,
            ),
            201,
        )
        assert light_plan["required_catch_fence_height_ft"] == 6

        with_rig = helpers.stop_with_show_timing(api, **_second_market_kwargs())
        _heavy_entry(api, with_rig["stop_id"], promoter_headers)
        heavy_plan = validate_success(
            api.create_safety_plan(
                with_rig["stop_id"],
                F.make_safety_plan_payload(),
                headers=safety_author_headers,
            ),
            201,
        )
        assert heavy_plan["required_catch_fence_height_ft"] == 8

    def test_the_posture_a_write_recomputed_is_readable_on_the_stop_at_once(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/corner_consistency_every_derived_field_is_visible_in_the_same_response
        """
        state = helpers.stop_with_show_timing(api)
        stop_id = state["stop_id"]
        _heavy_entry(api, stop_id, promoter_headers)
        helpers.create_show_segment(
            api,
            stop_id,
            segment_type="COMPETITION",
            segment_title="Heat Races",
            run_order_position=1,
            duration_minutes=COMPETITION_MINUTES,
        )
        helpers.draft_safety_plan(api, stop_id)

        stop = validate_success(api.get_tour_stop(stop_id, headers=promoter_headers))

        assert stop["competition_segment_count"] == 1
        assert stop["run_order_end_offset_minutes"] == COMPETITION_MINUTES
        assert stop["sales_state"] == "SALES_PENDING"
        assert stop["safety_state"] == "SAFETY_DRAFT"
        # The filed plan is only a draft, so the derived gate still holds the stop
        # short of selling — and it says so on the very first read.
        A.assert_readiness_posture(stop, "RESTRICTED")
