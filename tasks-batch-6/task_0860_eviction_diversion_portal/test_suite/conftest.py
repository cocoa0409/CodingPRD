"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle (restart before every test) and PYTHONPATH.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def landlord_headers():
    return TEST_USERS["landlord_headers"]


@pytest.fixture
def tenant_headers():
    return TEST_USERS["tenant_headers"]


@pytest.fixture
def mediator_headers():
    return TEST_USERS["mediator_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def sheriff_headers():
    return TEST_USERS["sheriff_headers"]
