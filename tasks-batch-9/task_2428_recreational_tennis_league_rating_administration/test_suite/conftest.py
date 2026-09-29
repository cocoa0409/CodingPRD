"""pytest configuration for the PRD-compliance suite.

The harness restarts the API server before every test, so each test observes an
empty database and builds all of its own preconditions.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)
from test_helpers.api_client import TennisApiClient  # noqa: E402
from test_helpers.fixtures import Scenario  # noqa: E402


@pytest.fixture
def api() -> TennisApiClient:
    """HTTP client bound to API_BASE_URL."""
    return TennisApiClient()


@pytest.fixture
def scenario(api: TennisApiClient) -> Scenario:
    """Empty scenario holder with the logical clock left at its default."""
    return Scenario(api)
