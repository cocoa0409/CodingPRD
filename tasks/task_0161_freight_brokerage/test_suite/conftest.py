"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, ready-check, teardown), PYTHONPATH, and
`API_BASE_URL` injection are owned by `prd-bench-local-runner`. These
fixtures simply expose the test_helpers objects to test functions.
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
    """Session-scoped API client. The runner guarantees the server is
    already running and reachable at API_BASE_URL by the time tests run."""
    return api_client


# ---------------------------------------------------------------------------
# Role-header fixtures — opaque roles use the shared deterministic ids.
# Tests that need ownership-gated headers for ShipperUser / CarrierUser
# import `make_shipper_headers` / `make_carrier_headers` directly from
# test_helpers and call them with the actual entity id.
# ---------------------------------------------------------------------------
@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def broker_ops_headers():
    return TEST_USERS["broker_ops_headers"]


@pytest.fixture
def broker_ops_secondary_headers():
    return TEST_USERS["broker_ops_secondary_headers"]


@pytest.fixture
def carrier_ops_headers():
    return TEST_USERS["carrier_ops_headers"]


@pytest.fixture
def carrier_ops_secondary_headers():
    return TEST_USERS["carrier_ops_secondary_headers"]


@pytest.fixture
def shipper_user_placeholder_headers():
    """ShipperUser headers carrying a placeholder id that does NOT
    resolve to any persisted Shipper. Appropriate only for auth/role/404
    probes — NEVER for ownership-gated calls (which need the real
    Shipper.id via make_shipper_headers(shipper["id"]))."""
    return TEST_USERS["shipper_user_headers"]


@pytest.fixture
def carrier_user_placeholder_headers():
    """CarrierUser placeholder headers — see shipper_user_placeholder_headers
    docstring."""
    return TEST_USERS["carrier_user_headers"]
