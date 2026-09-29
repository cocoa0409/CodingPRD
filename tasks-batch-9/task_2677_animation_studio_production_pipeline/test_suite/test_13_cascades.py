"""Transitive cascades: the review-close retake chain and the gate-activation fan-out."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_GATE_SEQUENCE_VIOLATION
from test_helpers.assertions import assert_unchanged
from test_helpers.constants import (
    GATE_APPROVED,
    GATE_IN_REVIEW,
    GATE_LOCKED,
    NOTE_MAJOR,
    NOTE_MINOR,
    NOTE_OPEN,
    NOTE_RETAKE_ISSUED,
    PHASE_PRE_PRODUCTION,
    PHASE_PRODUCTION_ACTIVE,
    SESSION_CLOSED,
    SESSION_DIRECTOR_REVIEW,
    SHOT_BLOCKED_PREPROD,
    SHOT_IN_PRODUCTION,
    SHOT_READY,
    TASK_APPROVED,
    TASK_RETAKE,
)
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SUPERVISOR_HEADERS,
)


def _show_with_shot(client):
    production = fx.active_production(
        client,
        title="Aurora Drift",
        production_code="AD01",
        budget_cents=100000000,
        render_allowance_cents=5000000,
        contingency_pct=0.10,
        approved_color_spaces=["ACEScg", "Rec709"],
        gate_types=["SCRIPT"],
    )
    shot = fx.create_shot(
        client,
        production["id"],
        shot_code="AD01_010_0010",
        sequence_code="010",
        frame_count=120,
        budget_cents=1000000,
        planned_start_at="2026-08-01T00:00:00Z",
        planned_finish_at="2026-09-30T00:00:00Z",
    )
    return production, shot


def _retake_layout_twice_then_approve(client, shot_id):
    """Walk the LAYOUT task through two supervisor retakes and one approval."""
    task = fx.task_for_stage(client, shot_id, "LAYOUT")
    fx.assign_task(client, task["id"])
    retakes = []
    for _ in range(2):
        fx.submit_task(client, task["id"])
        retakes.append(
            validate_success(
                client.decide_stage_task(
                    task["id"], f.task_decision_payload("RETAKE"), SUPERVISOR_HEADERS
                )
            )
        )
    fx.submit_task(client, task["id"])
    return task, retakes, fx.approve_task(client, task["id"])


def _director_review_in_progress(client, production_id):
    room = fx.calibrated_room(
        client, name="STAGE-1", seat_capacity=12, room_color_space="ACEScg"
    )
    return fx.running_session(
        client,
        production_id,
        room["id"],
        session_type=SESSION_DIRECTOR_REVIEW,
        window_start="2026-08-01T10:00:00Z",
        window_end="2026-08-01T11:00:00Z",
        attendee_count=6,
    )


class TestReviewCloseCascade:
    def test_one_close_walks_note_task_shot_and_production_in_a_single_request(self, client):
        """Closing the session flips the MAJOR note, which retakes an APPROVED task onto its
        third revision, which latches the shot's escalation flag, which raises the show's
        at-risk count — and the MINOR note in the same session moves nothing.

        PRD: "Each note that is still `OPEN` and whose `severity` is `MAJOR` or `BLOCKING`
        moves `OPEN → RETAKE_ISSUED`; each such note whose target stage task is in
        `SUBMITTED`, `IN_REVIEW` or `APPROVED` additionally drives that task to `RETAKE` with
        `revision_count` increased by 1."
        PRD: "Notes whose `severity` is `MINOR` stay `OPEN` and issue no retake at all."
        PRD: "The task's `revision_count` is increased by 1, and `escalated` is set to true
        when `revision_count` has reached **three or more** — the comparison is inclusive, so
        the third retake escalates the task and the second does not."
        PRD: "Every shot touched by those retakes recomputes its `retake_count`,
        `escalation_flag` and `status`, and the production recomputes `total_retake_count`,
        `at_risk_shot_count` and `completed_shot_count`."

        Design: Difficulty/transitive_cascade/review_close_note_retake_escalates_shot_and_production
        """
        production, shot = _show_with_shot(client)
        task, retakes, approved = _retake_layout_twice_then_approve(client, shot["id"])
        assert retakes[0]["revision_count"] == 1
        assert retakes[0]["escalated"] is False
        assert retakes[1]["revision_count"] == 2
        assert retakes[1]["escalated"] is False, "the second retake does not escalate"
        assert approved["status"] == TASK_APPROVED

        session = _director_review_in_progress(client, production["id"])
        major = fx.raise_note(client, session["id"], task["id"], NOTE_MAJOR)
        minor = fx.raise_note(client, session["id"], task["id"], NOTE_MINOR)
        assert major["status"] == NOTE_OPEN
        assert minor["status"] == NOTE_OPEN
        assert fx.read_task(client, task["id"])["status"] == TASK_APPROVED, (
            "raising a note against an approved task leaves its status alone"
        )

        closed = fx.close_session(client, session["id"])
        assert closed["status"] == SESSION_CLOSED
        assert closed["note_count"] == 2
        assert closed["retake_issued_count"] == 1, "only the MAJOR note issued a retake"
        assert closed["closed_at"] is not None

        assert (
            validate_success(client.get_director_note(major["id"], DIRECTOR_HEADERS))["status"]
            == NOTE_RETAKE_ISSUED
        )
        assert (
            validate_success(client.get_director_note(minor["id"], DIRECTOR_HEADERS))["status"]
            == NOTE_OPEN
        ), "link 1 never reaches a MINOR note"

        retaken = fx.read_task(client, task["id"])
        assert retaken["status"] == TASK_RETAKE
        assert retaken["revision_count"] == 3
        assert retaken["escalated"] is True
        assert retaken["approved_at"] is None

        escalated_shot = fx.read_shot(client, shot["id"])
        assert escalated_shot["status"] == SHOT_IN_PRODUCTION
        assert escalated_shot["retake_count"] == 3
        assert escalated_shot["escalation_flag"] is True

        rolled_up = fx.read_production(client, production["id"])
        assert rolled_up["total_retake_count"] == 3
        assert rolled_up["at_risk_shot_count"] == 1
        assert rolled_up["completed_shot_count"] == 0

    def test_a_minor_only_close_leaves_the_whole_chain_where_it_stood(self, client):
        """A session holding nothing but a MINOR note closes with no retakes issued, so the
        task keeps its approval and revision 2 and the show stays off the at-risk list.

        PRD: "The session's `retake_issued_count` is set to the number of notes actually moved
        to `RETAKE_ISSUED`."
        PRD: "Notes whose `severity` is `MINOR` stay `OPEN` and issue no retake at all."
        PRD: "Once true, `escalated` latches: a later approval never clears it, and
        `revision_count` never resets."

        Design: Difficulty/transitive_cascade/review_close_note_retake_escalates_shot_and_production
        """
        production, shot = _show_with_shot(client)
        task, _, approved = _retake_layout_twice_then_approve(client, shot["id"])
        shot_before = fx.read_shot(client, shot["id"])
        production_before = fx.read_production(client, production["id"])

        session = _director_review_in_progress(client, production["id"])
        minor = fx.raise_note(client, session["id"], task["id"], NOTE_MINOR)

        closed = fx.close_session(client, session["id"])
        assert closed["status"] == SESSION_CLOSED
        assert closed["note_count"] == 1
        assert closed["retake_issued_count"] == 0

        assert (
            validate_success(client.get_director_note(minor["id"], DIRECTOR_HEADERS))["status"]
            == NOTE_OPEN
        )

        untouched_task = fx.read_task(client, task["id"])
        assert untouched_task["status"] == TASK_APPROVED
        assert untouched_task["revision_count"] == 2
        assert untouched_task["escalated"] is False
        assert_unchanged(approved, untouched_task, ["status", "revision_count", "approved_at"])

        assert_unchanged(
            shot_before,
            fx.read_shot(client, shot["id"]),
            ["status", "retake_count", "escalation_flag", "bcwp_cents"],
        )
        assert_unchanged(
            production_before,
            fx.read_production(client, production["id"]),
            ["total_retake_count", "at_risk_shot_count", "completed_shot_count"],
        )


def _two_gate_show_with_two_blocked_shots(client):
    """AD02 in PRE_PRODUCTION with SCRIPT and STORYBOARD gates and two blocked shots."""
    production = fx.open_production(
        client,
        title="Aurora Drift II",
        production_code="AD02",
        budget_cents=100000000,
        render_allowance_cents=5000000,
        contingency_pct=0.10,
        gate_types=["SCRIPT", "STORYBOARD"],
    )
    shots = [
        fx.create_shot(
            client,
            production["id"],
            shot_code=shot_code,
            sequence_code="010",
            frame_count=120,
            budget_cents=1000000,
            planned_start_at="2026-08-01T00:00:00Z",
            planned_finish_at="2026-09-30T00:00:00Z",
        )
        for shot_code in ("AD02_010_0010", "AD02_010_0020")
    ]
    script = fx.gate_for_type(client, production["id"], "SCRIPT")
    storyboard = fx.gate_for_type(client, production["id"], "STORYBOARD")
    return production, shots, script, storyboard


class TestGateActivationFanOut:
    def test_approving_the_last_gate_locks_every_gate_and_releases_every_shot(self, client):
        """One review decision mutates four rows across three tables: the show starts, both
        gates drop to LOCKED, and both blocked shots come up READY.

        PRD: "Approving the production's last outstanding gate is the event that starts the
        show."
        PRD: "The moment every gate row of the production has `status` `APPROVED`, the system
        — with no separate request from anyone — moves the production `PRE_PRODUCTION →
        PRODUCTION_ACTIVE`, drives every one of its gates `APPROVED → LOCKED` (a locked gate
        is immutable, and any further submission attempt on it returns
        `ERR_GATE_STATE_INVALID`), recomputes every shot of the production from
        `BLOCKED_PREPROD` to `READY`, and adds 1 to the production's `version`."
        PRD: "A newly created shot has `status` `BLOCKED_PREPROD` while its production is
        still in `PRE_PRODUCTION`, and `READY` if the production has already reached
        `PRODUCTION_ACTIVE`."

        Design: Difficulty/transitive_cascade/design_gate_approval_activates_production_and_unblocks_shots
        """
        production, shots, script, storyboard = _two_gate_show_with_two_blocked_shots(client)
        assert script["sequence_index"] == 1
        assert storyboard["sequence_index"] == 2
        assert fx.read_production(client, production["id"])["phase"] == PHASE_PRE_PRODUCTION
        for shot in shots:
            assert fx.read_shot(client, shot["id"])["status"] == SHOT_BLOCKED_PREPROD

        fx.clear_gate(client, script["id"])
        mid = validate_success(client.get_gate(script["id"], PRODUCTION_MANAGER_HEADERS))
        assert mid["status"] == GATE_APPROVED, (
            "the first gate rests at APPROVED while a later gate is still outstanding"
        )
        assert fx.read_production(client, production["id"])["phase"] == PHASE_PRE_PRODUCTION

        submitted = validate_success(
            client.submit_gate(
                storyboard["id"],
                f.gate_submit_payload("s3://ad02/storyboard/v1.pdf"),
                PRODUCTION_MANAGER_HEADERS,
            )
        )
        assert submitted["status"] == GATE_IN_REVIEW
        validate_success(
            client.decide_gate(
                storyboard["id"], f.gate_decision_payload("APPROVED"), DIRECTOR_HEADERS
            )
        )

        started = fx.read_production(client, production["id"])
        assert started["phase"] == PHASE_PRODUCTION_ACTIVE
        assert started["shot_count"] == 2

        for gate_id in (script["id"], storyboard["id"]):
            assert (
                validate_success(client.get_gate(gate_id, PRODUCTION_MANAGER_HEADERS))["status"]
                == GATE_LOCKED
            )
        for shot in shots:
            assert fx.read_shot(client, shot["id"])["status"] == SHOT_READY

    def test_the_second_gate_cannot_be_submitted_before_the_first_is_approved(self, client):
        """An out-of-order submission is refused and the chain stays put: the show is still in
        pre-production and both shots are still blocked.

        PRD: "Submission is legal only while the production is in `PRE_PRODUCTION`, and only
        when every gate of the same production with a smaller `sequence_index` has already
        reached `APPROVED` — an out-of-order submission is refused with
        `ERR_GATE_SEQUENCE_VIOLATION`."
        PRD: "Every gate starts with `status` `DRAFT`, `revision_count` 0, and null
        `package_url`, `submitted_by_user_id`, `decided_by_user_id` and `decided_at`."

        Design: Difficulty/transitive_cascade/design_gate_approval_activates_production_and_unblocks_shots
        """
        production, shots, script, storyboard = _two_gate_show_with_two_blocked_shots(client)
        assert storyboard["status"] == "DRAFT"
        assert storyboard["package_url"] is None

        validate_error(
            client.submit_gate(
                storyboard["id"],
                f.gate_submit_payload("s3://ad02/storyboard/v1.pdf"),
                PRODUCTION_MANAGER_HEADERS,
            ),
            ERR_GATE_SEQUENCE_VIOLATION,
            409,
        )

        after = validate_success(client.get_gate(storyboard["id"], PRODUCTION_MANAGER_HEADERS))
        assert_unchanged(
            storyboard, after, ["status", "package_url", "submitted_by_user_id", "version"]
        )
        assert fx.read_production(client, production["id"])["phase"] == PHASE_PRE_PRODUCTION
        for shot in shots:
            assert fx.read_shot(client, shot["id"])["status"] == SHOT_BLOCKED_PREPROD

        fx.clear_gate(client, script["id"])
        reopened = validate_success(
            client.submit_gate(
                storyboard["id"],
                f.gate_submit_payload("s3://ad02/storyboard/v1.pdf"),
                PRODUCTION_MANAGER_HEADERS,
            )
        )
        assert reopened["status"] == GATE_IN_REVIEW
