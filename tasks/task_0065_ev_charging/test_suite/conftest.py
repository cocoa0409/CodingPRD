"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped api client.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Role-header fixtures.
#
# PRD §2.1:
# - PlatformOperator, FieldTechnician, CustomerService are OPAQUE; shared
#   constants are canonical.
# - StationOwner is entity_backed by Operator; tests that exercise
#   ownership MUST call make_station_owner_headers(operator['id']) from
#   test_helpers.
# - EVDriver is entity_backed by Member; tests that exercise ownership
#   MUST call make_ev_driver_headers(member['id']).
# ---------------------------------------------------------------------------
@pytest.fixture
def po_headers():
    return TEST_USERS["platform_operator_headers"]


@pytest.fixture
def po_headers_alt():
    return TEST_USERS["platform_operator_headers_alt"]


@pytest.fixture
def ft_headers():
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def ft_headers_alt():
    return TEST_USERS["field_technician_headers_alt"]


@pytest.fixture
def cs_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def cs_headers_alt():
    return TEST_USERS["customer_service_headers_alt"]


@pytest.fixture
def station_owner_fallback_headers():
    """Fallback StationOwner headers — X-User-ID 'station-owner-fallback'.

    PRD §2.1: ownership-gated StationOwner endpoints compare X-User-ID to
    Station.station_owner_id; this constant matches no real Operator.id,
    so use it only for tests that do NOT exercise ownership (missing-
    resource, wrong-role tests)."""
    return TEST_USERS["station_owner_headers"]


@pytest.fixture
def ev_driver_fallback_headers():
    """Fallback EVDriver headers — X-User-ID 'ev-driver-fallback'.

    PRD §2.1: ownership-gated EVDriver endpoints compare X-User-ID to
    Member.id; this constant matches no real Member.id, so use it only
    for tests that do NOT exercise ownership."""
    return TEST_USERS["ev_driver_headers"]
