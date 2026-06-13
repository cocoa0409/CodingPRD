"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle, PYTHONPATH, and API_BASE_URL are managed by
prd-bench-local-runner; these fixtures only surface the shared API client and
role headers.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is restarted before every test."""
    return api_client


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def underwriter_headers_2():
    return TEST_USERS["underwriter_headers_2"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]


@pytest.fixture
def adjuster_headers_2():
    return TEST_USERS["adjuster_headers_2"]


@pytest.fixture
def policyholder_headers():
    return TEST_USERS["policyholder_headers"]
