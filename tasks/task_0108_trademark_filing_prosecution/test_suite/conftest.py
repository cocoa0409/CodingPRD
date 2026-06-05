"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, injects API_BASE_URL,
and restarts the server (empty DB) before every test.
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    examiner_headers as _examiner_headers,
    ttab_clerk_headers as _ttab_clerk_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def examiner_headers():
    return TEST_USERS["examiner_headers"]


@pytest.fixture
def ttab_clerk_headers():
    return TEST_USERS["ttab_clerk_headers"]


@pytest.fixture
def applicant_headers():
    """Fallback Applicant header (non-ownership tests only)."""
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def attorney_headers():
    """Fallback Attorney header (non-ownership tests only)."""
    return TEST_USERS["attorney_headers"]
