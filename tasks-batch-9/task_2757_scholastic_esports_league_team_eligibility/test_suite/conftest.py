"""Shared pytest fixtures for the Scholastic Esports League compliance suite.

The harness restarts the API with an empty store before every individual test,
so each test builds all of the state it needs through the PRD's own endpoints.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import EsportsLeagueApiClient  # noqa: E402
from test_helpers import api_errors  # noqa: E402,F401  (registers §5 status map)


@pytest.fixture()
def api() -> EsportsLeagueApiClient:
    """A client pointed at the API under test."""
    return EsportsLeagueApiClient()
