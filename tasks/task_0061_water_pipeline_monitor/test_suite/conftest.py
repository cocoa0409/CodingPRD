"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
the session-scoped api client and per-role header fixtures.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Role-header fixtures. Per PRD §2.1 every role is opaque, so shared
# constants are safe for tests that do not need to thread a specific
# X-User-ID across multiple calls. Tests that DO need to thread identity
# (SoD or technician ownership) build headers explicitly via
# make_<role>_headers() in fixtures.
# ---------------------------------------------------------------------------
@pytest.fixture
def te_headers():
    return TEST_USERS["topology_engineer_headers"]


@pytest.fixture
def te_headers_alt():
    return TEST_USERS["topology_engineer_headers_alt"]


@pytest.fixture
def ta_headers():
    return TEST_USERS["topology_approver_headers"]


@pytest.fixture
def ta_headers_alt():
    return TEST_USERS["topology_approver_headers_alt"]


@pytest.fixture
def co_headers():
    return TEST_USERS["control_operator_headers"]


@pytest.fixture
def co_headers_alt():
    return TEST_USERS["control_operator_headers_alt"]


@pytest.fixture
def sup_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def sup_headers_alt():
    return TEST_USERS["supervisor_headers_alt"]


@pytest.fixture
def tech_headers():
    return TEST_USERS["technician_headers"]


@pytest.fixture
def tech_headers_alt():
    return TEST_USERS["technician_headers_alt"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
