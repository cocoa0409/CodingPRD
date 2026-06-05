"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def commissioner_headers():
    return TEST_USERS["commissioner_headers"]


@pytest.fixture
def team_gm_headers():
    return TEST_USERS["team_gm_headers"]
