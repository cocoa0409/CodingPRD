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
def content_reviewer_headers():
    return TEST_USERS["content_reviewer_headers"]


@pytest.fixture
def content_reviewer_headers_alt():
    return TEST_USERS["content_reviewer_headers_alt"]


@pytest.fixture
def legal_reviewer_headers():
    return TEST_USERS["legal_reviewer_headers"]


@pytest.fixture
def legal_reviewer_headers_alt():
    return TEST_USERS["legal_reviewer_headers_alt"]


@pytest.fixture
def financial_reviewer_headers():
    return TEST_USERS["financial_reviewer_headers"]


@pytest.fixture
def financial_reviewer_headers_alt():
    return TEST_USERS["financial_reviewer_headers_alt"]


# --- Fallback headers for entity-backed roles ---------------------------
# Used only by tests that don't exercise an ownership comparison
# (RBAC ERR_FORBIDDEN, ERR_AUTH_REQUIRED).
@pytest.fixture
def initiator_headers_fallback():
    return TEST_USERS["initiator_headers"]


@pytest.fixture
def backer_headers_fallback():
    return TEST_USERS["backer_headers"]
