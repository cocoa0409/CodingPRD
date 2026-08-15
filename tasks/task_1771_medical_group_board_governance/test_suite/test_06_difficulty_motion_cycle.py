"""Difficulty queue: cyclic Motion machine — OPEN <-> TABLED negotiation loop."""
from test_helpers import (
    ApiErrorId,
    api_client,
    capital_call_for_motion,
    cast_vote,
    close_motion,
    create_and_open_motion,
    create_policy,
    create_shareholder,
    get_motion,
    make_physician_headers,
    resume_motion,
    table_motion,
    validate_error,
    capital_call_payload,
)


class TestMotionOpenTabledOpenCycle:
    def test_table_freezes_voting_and_resume_reopens_fresh_window(self, api):
        """PRD §3.4: "A ballot is accepted only while the motion is `OPEN`
        (`ERR_MOTION_NOT_OPEN`)"
        PRD §3.4: "An `OPEN` motion may be tabled — voting pauses, cast votes are
        retained — and a `TABLED` motion may be resumed, which restarts the window
        fresh: `opened_at` resets to the clock and `closes_at` to the clock plus
        `voting_window_days` again."

        Design: Difficulty/non_linear_state_machine/motion_open_tabled_open_cycle
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL",
            a,
            capital_call_payload(1000000, purpose="Roof repair"),
        )
        tabled = table_motion(motion["id"], a)
        assert tabled["status"] == "TABLED"

        resp = api_client.cast_vote(
            motion["id"], {"vote_choice": "FOR"}, make_physician_headers(a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_MOTION_NOT_OPEN)

        resumed = resume_motion(motion["id"], a)
        assert resumed["status"] == "OPEN"
        assert resumed["opened_at"].startswith("2026-08-01T00:00:00"), (
            f"resume resets opened_at to the clock, got {resumed['opened_at']}"
        )
        assert resumed["closes_at"].startswith("2026-08-15T00:00:00"), (
            f"resume grants a fresh 14-day window, got {resumed['closes_at']}"
        )

    def test_adoption_effects_still_fire_after_the_loop(self, api):
        """PRD §3.4: "Adoption has type-specific effects. An adopted `CAPITAL_CALL`
        creates a `CapitalCall` in `APPROVED` status with `total_amount_cents`,
        `purpose`, and `due_date` from the payload."
        The OPEN -> TABLED -> OPEN cycle must not consume the adoption effect.

        Design: Difficulty/non_linear_state_machine/motion_open_tabled_open_cycle
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL",
            a,
            capital_call_payload(1000000, purpose="Roof repair"),
        )
        table_motion(motion["id"], a)
        resume_motion(motion["id"], a)
        cast_vote(motion["id"], a, "FOR")
        closed = close_motion(motion["id"])
        assert closed["status"] == "ADOPTED"
        call = capital_call_for_motion(motion["id"])
        assert call["status"] == "APPROVED"
        assert call["total_amount_cents"] == 1000000
        assert call["purpose"] == "Roof repair"
        assert get_motion(motion["id"])["status"] == "ADOPTED"
