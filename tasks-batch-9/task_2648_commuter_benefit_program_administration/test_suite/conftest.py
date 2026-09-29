"""Pytest wiring shared by every test module in this suite.

The harness restarts the service before each individual test, so every test
starts against an empty database and a logical clock that has been reset to its
documented default instant.  Nothing here creates domain state; each test builds
exactly the preconditions it needs through the documented endpoints.
"""

import pytest

from test_helpers.api_client import CommuterBenefitApiClient


@pytest.fixture
def api() -> CommuterBenefitApiClient:
    """A client bound to the service under test."""
    return CommuterBenefitApiClient()
