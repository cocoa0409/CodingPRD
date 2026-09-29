"""Cross-entity state dependencies: the grandparent's phase and the room's calibration."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CALIBRATION_EXPIRED,
    ERR_PREVIOUS_STAGE_NOT_APPROVED,
    ERR_PRODUCTION_PHASE_INVALID,
    ERR_ROOM_NOT_CALIBRATED,
)
from test_helpers.assertions import assert_instant, assert_unchanged
from test_helpers.constants import (
    CALIBRATION_CALIBRATED,
    CALIBRATION_EXPIRED,
    CALIBRATION_UNCALIBRATED,
    PHASE_PRE_PRODUCTION,
    SESSION_CLIENT_REVIEW,
    SESSION_IN_PROGRESS,
    SESSION_SCHEDULED,
    SHOT_BLOCKED_PREPROD,
    SHOT_IN_PRODUCTION,
    TASK_IN_PROGRESS,
    TASK_NOT_STARTED,
)
from test_helpers.test_users import (
    ARTIST_USER_ID,
    DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
)


def _pre_production_show_with_a_shot(client):
    """AD03 still in PRE_PRODUCTION, holding one blocked shot and five idle tasks."""
    production = fx.open_production(
        client,
        title="Aurora Drift III",
        production_code="AD03",
        budget_cents=100000000,
        render_allowance_cents=5000000,
        contingency_pct=0.10,
        gate_types=["SCRIPT"],
    )
    shot = fx.create_shot(
        client,
        production["id"],
        shot_code="AD03_010_0010",
        sequence_code="010",
        frame_count=120,
        budget_cents=1000000,
        planned_start_at="2026-08-01T00:00:00Z",
        planned_finish_at="2026-09-30T00:00:00Z",
    )
    layout = fx.task_for_stage(client, shot["id"], "LAYOUT")
    animation = fx.task_for_stage(client, shot["id"], "ANIMATION")
    return production, shot, layout, animation


class TestStageAssignDependsOnProductionPhase:
    def test_the_grandparent_phase_decides_whether_an_idle_task_may_be_assigned(self, client):
        """The task is a perfectly assignable NOT_STARTED row; only a gate decision two hops up
        the graph turns the identical call from a refusal into an assignment.

        PRD: "The owning production's `phase` permits the operation as described in §2.5 —
        otherwise `ERR_PRODUCTION_PHASE_INVALID` (409)."
        PRD: "Once the production is `PRODUCTION_ACTIVE`, gate work is closed and the shot floor
        opens: stage assignment, hour logging, stage submission and stage review decisions,
        render reservations, review session bookings, director notes and package issuance all
        require this phase."
        PRD: "Assignment drives the task `NOT_STARTED → IN_PROGRESS`, sets the shot's
        `current_stage` to this task's stage, and recomputes the shot `READY → IN_PRODUCTION`,
        adding 1 to the task's `version`."

        Design: Difficulty/cross_entity_state_dependency/stage_assign_blocked_while_production_in_pre_production
        """
        production, shot, layout, _ = _pre_production_show_with_a_shot(client)
        assert fx.read_production(client, production["id"])["phase"] == PHASE_PRE_PRODUCTION
        assert fx.read_shot(client, shot["id"])["status"] == SHOT_BLOCKED_PREPROD
        assert layout["status"] == TASK_NOT_STARTED

        validate_error(
            client.assign_stage_task(
                layout["id"], f.assign_payload(ARTIST_USER_ID), PRODUCTION_MANAGER_HEADERS
            ),
            ERR_PRODUCTION_PHASE_INVALID,
            409,
        )
        refused = fx.read_task(client, layout["id"])
        assert refused["status"] == TASK_NOT_STARTED
        assert refused["assigned_artist_user_id"] is None
        assert_unchanged(layout, refused, ["status", "assigned_artist_user_id", "version"])

        fx.clear_gate(client, fx.gate_for_type(client, production["id"], "SCRIPT")["id"])

        assigned = validate_success(
            client.assign_stage_task(
                layout["id"], f.assign_payload(ARTIST_USER_ID), PRODUCTION_MANAGER_HEADERS
            )
        )
        assert assigned["status"] == TASK_IN_PROGRESS
        assert assigned["assigned_artist_user_id"] == ARTIST_USER_ID

        working_shot = fx.read_shot(client, shot["id"])
        assert working_shot["status"] == SHOT_IN_PRODUCTION
        assert working_shot["current_stage"] == "LAYOUT"

    def test_the_sibling_task_is_the_second_cross_entity_gate_on_the_same_call(self, client):
        """With the show active the ANIMATION task still cannot start, because legality now
        hangs on the LAYOUT sibling one stage_order lower.

        PRD: "For a stage task whose `stage_order` is greater than 1, the sibling task of the
        same shot whose `stage_order` is one lower has status `APPROVED` — otherwise
        `ERR_PREVIOUS_STAGE_NOT_APPROVED` (409)."
        PRD: "Stages of a shot are thus worked strictly in order."

        Design: Difficulty/cross_entity_state_dependency/stage_assign_blocked_while_production_in_pre_production
        """
        production, shot, layout, animation = _pre_production_show_with_a_shot(client)
        fx.clear_gate(client, fx.gate_for_type(client, production["id"], "SCRIPT")["id"])
        fx.assign_task(client, layout["id"])

        validate_error(
            client.assign_stage_task(
                animation["id"], f.assign_payload(ARTIST_USER_ID), PRODUCTION_MANAGER_HEADERS
            ),
            ERR_PREVIOUS_STAGE_NOT_APPROVED,
            409,
        )
        blocked = fx.read_task(client, animation["id"])
        assert blocked["status"] == TASK_NOT_STARTED
        assert blocked["assigned_artist_user_id"] is None
        assert fx.read_shot(client, shot["id"])["current_stage"] == "LAYOUT"

        fx.submit_task(client, layout["id"])
        fx.approve_task(client, layout["id"])

        released = validate_success(
            client.assign_stage_task(
                animation["id"], f.assign_payload(ARTIST_USER_ID), PRODUCTION_MANAGER_HEADERS
            )
        )
        assert released["status"] == TASK_IN_PROGRESS
        assert fx.read_shot(client, shot["id"])["current_stage"] == "ANIMATION"


def _show_and_uncalibrated_client_room(client):
    """An active show that approves Rec709, plus a Rec709 room nobody has calibrated."""
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
    room = fx.create_room(
        client,
        name="CLIENT-A",
        seat_capacity=20,
        room_color_space="Rec709",
        calibration_valid_days=30,
    )
    return production, room


def _client_review_payload(production_id, room_id):
    return f.review_session_payload(
        production_id,
        room_id,
        session_type=SESSION_CLIENT_REVIEW,
        window_start="2026-08-01T10:00:00Z",
        window_end="2026-08-01T12:00:00Z",
        attendee_count=8,
    )


class TestSessionDependsOnRoomCalibration:
    def test_an_uncalibrated_room_cannot_be_booked_and_a_calibrated_one_can(self, client):
        """The room, not the session, carries the blocking state: the identical booking is
        refused while `last_calibrated_at` is null and accepted the moment it is stamped.

        PRD: "The screening room's `last_calibrated_at` is not null before a session may be
        booked in it — otherwise `ERR_ROOM_NOT_CALIBRATED` (422)."
        PRD: "Calibration is a bare action with no payload: it stamps `last_calibrated_at` with
        the logical clock now and restarts the validity window."
        PRD: "A freshly registered room has a null `last_calibrated_at` and therefore a
        `calibration_status` of `UNCALIBRATED`, and it cannot host anything until it is
        calibrated."

        Design: Difficulty/cross_entity_state_dependency/client_review_session_requires_calibrated_room
        """
        production, room = _show_and_uncalibrated_client_room(client)
        assert room["calibration_status"] == CALIBRATION_UNCALIBRATED
        assert room["last_calibrated_at"] is None

        validate_error(
            client.create_review_session(
                _client_review_payload(production["id"], room["id"]), DIRECTOR_HEADERS
            ),
            ERR_ROOM_NOT_CALIBRATED,
            422,
        )

        calibrated = validate_success(
            client.calibrate_screening_room(room["id"], {}, PRODUCTION_MANAGER_HEADERS)
        )
        assert calibrated["calibration_status"] == CALIBRATION_CALIBRATED
        assert_instant(
            calibrated["last_calibrated_at"], "2026-08-01T00:00:00Z", "last_calibrated_at"
        )

        session = validate_success(
            client.create_review_session(
                _client_review_payload(production["id"], room["id"]), DIRECTOR_HEADERS
            ),
            201,
        )
        assert session["status"] == SESSION_SCHEDULED
        assert session["note_count"] == 0
        assert session["opened_at"] is None

    def test_a_calibration_valid_at_booking_time_can_lapse_before_the_start(self, client):
        """Thirty-five days on the logical clock re-derive the room as EXPIRED with no write in
        between, so the booked session cannot open until the room is calibrated again.

        PRD: "`calibration_status` itself is never stored as an independent decision — it is
        derived on every read from three things: it is `UNCALIBRATED` when `last_calibrated_at`
        is null; it is `EXPIRED` when the age of the calibration in whole days is strictly
        greater than `calibration_valid_days`; and it is `CALIBRATED` otherwise."
        PRD: "It requires the session to be `SCHEDULED` (otherwise `ERR_SESSION_STATE_INVALID`),
        the production to be `PRODUCTION_ACTIVE` or `DELIVERY`, and — evaluated at the moment of
        the call, not at booking time — the room's `calibration_status` to be exactly
        `CALIBRATED`, otherwise `ERR_CALIBRATION_EXPIRED`."
        PRD: "A room can therefore pass the booking check in the morning and fail the opening
        check in the afternoon."

        Design: Difficulty/cross_entity_state_dependency/client_review_session_requires_calibrated_room
        """
        production, room = _show_and_uncalibrated_client_room(client)
        validate_success(
            client.calibrate_screening_room(room["id"], {}, PRODUCTION_MANAGER_HEADERS)
        )
        session = validate_success(
            client.create_review_session(
                _client_review_payload(production["id"], room["id"]), DIRECTOR_HEADERS
            ),
            201,
        )
        assert session["status"] == SESSION_SCHEDULED

        fx.move_clock(client, "2026-09-05T00:00:00Z")
        lapsed = fx.read_room(client, room["id"])
        assert lapsed["calibration_status"] == CALIBRATION_EXPIRED, (
            "35 whole days against a 30-day validity, re-derived on read"
        )
        assert_instant(
            lapsed["last_calibrated_at"], "2026-08-01T00:00:00Z", "last_calibrated_at"
        )

        validate_error(
            client.start_review_session(session["id"], {}, DIRECTOR_HEADERS),
            ERR_CALIBRATION_EXPIRED,
            422,
        )
        held = validate_success(client.get_review_session(session["id"], DIRECTOR_HEADERS))
        assert held["status"] == SESSION_SCHEDULED
        assert held["opened_at"] is None

        recalibrated = validate_success(
            client.calibrate_screening_room(room["id"], {}, PRODUCTION_MANAGER_HEADERS)
        )
        assert recalibrated["calibration_status"] == CALIBRATION_CALIBRATED
        assert_instant(
            recalibrated["last_calibrated_at"], "2026-09-05T00:00:00Z", "last_calibrated_at"
        )

        opened = validate_success(
            client.start_review_session(session["id"], {}, DIRECTOR_HEADERS)
        )
        assert opened["status"] == SESSION_IN_PROGRESS
        assert opened["opened_at"] is not None
