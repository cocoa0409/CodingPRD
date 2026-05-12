"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, shutdown) is managed by the
prd-bench-local-runner framework. PYTHONPATH points at the parent
directory so `test_helpers` is importable directly.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The base URL is supplied by the runner."""
    return api_client


# --- Opaque-role headers (PRD §2.1) -------------------------------------
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def planner_headers_alt():
    return TEST_USERS["planner_headers_alt"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def finance_headers_alt():
    return TEST_USERS["finance_headers_alt"]


# --- Fallback headers for entity-backed roles ---------------------------
# Use only for tests that don't exercise an ownership comparison.
@pytest.fixture
def driver_headers_fallback():
    return TEST_USERS["driver_headers"]


@pytest.fixture
def store_manager_headers_fallback():
    return TEST_USERS["store_manager_headers"]
