"""Shared pytest fixtures for the Drive-Thru Speed-Of-Service suite.

Every test runs against a freshly started server with an empty store of record,
so each test builds all of its own preconditions through the declared endpoints.
"""

import sys
from pathlib import Path

import pytest

# The helper package lives next to this suite, one directory up.
TASK_ROOT = Path(__file__).resolve().parent.parent
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))

from test_helpers.api_client import DriveThruApiClient  # noqa: E402


@pytest.fixture
def api() -> DriveThruApiClient:
    """A client bound to the API base URL supplied by the environment."""
    return DriveThruApiClient()
