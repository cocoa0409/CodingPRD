"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def producer_headers():
    return TEST_USERS["producer_headers"]


@pytest.fixture
def client_rep_headers():
    return TEST_USERS["client_rep_headers"]


@pytest.fixture
def composer_headers():
    return TEST_USERS["composer_headers"]


@pytest.fixture
def rights_admin_headers():
    return TEST_USERS["rights_admin_headers"]


@pytest.fixture
def rights_admin_issuer_headers():
    return TEST_USERS["rights_admin_issuer_headers"]


@pytest.fixture
def afm_steward_headers():
    return TEST_USERS["afm_steward_headers"]
