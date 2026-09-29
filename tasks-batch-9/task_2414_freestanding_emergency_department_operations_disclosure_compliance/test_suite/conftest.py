"""Pytest fixtures exposing the shared test infrastructure.

The composite setup chains live in ``test_helpers.fixtures`` and are re-exported
here so pytest discovers them; the per-role header fixtures below are the seven
declared roles, plus the second operator each segregation-of-duties control needs.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers.fixtures import (  # noqa: F401  (re-exported for pytest discovery)
    adjudicated_claim_context,
    bare_facility,
    default_clock,
    narrow_scope_facility_context,
    open_facility_context,
    transfer_context,
)

__all__ = [
    "adjudicated_claim_context",
    "bare_facility",
    "default_clock",
    "narrow_scope_facility_context",
    "open_facility_context",
    "transfer_context",
]


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def second_admin_headers():
    return TEST_USERS["second_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def second_compliance_officer_headers():
    return TEST_USERS["second_compliance_officer_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def second_clerk_headers():
    return TEST_USERS["second_clerk_headers"]


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def payer_headers():
    return TEST_USERS["payer_headers"]


@pytest.fixture
def idre_headers():
    return TEST_USERS["idre_headers"]
