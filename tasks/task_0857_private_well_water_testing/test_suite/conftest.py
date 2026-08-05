"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/health) is owned by prd-bench-local-runner; the
runner also sets PYTHONPATH so `test_helpers` imports cleanly.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is restarted before every test."""
    return api_client


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def driller_headers():
    return TEST_USERS["driller_headers"]


@pytest.fixture
def lab_analyst_headers():
    return TEST_USERS["lab_analyst_headers"]


@pytest.fixture
def health_officer_headers():
    return TEST_USERS["health_officer_headers"]
