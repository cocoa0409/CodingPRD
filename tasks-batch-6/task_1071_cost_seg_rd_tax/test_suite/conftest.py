"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def study_manager_headers():
    return TEST_USERS["study_manager_headers"]


@pytest.fixture
def cpa_headers():
    return TEST_USERS["cpa_headers"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]
