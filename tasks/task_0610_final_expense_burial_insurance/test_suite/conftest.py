"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; these fixtures only expose
the shared API client and pre-built role headers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def policy_admin_headers():
    return TEST_USERS["policy_admin_headers"]


@pytest.fixture
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture
def policyholder_headers():
    return TEST_USERS["policyholder_headers"]
