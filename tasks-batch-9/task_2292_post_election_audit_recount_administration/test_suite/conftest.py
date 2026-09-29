"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def elections_director_headers():
    """The state elections division director."""
    return TEST_USERS["elections_director_headers"]


@pytest.fixture
def audit_manager_headers():
    """The audit unit manager."""
    return TEST_USERS["audit_manager_headers"]


@pytest.fixture
def custody_officer_headers():
    """The secure-storage custodian."""
    return TEST_USERS["custody_officer_headers"]


@pytest.fixture
def canvassing_board_member_headers():
    """A canvassing board member."""
    return TEST_USERS["canvassing_board_member_headers"]


@pytest.fixture
def candidate_representative_headers():
    """An authorised representative of a candidate."""
    return TEST_USERS["candidate_representative_headers"]


@pytest.fixture
def tally_team_lead_headers():
    """Fallback TallyTeamLead headers; ownership-gated calls build their own."""
    return TEST_USERS["tally_team_lead_headers"]


@pytest.fixture
def observer_headers():
    """Fallback Observer headers; credential-gated calls build their own."""
    return TEST_USERS["observer_headers"]
