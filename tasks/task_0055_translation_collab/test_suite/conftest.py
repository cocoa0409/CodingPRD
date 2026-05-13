"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets API_BASE_URL and PYTHONPATH; this file only adapts
test_helpers into pytest-style fixtures.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiClient,
    api_client,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pm_headers():
    """Opaque ProjectManager headers (PRD §2.1)."""
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def pm_headers_alt():
    """Alternate opaque ProjectManager id (for audit actor_id tests)."""
    return TEST_USERS["project_manager_headers_alt"]


@pytest.fixture
def translator_headers_fallback():
    """Non-binding Translator fallback. ONLY use for tests that do not
    exercise ownership (e.g., 400/401/403 envelope checks on broken
    payloads, or proving that a fake X-User-ID fails the ownership
    check). Per PRD §2.1, real Translator-role calls must use
    make_translator_headers(real_translator['id'])."""
    return TEST_USERS["translator_headers"]
