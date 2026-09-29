"""Shared fixtures for the athletic field turf management test suite.

The harness restarts the API server before every individual test, so each test
below starts against an empty database and builds everything it needs through
the documented endpoints.
"""

import pytest

from test_helpers import ApiClient
from test_helpers.fixtures import Roster, build_full_roster, build_roster


@pytest.fixture
def client() -> ApiClient:
    """A client bound to the service mounted under `/turf`."""
    return ApiClient()


@pytest.fixture
def roster(client: ApiClient) -> Roster:
    """The bootstrap director plus one holder of each of the other four roles."""
    return build_roster(client)


@pytest.fixture
def full_roster(client: ApiClient) -> Roster:
    """A roster with a second holder of every role, for the four operations that
    compare the acting identity against the person who submitted the artefact."""
    return build_full_roster(client)
