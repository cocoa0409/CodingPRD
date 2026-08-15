"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop, API_BASE_URL, PYTHONPATH) is managed by
prd-bench-local-runner; this file only bridges test_helpers into fixtures.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner guarantees the server is up."""
    return api_client


@pytest.fixture
def contractor_pm_headers():
    return TEST_USERS["contractor_pm_headers"]


@pytest.fixture
def foreman_headers():
    return TEST_USERS["foreman_headers"]


@pytest.fixture
def utility_inspector_headers():
    return TEST_USERS["utility_inspector_headers"]


@pytest.fixture
def utility_dispatcher_headers():
    return TEST_USERS["utility_dispatcher_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]
