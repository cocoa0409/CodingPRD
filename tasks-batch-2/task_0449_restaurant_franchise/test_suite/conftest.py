"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, injects API_BASE_URL,
and restarts the server before every test. These fixtures just wire helpers in.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def franchisor_headers():
    return TEST_USERS["franchisor_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def finance_clerk_headers():
    return TEST_USERS["finance_clerk_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]


@pytest.fixture
def franchisee_headers():
    """Shared Franchisee constant — for tests that do NOT exercise franchisee
    ownership (e.g. RBAC 403, where the role is forbidden before ownership is
    checked). Ownership-gated franchisee calls must use make_franchisee_headers."""
    return TEST_USERS["franchisee_headers"]
