"""Shared pytest configuration for the program API compliance suite.

The runner relaunches the server before every individual test, so each test
begins against an empty database and must build all of its own preconditions
through the API.
"""

import os
import sys

import pytest

# The task root holds the ``test_helpers`` package alongside this suite.
TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.api_errors import register_error_status_map  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def error_status_map():
    """Teach the framework validators the PRD 5 error -> HTTP status mapping."""
    register_error_status_map()


@pytest.fixture
def client():
    """An API client pointed at the server under test."""
    return ApiClient(os.environ.get("API_BASE_URL"))
