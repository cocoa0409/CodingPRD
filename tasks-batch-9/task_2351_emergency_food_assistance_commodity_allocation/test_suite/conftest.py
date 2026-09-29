"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_agency_coordinator_headers,
    make_compliance_reviewer_headers,
    make_second_compliance_reviewer_headers,
    make_second_state_admin_headers,
    make_state_admin_headers,
    make_warehouse_operator_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """The state distributing agency operator (`StateAdmin`)."""
    return make_state_admin_headers()


@pytest.fixture
def second_admin_headers():
    """A different `StateAdmin`, for the recall closure segregation check."""
    return make_second_state_admin_headers()


@pytest.fixture
def reviewer_headers():
    """The first `ComplianceReviewer`."""
    return make_compliance_reviewer_headers()


@pytest.fixture
def second_reviewer_headers():
    """A different `ComplianceReviewer`, for four-eyes order review."""
    return make_second_compliance_reviewer_headers()


@pytest.fixture
def coordinator_headers():
    """Builder for an `AgencyCoordinator`, whose X-User-ID is the Agency id."""
    return make_agency_coordinator_headers


@pytest.fixture
def operator_headers():
    """Builder for a `StateWarehouseOperator`, whose X-User-ID is the Warehouse id."""
    return make_warehouse_operator_headers
