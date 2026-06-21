"""Conduct-report adjudication cycle, conduct-point accrual, and the suspension
threshold cascade.

Covers non_linear_state_machine (uphold/appeal cycle), transitive_cascade
(uphold -> conduct_points -> suspension), boundary_precision (exact 6 points), and the
terminal-state corner.
"""
from test_helpers import (
    validate_success, validate_error,
    make_league_admin_headers, make_conduct_officer_headers, make_team_captain_headers,
    ApiErrorId,
)
import test_helpers.fixtures as fx
import test_helpers.factories as F

ADMIN = make_league_admin_headers()
OFFICER = make_conduct_officer_headers()


def _conduct_setup(severity_first=None):
    """A scheduled game (no need to play) whose home captain is the cited player."""
    s = fx.setup_scheduled_game(with_head_referee=False)
    return s


def test_uphold_appeal_uphold_cycle_returns_to_upheld(api):
    """PRD §3.9: "After a report is upheld, the captain of a team that rosters the cited
    player — verified by an `ACTIVE` roster entry on a team that captain captains — may
    appeal it, moving it from `UPHELD` to `APPEALED`."
    PRD §3.9: "A conduct officer resolves an appeal either by denying it — `APPEALED`
    back to `UPHELD`, with the player's `conduct_points` and suspension unchanged
    because the points were already counted — or by granting it — `APPEALED` to the
    terminal `DISMISSED`, which resets the report's `points` to 0, recomputes the
    player's `conduct_points` downward, and re-evaluates suspension, which may lift it."

    Design: Difficulty/non_linear_state_machine/conduct_report_uphold_appeal_cycle
    """
    s = _conduct_setup()
    cited = s["home_player"]  # captain of home_team, on its ACTIVE roster
    report = fx.file_and_uphold_report(s["game"]["id"], cited["id"], "YELLOW")

    captain_headers = make_team_captain_headers(cited["id"])
    appealed = validate_success(
        api.transition_conduct_report(report["id"], F.transition_payload("APPEALED"), captain_headers)
    )
    assert appealed["status"] == "APPEALED"

    reupheld = validate_success(
        api.transition_conduct_report(report["id"], F.transition_payload("UPHELD"), OFFICER)
    )
    assert reupheld["status"] == "UPHELD", "denying the appeal returns the report to UPHELD"


def test_appealed_report_keeps_counting_conduct_points(api):
    """PRD §3.9: "An appealed report keeps counting: its `points` and the player's
    `conduct_points` are unchanged while appealed, so an appeal does not by itself lift
    a suspension."

    Design: Difficulty/non_linear_state_machine/conduct_report_uphold_appeal_cycle
    """
    s = _conduct_setup()
    cited = s["home_player"]
    report = fx.file_and_uphold_report(s["game"]["id"], cited["id"], "YELLOW")

    after_uphold = validate_success(api.get_player(cited["id"], ADMIN))
    assert after_uphold["conduct_points"] == 2, "YELLOW base is 2 points"

    captain_headers = make_team_captain_headers(cited["id"])
    validate_success(
        api.transition_conduct_report(report["id"], F.transition_payload("APPEALED"), captain_headers)
    )
    after_appeal = validate_success(api.get_player(cited["id"], ADMIN))
    assert after_appeal["conduct_points"] == 2, "appealed report still counts; points unchanged"


def test_uphold_recomputes_conduct_points_then_suspension(api):
    """PRD §3.9: "A player's `conduct_points` is the sum, across all reports cited
    against them whose `status` is `UPHELD` or `APPEALED`, of the base value for each
    report's severity. The base values are one point for `WARNING`, two for `YELLOW`,
    four for `RED`, and eight for `ABUSE`."
    PRD §3.9: "otherwise at 6 or more points the player is `SUSPENDED` and their
    `suspended_until_game_index` is set to the larger of its current value and the
    triggering game's `round_index` plus 2 (the two-game suspension span)".

    Design: Difficulty/transitive_cascade/uphold_recomputes_conduct_then_suspension_depth3
    """
    s = _conduct_setup()  # game round_index defaults to 1
    cited = s["home_player"]
    # First RED upheld (4 points -> WARNED).
    fx.file_and_uphold_report(s["game"]["id"], cited["id"], "RED")
    # Second YELLOW: file + review, then uphold to cross to 6.
    second = fx.file_and_review_report(s["game"]["id"], cited["id"], "YELLOW")
    validate_success(
        api.transition_conduct_report(second["id"], F.transition_payload("UPHELD"), OFFICER)
    )
    player = validate_success(api.get_player(cited["id"], ADMIN))
    assert player["conduct_points"] == 6, f"4 RED + 2 YELLOW must be 6, got {player['conduct_points']}"
    assert player["suspension_status"] == "SUSPENDED", "6 >= SUSPEND_THRESHOLD -> SUSPENDED"
    assert player["suspended_until_game_index"] == 3, (
        f"round_index 1 + 2 must be 3, got {player['suspended_until_game_index']}"
    )


def test_suspension_status_after_red_then_yellow_cascade(api):
    """PRD §3.9: "Upholding (`UNDER_REVIEW` to `UPHELD`) sets the report's `points` to
    the base value for its severity and recomputes the cited player's `conduct_points`
    and suspension."

    Design: Difficulty/transitive_cascade/uphold_recomputes_conduct_then_suspension_depth3
    """
    s = _conduct_setup()
    cited = s["home_player"]
    fx.file_and_uphold_report(s["game"]["id"], cited["id"], "RED")
    after_red = validate_success(api.get_player(cited["id"], ADMIN))
    assert after_red["suspension_status"] == "WARNED", "4 points -> WARNED (4 < 6)"
    second = fx.file_and_review_report(s["game"]["id"], cited["id"], "YELLOW")
    validate_success(
        api.transition_conduct_report(second["id"], F.transition_payload("UPHELD"), OFFICER)
    )
    after_yellow = validate_success(api.get_player(cited["id"], ADMIN))
    assert after_yellow["suspension_status"] == "SUSPENDED"


def test_warned_at_four_points_not_suspended(api):
    """PRD §3.9: "otherwise at 3 or more points the player is `WARNED` with
    `suspended_until_game_index` left unchanged; otherwise the player is `CLEAR` ..."

    Design: Difficulty/boundary_precision_check/suspension_threshold_exact_six_points
    """
    s = _conduct_setup()
    cited = s["home_player"]
    fx.file_and_uphold_report(s["game"]["id"], cited["id"], "RED")  # exactly 4
    player = validate_success(api.get_player(cited["id"], ADMIN))
    assert player["conduct_points"] == 4
    assert player["suspension_status"] == "WARNED", "4 points: WARNED (>=3, <6)"


def test_suspended_at_exactly_six_points(api):
    """PRD §3.9: "otherwise at 6 or more points the player is `SUSPENDED` and their
    `suspended_until_game_index` is set to the larger of its current value and the
    triggering game's `round_index` plus 2 (the two-game suspension span)".

    Design: Difficulty/boundary_precision_check/suspension_threshold_exact_six_points
    """
    s = _conduct_setup()
    cited = s["home_player"]
    fx.file_and_uphold_report(s["game"]["id"], cited["id"], "RED")  # 4
    second = fx.file_and_review_report(s["game"]["id"], cited["id"], "YELLOW")  # +2 = 6
    validate_success(
        api.transition_conduct_report(second["id"], F.transition_payload("UPHELD"), OFFICER)
    )
    player = validate_success(api.get_player(cited["id"], ADMIN))
    assert player["conduct_points"] == 6
    assert player["suspension_status"] == "SUSPENDED", "exactly 6 >= 6 boundary -> SUSPENDED"


def test_transition_on_dismissed_report_rejected(api):
    """PRD §3.9: "Dismissing from review (`UNDER_REVIEW` to `DISMISSED`, a terminal
    state) leaves the report's `points` at 0 and the player's `conduct_points`
    untouched."
    PRD §3.9: "A transition requested from a state that does not permit it is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/review_already_dismissed_report_returns_invalid_state
    """
    s = _conduct_setup()
    cited = s["home_player"]
    report = fx.file_and_review_report(s["game"]["id"], cited["id"], "YELLOW")
    validate_success(
        api.transition_conduct_report(report["id"], F.transition_payload("DISMISSED"), OFFICER)
    )
    resp = api.transition_conduct_report(report["id"], F.transition_payload("UPHELD"), OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
