"""
Shared fixtures for the Bridge Inspection & Load Rating Program test suite.

Every test in this suite runs against a freshly restarted server with an empty
database, so nothing may be assumed to pre-exist. Each fixture below therefore
builds its preconditions from scratch through the public API.

The logical clock is the one piece of global state a test almost always has to
pin first: PRD §2.4 says "Before any client sets it, the logical clock reads
exactly `2026-08-01T00:00:00Z`", and a scenario that depends on a due date, an
expiry comparison or a notification deadline needs a deliberate instant instead.
"""

import os
import sys

import pytest

# The helper package sits beside this directory, one level up from `test_suite/`.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers import BridgeProgramClient  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402


@pytest.fixture
def client() -> BridgeProgramClient:
    """A client for the API under test."""
    return BridgeProgramClient()


@pytest.fixture
def roster(client: BridgeProgramClient) -> fx.Roster:
    """
    The four entity-backed identities of PRD §2.1 — an inspector, a QA reviewer,
    a rating engineer and a district engineer — each registered on the
    `Personnel` roster with a refresher expiry far enough out that
    `qualification_status` reads `CURRENT` at every clock these tests pin.

    The clock is pinned before the roster is written because PRD §2.10 compares
    `nbis_refresher_expiry_date` against "the logical clock's current date".
    """
    fx.pin_base_clock(client)
    return fx.Roster(fx.create_roster(client))


@pytest.fixture
def bridge(client: BridgeProgramClient, roster: fx.Roster) -> dict:
    """
    The Cedar Creek Bridge of the PRD's worked examples: a girder structure of
    1000 m² built in 1972 carrying 12,000 vehicles a day with an 8.5 km detour,
    spanning water and seeded with the default component ratings of 7.
    """
    return fx.create_cedar_creek(client)


@pytest.fixture
def accepted(client: BridgeProgramClient, roster: fx.Roster, bridge: dict) -> dict:
    """
    An `ACCEPTED` routine report on Cedar Creek carrying the baseline element set
    of the PRD's worked example, together with its element rows and the structure
    as it reads after the acceptance cascade has run.
    """
    return fx.accepted_report(client, bridge["id"], roster)
