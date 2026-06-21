"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle (start/stop per test) and PYTHONPATH so
test_helpers is importable without sys.path manipulation.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# ─── Role-header fixtures (PRD §2.1) ──────────────────────────────────────

@pytest.fixture
def hr_clerk_headers():
    return TEST_USERS["hr_clerk_headers"]


@pytest.fixture
def payroll_preparer_headers():
    return TEST_USERS["payroll_preparer_headers"]


@pytest.fixture
def payroll_approver_headers():
    return TEST_USERS["payroll_approver_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
