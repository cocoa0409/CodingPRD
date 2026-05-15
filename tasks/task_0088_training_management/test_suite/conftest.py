"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- TrainingAdmin, CourseDesigner, DepartmentManager — OPAQUE: shared
  constants canonical.
- Trainee — ENTITY-BACKED: X-User-ID must equal Trainee.id. Tests
  that exercise ownership-gated calls MUST use
  make_trainee_headers(trainee['id']); the trainee_fallback_headers
  fixture is for tests that do NOT exercise ownership (missing-auth,
  wrong-role on admin endpoints).
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, reset_clock_to_epoch


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Wipe the implementation's in-memory store before each test so
    catalog state cannot leak. The /__test__/reset endpoint is a
    test-infrastructure extension parallel to the test-driver
    endpoints in PRD §2.10; a 404 from an implementation that does
    not expose it is tolerated."""
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Role headers — opaque roles (PRD §2.1)
# ---------------------------------------------------------------------------
@pytest.fixture
def training_admin_headers():
    return TEST_USERS["training_admin_headers"]


@pytest.fixture
def training_admin_headers_alt():
    return TEST_USERS["training_admin_headers_alt"]


@pytest.fixture
def course_designer_headers():
    return TEST_USERS["course_designer_headers"]


@pytest.fixture
def course_designer_headers_alt():
    return TEST_USERS["course_designer_headers_alt"]


@pytest.fixture
def department_manager_headers():
    return TEST_USERS["department_manager_headers"]


@pytest.fixture
def department_manager_headers_alt():
    return TEST_USERS["department_manager_headers_alt"]


# ---------------------------------------------------------------------------
# Trainee fallback headers — for tests that do NOT exercise the
# entity-backed ownership check (PRD §2.1). Ownership-gated tests MUST
# call make_trainee_headers(trainee['id']).
# ---------------------------------------------------------------------------
@pytest.fixture
def trainee_fallback_headers():
    return TEST_USERS["trainee_fallback_headers"]


@pytest.fixture
def trainee_fallback_headers_alt():
    return TEST_USERS["trainee_fallback_headers_alt"]


@pytest.fixture(autouse=True)
def _reset_logical_clock():
    """PRD §2.10: anchor the server's logical clock at TEST_EPOCH on
    every test so tests that don't rely on the sweep observe a fresh
    starting point. Failures are tolerated so tests that don't need
    the clock still pass when the implementation lacks the
    test-driver endpoint."""
    try:
        reset_clock_to_epoch()
    except Exception:
        pass
    yield
