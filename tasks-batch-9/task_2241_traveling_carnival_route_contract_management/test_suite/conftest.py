"""Shared pytest configuration for the traveling-carnival API compliance suite.

The runner relaunches the service before every test, so each test starts against
an empty database and builds all of its own preconditions through the endpoints
the PRD declares.
"""

import sys
from pathlib import Path

import pytest

TASK_ROOT = Path(__file__).resolve().parent.parent
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))

from test_helpers import ApiClient, api_client  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """The HTTP client bound to the service under test."""
    return api_client
