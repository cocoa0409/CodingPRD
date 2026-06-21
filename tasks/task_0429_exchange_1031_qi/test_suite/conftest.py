"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and manages the server
lifecycle (restart + empty DB + clock reset to 2026-01-01 before every test).
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_qi_coordinator_headers, make_settlement_officer_headers, make_exchanger_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def qi_coordinator_headers():
    return TEST_USERS["qi_coordinator_headers"]


@pytest.fixture
def settlement_officer_headers():
    return TEST_USERS["settlement_officer_headers"]


@pytest.fixture
def exchanger_headers():
    return TEST_USERS["exchanger_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def coordinator_headers_factory():
    """Returns make_qi_coordinator_headers so tests can mint coordinator headers with
    a controlled opaque X-User-ID (the anchor for segregation-of-duties)."""
    return make_qi_coordinator_headers


@pytest.fixture
def officer_headers_factory():
    return make_settlement_officer_headers


@pytest.fixture
def exchanger_headers_factory():
    return make_exchanger_headers
