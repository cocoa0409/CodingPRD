"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def adviser_headers():
    return TEST_USERS["adviser_headers"]


@pytest.fixture
def staff_headers():
    return TEST_USERS["staff_headers"]


@pytest.fixture
def contributor_headers():
    return TEST_USERS["contributor_headers"]


@pytest.fixture
def salesrep_headers():
    return TEST_USERS["salesrep_headers"]
