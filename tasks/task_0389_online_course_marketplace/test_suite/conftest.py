"""Pytest fixtures exposing test_helpers infrastructure (PRD §2.1).

Server lifecycle is managed by prd-bench-local-runner; each test starts against a
freshly-restarted (empty-database) API per the per-test-server isolation contract.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def anonymous_headers() -> dict:
    """Anonymous (opaque id) — registration endpoints only."""
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def admin_headers() -> dict:
    """PlatformAdmin (opaque id admin-1)."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def instructor_headers() -> dict:
    """Generic Instructor headers (fake id). Use only for non-ownership paths
    (401/403/404), never where ownership must match a real Instructor.id (PRD §2.1)."""
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def learner_headers() -> dict:
    """Generic Learner headers (fake id). Use only for non-ownership paths
    (401/403/404), never where ownership must match a real Learner.id (PRD §2.1)."""
    return TEST_USERS["learner_headers"]
