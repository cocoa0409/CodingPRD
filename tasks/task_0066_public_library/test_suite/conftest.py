"""Pytest fixtures exposing test_helpers infrastructure for the Public Library API.

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
def librarian_headers():
    return TEST_USERS["librarian_headers"]


@pytest.fixture
def librarian_headers_alt():
    return TEST_USERS["librarian_headers_alt"]


@pytest.fixture
def fine_officer_headers():
    return TEST_USERS["fine_officer_headers"]


@pytest.fixture
def ill_coordinator_headers():
    return TEST_USERS["ill_coordinator_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def reader_headers_fallback():
    """Fallback Reader headers — safe ONLY for tests that do not exercise
    ownership (RBAC probes, missing-header probes). Tests that hit
    ownership-gated endpoints must mint headers via make_reader_headers(<id>).
    """
    return TEST_USERS["reader_headers_fallback"]
