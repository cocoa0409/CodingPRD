"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, ready-check, stop) is managed by
prd-bench-local-runner; this file only wires the test_helpers package
into pytest-friendly fixtures.
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
    """Session-scoped API client. Server is reachable at API_BASE_URL."""
    return api_client


# Pre-built role headers from TEST_USERS — usable for auth / 404 / role
# probes only. For ownership-gated calls, tests must mint per-instance
# headers via make_<role>_headers() against a real Employee.id.
@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_secondary_headers():
    return TEST_USERS["admin_secondary_headers"]


@pytest.fixture
def hrbp_placeholder_headers():
    return TEST_USERS["hrbp_placeholder_headers"]


@pytest.fixture
def manager_placeholder_headers():
    return TEST_USERS["manager_placeholder_headers"]


@pytest.fixture
def reviewer_placeholder_headers():
    return TEST_USERS["reviewer_placeholder_headers"]


@pytest.fixture
def approver_placeholder_headers():
    return TEST_USERS["approver_placeholder_headers"]
