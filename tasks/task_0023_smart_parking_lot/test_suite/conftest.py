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
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def operator_headers_alt():
    return TEST_USERS["operator_headers_alt"]


@pytest.fixture
def gate_headers():
    return TEST_USERS["gate_headers"]


@pytest.fixture
def gate_headers_alt():
    return TEST_USERS["gate_headers_alt"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def partner_headers():
    return TEST_USERS["partner_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


# --- Driver fallback (PRD §2.1: entity-backed on Vehicle) ---------------
# Use only for tests that don't exercise an ownership comparison.
@pytest.fixture
def driver_headers_fallback():
    return TEST_USERS["driver_headers"]
