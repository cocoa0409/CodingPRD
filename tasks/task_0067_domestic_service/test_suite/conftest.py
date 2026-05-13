"""Pytest fixtures exposing test_helpers infrastructure for the Domestic Service Dispatch API.

Server lifecycle, PYTHONPATH, and base URL are managed by prd-bench-local-runner;
this file just wires test_helpers into pytest fixtures.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner guarantees the server is up at API_BASE_URL."""
    return api_client


# ─────────────────────────────────────────────────────────────
# Opaque-role headers (PRD §2.1: X-User-ID is not compared to any entity).
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def operator_headers_alt():
    return TEST_USERS["operator_headers_alt"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]


# ─────────────────────────────────────────────────────────────
# Entity-backed fallbacks — safe ONLY for tests that do NOT exercise ownership
# (RBAC probes, missing-header probes). Tests that hit ownership-gated
# endpoints must mint headers via make_customer_headers / make_personnel_headers.
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def customer_headers_fallback():
    return TEST_USERS["customer_headers_fallback"]


@pytest.fixture
def personnel_headers_fallback():
    return TEST_USERS["personnel_headers_fallback"]
