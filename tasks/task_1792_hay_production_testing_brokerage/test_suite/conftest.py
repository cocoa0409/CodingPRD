"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner: the server is
restarted before every test, so each test starts against an empty database.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["ops_headers"]


@pytest.fixture
def tech_headers():
    return TEST_USERS["tech_headers"]


@pytest.fixture
def grower_headers():
    """Shared fallback only — ownership-gated calls must use
    make_grower_headers(grower_id) with the real Grower.id."""
    return TEST_USERS["grower_headers"]


@pytest.fixture
def buyer_headers():
    """Shared fallback only — ownership-gated calls must use
    make_buyer_headers(buyer_id) with the real Buyer.id."""
    return TEST_USERS["buyer_headers"]
