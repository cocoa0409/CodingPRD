"""Field reset dependency for take-field and the 300-second field-interval
boundary on match creation (PRD §3.5)."""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_queue_slots,
    complete_open_reset_log,
    create_manual_match,
    create_match_payload,
    drive_match_to_scored,
    make_scorekeeper_headers,
    next_safe_match_time,
    queue_and_take_field,
    setup_matches_running,
    validate_error,
    validate_success,
    api_client,
)

QM = TEST_USERS["queue_manager_headers"]


def _six(ctx):
    return [entry["team"]["id"] for entry in ctx["teams"][:6]]


class TestTakeFieldResetDependency:
    def test_take_field_blocked_while_prior_reset_in_progress(self):
        """PRD §3.5: "the prior `FieldResetLog` for the same `field_index`
        must be `COMPLETE` (or nonexistent — the first match of the day has no
        prior reset), else `ERR_FIELD_NOT_RESET`."

        Design: Difficulty/cross_entity_state_dependency/match_take_field_depends_on_field_reset_complete
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        red_bd = {"auto_points": 10, "teleop_points": 40, "endgame_points": 10,
                  "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"}
        blue_bd = {"auto_points": 5, "teleop_points": 20, "endgame_points": 5,
                   "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"}
        m1 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9301, field_index=1,
        )
        # Scoring M1 creates its FieldResetLog in IN_PROGRESS (PRD §3.5).
        drive_match_to_scored(ctx, m1["id"], _six(ctx), red_bd, blue_bd)
        m2 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9302, field_index=1,
        )
        slots = add_queue_slots(ctx, m2["id"], _six(ctx))
        validate_success(api_client.queue_match(ctx["event"]["id"], m2["id"], QM))
        for slot in slots:
            validate_success(
                api_client.mark_slot_at_field(ctx["event"]["id"], m2["id"], slot["id"], QM)
            )
        resp = api_client.take_field(ctx["event"]["id"], m2["id"], QM)
        validate_error(resp, ApiErrorId.ERR_FIELD_NOT_RESET)

    def test_take_field_succeeds_after_reset_complete(self):
        """PRD §3.5: take-field requires "the prior `FieldResetLog` for the
        same `field_index` must be `COMPLETE`" — once the crew completes it,
        the next match takes the field.

        Design: Difficulty/cross_entity_state_dependency/match_take_field_depends_on_field_reset_complete
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        red_bd = {"auto_points": 10, "teleop_points": 40, "endgame_points": 10,
                  "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"}
        blue_bd = {"auto_points": 5, "teleop_points": 20, "endgame_points": 5,
                   "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"}
        m1 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9303, field_index=1,
        )
        drive_match_to_scored(ctx, m1["id"], _six(ctx), red_bd, blue_bd)
        complete_open_reset_log(ctx, m1["id"])
        m2 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9304, field_index=1,
        )
        slots = add_queue_slots(ctx, m2["id"], _six(ctx))
        on_field = queue_and_take_field(ctx, m2["id"], slots)
        assert on_field["status"] == "ON_FIELD"


class TestFieldIntervalBoundary:
    def _base(self):
        ctx = setup_matches_running(num_teams=6, field_count=2)
        # Anchor manual matches well clear of the generated slate on field 1.
        anchor = next_safe_match_time(ctx["event"]["id"], 1)
        m1 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9401, field_index=1, scheduled_at=anchor,
        )
        return ctx, m1, datetime.fromisoformat(anchor.replace("Z", "+00:00"))

    def test_299_seconds_apart_rejected(self):
        """PRD §3.5: "any two consecutive matches on the same field must be
        separated by at least `FIELD_RESET_MIN_SECONDS` = 300 seconds of
        `scheduled_at` time — a violation of this interval is rejected with
        `ERR_FIELD_INTERVAL_VIOLATION` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/field_reset_interval_boundary
        """
        ctx, m1, anchor = self._base()
        too_close = (anchor + timedelta(seconds=299)).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = api_client.create_match(
            ctx["event"]["id"],
            create_match_payload(
                match_number=9402, scheduled_at=too_close, field_index=1,
                red_alliance_id=m1["red_alliance_id"],
                blue_alliance_id=m1["blue_alliance_id"],
            ),
            make_scorekeeper_headers(ctx["scorekeeper"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FIELD_INTERVAL_VIOLATION)

    def test_300_seconds_apart_accepted(self):
        """PRD §3.5: the separation must be "at least
        `FIELD_RESET_MIN_SECONDS` = 300 seconds" — exactly 300 seconds
        satisfies the rule (boundary is inclusive).

        Design: Difficulty/boundary_precision_check/field_reset_interval_boundary
        """
        ctx, m1, anchor = self._base()
        exactly = (anchor + timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ")
        created = validate_success(
            api_client.create_match(
                ctx["event"]["id"],
                create_match_payload(
                    match_number=9403, scheduled_at=exactly, field_index=1,
                    red_alliance_id=m1["red_alliance_id"],
                    blue_alliance_id=m1["blue_alliance_id"],
                ),
                make_scorekeeper_headers(ctx["scorekeeper"]["id"]),
            ),
            expected_status=201,
        )
        assert created["status"] == "SCHEDULED"
