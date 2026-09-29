"""Pytest configuration for the Player Transactions & Roster Compliance suite.

The harness relaunches the API server before every individual test, so each test
starts against an empty database and builds all the state it needs through the
public API. Nothing is shared between tests.
"""

import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from test_helpers.fixtures import (  # noqa: E402,F401
    active_ir_designation,
    api,
    club,
    club_and_free_agent,
    club_at_active_roster_limit,
    club_over_active_roster_limit,
    draft_signing,
    filed_signing,
    free_agent,
    frozen_club,
    league,
    officer,
    pending_wire,
    proposed_trade,
    rejected_signing,
    rostered_player,
    second_club,
    voided_at_revision_limit,
)
