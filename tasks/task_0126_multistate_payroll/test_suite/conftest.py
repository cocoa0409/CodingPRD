"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1: ALL FOUR ROLES (PayrollSpecialist, PayrollManager,
Treasurer, Any) ARE OPAQUE — shared *_headers constants are
canonical. SOD (PRD §2.6) requires distinct X-User-IDs across
consecutive control steps on the same artifact, which the fixtures
satisfy by defaulting to specialist/manager/treasurer ids that are
distinct from each other.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, seed_all_tax_brackets


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
        api_client._request(
            "POST", "/__test__/reset", None,
            TEST_USERS["manager_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Opaque-role headers (PRD §2.1).
# ---------------------------------------------------------------------------
@pytest.fixture
def specialist_headers():
    return TEST_USERS["specialist_headers"]


@pytest.fixture
def specialist_headers_alt():
    return TEST_USERS["specialist_headers_alt"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager_headers_alt():
    return TEST_USERS["manager_headers_alt"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def treasurer_headers_alt():
    return TEST_USERS["treasurer_headers_alt"]


@pytest.fixture
def seeded_world():
    """Seed every PRD §3.4 tax bracket so calculate calls do not fail
    with ERR_TAX_BRACKET_NOT_FOUND. Idempotent."""
    seed_all_tax_brackets()
    return None
