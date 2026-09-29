"""Firmware rollout windows, cohort selection, close dispositions and fleet health scoring."""

import pytest

from test_helpers import (
    ApiErrorId,
    campaign_close_payload,
    close_campaign,
    coverage_action,
    create_connected_unit,
    create_equipment_model,
    create_firmware_campaign,
    post_telemetry,
    read_connected_unit,
    read_firmware_campaign,
    recipe_push_payload,
    report_unit_result,
    schedule_campaign,
    set_clock,
    setup_active_fleet,
    setup_listed_model,
    setup_running_campaign,
    start_campaign,
    unit_result_payload,
    validate_error,
    validate_success,
)

BASE_TRIO = (("SN-1", "BASE"), ("SN-2", "BASE"), ("SN-3", "BASE"))


def _listed_fleet(units=BASE_TRIO):
    """A LISTED model plus a fleet of covered units on firmware 1.0.0."""
    set_clock()
    listed = setup_listed_model()
    fleet = setup_active_fleet(listed["model"]["id"], units)
    return listed["model"], fleet


def _campaign(model_id, campaign_code, window_start, window_end, **overrides):
    return create_firmware_campaign(
        model_id,
        campaign_code=campaign_code,
        window_start=window_start,
        window_end=window_end,
        **overrides,
    )


class TestCampaignWindowSaturation:
    def test_a_third_intersecting_window_is_refused_while_a_touching_one_is_accepted(
        self, api, connected_ops_engineer
    ):
        """Two rollouts may share an instant; the third intersecting window is refused.

        PRD §3.8: "The window must not be saturated: count the other campaigns for the
        same `equipment_model_id` whose `status` is `SCHEDULED` or `RUNNING` and whose
        half-open window strictly intersects this campaign's half-open window, and reject
        with `ERR_CAMPAIGN_WINDOW_SATURATED` when that count already stands at two or
        more, since a model tolerates at most two concurrent rollouts."

        Design: Difficulty/resource_temporal_overlap/firmware_campaign_half_open_windows_allow_touching_but_cap_intersecting_at_two
        """
        model, _fleet = _listed_fleet()
        first = _campaign(
            model["id"], "FW-1", "2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z"
        )
        second = _campaign(
            model["id"], "FW-2", "2026-10-04T00:00:00Z", "2026-10-08T00:00:00Z"
        )
        third = _campaign(
            model["id"], "FW-3", "2026-10-04T12:00:00Z", "2026-10-06T00:00:00Z"
        )
        fourth = _campaign(
            model["id"], "FW-4", "2026-10-08T00:00:00Z", "2026-10-12T00:00:00Z"
        )

        assert schedule_campaign(first["id"])["status"] == "SCHEDULED", (
            "the first rollout schedules against an empty window"
        )
        assert schedule_campaign(second["id"])["status"] == "SCHEDULED", (
            "the second rollout may intersect the first, since two concurrent rollouts "
            "are tolerated"
        )

        saturated = api.schedule_firmware_campaign(
            third["id"], {}, connected_ops_engineer
        )
        validate_error(saturated, ApiErrorId.ERR_CAMPAIGN_WINDOW_SATURATED.value, 409)

        refused = read_firmware_campaign(third["id"])
        assert refused["status"] == "DRAFT", (
            "a campaign whose window intersects both scheduled rollouts stays DRAFT, "
            f"got {refused['status']}"
        )
        assert refused["cohort_unit_ids"] == [], (
            "and it selects no cohort, got "
            f"{refused['cohort_unit_ids']}"
        )

        touching = schedule_campaign(fourth["id"])
        assert touching["status"] == "SCHEDULED", (
            "a window starting exactly at the second rollout's exclusive end does not "
            f"intersect it, got {touching['status']}"
        )
        assert len(touching["cohort_unit_ids"]) == 3, (
            "a CANARY cohort is three units, got "
            f"{len(touching['cohort_unit_ids'])}"
        )

    def test_the_intersection_boundary_is_one_second_wide_at_a_shared_window_end(
        self, api, connected_ops_engineer
    ):
        """Starting at another rollout's window_end is free; one second earlier saturates.

        PRD §3.8: "Because both windows are half-open and unpadded, a campaign that
        starts exactly at another's `window_end` does not intersect it and is accepted —
        the deliberate opposite of the padded, closed-interval rule that governs factory
        slots."

        Design: Difficulty/resource_temporal_overlap/firmware_campaign_half_open_windows_allow_touching_but_cap_intersecting_at_two
        """
        model, _fleet = _listed_fleet()
        for code in ("FW-1", "FW-2"):
            campaign = _campaign(
                model["id"], code, "2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z"
            )
            assert schedule_campaign(campaign["id"])["status"] == "SCHEDULED", (
                f"{code} occupies the same window as its sibling, which is the cap"
            )

        touching = _campaign(
            model["id"], "FW-TOUCH", "2026-10-05T00:00:00Z", "2026-10-09T00:00:00Z"
        )
        scheduled = schedule_campaign(touching["id"])
        assert scheduled["status"] == "SCHEDULED", (
            "a start exactly at the two saturated windows' exclusive end intersects "
            f"neither of them, got {scheduled['status']}"
        )
        assert len(scheduled["cohort_unit_ids"]) == 3, (
            "the same three eligible units form its cohort, got "
            f"{len(scheduled['cohort_unit_ids'])}"
        )

        overlapping = _campaign(
            model["id"], "FW-OVER", "2026-10-04T23:59:59Z", "2026-10-09T00:00:00Z"
        )
        saturated = api.schedule_firmware_campaign(
            overlapping["id"], {}, connected_ops_engineer
        )
        validate_error(saturated, ApiErrorId.ERR_CAMPAIGN_WINDOW_SATURATED.value, 409)

        blocked = read_firmware_campaign(overlapping["id"])
        assert blocked["status"] == "DRAFT", (
            "one second earlier the window covers the shared instant and is refused, "
            f"got {blocked['status']}"
        )
        assert blocked["cohort_unit_ids"] == [], (
            f"the refused schedule freezes no cohort, got {blocked['cohort_unit_ids']}"
        )


class TestCampaignStartWindow:
    def test_the_start_gate_opens_exactly_at_window_start(
        self, api, connected_ops_engineer
    ):
        """A start at 2026-08-01 is refused and one at exactly 2026-10-01 is admitted.

        PRD §3.8: "Starting the campaign takes it `SCHEDULED → RUNNING` and is permitted
        only while the clock has reached or passed `window_start` and is still strictly
        before `window_end`; outside that half-open window the start is rejected with
        `ERR_CAMPAIGN_WINDOW_NOT_OPEN`. Starting resets `success_count` and
        `failure_count` to zero."

        Design: Corner/validations/campaign_start_window_lower_bound_is_inclusive
        """
        model, _fleet = _listed_fleet()
        campaign = schedule_campaign(create_firmware_campaign(model["id"])["id"])
        assert campaign["status"] == "SCHEDULED", (
            f"the campaign is scheduled before the window opens, got {campaign['status']}"
        )

        too_early = api.start_firmware_campaign(
            campaign["id"], {}, connected_ops_engineer
        )
        validate_error(too_early, ApiErrorId.ERR_CAMPAIGN_WINDOW_NOT_OPEN.value, 409)
        assert read_firmware_campaign(campaign["id"])["status"] == "SCHEDULED", (
            "the refused start leaves the campaign SCHEDULED"
        )

        set_clock("2026-10-01T00:00:00Z")
        running = start_campaign(campaign["id"])
        assert running["status"] == "RUNNING", (
            "the clock standing exactly on window_start opens the window, got "
            f"{running['status']}"
        )
        assert running["success_count"] == 0, (
            f"starting resets the success counter, got {running['success_count']}"
        )
        assert running["failure_count"] == 0, (
            f"and the failure counter, got {running['failure_count']}"
        )


class TestCohortEligibility:
    def test_a_canary_cohort_needs_three_units_with_live_coverage(
        self, api, connected_ops_engineer
    ):
        """Two covered units plus one PENDING_INSTALL cannot fill a cohort of three.

        PRD §3.8: "Finally the fleet must have enough eligible units: a unit is eligible
        when it belongs to the campaign's model, its `service_program_status` is `ACTIVE`
        or `EXTENDED`, and its `firmware_version` is not already the
        `target_firmware_version`; fewer eligible units than the cohort size is rejected
        with `ERR_NO_ELIGIBLE_UNITS`."

        Design: Corner/validations/cohort_sizing_needs_three_eligible_units_before_a_canary_campaign_can_schedule
        """
        set_clock()
        listed = setup_listed_model()
        model_id = listed["model"]["id"]
        setup_active_fleet(model_id, (("SN-1", "BASE"), ("SN-2", "BASE")))
        dormant = create_connected_unit(model_id, "SN-3")
        campaign = create_firmware_campaign(model_id)

        assert dormant["service_program_status"] == "PENDING_INSTALL", (
            "the third unit is registered but never activated, got "
            f"{dormant['service_program_status']}"
        )

        short = api.schedule_firmware_campaign(
            campaign["id"], {}, connected_ops_engineer
        )
        validate_error(short, ApiErrorId.ERR_NO_ELIGIBLE_UNITS.value, 422)
        assert read_firmware_campaign(campaign["id"])["status"] == "DRAFT", (
            "the refused schedule leaves the campaign DRAFT"
        )

        activated = coverage_action(dormant["id"], "ACTIVATE")
        assert activated["service_program_status"] == "ACTIVE", (
            f"activating the third unit makes it eligible, got "
            f"{activated['service_program_status']}"
        )

        scheduled = schedule_campaign(campaign["id"])
        assert scheduled["status"] == "SCHEDULED", (
            "exactly three eligible units meet the inclusive cohort size, got "
            f"{scheduled['status']}"
        )
        assert len(scheduled["cohort_unit_ids"]) == 3, (
            f"and all three are frozen into the cohort, got "
            f"{len(scheduled['cohort_unit_ids'])}"
        )


class TestCohortIsFrozenAtSchedule:
    def test_results_are_refused_outside_the_cohort_and_on_a_replay(
        self, api, connected_ops_engineer
    ):
        """The healthiest fourth unit is outside the cohort, and a second report is refused.

        PRD §3.8: "Results are accepted only while the campaign is `RUNNING`, and only
        for a unit that is in `cohort_unit_ids` and has not already reported in this run;
        anything else is rejected with `ERR_UNIT_NOT_IN_COHORT`."

        Design: Corner/validations/unit_results_are_restricted_to_the_frozen_cohort_and_to_one_report_per_unit
        """
        set_clock()
        listed = setup_listed_model()
        model_id = listed["model"]["id"]
        fleet = setup_active_fleet(
            model_id,
            (("SN-1", "BASE"), ("SN-2", "BASE"), ("SN-3", "BASE"), ("SN-4", "BASE")),
        )
        first, second, third, fourth = fleet

        assert post_telemetry(first["id"], 1, 0)["health_score"] == 93, (
            "one fault costs seven points"
        )
        assert post_telemetry(second["id"], 2, 0)["health_score"] == 86, (
            "two faults cost fourteen points"
        )
        assert post_telemetry(third["id"], 3, 0)["health_score"] == 79, (
            "three faults cost twenty-one points"
        )
        assert read_connected_unit(fourth["id"])["health_score"] == 100, (
            "the fourth unit has reported no telemetry and stays perfect"
        )

        campaign = schedule_campaign(create_firmware_campaign(model_id)["id"])
        assert campaign["cohort_unit_ids"] == [
            third["id"],
            second["id"],
            first["id"],
        ], (
            "the cohort is the three sickest units, ordered by health ascending, got "
            f"{campaign['cohort_unit_ids']}"
        )

        set_clock("2026-10-02T00:00:00Z")
        start_campaign(campaign["id"])
        reported = report_unit_result(campaign["id"], first["id"], "SUCCESS")
        assert reported["success_count"] == 1, (
            f"the first report lands, got {reported['success_count']}"
        )

        outsider = api.report_unit_result(
            campaign["id"],
            unit_result_payload(fourth["id"], "SUCCESS"),
            connected_ops_engineer,
        )
        validate_error(outsider, ApiErrorId.ERR_UNIT_NOT_IN_COHORT.value, 422)

        replay = api.report_unit_result(
            campaign["id"],
            unit_result_payload(first["id"], "FAILURE"),
            connected_ops_engineer,
        )
        validate_error(replay, ApiErrorId.ERR_UNIT_NOT_IN_COHORT.value, 422)

        final = read_firmware_campaign(campaign["id"])
        assert final["success_count"] == 1, (
            f"neither refusal may move the success counter, got {final['success_count']}"
        )
        assert final["failure_count"] == 0, (
            f"nor the failure counter, got {final['failure_count']}"
        )


class TestCloseDispositions:
    def test_the_success_floor_gates_complete_only_and_rollback_resyncs_recipes(
        self, api, connected_ops_engineer
    ):
        """At two successes and one failure COMPLETE is refused and ROLL_BACK is accepted.

        PRD §3.8: "`ROLL_BACK` takes the campaign `RUNNING → ROLLED_BACK` with no
        success-rate floor at all, leaves `firmware_version` unchanged on every cohort
        unit including the successful ones, and instead increments `recipe_book_version`
        by one on every cohort unit that reported `SUCCESS`, recording the recipe re-sync
        that a rollback forces on units which had already moved."

        Design: Corner/validations/campaign_close_gate_applies_to_complete_only_and_roll_back_resyncs_recipes
        """
        model, fleet = _listed_fleet()
        state = setup_running_campaign(
            model["id"], fleet=fleet, open_clock="2026-10-02T00:00:00Z"
        )
        campaign = state["campaign"]
        cohort = campaign["cohort_unit_ids"]
        report_unit_result(campaign["id"], cohort[0], "SUCCESS")
        report_unit_result(campaign["id"], cohort[1], "SUCCESS")
        partial = report_unit_result(campaign["id"], cohort[2], "FAILURE")

        assert partial["success_count"] == 2, (
            f"two units reported success, got {partial['success_count']}"
        )
        assert partial["failure_count"] == 1, (
            f"and one reported failure, got {partial['failure_count']}"
        )

        refused = api.close_firmware_campaign(
            campaign["id"], campaign_close_payload("COMPLETE"), connected_ops_engineer
        )
        validate_error(refused, ApiErrorId.ERR_CAMPAIGN_SUCCESS_RATE_TOO_LOW.value, 422)
        assert read_firmware_campaign(campaign["id"])["status"] == "RUNNING", (
            "the refused completion leaves the campaign RUNNING"
        )

        rolled_back = close_campaign(campaign["id"], "ROLL_BACK")
        assert rolled_back["status"] == "ROLLED_BACK", (
            f"a rollback carries no success floor, got {rolled_back['status']}"
        )
        assert rolled_back["success_rate"] == pytest.approx(0.6667, abs=0.0001), (
            "two successes over a cohort of three is 0.6667 to four places, got "
            f"{rolled_back['success_rate']}"
        )

        successful = read_connected_unit(cohort[0])
        assert successful["firmware_version"] == "1.0.0", (
            "a rollback leaves even the successful units on their old firmware, got "
            f"{successful['firmware_version']}"
        )
        assert successful["recipe_book_version"] == 2, (
            "and forces a recipe re-sync on them, got "
            f"{successful['recipe_book_version']}"
        )

        failed = read_connected_unit(cohort[2])
        assert failed["firmware_version"] == "1.0.0", (
            f"the failing unit never moved, got {failed['firmware_version']}"
        )
        assert failed["recipe_book_version"] == 1, (
            "and it is not re-synced, since only SUCCESS units are, got "
            f"{failed['recipe_book_version']}"
        )

    def test_a_completed_campaign_cannot_be_closed_a_second_time(
        self, api, connected_ops_engineer
    ):
        """A replayed close on a COMPLETED campaign is refused and re-stamps nothing.

        PRD §2.6: "The unit's coverage dimension or the campaign's `status` admits the
        requested operation, on `POST /connected-units/{id}/recipe-pushes`, `POST
        /connected-units/{id}/coverage-actions`, `POST /firmware-campaigns/{id}/schedule`,
        `POST /firmware-campaigns/{id}/start`, `POST /firmware-campaigns/{id}/unit-results`
        and `POST /firmware-campaigns/{id}/close`. `ERR_CONNECTED_STATE_INVALID`."

        Design: Corner/state_machines/completed_firmware_campaign_cannot_be_closed_a_second_time
        """
        model, fleet = _listed_fleet()
        state = setup_running_campaign(
            model["id"], fleet=fleet, open_clock="2026-10-02T00:00:00Z"
        )
        campaign = state["campaign"]
        cohort = campaign["cohort_unit_ids"]
        assert len(cohort) == 3, (
            f"a CANARY cohort holds three units, got {len(cohort)}"
        )
        for unit_id in cohort:
            report_unit_result(campaign["id"], unit_id, "SUCCESS")

        completed = close_campaign(campaign["id"], "COMPLETE")
        assert completed["status"] == "COMPLETED", (
            f"a fully successful cohort completes, got {completed['status']}"
        )
        assert completed["success_rate"] == pytest.approx(1.0, abs=0.0001), (
            f"three successes over three units is 1.0, got {completed['success_rate']}"
        )

        replay = api.close_firmware_campaign(
            campaign["id"], campaign_close_payload("ROLL_BACK"), connected_ops_engineer
        )
        validate_error(replay, ApiErrorId.ERR_CONNECTED_STATE_INVALID.value, 409)

        final = read_firmware_campaign(campaign["id"])
        assert final["status"] == "COMPLETED", (
            f"COMPLETED is terminal, got {final['status']}"
        )
        assert final["success_rate"] == pytest.approx(1.0, abs=0.0001), (
            f"the refused replay does not re-stamp the rate, got {final['success_rate']}"
        )

        unit = read_connected_unit(cohort[0])
        assert unit["firmware_version"] == "2.0.0", (
            "the completion moved the cohort to the target firmware, got "
            f"{unit['firmware_version']}"
        )
        assert unit["recipe_book_version"] == 1, (
            "and the refused rollback did not re-sync any recipe book, got "
            f"{unit['recipe_book_version']}"
        )


class TestHealthScoring:
    def test_the_firmware_bonus_is_applied_before_the_upper_clamp(self):
        """Completion lifts a one-fault unit from 93 to 98 while a clean unit clamps at 100.

        PRD §3.8: "The result is then clamped into the inclusive range 0 through 100,
        once, after the bonus has been applied — so a unit with many faults floors at 0
        rather than going negative, and a fault-free unit running the reference firmware
        caps at 100 rather than reaching 105."

        Design: Corner/calculations/firmware_bonus_is_added_before_the_upper_clamp_at_one_hundred
        """
        model, fleet = _listed_fleet()
        faulty, clean = fleet[0], fleet[1]
        scored = post_telemetry(faulty["id"], 1, 0)
        assert scored["health_score"] == 93, (
            "one fault costs seven points off a perfect hundred, got "
            f"{scored['health_score']}"
        )

        state = setup_running_campaign(
            model["id"], fleet=fleet, open_clock="2026-10-02T00:00:00Z"
        )
        campaign = state["campaign"]
        for unit_id in campaign["cohort_unit_ids"]:
            report_unit_result(campaign["id"], unit_id, "SUCCESS")
        completed = close_campaign(campaign["id"], "COMPLETE")

        assert completed["status"] == "COMPLETED", (
            f"the campaign completes, got {completed['status']}"
        )
        assert completed["success_rate"] == pytest.approx(1.0, abs=0.0001), (
            f"every cohort unit succeeded, got {completed['success_rate']}"
        )

        faulty_after = read_connected_unit(faulty["id"])
        clean_after = read_connected_unit(clean["id"])
        assert faulty_after["firmware_version"] == "2.0.0", (
            "the successful units move to the target firmware, got "
            f"{faulty_after['firmware_version']}"
        )
        assert clean_after["firmware_version"] == "2.0.0", (
            f"including the clean one, got {clean_after['firmware_version']}"
        )
        assert faulty_after["health_score"] == 98, (
            "the one-fault unit is now on the reference firmware, so 100 less 7 plus 5 "
            f"is 98, got {faulty_after['health_score']}"
        )
        assert clean_after["health_score"] == 100, (
            "the clean unit's raw 105 is clamped once to 100, so the bonus is never "
            f"visible above the ceiling, got {clean_after['health_score']}"
        )

    def test_fault_and_heartbeat_weights_apply_and_the_score_floors_at_zero(self):
        """Three faults and four missed heartbeats give 67, while twenty faults floor at 0.

        PRD §3.8: "The score starts from a perfect 100, subtracts seven points for each
        fault in the trailing window and three points for each missed heartbeat, then adds
        a five-point currency bonus when the unit is running the reference firmware."

        Design: Corner/calculations/health_score_applies_fault_and_heartbeat_weights_and_clamps_at_zero
        """
        set_clock()
        model = create_equipment_model()
        first = create_connected_unit(model["id"], "SN-1")
        second = create_connected_unit(model["id"], "SN-2")

        assert first["health_score"] == 100, (
            f"a freshly registered unit scores a perfect 100, got {first['health_score']}"
        )

        scored_first = post_telemetry(first["id"], 3, 4)
        assert scored_first["health_score"] == 67, (
            "there is no completed campaign for the model, so no bonus applies and the "
            f"score is 100 less 21 less 12, got {scored_first['health_score']}"
        )
        assert scored_first["fault_count_30d"] == 3, (
            f"the posted fault count is stored, got {scored_first['fault_count_30d']}"
        )
        assert scored_first["missed_heartbeat_count"] == 4, (
            "and the posted heartbeat count, got "
            f"{scored_first['missed_heartbeat_count']}"
        )

        scored_second = post_telemetry(second["id"], 20, 0)
        assert scored_second["health_score"] == 0, (
            "a raw score of minus forty is clamped once to zero rather than stored "
            f"negative, got {scored_second['health_score']}"
        )
        assert read_connected_unit(second["id"])["health_score"] == 0, (
            "and the clamped score is what the row keeps"
        )


class TestRecipePushes:
    def test_a_recipe_push_needs_live_coverage(self, api, connected_ops_engineer):
        """A push to a PENDING_INSTALL unit is refused; after activation it sets generation 4.

        PRD §3.8: "Pushing a recipe book generation sets the unit's `recipe_book_version`
        to the supplied value, and is permitted only while the unit's
        `service_program_status` is `ACTIVE` or `EXTENDED`; an uninstalled, expired,
        in-grace or voided unit is rejected with `ERR_CONNECTED_STATE_INVALID`."

        Design: Corner/endpoints/recipe_push_is_allowed_only_while_coverage_is_live
        """
        set_clock()
        listed = setup_listed_model()
        unit = create_connected_unit(listed["model"]["id"], "SN-1")

        assert unit["service_program_status"] == "PENDING_INSTALL", (
            f"the unit is registered but not installed, got "
            f"{unit['service_program_status']}"
        )
        assert unit["recipe_book_version"] == 1, (
            f"a new unit ships on recipe generation 1, got {unit['recipe_book_version']}"
        )

        too_early = api.push_recipe(
            unit["id"], recipe_push_payload(4), connected_ops_engineer
        )
        validate_error(too_early, ApiErrorId.ERR_CONNECTED_STATE_INVALID.value, 409)
        assert read_connected_unit(unit["id"])["recipe_book_version"] == 1, (
            "the refused push leaves the recipe generation alone"
        )

        activated = coverage_action(unit["id"], "ACTIVATE")
        assert activated["service_program_status"] == "ACTIVE", (
            f"activation makes coverage live, got {activated['service_program_status']}"
        )

        pushed = validate_success(
            api.push_recipe(unit["id"], recipe_push_payload(4), connected_ops_engineer)
        )
        assert pushed["recipe_book_version"] == 4, (
            "the same push now sets the supplied generation, got "
            f"{pushed['recipe_book_version']}"
        )
        assert pushed["firmware_version"] == "1.0.0", (
            "a recipe push does not touch firmware, got "
            f"{pushed['firmware_version']}"
        )
