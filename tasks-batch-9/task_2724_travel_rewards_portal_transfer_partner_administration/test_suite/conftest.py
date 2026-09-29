"""
Shared pytest fixtures for the Travel Rewards Portal & Transfer Partner suite.

The harness relaunches the server before every test, so each test starts from an
empty database with the logical clock at its start-up instant: "Before any client
sets it, the clock reads `2026-08-01T00:00:00.000Z`."
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing.validators import (  # noqa: E402
    set_error_http_status_map,
)

from test_helpers.api_client import RewardsApiClient  # noqa: E402
from test_helpers.api_errors import ERROR_HTTP_STATUS  # noqa: E402

#: "§5 lists the error identifiers with their HTTP status codes and nothing else."
set_error_http_status_map(ERROR_HTTP_STATUS)


@pytest.fixture(scope="session")
def api():
    """One HTTP client for the whole session; it holds no state of its own."""
    return RewardsApiClient()
