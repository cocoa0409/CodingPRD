"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable and injects
API_BASE_URL; the server lifecycle (restart-before-each-test) is the runner's job.
"""
import pytest

from test_helpers import ANONYMOUS_HEADERS, ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def distributor_headers():
    return TEST_USERS["distributor_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
