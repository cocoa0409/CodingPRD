"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner manages server lifecycle and PYTHONPATH; these fixtures
only wire the shared ApiClient and per-role headers into tests.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def grower_manager_headers():
    return TEST_USERS["grower_manager_headers"]


@pytest.fixture
def production_tech_headers():
    return TEST_USERS["production_tech_headers"]


@pytest.fixture
def sales_coordinator_headers():
    return TEST_USERS["sales_coordinator_headers"]


@pytest.fixture
def broker_headers():
    return TEST_USERS["broker_headers"]
