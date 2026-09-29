"""Shared fixtures for the Ticket Access Control suite.

The harness restarts the server and empties the database before every single
test, so every test builds the state it needs from scratch through the declared
endpoints. The only shared fixture is the client itself, pinned to the logical
clock's declared starting instant.
"""

import pytest

from test_helpers import ApiClient, fixtures as fx
from test_helpers.constants import CLOCK_EPOCH_START


@pytest.fixture
def api() -> ApiClient:
    """A client whose logical clock sits at the instant it reads before any move."""
    client = ApiClient()
    fx.set_clock(client, CLOCK_EPOCH_START)
    return client
