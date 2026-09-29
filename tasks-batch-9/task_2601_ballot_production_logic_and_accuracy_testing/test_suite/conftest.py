"""Shared pytest fixtures.

The service is restarted with an empty store before each test, so every fixture
here is cheap and stateless: it hands the test a client and lets the test build
exactly the world its rule needs.
"""

import pytest

from test_helpers import api_errors  # noqa: F401  (registers the error status map)
from test_helpers.api_client import BallotProductionApiClient
from test_helpers.constants import CLOCK_START
from test_helpers.fixtures import set_clock


@pytest.fixture
def client() -> BallotProductionApiClient:
    """A client pointed at the service under test."""
    return BallotProductionApiClient()


@pytest.fixture
def clock_at_start(client: BallotProductionApiClient) -> str:
    """Place the server logical clock at the campaign-start instant."""
    set_clock(client, CLOCK_START)
    return CLOCK_START
