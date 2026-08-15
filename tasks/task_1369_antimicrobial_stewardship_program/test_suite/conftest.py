"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def pharmacist_headers():
    return TEST_USERS["pharmacist_headers"]


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]


@pytest.fixture
def microbiologist_headers():
    return TEST_USERS["microbiologist_headers"]


@pytest.fixture
def preventionist_headers():
    return TEST_USERS["preventionist_headers"]
