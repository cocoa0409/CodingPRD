"""Shared pytest wiring for the Fit Guidance & Return Reduction Program suite.

The API server is already listening when a test runs, and the program is empty:
every test builds the state it needs through public endpoints.  Importing
`test_helpers` registers the error-to-HTTP-status table, so `validate_error`
cross-checks the status code of every refusal a test asserts.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers import fixtures as fx  # noqa: E402


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the running server, with one method per endpoint."""
    return ApiClient()


@pytest.fixture
def clock(api: ApiClient):
    """Pin the logical clock before a test builds anything, so no outcome depends
    on wall-clock time.  Returns the setter so a test can move the clock again."""
    fx.set_clock(api, fx.SCENARIO_CLOCK)

    def _set(to_iso8601: str):
        return fx.set_clock(api, to_iso8601)

    return _set
