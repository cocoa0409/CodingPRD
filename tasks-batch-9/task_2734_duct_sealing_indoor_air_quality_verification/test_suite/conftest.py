"""Shared pytest fixtures for the Duct Sealing IAQ compliance suite.

The service under test is already running and its database is empty at the start
of every test, so each test builds the state it needs from scratch through the
endpoints of PRD section 4.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import DuctSealingApiClient  # noqa: E402


@pytest.fixture()
def api() -> DuctSealingApiClient:
    """A client aimed at the running service."""
    return DuctSealingApiClient()
