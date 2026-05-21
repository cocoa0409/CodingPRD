"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.

PRD §2.1: Employee is the only entity_backed role. The shared-constant
`employee_headers` fixture is a placeholder used only by tests that
probe auth / role / 404 paths without exercising ownership. Tests that
exercise ownership use `make_employee_headers(employee_id)` with the
actual Employee.id.
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
    Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["employee_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor_secondary_headers():
    return TEST_USERS["supervisor_secondary_headers"]


@pytest.fixture
def payroll_admin_headers():
    return TEST_USERS["payroll_admin_headers"]


@pytest.fixture
def payroll_admin_secondary_headers():
    return TEST_USERS["payroll_admin_secondary_headers"]
