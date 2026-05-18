"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest
wires per-role headers and the session-scoped API client.

PRD §2.1: all three roles (Paralegal, Attorney, ManagingPartner) use
opaque identity semantics — shared *_headers constants are canonical.
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
    """Best-effort wipe of the implementation's in-memory store
    between tests. Implementations that do not expose
    /__test__/reset are tolerated; tests still pass as long as they
    create unique entities.
    """
    try:
        api_client._request(
            "POST", "/__test__/reset", None,
            TEST_USERS["managing_partner_headers"],
        )
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Per-role headers — PRD §2.1.
# ---------------------------------------------------------------------------
@pytest.fixture
def paralegal_headers():
    return TEST_USERS["paralegal_headers"]


@pytest.fixture
def paralegal_headers_alt():
    return TEST_USERS["paralegal_headers_alt"]


@pytest.fixture
def attorney_headers():
    return TEST_USERS["attorney_headers"]


@pytest.fixture
def attorney_headers_alt():
    return TEST_USERS["attorney_headers_alt"]


@pytest.fixture
def managing_partner_headers():
    return TEST_USERS["managing_partner_headers"]


@pytest.fixture
def managing_partner_headers_alt():
    return TEST_USERS["managing_partner_headers_alt"]
