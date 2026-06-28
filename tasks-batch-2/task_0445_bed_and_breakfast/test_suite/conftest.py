"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, injects API_BASE_URL,
and restarts the server before every test. These fixtures just wire helpers in.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def innkeeper_headers():
    return TEST_USERS["innkeeper_headers"]


@pytest.fixture
def housekeeper_headers():
    return TEST_USERS["housekeeper_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def guest_headers():
    """Shared Guest constant — for guest tests that do NOT exercise booking
    ownership. Ownership-gated calls must use make_guest_headers(guest_id)."""
    return TEST_USERS["guest_headers"]
