"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and injects
API_BASE_URL. The server lifecycle (start/stop/restart-per-test) is owned by
prd-bench-local-runner; these fixtures never touch it.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def candidate_headers():
    return TEST_USERS["candidate_headers"]


@pytest.fixture
def test_center_admin_headers():
    return TEST_USERS["test_center_admin_headers"]


@pytest.fixture
def accommodation_reviewer_headers():
    return TEST_USERS["accommodation_reviewer_headers"]


@pytest.fixture
def score_ops_headers():
    return TEST_USERS["score_ops_headers"]
