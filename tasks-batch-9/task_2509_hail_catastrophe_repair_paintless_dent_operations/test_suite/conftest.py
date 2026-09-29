"""Shared pytest wiring for the Hail Catastrophe PDR Operations suite.

The harness restarts the service before every individual test, so each test
starts from an empty database and a logical clock at its startup value.  Every
scenario below is therefore built from scratch through the documented
endpoints.
"""

import pytest

from test_helpers import ApiClient


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the service under test."""
    return ApiClient()
