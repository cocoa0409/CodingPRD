"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def cae_headers():
    return TEST_USERS["cae_headers"]


@pytest.fixture
def cae2_headers():
    return TEST_USERS["cae2_headers"]


@pytest.fixture
def committee_headers():
    return TEST_USERS["committee_headers"]


@pytest.fixture
def committee2_headers():
    return TEST_USERS["committee2_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]
