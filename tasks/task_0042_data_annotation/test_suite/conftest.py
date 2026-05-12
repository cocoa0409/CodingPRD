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


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset the in-memory server state before every test so the test
    suite's hardcoded date windows, ids, and counters all start from a
    clean slate. The /_test/reset endpoint is a test-only hook on the
    server (not part of PRD)."""
    try:
        api_client._request(
            "POST", "/_test/reset", None,
            TEST_USERS["project_manager_headers"],
        )
    except Exception:
        # Server may not implement /_test/reset; if not, tests share state
        # and overlapping fixtures may surface as failures.
        pass
    yield


# --- Opaque-role headers (PRD §2.1) ----------------------------------------
@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def project_manager_headers_alt():
    return TEST_USERS["project_manager_headers_alt"]


@pytest.fixture
def qa_reviewer_headers():
    return TEST_USERS["qa_reviewer_headers"]


@pytest.fixture
def qa_reviewer_headers_alt():
    return TEST_USERS["qa_reviewer_headers_alt"]


# --- Fallback header for the entity-backed Annotator role ------------------
# Use only on tests that do NOT exercise an ownership comparison (RBAC role
# mismatch, ERR_ANNOTATOR_NOT_FOUND, ERR_INSUFFICIENT_PERMISSIONS).
@pytest.fixture
def annotator_headers_fallback():
    return TEST_USERS["annotator_headers"]
