"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client, make_account_holder_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def ops_admin_2_headers():
    return TEST_USERS["ops_admin_2_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst_2_headers():
    return TEST_USERS["analyst_2_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor_2_headers():
    return TEST_USERS["supervisor_2_headers"]


@pytest.fixture
def bsa_officer_headers():
    return TEST_USERS["bsa_officer_headers"]


@pytest.fixture
def counsel_headers():
    return TEST_USERS["counsel_headers"]


@pytest.fixture
def counsel_2_headers():
    return TEST_USERS["counsel_2_headers"]


@pytest.fixture
def account_holder_headers_for():
    """Builder for AccountHolder headers bound to a real Customer id."""
    return make_account_holder_headers
