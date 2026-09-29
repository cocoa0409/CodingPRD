"""
Shared pytest fixtures for the Open Data Portal API compliance suite.

The API server is restarted before every individual test, so each test starts
against an empty database and builds every precondition it needs through the
public API. These fixtures only supply the endpoint client and the caller
identities; all state comes from the ladders in `test_helpers.fixtures`.
"""

import sys
from pathlib import Path

import pytest

_TASK_ROOT = Path(__file__).resolve().parent.parent
if str(_TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(_TASK_ROOT))

from test_helpers import TEST_USERS, ApiClient, api_client  # noqa: E402
from test_helpers import (  # noqa: E402
    make_community_member_headers,
    make_data_coordinator_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The endpoint client every test drives the API through."""
    return api_client


@pytest.fixture
def portal_admin_headers():
    """Programme-office caller: shared registries, moderation, sweep and clock."""
    return TEST_USERS["portal_admin_headers"]


@pytest.fixture
def privacy_assessor_headers():
    """The reviewer who authors an assessment and is recorded as its assessor."""
    return TEST_USERS["privacy_assessor_headers"]


@pytest.fixture
def privacy_decider_headers():
    """A second reviewer, distinct from the assessor, who may decide it."""
    return TEST_USERS["privacy_decider_headers"]


@pytest.fixture
def anonymous_headers():
    """The public catalogue browser, which carries no `X-User-ID`."""
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def coordinator_headers_for():
    """Build coordinator headers for a department created inside the test.

    A coordinator's `X-User-ID` is the id of the acting department, so the
    identity can only be built once that department exists.
    """
    return make_data_coordinator_headers


@pytest.fixture
def member_headers_for():
    """Build community-member headers for a member registered inside the test."""
    return make_community_member_headers
