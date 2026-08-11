"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def desk_admin_headers():
    return TEST_USERS["desk_admin_headers"]


@pytest.fixture
def vendor_feed_headers():
    return TEST_USERS["vendor_feed_headers"]


@pytest.fixture
def analyst_1_headers():
    return TEST_USERS["analyst_1_headers"]


@pytest.fixture
def analyst_2_headers():
    return TEST_USERS["analyst_2_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def examiner_1_headers():
    return TEST_USERS["examiner_1_headers"]


@pytest.fixture
def custodian_feed_headers():
    return TEST_USERS["custodian_feed_headers"]


@pytest.fixture
def account_holder_headers():
    return TEST_USERS["account_holder_headers"]
