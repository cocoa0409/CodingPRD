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


# --- Opaque-role headers (PRD §2.1) -------------------------------------
@pytest.fixture
def site_manager_headers():
    return TEST_USERS["site_manager_headers"]


@pytest.fixture
def site_manager_headers_alt():
    return TEST_USERS["site_manager_headers_alt"]


@pytest.fixture
def plan_owner_headers():
    return TEST_USERS["plan_owner_headers"]


@pytest.fixture
def plan_owner_headers_alt():
    return TEST_USERS["plan_owner_headers_alt"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def dispatcher_headers_alt():
    return TEST_USERS["dispatcher_headers_alt"]


@pytest.fixture
def storekeeper_headers():
    return TEST_USERS["storekeeper_headers"]


@pytest.fixture
def storekeeper_headers_alt():
    return TEST_USERS["storekeeper_headers_alt"]


# --- Fallback headers for entity-backed Technician role ----------------
# Used only by tests that don't exercise an ownership comparison
# (RBAC ERR_FORBIDDEN wrong-role, ERR_NOT_FOUND on missing resource).
@pytest.fixture
def technician_headers_fallback():
    return TEST_USERS["technician_headers"]
