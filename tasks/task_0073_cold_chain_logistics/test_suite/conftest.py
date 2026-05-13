"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects PYTHONPATH so test_helpers is importable without
sys.path hacks. The API server is also started by the runner; the
session-scoped api client just talks to it.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle handled by runner."""
    return api_client


# ---------------------------------------------------------------------------
# One fixture per role from TEST_USERS — shared opaque constants are
# safe for non-ownership-gated tests. Ownership-gated calls must use
# the per-instance builders from test_helpers.test_users.
# ---------------------------------------------------------------------------
@pytest.fixture
def shipper_headers():
    return TEST_USERS["shipper_headers"]


@pytest.fixture
def carrier_headers():
    return TEST_USERS["carrier_headers"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_headers"]


@pytest.fixture
def consignee_headers():
    return TEST_USERS["consignee_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def insurance_headers():
    return TEST_USERS["insurance_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]
