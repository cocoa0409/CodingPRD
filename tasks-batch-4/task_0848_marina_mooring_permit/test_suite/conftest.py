"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def harbor_headers():
    return TEST_USERS["harbormaster_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_clerk_headers"]


@pytest.fixture
def boater_headers():
    return TEST_USERS["boater_headers"]
