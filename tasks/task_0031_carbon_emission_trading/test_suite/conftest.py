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
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def regulator_headers_alt():
    return TEST_USERS["regulator_headers_alt"]


# --- Fallback headers for entity-backed / opaque-but-ownership-gated roles
# Use only for tests that don't exercise an ownership comparison.
@pytest.fixture
def enterprise_headers_fallback():
    return TEST_USERS["enterprise_headers"]


@pytest.fixture
def verifier_agency_headers_fallback():
    return TEST_USERS["verifier_agency_headers"]
