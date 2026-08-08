"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def grounds_foreman_headers():
    return TEST_USERS["grounds_foreman_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def health_officer_headers():
    return TEST_USERS["health_officer_headers"]


@pytest.fixture
def cemetery_director_headers():
    return TEST_USERS["cemetery_director_headers"]


@pytest.fixture
def right_holder_headers():
    return TEST_USERS["right_holder_headers"]
