"""Shared fixtures for the Inpatient Psychiatric Admission API test suite.

The harness restarts the server before each test, so every test opens against an
empty database with the logical clock reading its startup instant. Fixtures here
are therefore deliberately thin: a client, and the recurring roster and ward that
almost every scenario builds on top of.
"""

import pytest

from test_helpers import ApiClient, build_roster, build_ward, pin_clock


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client for the API under test."""
    return ApiClient()


@pytest.fixture
def clock(api) -> str:
    """Pin the logical clock to a weekday inside the court and business windows."""
    return pin_clock(api)


@pytest.fixture
def roster(api):
    """The recurring cast of five clinicians, one per roster credential."""
    return build_roster(api)


@pytest.fixture
def ward(api):
    """A three-standard-bed unit under the SEPARATE_BY_ROOM mixing policy."""
    return build_ward(api)
