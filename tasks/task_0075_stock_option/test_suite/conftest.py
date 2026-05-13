"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped api client.

PRD §2.1 identity rules:
- PlanAdministrator, BoardSecretary, ShareholderRegistrar, AuditViewer
  are OPAQUE → shared constants are canonical.
- Grantee is entity_backed → ownership-gated tests MUST use
  make_grantee_headers(grantee['hr_employee_id']).
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Opaque-role headers (canonical via shared constants)
# ---------------------------------------------------------------------------
@pytest.fixture
def plan_admin_headers():
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def plan_admin_headers_alt():
    """A second PlanAdministrator id; needed for segregation-of-duties
    tests when the draft submitter must differ from another actor."""
    return TEST_USERS["plan_admin_headers_alt"]


@pytest.fixture
def board_secretary_headers():
    return TEST_USERS["board_secretary_headers"]


@pytest.fixture
def board_secretary_headers_alt():
    return TEST_USERS["board_secretary_headers_alt"]


@pytest.fixture
def shareholder_registrar_headers():
    return TEST_USERS["shareholder_registrar_headers"]


@pytest.fixture
def shareholder_registrar_headers_alt():
    return TEST_USERS["shareholder_registrar_headers_alt"]


@pytest.fixture
def audit_viewer_headers():
    return TEST_USERS["audit_viewer_headers"]


@pytest.fixture
def grantee_fallback_headers():
    """Fallback Grantee headers — X-User-ID 'grantee-fallback'.

    PRD §2.1: real Grantee X-User-ID must equal Grantee.hr_employee_id;
    this constant matches no real grantee, so use it only for tests that
    do NOT exercise ownership (missing-auth, wrong-role, missing-resource).
    """
    return TEST_USERS["grantee_headers"]
