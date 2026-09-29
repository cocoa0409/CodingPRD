"""State-machine tests: initial states, guarded transitions, cascades and lockdown."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ASSET_BUILD_STATE_INVALID,
    ERR_DELIVERABLES_INCOMPLETE,
    ERR_GATE_STATE_INVALID,
    ERR_PRODUCTION_PHASE_INVALID,
    ERR_SESSION_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_two_decimal,
)
from test_helpers.constants import (
    CLOCK_START,
    COLOR_ACESCG,
    COLOR_REC709,
    JOB_RESERVED,
    LIBRARY_DEPRECATED,
    LIBRARY_PRIVATE,
    PHASE_DELIVERY,
    PHASE_WRAPPED,
    SESSION_CLOSED,
    SHOT_COMPLETE,
    SHOT_IN_PRODUCTION,
    STAGES_IN_ORDER,
    TASK_APPROVED,
    TASK_IN_REVIEW,
    TASK_SUBMITTED,
)
from test_helpers.test_users import (
    ARTIST_HEADERS,
    DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SUPERVISOR_HEADERS,
)


def _single_gate_active_production(client, **overrides):
    """A production whose only gate has been cleared, so the show is active."""
    overrides.setdefault("gate_types", ["SCRIPT"])
    return fx.active_production(client, **overrides)


class TestRenderJobInitialState:
    def test_new_reservation_opens_reserved_with_no_settlement_figures(self, client):
        """A newly accepted reservation opens at RESERVED with no settled cost and lifts
        the pool's reserved job count in the same request.

        PRD: "Accepting the reservation sets `status` to `RESERVED`, adds 1 to the pool's
        `version`, recomputes the pool's `committed_core_hours` and `reserved_job_count`,
        and then recomputes the shot's `render_cost_committed_cents` followed by the
        production's `render_committed_cents` — in that order, so the ledger above always
        agrees with the ledger below."
        PRD: "`actual_seconds_per_frame`, `frames_completed` and `final_cost_cents` all
        stay null while the job is `RESERVED`."

        Design: Corner/state_machines/render_job_initial_state_is_reserved
        """
        production = _single_gate_active_production(
            client, title="Aurora Drift", production_code="AD01"
        )
        shot = fx.create_shot(
            client,
            production["id"],
            shot_code="AD01_010_0010",
            budget_cents=1000000,
            planned_finish_at="2026-09-30T00:00:00Z",
        )
        layout = fx.task_for_stage(client, shot["id"], "LAYOUT")
        fx.assign_task(client, layout["id"])
        pool = fx.create_pool(
            client, name="FARM-A", total_cores=100, cost_per_core_hour_cents=175
        )

        job = validate_success(
            client.create_render_job(
                {
                    "render_pool_id": pool["id"],
                    "shot_stage_task_id": layout["id"],
                    "priority": "NORMAL",
                    "requested_cores": 3,
                    "window_start": "2026-08-10T00:00:00Z",
                    "window_end": "2026-08-10T06:00:00Z",
                    "frame_count": 120,
                    "seconds_per_frame": 50,
                    "expected_render_pool_version": pool["version"],
                },
                PRODUCTION_MANAGER_HEADERS,
            ),
            201,
        )
        assert job["status"] == JOB_RESERVED
        assert job["final_cost_cents"] is None
        assert job["actual_seconds_per_frame"] is None
        assert job["preempted_by_render_job_id"] is None

        pool_after = fx.read_pool(client, pool["id"])
        assert pool_after["reserved_job_count"] == 1


class TestLibraryNominationPrecondition:
    def test_nomination_before_publication_is_refused_and_leaves_both_dimensions(self, client):
        """Nominating an asset that has not been published is refused on the build
        dimension and moves neither dimension nor the nominator field.

        PRD: "An artist nominates a published asset, which moves `library_status` `PRIVATE
        → LIBRARY_CANDIDATE` and records the nominator in
        `library_submitted_by_user_id`; the nomination requires `build_status` to be
        `PUBLISHED` (otherwise `ERR_ASSET_BUILD_STATE_INVALID`) and `library_status` to be
        `PRIVATE` (otherwise `ERR_ASSET_LIBRARY_STATE_INVALID`), and it leaves
        `build_status` completely untouched."

        Design: Corner/state_machines/library_submit_before_publish_rejects
        """
        production = fx.open_production(client, title="Aurora Drift", production_code="AD01")
        asset = fx.create_asset(
            client,
            production["id"],
            asset_code="AD01_PROP_01",
            asset_type="PROP",
            base_complexity_points=50.00,
        )

        response = client.library_submit_asset(asset["id"], {}, ARTIST_HEADERS)
        validate_error(response, ERR_ASSET_BUILD_STATE_INVALID, 409)

        stored = fx.read_asset(client, asset["id"])
        assert stored["build_status"] == "BRIEFED"
        assert stored["library_status"] == LIBRARY_PRIVATE
        assert stored["library_submitted_by_user_id"] is None


class TestDirectorNoteSideEffect:
    def test_raising_a_note_moves_a_submitted_task_into_review(self, client):
        """A note raised against a submitted task opens OPEN, counts on its session and
        flips the task into review without touching its revision tally.

        PRD: "A new note opens at `status` `OPEN` with `raised_by_user_id` set to the
        director and `resolved_by_user_id` null, recomputes the session's `note_count`,
        and — as noted above — moves a `SUBMITTED` target task to `IN_REVIEW`."
        PRD: "Handing work in drives the task `IN_PROGRESS → SUBMITTED`, records
        `submitted_by_user_id` and stamps `submitted_at` from the logical clock; an
        optional `hours` field on the same call is added to `actual_hours` before the
        transition is recorded."

        Design: Corner/state_machines/director_note_moves_submitted_task_to_in_review
        """
        production = _single_gate_active_production(
            client, title="Aurora Drift", production_code="AD01"
        )
        shot = fx.create_shot(
            client,
            production["id"],
            shot_code="AD01_010_0010",
            budget_cents=1000000,
            planned_finish_at="2026-09-30T00:00:00Z",
        )
        layout = fx.task_for_stage(client, shot["id"], "LAYOUT")
        fx.assign_task(client, layout["id"])
        submitted = fx.submit_task(client, layout["id"], hours=4.00)
        assert submitted["status"] == TASK_SUBMITTED
        assert_two_decimal(submitted["actual_hours"], 4.00, "actual_hours")

        room = fx.calibrated_room(
            client, name="STAGE-1", seat_capacity=12, room_color_space=COLOR_ACESCG
        )
        session = fx.running_session(
            client,
            production["id"],
            room["id"],
            session_type="DAILIES",
            window_start="2026-08-05T09:00:00Z",
            window_end="2026-08-05T10:00:00Z",
            attendee_count=5,
        )

        note = validate_success(
            client.create_director_note(
                {
                    "review_session_id": session["id"],
                    "shot_stage_task_id": layout["id"],
                    "severity": "MINOR",
                    "note_text": "Tighten the framing by two percent.",
                },
                DIRECTOR_HEADERS,
            ),
            201,
        )
        assert note["status"] == "OPEN"
        assert note["raised_by_user_id"] == "u-dir-01"
        assert note["resolved_by_user_id"] is None

        task_after = fx.read_task(client, layout["id"], SUPERVISOR_HEADERS)
        assert task_after["status"] == TASK_IN_REVIEW
        assert task_after["revision_count"] == 0

        session_after = validate_success(
            client.get_review_session(session["id"], DIRECTOR_HEADERS)
        )
        assert session_after["note_count"] == 1
        assert session_after["retake_issued_count"] == 0


class TestClosedSessionIsTerminal:
    def test_a_closed_session_can_be_neither_cancelled_nor_reopened(self, client):
        """A closed session refuses both cancellation and a second start, and keeps the
        stamps the close wrote.

        PRD: "Cancelling a session that is already `CLOSED` is `ERR_SESSION_STATE_INVALID`."
        PRD: "Opening a session moves it `SCHEDULED → IN_PROGRESS` and stamps `opened_at`."
        PRD: "Before any client sets it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to real time."

        Design: Corner/state_machines/closed_review_session_cannot_be_cancelled
        """
        production = _single_gate_active_production(
            client, title="Aurora Drift", production_code="AD01"
        )
        room = fx.calibrated_room(
            client, name="STAGE-1", seat_capacity=12, room_color_space=COLOR_ACESCG
        )
        session = fx.book_session(
            client,
            production["id"],
            room["id"],
            session_type="DAILIES",
            window_start="2026-08-05T09:00:00Z",
            window_end="2026-08-05T10:00:00Z",
            attendee_count=5,
        )
        opened = fx.open_session(client, session["id"])
        assert_instant(opened["opened_at"], CLOCK_START, "opened_at")
        closed = fx.close_session(client, session["id"])
        assert closed["status"] == SESSION_CLOSED
        assert_instant(closed["closed_at"], CLOCK_START, "closed_at")

        cancel = client.cancel_review_session(
            session["id"], {"reason": "No longer needed."}, PRODUCTION_MANAGER_HEADERS
        )
        validate_error(cancel, ERR_SESSION_STATE_INVALID, 409)

        restart = client.start_review_session(session["id"], {}, DIRECTOR_HEADERS)
        validate_error(restart, ERR_SESSION_STATE_INVALID, 409)

        after = validate_success(client.get_review_session(session["id"], DIRECTOR_HEADERS))
        assert after["status"] == SESSION_CLOSED
        assert after["closed_at"] == closed["closed_at"]


class TestGateSubmissionIsNotIdempotent:
    def test_second_submit_on_a_gate_in_review_is_refused_and_keeps_the_url(self, client):
        """Re-submitting a gate that is already in review is refused and overwrites
        neither the stored package URL nor the revision tally.

        PRD: "Submitting a gate that is not in `DRAFT` or `CHANGES_REQUESTED` — one
        already `IN_REVIEW`, `APPROVED` or `LOCKED` — is refused with
        `ERR_GATE_STATE_INVALID`."

        Design: Corner/state_machines/duplicate_gate_submit_rejects_second_call
        """
        production = fx.open_production(
            client, title="Aurora Drift", production_code="AD01", gate_types=["SCRIPT"]
        )
        gate = fx.gates_of(client, production["id"])[0]

        first = validate_success(
            client.submit_gate(
                gate["id"],
                {"package_url": "s3://ad01/script/v1.pdf"},
                PRODUCTION_MANAGER_HEADERS,
            )
        )
        assert first["status"] == "IN_REVIEW"
        assert first["package_url"] == "s3://ad01/script/v1.pdf"
        assert first["revision_count"] == 0
        assert first["submitted_by_user_id"] == "u-pm-01"

        second = client.submit_gate(
            gate["id"],
            {"package_url": "s3://ad01/script/v1-again.pdf"},
            PRODUCTION_MANAGER_HEADERS,
        )
        validate_error(second, ERR_GATE_STATE_INVALID, 409)

        after = validate_success(client.get_gate(gate["id"], PRODUCTION_MANAGER_HEADERS))
        assert after["status"] == "IN_REVIEW"
        assert after["package_url"] == "s3://ad01/script/v1.pdf"
        assert after["revision_count"] == 0


class TestAssetRetirementCascade:
    def test_retiring_a_library_asset_deprecates_it_and_restores_descendant_points(
        self, client
    ):
        """Retiring a library-approved asset deprecates its library entry and withdraws
        the reuse credit from its descendant, while retiring a private asset cascades
        nothing.

        PRD: "When an asset advances `PUBLISHED → RETIRED` and its `library_status` is
        `LIBRARY_APPROVED` at that moment, the library dimension follows it down:
        `library_status` moves `LIBRARY_APPROVED → LIBRARY_DEPRECATED`."
        PRD: "Each such descendant recomputes its reuse credit under the rule above:
        because `reuse_source_stale` is now true, its `reuse_discount_pct` collapses to
        0.00 and its `effective_complexity_points` returns to its full
        `base_complexity_points`."

        Design: Corner/state_machines/asset_retire_deprecates_library_entry_and_restores_descendant_points
        """
        production = fx.open_production(client, title="Aurora Drift", production_code="AD01")
        hero = fx.library_source_asset(
            client,
            production["id"],
            asset_code="AD01_CHAR_HERO",
            asset_type="CHARACTER_MODEL",
            base_complexity_points=300.00,
        )
        assert hero["library_status"] == "LIBRARY_APPROVED"

        sidekick = fx.create_asset(
            client,
            production["id"],
            asset_code="AD01_CHAR_SIDEKICK",
            asset_type="CHARACTER_MODEL",
            base_complexity_points=200.00,
            derived_from_asset_id=hero["id"],
        )
        assert sidekick["reuse_depth"] == 1
        assert_two_decimal(sidekick["reuse_discount_pct"], 0.40, "reuse_discount_pct")
        assert_two_decimal(
            sidekick["effective_complexity_points"], 120.00, "effective_complexity_points"
        )
        assert sidekick["reuse_source_stale"] is False

        prop = fx.create_asset(
            client,
            production["id"],
            asset_code="AD01_PROP_01",
            asset_type="PROP",
            base_complexity_points=50.00,
        )
        fx.publish_asset(client, prop["id"])

        retired = validate_success(
            client.advance_asset_build(
                hero["id"], {"to_build_status": "RETIRED"}, ARTIST_HEADERS
            )
        )
        assert retired["build_status"] == "RETIRED"
        assert retired["library_status"] == LIBRARY_DEPRECATED

        descendant = fx.read_asset(client, sidekick["id"])
        assert descendant["reuse_source_stale"] is True
        assert_two_decimal(descendant["reuse_discount_pct"], 0.00, "reuse_discount_pct")
        assert_two_decimal(
            descendant["effective_complexity_points"], 200.00, "effective_complexity_points"
        )
        assert descendant["reuse_depth"] == 1

        retired_prop = validate_success(
            client.advance_asset_build(
                prop["id"], {"to_build_status": "RETIRED"}, ARTIST_HEADERS
            )
        )
        assert retired_prop["build_status"] == "RETIRED"
        assert retired_prop["library_status"] == LIBRARY_PRIVATE

        derived_rows, _ = validate_paginated(
            client.list_assets(ARTIST_HEADERS, {"derived_from_asset_id": hero["id"]})
        )
        assert [row["asset_code"] for row in derived_rows] == ["AD01_CHAR_SIDEKICK"]


class TestShotCompletion:
    def test_shot_completes_only_when_the_fifth_stage_is_approved(self, client):
        """The shot flips to complete on the fifth approval, clearing the current stage
        and earning the whole budget, and the production counts it as completed.

        PRD: "Alongside `status`, `current_stage` always names the stage of the
        lowest-`stage_order` task of the shot whose status is not `APPROVED`, and is null
        once the shot is `COMPLETE`."
        PRD: "Under it, credit is earned only in discrete stage-sized jumps: the system
        sums `stage_weight_pct` over exactly those stage tasks of the shot whose `status`
        is `APPROVED`, multiplies the shot's `budget_cents` by that sum, and rounds
        half-up to a whole cent."

        Design: Corner/state_machines/shot_completes_when_all_five_stages_approved
        """
        production = _single_gate_active_production(
            client, title="Aurora Drift", production_code="AD01"
        )
        shot = fx.create_shot(
            client,
            production["id"],
            shot_code="AD01_010_0010",
            budget_cents=1000000,
            planned_finish_at="2026-09-30T00:00:00Z",
        )
        for stage in STAGES_IN_ORDER[:4]:
            approved = fx.walk_stage_to_approved(client, shot["id"], stage)
            assert approved["status"] == TASK_APPROVED

        comp = fx.task_for_stage(client, shot["id"], "COMP")
        fx.assign_task(client, comp["id"])
        fx.submit_task(client, comp["id"])

        before = fx.read_shot(client, shot["id"])
        assert before["status"] == SHOT_IN_PRODUCTION
        assert before["current_stage"] == "COMP"
        assert_cents(before["bcwp_cents"], 800000, "bcwp_cents")

        decided = fx.approve_task(client, comp["id"])
        assert decided["status"] == TASK_APPROVED
        assert_instant(decided["approved_at"], CLOCK_START, "approved_at")

        after = fx.read_shot(client, shot["id"])
        assert after["status"] == SHOT_COMPLETE
        assert after["current_stage"] is None
        assert_cents(after["bcwp_cents"], 1000000, "bcwp_cents")

        production_after = fx.read_production(client, production["id"])
        assert production_after["shot_count"] == 1
        assert production_after["completed_shot_count"] == 1
        assert_cents(production_after["bcwp_cents"], 1000000, "bcwp_cents")


class TestWrappedProductionLockdown:
    def test_wrap_waits_for_delivery_and_then_locks_the_whole_show(self, client):
        """A show cannot wrap while its only deliverable is merely QC-passed, and once
        wrapped it refuses both new shots and any move back to delivery.

        PRD: "Moving `DELIVERY → WRAPPED` requires at least one deliverable of the
        production to be `DELIVERED` and no deliverable to remain in `DRAFT`, `SUBMITTED`
        or `QC_PASSED`, otherwise `ERR_DELIVERABLES_INCOMPLETE`."
        PRD: "Once a production is `WRAPPED`, nothing under it is writable at all."

        Design: Corner/state_machines/wrapped_production_rejects_further_writes
        """
        production = _single_gate_active_production(
            client,
            title="Slate Harbour",
            production_code="AD04",
            format="SHORT",
            budget_cents=20000000,
            render_allowance_cents=2000000,
            approved_color_spaces=[COLOR_ACESCG, COLOR_REC709],
        )
        deliverable = fx.create_deliverable(
            client,
            production["id"],
            expected_version=production["version"],
            deliverable_type="PROXY_MP4",
            color_space=COLOR_REC709,
            resolution="1920x1080",
            bit_depth=8,
        )
        assert deliverable["version_label"] == "v01"
        fx.submit_deliverable(client, deliverable["id"])
        passed = fx.qc_pass_deliverable(client, deliverable["id"])
        assert passed["status"] == "QC_PASSED"

        to_delivery = fx.advance_to_delivery(client, production["id"])
        assert to_delivery["phase"] == PHASE_DELIVERY

        early_wrap = client.advance_production_phase(
            production["id"], {"to_phase": PHASE_WRAPPED}, PRODUCTION_MANAGER_HEADERS
        )
        validate_error(early_wrap, ERR_DELIVERABLES_INCOMPLETE, 409)

        shipped = validate_success(
            client.deliver_deliverable(deliverable["id"], {}, PRODUCTION_MANAGER_HEADERS)
        )
        assert shipped["status"] == "DELIVERED"
        assert_instant(shipped["delivered_at"], CLOCK_START, "delivered_at")

        wrapped = validate_success(
            client.advance_production_phase(
                production["id"], {"to_phase": PHASE_WRAPPED}, PRODUCTION_MANAGER_HEADERS
            )
        )
        assert wrapped["phase"] == PHASE_WRAPPED

        blocked_shot = client.create_shot(
            {
                "production_id": production["id"],
                "shot_code": "AD04_010_0010",
                "sequence_code": "010",
                "frame_count": 48,
                "budget_cents": 200000,
                "planned_start_at": "2026-08-05T00:00:00Z",
                "planned_finish_at": "2026-09-05T00:00:00Z",
            },
            PRODUCTION_MANAGER_HEADERS,
        )
        validate_error(blocked_shot, ERR_PRODUCTION_PHASE_INVALID, 409)

        backwards = client.advance_production_phase(
            production["id"], {"to_phase": PHASE_DELIVERY}, PRODUCTION_MANAGER_HEADERS
        )
        validate_error(backwards, ERR_PRODUCTION_PHASE_INVALID, 409)
