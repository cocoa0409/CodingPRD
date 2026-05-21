"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.

PRD §2.1: Employee and HRSpecialist are entity_backed. The shared-
constant `employee_headers` fixture is a placeholder used only by tests
that probe auth / role / 404 paths without exercising ownership. Tests
that exercise ownership use `make_employee_headers(employee_id)` with
the actual Employee.id. Tests that exercise HR-acted endpoints use the
shared `hr_specialist_headers` (backed by HR_SPECIALIST_SHARED_ID,
which the implementation is expected to resolve to a known specialist
row or to accept as a permissive non-empty id).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


# ===========================================================================
# Session-scoped API client — server lifecycle managed by the runner.
# ===========================================================================
@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


# ===========================================================================
# Shared-constant role headers. For ownership-gated Employee calls,
# tests MUST mint headers via make_employee_headers(employee_id).
# ===========================================================================
@pytest.fixture
def employee_headers():
    """Placeholder Employee headers (NOT tied to any persisted Employee).
    Use only for auth / role-forbidden / 404 / ERR_UNKNOWN_IDENTITY
    probes."""
    return TEST_USERS["employee_headers"]


@pytest.fixture
def hr_specialist_headers():
    return TEST_USERS["hr_specialist_headers"]


@pytest.fixture
def hr_specialist_secondary_headers():
    return TEST_USERS["hr_specialist_secondary_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def compliance_officer_secondary_headers():
    return TEST_USERS["compliance_officer_secondary_headers"]
