"""Two exclusive timelines: the attraction's day and a scene's channel."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_scene,
    book_run,
    open_project,
    place_cue,
    setup_program_at_technical_rehearsal,
    validate_error,
    validate_paginated,
    validate_success,
)

CONTRACTOR = TEST_USERS["contractor_pm_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]
PROGRAMMER = TEST_USERS["show_programmer_headers"]


class TestRehearsalChangeoverGap:
    """Closed endpoints touch, and the changeover is two full hours wide."""

    def _programme_with_a_morning_run(self):
        ctx = setup_program_at_technical_rehearsal()
        ctx["incumbent"] = book_run(ctx["project"]["id"])
        return ctx

    def test_a_window_starting_where_the_incumbent_ends_collides(self, api):
        """The attraction can only host one activity at a time, and changeover takes real work: the requested closed interval must not overlap any `SCHEDULED` or `COMPLETED` run of the same programme, and it must additionally leave at least two hours of clear gap on both sides of every existing run.

        A `ContractorPM` books a window against a `project_id` with a `run_kind` of
        `TECHNICAL_REHEARSAL`, `CAST_REHEARSAL` or `SOFT_OPEN`, and an occupied window
        given by an inclusive `window_start_utc` and an inclusive `window_end_utc`
        that must be strictly after the start — an end at or before the start is a
        schema violation reported as `ERR_INVALID_REQUEST`.

        The incumbent occupies nine until one, and a window that opens exactly at one
        shares that closed endpoint, so it is refused and the day still holds a
        single booking.

        Design: Difficulty/resource_temporal_overlap/rehearsal_window_treats_endpoints_as_closed_and_demands_a_full_changeover_gap
        """
        ctx = self._programme_with_a_morning_run()

        response = api.create_rehearsal_run(
            {
                "project_id": ctx["project"]["id"], "run_kind": "TECHNICAL_REHEARSAL",
                "window_start_utc": "2026-08-01T13:00:00Z",
                "window_end_utc": "2026-08-01T14:00:00Z",
            },
            CONTRACTOR,
        )

        validate_error(response, ApiErrorId.ERR_REHEARSAL_WINDOW_CONFLICT.value)
        incumbent = validate_success(
            api.get_rehearsal_run(ctx["incumbent"]["id"], CONTRACTOR))
        assert incumbent["status"] == "SCHEDULED"
        runs, meta = validate_paginated(
            api.list_project_rehearsal_runs(ctx["project"]["id"], CONTRACTOR))
        assert len(runs) == 1
        assert meta["total_count"] == 1

    def test_an_hour_of_changeover_collides_but_two_full_hours_is_accepted(self, api):
        """A booking that overlaps, or that crowds an existing run inside that mandatory 120-minute changeover, is refused with `ERR_REHEARSAL_WINDOW_CONFLICT`.

        The run is created `SCHEDULED` with `guests_cycled`, `duration_minutes`,
        `measured_hourly_throughput_guests`, `pass_threshold_guests` and `result` all
        null.

        Sixty minutes of clear air after the incumbent is still inside the mandatory
        changeover and is refused, while a window opening at three — a full two hours
        after the incumbent closes — is booked, and it carries no verdict yet.

        Design: Difficulty/resource_temporal_overlap/rehearsal_window_treats_endpoints_as_closed_and_demands_a_full_changeover_gap
        """
        ctx = self._programme_with_a_morning_run()

        crowding = api.create_rehearsal_run(
            {
                "project_id": ctx["project"]["id"], "run_kind": "TECHNICAL_REHEARSAL",
                "window_start_utc": "2026-08-01T14:00:00Z",
                "window_end_utc": "2026-08-01T16:00:00Z",
            },
            CONTRACTOR,
        )
        validate_error(crowding, ApiErrorId.ERR_REHEARSAL_WINDOW_CONFLICT.value)

        accepted = validate_success(
            api.create_rehearsal_run(
                {
                    "project_id": ctx["project"]["id"], "run_kind": "CAST_REHEARSAL",
                    "window_start_utc": "2026-08-01T15:00:00Z",
                    "window_end_utc": "2026-08-01T17:00:00Z",
                },
                CONTRACTOR,
            ),
            201,
        )

        assert accepted["status"] == "SCHEDULED"
        assert accepted["run_kind"] == "CAST_REHEARSAL"
        assert accepted["pass_threshold_guests"] is None
        assert accepted["measured_hourly_throughput_guests"] is None
        assert accepted["result"] is None
        runs, meta = validate_paginated(
            api.list_project_rehearsal_runs(ctx["project"]["id"], CONTRACTOR))
        assert len(runs) == 2
        assert meta["total_count"] == 2


class TestCueChannelInterlockBuffer:
    """Zero gap is a collision on animation and a legal cut on lighting."""

    def _scene_with_one_animation_and_one_lighting_cue(self):
        project = open_project()
        scene = add_scene(project["id"], scene_label="Prologue", sequence_index=1,
                          duration_seconds=180)
        animation = place_cue(scene["id"], cue_label="Dragon Head Move",
                              discipline_channel="ANIMATION", offset_ms=1000,
                              duration_ms=2000)
        lighting = place_cue(scene["id"], cue_label="Cavern Wash",
                             discipline_channel="LIGHTING", offset_ms=1000,
                             duration_ms=2000)
        return {"project": project, "scene": scene,
                "animation": animation, "lighting": lighting}

    def test_a_zero_gap_is_refused_on_the_animation_channel(self, api):
        """On the `ANIMATION` and `SPECIAL_EFFECT` channels a mandatory interlock buffer of 250 milliseconds is added on both sides of every existing occupation, so a cue that begins exactly where its neighbour ends is rejected on those two channels; on `LIGHTING`, `AUDIO` and `MEDIA` exact adjacency with a zero gap is permitted.

        Each cue occupies the half-open span from its `offset_ms` up to but not
        including `offset_ms` plus `duration_ms`, and two cues on the same scene and
        the same `discipline_channel` may not collide.

        The animation channel is already occupied from one second to three, so a snap
        beginning exactly at three seconds falls inside the interlock buffer and is
        refused; the timeline still holds the two cues it started with.

        Design: Difficulty/resource_temporal_overlap/effect_cue_half_open_millisecond_interlock_buffer_binds_only_animation_channels
        """
        ctx = self._scene_with_one_animation_and_one_lighting_cue()

        response = api.create_effect_cue(
            {
                "scene_id": ctx["scene"]["id"], "cue_label": "Dragon Tail Snap Adjacent",
                "discipline_channel": "ANIMATION", "offset_ms": 3000, "duration_ms": 500,
            },
            PROGRAMMER,
        )

        validate_error(response, ApiErrorId.ERR_CUE_CHANNEL_CONFLICT.value)
        cues, meta = validate_paginated(
            api.list_scene_effect_cues(ctx["scene"]["id"], PROGRAMMER))
        assert len(cues) == 2
        assert meta["total_count"] == 2
        assert all(cue["status"] == "PLANNED" for cue in cues)

    def test_the_buffer_clears_at_250_ms_and_never_binds_lighting(self, api):
        """A cue is created `PLANNED`; verifying it on the console advances it to the terminal `VERIFIED` and increments its `version` by one.

        On the `ANIMATION` and `SPECIAL_EFFECT` channels a mandatory interlock buffer
        of 250 milliseconds is added on both sides of every existing occupation, so a
        cue that begins exactly where its neighbour ends is rejected on those two
        channels; on `LIGHTING`, `AUDIO` and `MEDIA` exact adjacency with a zero gap is
        permitted.

        Moving the snap to 3250 milliseconds clears the buffer exactly, and the very
        offset that animation refused is a legal cut on lighting, so the scene ends
        up with four planned cues.

        Design: Difficulty/resource_temporal_overlap/effect_cue_half_open_millisecond_interlock_buffer_binds_only_animation_channels
        """
        ctx = self._scene_with_one_animation_and_one_lighting_cue()

        buffered = validate_success(
            api.create_effect_cue(
                {
                    "scene_id": ctx["scene"]["id"],
                    "cue_label": "Dragon Tail Snap Buffered",
                    "discipline_channel": "ANIMATION", "offset_ms": 3250,
                    "duration_ms": 500,
                },
                PROGRAMMER,
            ),
            201,
        )
        blackout = validate_success(
            api.create_effect_cue(
                {
                    "scene_id": ctx["scene"]["id"], "cue_label": "Cavern Blackout",
                    "discipline_channel": "LIGHTING", "offset_ms": 3000,
                    "duration_ms": 500,
                },
                PROGRAMMER,
            ),
            201,
        )

        assert buffered["offset_ms"] == 3250
        assert buffered["discipline_channel"] == "ANIMATION"
        assert buffered["status"] == "PLANNED"
        assert blackout["offset_ms"] == 3000
        assert blackout["discipline_channel"] == "LIGHTING"
        assert blackout["status"] == "PLANNED"
        cues, meta = validate_paginated(
            api.list_scene_effect_cues(ctx["scene"]["id"], PROGRAMMER))
        assert len(cues) == 4
        assert meta["total_count"] == 4
