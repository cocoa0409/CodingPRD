"""Pytest fixtures exposing test_helpers infrastructure to test files.

The runner (prd-bench-local-runner) handles PYTHONPATH so test_helpers is
importable, manages server lifecycle, and injects API_BASE_URL — so this file
only wires the request-time fixtures the tests need.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def seller_headers():
    """Shared-constant Seller headers — only safe for tests that do NOT
    exercise ownership. Tests requiring ownership must call
    ``make_seller_headers(seller["id"])`` directly."""
    return TEST_USERS["seller_headers"]


@pytest.fixture
def buyer_headers():
    """Shared-constant Buyer headers — only safe for tests that do NOT
    exercise ownership. Tests requiring ownership must call
    ``make_buyer_headers(buyer["id"])`` directly."""
    return TEST_USERS["buyer_headers"]
