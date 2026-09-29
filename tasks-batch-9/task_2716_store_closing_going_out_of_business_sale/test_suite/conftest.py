"""Shared pytest fixtures for the store-closing liquidation suite.

The harness relaunches the service before every individual test, so every test
below starts against an empty database and builds the state it needs from
scratch through the endpoints the PRD declares.
"""
import pytest

from test_helpers import (
    ApiClient,
    make_compliance_headers,
    make_consultant_headers,
    make_controller_headers,
    make_store_manager_headers,
    make_system_operator_headers,
)
from test_helpers import api_client as shared_api_client


@pytest.fixture
def client() -> ApiClient:
    """The API client every test drives the service through."""
    return shared_api_client


@pytest.fixture
def consultant_headers() -> dict:
    """The LiquidationConsultant who authors the agreement and the cadence."""
    return make_consultant_headers()


@pytest.fixture
def second_consultant_headers() -> dict:
    """A second LiquidationConsultant identity, for segregation-of-duties work."""
    return make_consultant_headers("lc-2")


@pytest.fixture
def controller_headers() -> dict:
    """The RetailerController who holds every money decision."""
    return make_controller_headers()


@pytest.fixture
def second_controller_headers() -> dict:
    """A second RetailerController identity."""
    return make_controller_headers("rc-2")


@pytest.fixture
def compliance_headers() -> dict:
    """The ComplianceOfficer who files licence applications and disclosures."""
    return make_compliance_headers()


@pytest.fixture
def second_compliance_headers() -> dict:
    """The second ComplianceOfficer, who decides what the first one filed."""
    return make_compliance_headers("co-2")


@pytest.fixture
def system_operator_headers() -> dict:
    """The SystemOperator who pins the logical clock."""
    return make_system_operator_headers()


@pytest.fixture
def store_manager_headers_for():
    """Build StoreManager headers for a given store row or store id."""
    def _build(store):
        store_id = store["id"] if isinstance(store, dict) else store
        return make_store_manager_headers(store_id)
    return _build
