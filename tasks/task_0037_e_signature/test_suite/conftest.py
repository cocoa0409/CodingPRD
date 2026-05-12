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
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def system_sweeper_headers():
    return TEST_USERS["system_sweeper_headers"]


# --- Fallback headers for entity-backed roles ---------------------------
# Used only by tests that do NOT exercise an ownership/segregation
# comparison (e.g., RBAC ERR_FORBIDDEN, ERR_UNAUTHENTICATED).
@pytest.fixture
def template_admin_headers_fallback():
    return TEST_USERS["template_admin_headers"]


@pytest.fixture
def contract_initiator_headers_fallback():
    return TEST_USERS["contract_initiator_headers"]


@pytest.fixture
def signer_headers_fallback():
    return TEST_USERS["signer_headers"]


@pytest.fixture
def evidence_archivist_headers_fallback():
    return TEST_USERS["evidence_archivist_headers"]
