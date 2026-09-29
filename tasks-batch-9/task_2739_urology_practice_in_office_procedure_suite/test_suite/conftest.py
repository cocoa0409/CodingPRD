"""
Shared pytest fixtures for the Urology Practice & In-Office Procedure Suite
test suite.

The service under test is restarted with an empty database before every
individual test, so nothing may be shared across tests except the HTTP client
itself and the practice administrator's opaque identifier — the one identity in
this contract that is never resolved to a persisted row.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.fixtures import build_roster  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    PRACTICE_ADMIN_USER_ID,
    make_practice_admin_headers,
)

_api_client = ApiClient()


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client for the API under test."""
    return _api_client


@pytest.fixture(scope="session")
def admin_headers():
    """
    Headers for a practice administrator. The administrator's identifier is
    opaque, so it needs no roster row and can be reused for the whole session.
    """
    return make_practice_admin_headers()


@pytest.fixture(scope="session")
def admin_user_id() -> str:
    return PRACTICE_ADMIN_USER_ID


@pytest.fixture
def roster(api):
    """
    A freshly registered practice roster: one Provider per entity-backed role
    plus a spare where two distinct actors are needed, together with the
    request headers each of them authenticates with.
    """
    return build_roster(api)
