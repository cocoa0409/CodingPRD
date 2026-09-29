"""
Shared pytest fixtures.

The server is restarted and its database emptied before every individual test,
so every fixture here is function-scoped and builds its state from scratch
through the public endpoints. Nothing is cached across tests and no fixture
assumes a row it did not create.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.constants import CLOCK_INITIAL, CLOCK_SETUP_DAY_START
from test_helpers.fixtures import pin_clock


@pytest.fixture()
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


@pytest.fixture()
def clock(api: ApiClient) -> str:
    """The instant the logical clock reads before any test moves it.

    No call is needed to reach it — the clock reads exactly this value on a
    fresh server — so the fixture only names the instant for the tests that
    assert against it.
    """
    return CLOCK_INITIAL


@pytest.fixture()
def setup_day(api: ApiClient) -> str:
    """Move the logical clock to the start of the canonical setup window."""
    pin_clock(api, CLOCK_SETUP_DAY_START)
    return CLOCK_SETUP_DAY_START
