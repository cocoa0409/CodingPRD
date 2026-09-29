"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle and database reset are owned by prd-bench-local-runner: the
server is restarted and the database emptied before every individual test, so
every fixture below builds its state from scratch through declared endpoints.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS
from test_helpers.test_users import make_royalty_owner_headers


@pytest.fixture()
def api() -> ApiClient:
    """API client bound to the server under test."""
    return ApiClient()


@pytest.fixture()
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture()
def analyst_alt_headers():
    return TEST_USERS["analyst_alt_headers"]


@pytest.fixture()
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture()
def manager_alt_headers():
    return TEST_USERS["manager_alt_headers"]


@pytest.fixture()
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture()
def admin_alt_headers():
    return TEST_USERS["admin_alt_headers"]


@pytest.fixture()
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture()
def operator_alt_headers():
    return TEST_USERS["operator_alt_headers"]


@pytest.fixture()
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture()
def owner_headers():
    """Factory for the RoyaltyOwner whose X-User-ID is its own entity id."""
    return make_royalty_owner_headers
