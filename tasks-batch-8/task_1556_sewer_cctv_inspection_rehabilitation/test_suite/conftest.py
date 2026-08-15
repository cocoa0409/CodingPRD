"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; tests assume the API is
already reachable at API_BASE_URL and the database is empty per test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def csr_headers():
    return TEST_USERS["csr_headers"]


@pytest.fixture
def coder_headers():
    return TEST_USERS["coder_headers"]


@pytest.fixture
def qa_reviewer_headers():
    return TEST_USERS["qa_reviewer_headers"]


@pytest.fixture
def crew_lead_headers():
    return TEST_USERS["crew_lead_headers"]
