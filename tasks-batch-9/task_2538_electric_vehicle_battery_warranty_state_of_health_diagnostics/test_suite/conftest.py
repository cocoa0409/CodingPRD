"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    """ProgramAdmin — programs, packs, campaigns, receipts and the clock."""
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def second_admin_headers():
    """A second ProgramAdmin identity, for two-operator workflows."""
    return TEST_USERS["program_admin_2_headers"]


@pytest.fixture
def adjudicator_headers():
    """WarrantyAdjudicator — claim decisions, information requests, closures."""
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def second_adjudicator_headers():
    """A second WarrantyAdjudicator identity, for the segregation-of-duties rule."""
    return TEST_USERS["adjudicator_2_headers"]


@pytest.fixture
def gateway_headers():
    """TelematicsGateway — snapshot ingestion and thermal event reporting."""
    return TEST_USERS["gateway_headers"]


@pytest.fixture
def lab_headers():
    """IndependentLab — capacity dispute lab results."""
    return TEST_USERS["lab_headers"]


@pytest.fixture
def liaison_headers():
    """RegulatoryLiaison — regulatory notification filing."""
    return TEST_USERS["liaison_headers"]


@pytest.fixture
def technician_headers():
    """Shared ServiceTechnician constant.

    Technician identity is entity backed, so this is safe only for calls that
    never reach an identity comparison. Anything identity-gated must use
    make_technician_headers(technician_id).
    """
    return TEST_USERS["technician_headers"]


@pytest.fixture
def owner_headers():
    """Shared VehicleOwner constant.

    Owner identity is the acting Vehicle's `id`, so this is safe only for calls
    that never reach an ownership comparison. Anything ownership-gated must use
    make_owner_headers(vehicle_id).
    """
    return TEST_USERS["owner_headers"]
