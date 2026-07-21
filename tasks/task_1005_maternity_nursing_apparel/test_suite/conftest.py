"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and restarts the
server (empty DB) before every test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def shopper_headers_shared():
    """Shared-constant Shopper headers — valid ONLY for tests that do not
    exercise ownership (auth denials, bad-payload, missing-resource). Tests that
    need ownership semantics must call make_shopper_headers(customer_id)."""
    return TEST_USERS["shopper_headers"]


@pytest.fixture
def fulfillment_agent_headers():
    return TEST_USERS["fulfillment_agent_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["guest_headers"]


@pytest.fixture
def unknown_role_headers():
    return TEST_USERS["unknown_role_headers"]
