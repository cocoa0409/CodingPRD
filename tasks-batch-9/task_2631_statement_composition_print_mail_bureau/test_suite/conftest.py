"""Shared pytest fixtures for the statement composition and print-mail bureau suite.

The harness restarts the API server before every individual test, so each test
sees an empty database and must build its own preconditions. The fixtures here
therefore only supply the client object and the logical-clock reset the contract
guarantees; anything with domain state is built inside the test from the helpers
in ``test_helpers.fixtures``.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.constants import DEFAULT_CLOCK_UTC  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """An HTTP client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def clock(api: ApiClient) -> str:
    """The logical clock pinned to its documented initial instant.

    Before the clock endpoint is ever called the logical clock reads exactly
    2026-08-01T00:00:00Z; pinning it explicitly keeps a test that relies on that
    instant independent of call ordering.
    """
    fx.set_clock(api, DEFAULT_CLOCK_UTC)
    return DEFAULT_CLOCK_UTC
