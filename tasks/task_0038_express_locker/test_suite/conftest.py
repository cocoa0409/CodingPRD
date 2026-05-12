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


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Base URL supplied by the runner."""
    return api_client


# --- Opaque-role headers (PRD §2.1) -----------------------------------------
@pytest.fixture
def operations_admin_headers():
    return TEST_USERS["operations_admin_headers"]


@pytest.fixture
def operations_admin_headers_alt():
    return TEST_USERS["operations_admin_headers_alt"]


@pytest.fixture
def recipient_headers():
    return TEST_USERS["recipient_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


# --- Fallback headers for the entity-backed Courier role --------------------
# Use ONLY for tests that don't depend on ownership matching (e.g., RBAC
# wrong-role tests, missing-header tests).
@pytest.fixture
def courier_headers_fallback():
    return TEST_USERS["courier_headers"]
