"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts against a
freshly-restarted (empty-database) API per the per-test-server isolation contract.
"""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    """Opaque PlatformAdmin headers (PRD §2.1)."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def hr_admin_headers() -> dict:
    """Opaque HRAdmin headers (PRD §2.1)."""
    return TEST_USERS["hr_admin_headers"]


@pytest.fixture
def employee_headers() -> dict:
    """Generic (entity-unbound) Employee headers (PRD §2.1).

    For ownership-gated tests use `make_employee_headers(employee_id)` instead.
    """
    return TEST_USERS["employee_headers"]


@pytest.fixture
def healthcare_provider_headers() -> dict:
    """Generic (entity-unbound) HealthcareProvider headers (PRD §2.1).

    For ownership-gated tests use `make_provider_headers(provider_id)` instead.
    """
    return TEST_USERS["healthcare_provider_headers"]
