"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable and injects
API_BASE_URL; the server lifecycle (restart-before-every-test) is owned by
prd-bench-local-runner, not these fixtures.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def support_headers():
    return TEST_USERS["support_headers"]


@pytest.fixture
def restaurant_headers():
    return TEST_USERS["restaurant_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def dasher_headers():
    return TEST_USERS["dasher_headers"]
