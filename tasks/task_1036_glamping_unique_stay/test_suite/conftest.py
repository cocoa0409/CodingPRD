"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def permit_reviewer_headers():
    return TEST_USERS["permit_reviewer_headers"]


@pytest.fixture
def host_headers():
    """Fallback Host headers — only for tests that do NOT exercise ownership."""
    return TEST_USERS["host_headers"]


@pytest.fixture
def guest_headers():
    """Fallback Guest headers — only for tests that do NOT exercise ownership."""
    return TEST_USERS["guest_headers"]
