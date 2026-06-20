"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable. Server lifecycle
(start/stop, readiness) is owned by prd-bench-local-runner — these tests assume a
running server reachable at API_BASE_URL and an empty database per test.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["platform_operator_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["underwriting_officer_headers"]


@pytest.fixture
def merchant_user_headers():
    return TEST_USERS["merchant_user_headers"]
