"""Pytest fixtures bridging test_helpers infrastructure to the test suite.

The runner manages PYTHONPATH so test_helpers is importable without
sys.path manipulation. Server lifecycle (start/stop, readiness, crash
recovery) is also the runner's responsibility -- conftest only wires up
fixtures.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped ApiClient. Server lifecycle is managed by
    prd-bench-local-runner."""
    return api_client


# ---------------------------------------------------------------------------
# Per-role headers (PRD §2.1). Investor headers are entity-backed; tests
# that need ownership-resolving Investor headers should call
# make_investor_headers(investor_id) directly via test_helpers, not the
# fallback fixture below.
# ---------------------------------------------------------------------------
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def product_operator_headers():
    return TEST_USERS["product_operator_headers"]


@pytest.fixture
def product_operator_headers_alt():
    return TEST_USERS["product_operator_headers_alt"]


@pytest.fixture
def compliance_reviewer_headers():
    return TEST_USERS["compliance_reviewer_headers"]


@pytest.fixture
def compliance_reviewer_headers_alt():
    return TEST_USERS["compliance_reviewer_headers_alt"]


@pytest.fixture
def nav_operator_headers():
    return TEST_USERS["nav_operator_headers"]


@pytest.fixture
def nav_operator_headers_alt():
    return TEST_USERS["nav_operator_headers_alt"]


@pytest.fixture
def clearing_operator_headers():
    return TEST_USERS["clearing_operator_headers"]


@pytest.fixture
def clearing_operator_headers_alt():
    return TEST_USERS["clearing_operator_headers_alt"]


@pytest.fixture
def investor_headers_fallback():
    """PRD §2.1 fallback. Use ONLY for tests that don't exercise ownership
    comparison (404, missing-header, schema-violation tests)."""
    return TEST_USERS["investor_headers_fallback"]
