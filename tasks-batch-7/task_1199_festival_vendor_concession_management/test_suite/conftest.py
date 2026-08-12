"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def director2_headers():
    return TEST_USERS["director2_headers"]


@pytest.fixture
def vendor_manager_headers():
    return TEST_USERS["vendor_manager_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def health_inspector_headers():
    return TEST_USERS["health_inspector_headers"]


@pytest.fixture
def sustainability_headers():
    return TEST_USERS["sustainability_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def finance2_headers():
    return TEST_USERS["finance2_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]
