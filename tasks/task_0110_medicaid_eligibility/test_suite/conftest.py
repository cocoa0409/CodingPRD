"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- All four roles (IntakeWorker, EligibilityCaseworker, AppealsOfficer,
  PolicyAdmin) have opaque identity. The shared TEST_USERS constants
  are canonical. _alt variants are used to satisfy segregation-of-
  duties on re-decide and on appeal grant/uphold (PRD §2.1).
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle owned by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Best-effort wipe of the implementation's in-memory store between
    tests. Implementations that do not expose /__test__/reset are
    tolerated; tests still pass as long as they create unique entities.
    """
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers — PRD §2.1 (all four roles opaque).
# ---------------------------------------------------------------------------
@pytest.fixture
def intake_worker_headers():
    return TEST_USERS["intake_worker_headers"]


@pytest.fixture
def intake_worker_headers_alt():
    return TEST_USERS["intake_worker_headers_alt"]


@pytest.fixture
def eligibility_caseworker_headers():
    return TEST_USERS["eligibility_caseworker_headers"]


@pytest.fixture
def eligibility_caseworker_headers_alt():
    return TEST_USERS["eligibility_caseworker_headers_alt"]


@pytest.fixture
def appeals_officer_headers():
    return TEST_USERS["appeals_officer_headers"]


@pytest.fixture
def appeals_officer_headers_alt():
    return TEST_USERS["appeals_officer_headers_alt"]


@pytest.fixture
def policy_admin_headers():
    return TEST_USERS["policy_admin_headers"]


@pytest.fixture
def policy_admin_headers_alt():
    return TEST_USERS["policy_admin_headers_alt"]
