"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_inspector_headers,
    make_plant_dispatcher_headers,
    make_set_crew_lead_headers,
    make_transport_manager_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def permit_desk_headers():
    return TEST_USERS["permit_desk_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def installation_inspector_headers():
    return TEST_USERS["installation_inspector_headers"]


@pytest.fixture
def plant_dispatcher_headers():
    """Fallback PlantDispatcher headers — never use for ownership-gated calls."""
    return TEST_USERS["plant_dispatcher_headers"]


@pytest.fixture
def transport_manager_headers():
    """Fallback TransportManager headers — never use for ownership-gated calls."""
    return TEST_USERS["transport_manager_headers"]


@pytest.fixture
def set_crew_lead_headers():
    """Fallback SetCrewLead headers — never use for ownership-gated calls."""
    return TEST_USERS["set_crew_lead_headers"]


@pytest.fixture
def dispatcher_for():
    """Build PlantDispatcher headers bound to a real Plant id."""
    return make_plant_dispatcher_headers


@pytest.fixture
def carrier_for():
    """Build TransportManager headers bound to a real Hauler id."""
    return make_transport_manager_headers


@pytest.fixture
def crew_lead_for():
    """Build SetCrewLead headers bound to a real SetCrew id."""
    return make_set_crew_lead_headers


@pytest.fixture
def inspector_for():
    """Build InstallationInspector headers for a named operator identifier."""
    return make_inspector_headers
