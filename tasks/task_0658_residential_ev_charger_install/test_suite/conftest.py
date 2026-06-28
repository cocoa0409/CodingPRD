"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (test_helpers importable), server lifecycle, and
API_BASE_URL injection. These fixtures just wire test_helpers into pytest.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def utility_reviewer_headers():
    return TEST_USERS["utility_reviewer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def homeowner_headers():
    return TEST_USERS["homeowner_headers"]


@pytest.fixture
def electrician_headers():
    return TEST_USERS["electrician_headers"]
