"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so `test_helpers` is importable, and manages
server lifecycle (kills + relaunches the server before every test). Tests
therefore start against an empty database.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["curation_admin_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_operator_headers"]


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]
