"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest wires
per-role headers and the session-scoped api client.

PRD §2.1: every role's identity is opaque, so the shared TEST_USERS
constants are canonical for every call — no per-instance header builder
is required.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Per-role headers (PRD §2.1 — every role is opaque)
# ---------------------------------------------------------------------------
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def data_steward_headers():
    return TEST_USERS["data_steward_headers"]


@pytest.fixture
def data_steward_headers_alt():
    return TEST_USERS["data_steward_headers_alt"]


@pytest.fixture
def factor_manager_headers():
    return TEST_USERS["factor_manager_headers"]


@pytest.fixture
def factor_manager_headers_alt():
    return TEST_USERS["factor_manager_headers_alt"]


@pytest.fixture
def verifier_headers():
    return TEST_USERS["verifier_headers"]


@pytest.fixture
def verifier_headers_alt():
    return TEST_USERS["verifier_headers_alt"]


@pytest.fixture
def discloser_headers():
    return TEST_USERS["discloser_headers"]
