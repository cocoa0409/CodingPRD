"""
Shared pytest wiring for the Neurodiagnostic EMU API suite.

Each test runs against a freshly launched server with an empty database and a
logical clock standing at its startup value, so every precondition a test needs
is built through the public endpoints inside the test itself.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the server under test."""
    return ApiClient()
