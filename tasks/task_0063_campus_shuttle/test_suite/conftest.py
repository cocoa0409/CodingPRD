"""Pytest fixtures exposing test_helpers infrastructure.

The runner (prd-bench-local-runner) sets API_BASE_URL and PYTHONPATH;
this file only adapts test_helpers into pytest-style fixtures.
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
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


# ---------------------------------------------------------------------------
# Opaque-role headers (PRD §2.1)
# ---------------------------------------------------------------------------
@pytest.fixture
def dispatcher_headers():
    """Opaque Dispatcher headers (PRD §2.1)."""
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def dispatcher_headers_alt():
    """Alternate opaque Dispatcher id (used for race / actor-id tests)."""
    return TEST_USERS["dispatcher_headers_alt"]


@pytest.fixture
def auditor_headers():
    """Opaque Auditor headers (PRD §2.1)."""
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def driver_headers_fallback():
    """Non-binding Driver fallback. ONLY use for tests that do not exercise
    ownership (e.g., envelope / 401 / 403 checks). Per PRD §2.1 real
    Driver-role calls must use make_driver_headers(driver["id"])."""
    return TEST_USERS["driver_headers"]


@pytest.fixture
def employee_headers_fallback():
    """Non-binding Employee fallback. Per PRD §2.1 X-User-ID for Employee
    is opaque BUT 'is carried through to the employee_id field on a new
    reservation and used to scope cancellation and listing'; tests that
    exercise those semantics should use make_employee_headers(employee_id)."""
    return TEST_USERS["employee_headers"]
