"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts against
a freshly-restarted (empty-database) API per the per-test-server isolation
contract.
"""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def state_admin_headers() -> dict:
    """StateAdmin headers (opaque user-id)."""
    return TEST_USERS["state_admin_headers"]


@pytest.fixture
def compliance_officer_headers() -> dict:
    """ComplianceOfficer headers (opaque user-id)."""
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def anonymous_headers() -> dict:
    """Anonymous headers (PRD §2.1)."""
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def filer_headers() -> dict:
    """Generic Filer headers (fake user-id). Use only for non-ownership tests
    (e.g., 401/404 paths or assertions that do not depend on ownership
    matching). For ownership-gated calls use make_filer_headers(business_entity_id).
    """
    return TEST_USERS["filer_headers"]
