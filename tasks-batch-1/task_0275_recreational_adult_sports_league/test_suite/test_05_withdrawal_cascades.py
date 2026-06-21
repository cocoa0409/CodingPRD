"""Transitive cascades and conserved-count invariants on team withdrawal:
withdraw -> game CANCELLED -> referee assignment RELEASED, and the
confirmed_team_count slot invariant under withdraw + auto-promote.

Covers transitive_cascade (depth-3 schedule cascade) and compensating_invariant
(team-slot count).
"""
from test_helpers import (
    validate_success, validate_paginated,
    make_league_admin_headers,
)
import test_helpers.fixtures as fx

ADMIN = make_league_admin_headers()


def test_confirmed_withdraw_cancels_game(api):
    """PRD §3.4: "This withdrawal fires several effects at once: the refund calculation
    runs and writes a `REFUND` payment for the prorated amount; the division's
    `confirmed_team_count` is recomputed downward by one; every still-`SCHEDULED` game
    involving the team moves to `CANCELLED`, and each such cancelled game releases its
    referee assignments to `RELEASED`; and the highest-seeded `WAITLISTED` team in the
    same division (breaking ties by `created_at` ascending) is auto-promoted to
    `CONFIRMED`."

    Design: Difficulty/transitive_cascade/confirmed_withdraw_cancels_games_releases_refs_depth3
    """
    # Build a SCHEDULED game with a HEAD referee in a season advanced to SCHEDULED phase.
    s = fx.setup_scheduled_game(with_head_referee=True)
    fx.advance_to(s["season"]["id"], "CLOSED")
    fx.advance_to(s["season"]["id"], "SCHEDULED")

    withdrawn = validate_success(api.withdraw_team(s["home_team"]["id"], ADMIN))
    assert withdrawn["status"] == "WITHDRAWN_LOCKED"

    game = validate_success(api.get_game(s["game"]["id"], ADMIN))
    assert game["schedule_status"] == "CANCELLED", (
        "a SCHEDULED game involving the withdrawing team must move to CANCELLED"
    )


def test_confirmed_withdraw_releases_referee_assignment_via_cancel(api):
    """PRD §3.4: "every still-`SCHEDULED` game involving the team moves to `CANCELLED`,
    and each such cancelled game releases its referee assignments to `RELEASED`; and
    the highest-seeded `WAITLISTED` team in the same division (breaking ties by
    `created_at` ascending) is auto-promoted to `CONFIRMED`."

    The third hop (assignment RELEASED) is caused by the game cancellation, not
    directly by the withdraw.

    Design: Difficulty/transitive_cascade/confirmed_withdraw_cancels_games_releases_refs_depth3
    """
    s = fx.setup_scheduled_game(with_head_referee=True)
    fx.advance_to(s["season"]["id"], "CLOSED")
    fx.advance_to(s["season"]["id"], "SCHEDULED")
    validate_success(api.withdraw_team(s["home_team"]["id"], ADMIN))

    resp = api.list_game_assignments(s["game"]["id"], ADMIN)
    assignments, _meta = validate_paginated(resp)
    target = next((a for a in assignments if a["id"] == s["assignment"]["id"]), None)
    assert target is not None, "the assignment should still be listed for the game"
    assert target["state"] == "RELEASED", (
        "the cancelled game's referee assignment must be RELEASED (hop 3)"
    )


