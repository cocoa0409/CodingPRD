"""Shared pytest wiring for the upfitting compliance suite.

The harness restarts the API server before every test, so each test observes a
completely empty store and builds the state it needs through the public API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers the §5 status map)
from test_helpers.api_client import UpfitApiClient  # noqa: E402
from test_helpers.constants import CLOCK_ORIGIN  # noqa: E402
from test_helpers.fixtures import pin_clock  # noqa: E402


@pytest.fixture()
def api() -> UpfitApiClient:
    """A client pointed at the API under test."""
    return UpfitApiClient()


@pytest.fixture()
def clocked_api(api: UpfitApiClient) -> UpfitApiClient:
    """A client whose logical clock has been pinned to the PRD origin instant."""
    pin_clock(api, CLOCK_ORIGIN)
    return api
