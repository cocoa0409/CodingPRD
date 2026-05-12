"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; tests assume the
server is already running. PYTHONPATH points at the parent directory so
`test_helpers` is importable directly.
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
    """Session-scoped API client. Base URL is supplied by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset in-memory server state before every test so each test starts
    from a clean slate. /_test/reset is a test-only hook on the server."""
    try:
        api_client._request(
            "POST", "/_test/reset", None,
            TEST_USERS["triage_manager_headers"],
        )
    except Exception:
        pass
    yield


# --- Opaque pseudo-role for read endpoints ---------------------------------
@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


# --- Fallback headers for entity-backed roles -----------------------------
# Use ONLY on tests that do NOT exercise an ownership comparison.
@pytest.fixture
def triage_manager_headers_fallback():
    return TEST_USERS["triage_manager_headers"]


@pytest.fixture
def developer_headers_fallback():
    return TEST_USERS["developer_headers"]


@pytest.fixture
def qa_engineer_headers_fallback():
    return TEST_USERS["qa_engineer_headers"]


@pytest.fixture
def release_manager_headers_fallback():
    return TEST_USERS["release_manager_headers"]
