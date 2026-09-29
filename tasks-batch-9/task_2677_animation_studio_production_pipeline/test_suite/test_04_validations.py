"""Validation tests: code scoping, cross-aggregate gates and window sanity."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_two_decimal
from test_helpers.constants import (
    DELIVERABLE_DRAFT,
    DELIVERABLE_SUBMITTED,
    JOB_RESERVED,
    NOTE_OPEN,
    NOTE_WAIVED,
    SESSION_CLOSED,
    SESSION_IN_PROGRESS,
    TASK_IN_REVIEW,
)
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    DIRECTOR_USER_ID,
    PRODUCTION_MANAGER_HEADERS,
)


class TestCodeUniquenessScope:
    def test_shot_code_is_unique_per_production_while_production_code_is_studio_wide(
        self, client
    ):
        """The same shot code is a conflict inside one show and a clean create inside another,
        whereas a repeated production code conflicts across the whole studio.

        PRD: "`production_code` is unique across all productions; `shot_code` and `asset_code`
        are unique within their production; `package_code` is unique within its production —
        otherwise `ERR_DUPLICATE_CODE` (409)."

        Design: Corner/validations/duplicate_shot_code_rejects_within_production_but_passes_across_productions
        """
        first = fx.open_production(
            client, title="Aurora Drift", production_code="AD01", budget_cents=100000000
        )
        second = fx.open_production(
            client,
            title="Aurora Drift Two",
            production_code="AD02",
            format="SHORT",
            budget_cents=20000000,
        )
        fx.create_shot(
            client,
            first["id"],
            shot_code="AD01_010_0010",
            planned_finish_at="2026-09-30T00:00:00Z",
        )

        duplicate = client.create_shot(
            f.shot_payload(
                first["id"],
                shot_code="AD01_010_0010",
                frame_count=200,
                budget_cents=2000000,
                planned_finish_at="2026-09-30T00:00:00Z",
            ),
            PRODUCTION_MANAGER_HEADERS,
        )
        validate_error(duplicate, "ERR_DUPLICATE_CODE", 409)

        elsewhere = validate_success(
            client.create_shot(
                f.shot_payload(
                    second["id"],
                    shot_code="AD01_010_0010",
                    budget_cents=500000,
                    planned_finish_at="2026-09-30T00:00:00Z",
                ),
                PRODUCTION_MANAGER_HEADERS,
            ),
            201,
        )
        assert elsewhere["shot_code"] == "AD01_010_0010"
        assert elsewhere["production_id"] == second["id"]

        clone = client.create_production(
            f.production_payload(
                title="Aurora Drift Clone",
                production_code="AD01",
                format="SHORT",
                budget_cents=1000000,
                render_allowance_cents=100000,
            ),
            PRODUCTION_MANAGER_HEADERS,
        )
        validate_error(clone, "ERR_DUPLICATE_CODE", 409)

        _, meta = validate_paginated(
            client.list_shots(PRODUCTION_MANAGER_HEADERS, {"production_id": first["id"]})
        )
        assert meta["total_count"] == 1


class TestBlockingNoteGate:
    def test_waiving_the_last_blocking_note_unblocks_the_identical_submit(self, client):
        """A blocking note anywhere in the deliverable's scope refuses the submit, and waiving
        that note lets the very same call through without disturbing the target task.

        PRD: "First, no director note with `severity` `BLOCKING` may still be `OPEN` or
        `RETAKE_ISSUED` within the deliverable's scope — that scope is the single shot when
        `shot_id` is set, and every shot of the production otherwise — or the submission is
        refused with `ERR_BLOCKING_NOTES_OPEN`."
        PRD: "`WAIVED` is permitted from either state without any condition on the target
        task, records `resolved_by_user_id`, and — importantly — **does not revert a retake
        that has already been issued**: waiving the note does not restore the task, and no
        counter on the shot or the production changes."

        Design: Corner/validations/open_blocking_note_blocks_deliverable_submit_until_waived
        """
        production = fx.active_production(
            client,
            title="Aurora Drift",
            production_code="AD01",
            gate_types=["SCRIPT"],
            approved_color_spaces=["ACEScg", "Rec709"],
        )
        shot = fx.create_shot(
            client,
            production["id"],
            shot_code="AD01_010_0010",
            planned_finish_at="2026-09-30T00:00:00Z",
        )
        task = fx.task_for_stage(client, shot["id"], "LAYOUT")
        fx.assign_task(client, task["id"])
        fx.submit_task(client, task["id"])

        room = fx.calibrated_room(client, name="SCREEN_1", seat_capacity=12)
        session = fx.running_session(
            client,
            production["id"],
            room["id"],
            window_start="2026-08-01T09:00:00Z",
            window_end="2026-08-01T11:00:00Z",
            attendee_count=6,
        )
        note = fx.raise_note(
            client,
            session["id"],
            task["id"],
            "BLOCKING",
            note_text="Camera drifts off the layout guide in the last 20 frames.",
        )
        assert note["status"] == NOTE_OPEN

        deliverable = fx.create_deliverable(
            client,
            production["id"],
            deliverable_type="PROXY_MP4",
            color_space="Rec709",
            resolution="1920x1080",
            bit_depth=8,
        )
        assert deliverable["status"] == DELIVERABLE_DRAFT

        blocked = client.submit_deliverable(
            deliverable["id"], {}, PRODUCTION_MANAGER_HEADERS
        )
        validate_error(blocked, "ERR_BLOCKING_NOTES_OPEN", 422)
        assert fx.read_deliverable(client, deliverable["id"])["status"] == DELIVERABLE_DRAFT

        waived = validate_success(
            client.resolve_director_note(
                note["id"], f.note_resolution_payload("WAIVED"), DIRECTOR_HEADERS
            )
        )
        assert waived["status"] == NOTE_WAIVED
        assert waived["resolved_by_user_id"] == DIRECTOR_USER_ID

        submitted = fx.submit_deliverable(client, deliverable["id"])
        assert submitted["status"] == DELIVERABLE_SUBMITTED

        task_after = fx.read_task(client, task["id"])
        assert task_after["status"] == TASK_IN_REVIEW
        assert task_after["revision_count"] == 0


class TestMasteringPrecondition:
    def test_only_the_master_needs_a_closed_client_review(self, client):
        """A proxy submits with no client review at all, while the master is refused until a
        client review session has actually reached CLOSED — running is not enough.

        PRD: "Second, a `MASTER_EXR` submission additionally requires that at least one review
        session of the production with `session_type` `CLIENT_REVIEW` has reached `status`
        `CLOSED`; a client review that was cancelled does not count, and the absence of a
        closed one is `ERR_CLIENT_REVIEW_REQUIRED`."

        Design: Corner/validations/master_exr_submit_requires_closed_client_review
        """
        production = fx.active_production(
            client,
            title="Aurora Drift",
            production_code="AD01",
            gate_types=["SCRIPT"],
            approved_color_spaces=["ACEScg", "Rec709"],
        )
        room = fx.calibrated_room(client, name="SCREEN_1", seat_capacity=12)

        master = fx.create_deliverable(
            client,
            production["id"],
            deliverable_type="MASTER_EXR",
            color_space="ACEScg",
            resolution="3840x2160",
            bit_depth=16,
        )
        assert master["version_label"] == "v01"
        proxy = fx.create_deliverable(
            client,
            production["id"],
            deliverable_type="PROXY_MP4",
            color_space="Rec709",
            resolution="1920x1080",
            bit_depth=8,
        )

        refused = client.submit_deliverable(master["id"], {}, PRODUCTION_MANAGER_HEADERS)
        validate_error(refused, "ERR_CLIENT_REVIEW_REQUIRED", 422)

        assert fx.submit_deliverable(client, proxy["id"])["status"] == DELIVERABLE_SUBMITTED

        session = fx.running_session(
            client,
            production["id"],
            room["id"],
            session_type="CLIENT_REVIEW",
            window_start="2026-08-01T09:00:00Z",
            window_end="2026-08-01T11:00:00Z",
            attendee_count=8,
        )
        assert session["status"] == SESSION_IN_PROGRESS

        still_refused = client.submit_deliverable(
            master["id"], {}, PRODUCTION_MANAGER_HEADERS
        )
        validate_error(still_refused, "ERR_CLIENT_REVIEW_REQUIRED", 422)

        closed = fx.close_session(client, session["id"])
        assert closed["status"] == SESSION_CLOSED
        assert closed["retake_issued_count"] == 0

        assert fx.submit_deliverable(client, master["id"])["status"] == DELIVERABLE_SUBMITTED


class TestRenderWindowSanity:
    def test_a_window_opening_exactly_at_the_clock_is_admitted(self, client):
        """One second before the clock is refused and a zero-length window is refused, but a
        window opening on the clock instant itself reserves, and neither rejection consumed
        the pool version.

        PRD: "`window_start` is strictly earlier than `window_end` and is not earlier than the
        logical clock now; and a shot's `planned_start_at` is strictly earlier than its
        `planned_finish_at` — otherwise `ERR_INVALID_WINDOW` (422)."

        Design: Corner/validations/render_window_start_before_clock_rejects_at_the_boundary
        """
        pool = fx.create_pool(
            client, name="FARM_A", total_cores=100, cost_per_core_hour_cents=175
        )
        production = fx.active_production(
            client, title="Aurora Drift", production_code="AD01", gate_types=["SCRIPT"]
        )
        shot = fx.create_shot(
            client,
            production["id"],
            shot_code="AD01_010_0010",
            planned_finish_at="2026-09-30T00:00:00Z",
        )
        task = fx.task_for_stage(client, shot["id"], "LAYOUT")
        fx.assign_task(client, task["id"])
        pool_version = fx.read_pool(client, pool["id"])["version"]

        def attempt(window_start, window_end):
            return client.create_render_job(
                f.render_job_payload(
                    pool["id"],
                    task["id"],
                    pool_version,
                    requested_cores=3,
                    window_start=window_start,
                    window_end=window_end,
                    frame_count=120,
                    seconds_per_frame=50,
                ),
                PRODUCTION_MANAGER_HEADERS,
            )

        validate_error(
            attempt("2026-07-31T23:59:59Z", "2026-08-02T06:00:00Z"),
            "ERR_INVALID_WINDOW",
            422,
        )
        validate_error(
            attempt("2026-08-02T00:00:00Z", "2026-08-02T00:00:00Z"),
            "ERR_INVALID_WINDOW",
            422,
        )

        reserved = validate_success(
            attempt("2026-08-01T00:00:00Z", "2026-08-01T06:00:00Z"), 201
        )
        assert reserved["status"] == JOB_RESERVED
        assert_two_decimal(reserved["committed_core_hours"], 18.00, "committed_core_hours")

        _, meta = validate_paginated(
            client.list_render_jobs(
                PRODUCTION_MANAGER_HEADERS, {"render_pool_id": pool["id"]}
            )
        )
        assert meta["total_count"] == 1
