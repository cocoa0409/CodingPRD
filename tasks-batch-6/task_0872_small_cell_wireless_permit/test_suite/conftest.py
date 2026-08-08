"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so ``test_helpers`` is importable, injects
API_BASE_URL, and restarts the server before every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def row_reviewer_headers():
    return TEST_USERS["row_reviewer_headers"]


@pytest.fixture
def aesthetic_reviewer_headers():
    return TEST_USERS["aesthetic_reviewer_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
