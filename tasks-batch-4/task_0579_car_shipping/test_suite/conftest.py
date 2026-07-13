"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner sets PYTHONPATH so `test_helpers` is importable and
manages server lifecycle (restarting the server before every test).
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def shipper_headers():
    return TEST_USERS["shipper_headers"]


@pytest.fixture
def broker_headers():
    return TEST_USERS["broker_headers"]


@pytest.fixture
def carrier_headers():
    return TEST_USERS["carrier_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
