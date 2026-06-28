"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only wires the
shared API client and role headers into pytest fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def plan_admin_headers():
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def clinic_staff_headers():
    return TEST_USERS["clinic_staff_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
