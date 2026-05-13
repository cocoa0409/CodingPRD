"""Pytest fixtures exposing test_helpers infrastructure to all test
modules in this directory.

The prd-bench-local-runner harness handles PYTHONPATH so test_helpers
is importable without sys.path manipulation; it also starts the
server before tests run and registers API_BASE_URL.
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
    """Session-scoped API client. Server lifecycle is managed by the
    prd-bench-local-runner harness."""
    return api_client


# ---------------------------------------------------------------------------
# Role headers (PRD §2.1)
#
# For the entity_backed roles (Client, Designer, Reviewer), these
# constants are non-binding fallbacks suitable ONLY for tests that do
# not exercise ownership (401/403/404 negative tests). Any test that
# acts on a resource owned by a specific Client/Designer/Reviewer must
# instead use make_<role>_headers(entity_id) from test_helpers.
# ---------------------------------------------------------------------------
@pytest.fixture
def platform_ops_headers():
    """PRD §2.1: PlatformOps X-User-ID is opaque (shared constant safe)."""
    return TEST_USERS["platform_ops_headers"]


@pytest.fixture
def platform_ops_headers_alt():
    return TEST_USERS["platform_ops_headers_alt"]


@pytest.fixture
def client_headers_fallback():
    """Non-binding Client header — use only for tests that do NOT exercise
    ownership. PRD §2.1 requires X-User-ID == Client.id for ownership."""
    return TEST_USERS["client_headers"]


@pytest.fixture
def designer_headers_fallback():
    """Non-binding Designer header — use only for tests that do NOT
    exercise ownership."""
    return TEST_USERS["designer_headers"]


@pytest.fixture
def reviewer_headers_fallback():
    """Non-binding Reviewer header — use only for tests that do NOT
    exercise ownership."""
    return TEST_USERS["reviewer_headers"]
