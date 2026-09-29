"""Pytest fixtures exposing the shared test infrastructure.

The runner manages the server lifecycle and relaunches it before every test, so
each test starts against an empty database and builds its own preconditions.
"""
import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_asset_manager_headers,
    make_compliance_officer_headers,
    make_lease_administrator_headers,
    make_lender_rep_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client pointed at the server under test."""
    return api_client


@pytest.fixture
def lease_admin_headers():
    """Headers for the default ``LeaseAdministrator``."""
    return make_lease_administrator_headers()


@pytest.fixture
def compliance_officer_headers():
    """Headers for the default ``ComplianceOfficer``."""
    return make_compliance_officer_headers()


@pytest.fixture
def asset_manager_headers():
    """Headers for the default ``AssetManager``."""
    return make_asset_manager_headers()


@pytest.fixture
def lender_rep_headers():
    """Headers for the default ``LenderRep``."""
    return make_lender_rep_headers()
