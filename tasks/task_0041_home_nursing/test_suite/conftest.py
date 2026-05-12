"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, shutdown) is managed by the
prd-bench-local-runner framework. PYTHONPATH points at the parent
directory so `test_helpers` is importable directly.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)
from test_helpers.fixtures import reset_isolation_for_new_test


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Base URL supplied by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _isolate_test_state():
    """Per-test isolation: drop all in-memory rows on the implementation
    side AND rotate the default (lat,lng) cluster so any inadvertent
    cross-test contamination still falls outside the 15 km dispatch
    radius. POST /_test/reset is a test-only impl hook (not in PRD).

    The implementation runs in a single shared container, so without
    this fixture the in-memory db accumulates across the test session
    and leaked CERTIFIED nurses pollute the dispatch candidate pool.
    """
    api_client.reset_state(TEST_USERS["platform_admin_headers"])
    reset_isolation_for_new_test()
    yield


# --- Opaque-role headers (PRD §2.1) -------------------------------------
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_headers_alt():
    return TEST_USERS["compliance_officer_headers_alt"]


# --- Fallback headers for identity-bearing roles ------------------------
# Used only by tests that do NOT exercise an ownership/identity comparison
# (e.g., RBAC ERR_INSUFFICIENT_PERMISSIONS, header-validation tests).
@pytest.fixture
def nurse_headers_fallback():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def patient_headers_fallback():
    return TEST_USERS["patient_headers"]
