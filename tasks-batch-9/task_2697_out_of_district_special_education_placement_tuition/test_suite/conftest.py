"""
Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle is owned by the harness: the API process is restarted before
every individual test, so the client is function scoped and every test builds its
own preconditions from an empty database.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    COORDINATOR_2_HEADERS,
    COORDINATOR_HEADERS,
    FISCAL_OFFICER_2_HEADERS,
    FISCAL_OFFICER_HEADERS,
    HEARING_ADJUDICATOR_HEADERS,
    NO_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    TEAM_CHAIR_2_HEADERS,
    TEAM_CHAIR_HEADERS,
)


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test for the duration of one test."""
    return ApiClient()


@pytest.fixture
def coordinator_headers():
    return COORDINATOR_HEADERS


@pytest.fixture
def coordinator_2_headers():
    return COORDINATOR_2_HEADERS


@pytest.fixture
def team_chair_headers():
    return TEAM_CHAIR_HEADERS


@pytest.fixture
def team_chair_2_headers():
    return TEAM_CHAIR_2_HEADERS


@pytest.fixture
def fiscal_officer_headers():
    return FISCAL_OFFICER_HEADERS


@pytest.fixture
def fiscal_officer_2_headers():
    return FISCAL_OFFICER_2_HEADERS


@pytest.fixture
def hearing_adjudicator_headers():
    return HEARING_ADJUDICATOR_HEADERS


@pytest.fixture
def system_admin_headers():
    return SYSTEM_ADMIN_HEADERS


@pytest.fixture
def unauthenticated_headers():
    return NO_HEADERS
