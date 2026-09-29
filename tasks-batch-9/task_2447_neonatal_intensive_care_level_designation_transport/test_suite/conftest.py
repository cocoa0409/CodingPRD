"""Shared pytest fixtures for the Neonatal Network API suite.

The API server is restarted before every individual test, so every test starts
against an empty database and builds its own preconditions through the documented
endpoints.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_helpers import api_client  # noqa: E402
from test_helpers import fixtures  # noqa: E402


@pytest.fixture
def api():
    """The typed API client — one method per documented endpoint."""
    return api_client


@pytest.fixture
def network():
    """A pinned clock, the LEVEL_I/II/III standards, a staffed and equipped
    LEVEL_III regional unit, and a LEVEL_I community unit that refers into it."""
    return fixtures.setup_network()
