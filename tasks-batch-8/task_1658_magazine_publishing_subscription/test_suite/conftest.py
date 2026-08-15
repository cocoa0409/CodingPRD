"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the server is
already reachable at API_BASE_URL.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def publishing_director_headers():
    return TEST_USERS["publishing_director_headers"]


@pytest.fixture
def production_manager_headers():
    return TEST_USERS["production_manager_headers"]


@pytest.fixture
def circulation_manager_headers():
    return TEST_USERS["circulation_manager_headers"]


@pytest.fixture
def fulfillment_manager_headers():
    return TEST_USERS["fulfillment_manager_headers"]


@pytest.fixture
def postal_compliance_officer_headers():
    return TEST_USERS["postal_compliance_officer_headers"]
