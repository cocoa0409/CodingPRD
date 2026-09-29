"""Shared pytest fixtures for the Elite Field Purse Admin API suite.

The API server is relaunched before every individual test, so each test starts
against an empty database with the logical clock at the fixed instant
`2026-08-01T00:00:00Z` described in PRD §2.4. Every precondition a test needs is
therefore built from scratch through the endpoints of PRD §4.
"""
import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The HTTP client for the API under test."""
    return api_client


@pytest.fixture
def elites_director_headers():
    """`ElitesDirector` — configures editions, recruits and runs elite services."""
    return TEST_USERS["elites_director_headers"]


@pytest.fixture
def technical_official_headers():
    """`TechnicalOfficial` — verifies times, opens the race, certifies results."""
    return TEST_USERS["technical_official_headers"]


@pytest.fixture
def anti_doping_liaison_headers():
    """`AntiDopingLiaison` — schedules tests and collects samples."""
    return TEST_USERS["anti_doping_liaison_headers"]


@pytest.fixture
def sanctioning_body_headers():
    """`SanctioningBody` — returns laboratory outcomes and closes record claims."""
    return TEST_USERS["sanctioning_body_headers"]


@pytest.fixture
def finance_officer_headers():
    """`FinanceOfficer` — the operator that approves an award."""
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def finance_payer_headers():
    """A second `FinanceOfficer` operator, distinct from the approver."""
    return TEST_USERS["finance_payer_headers"]


@pytest.fixture
def finance_second_approver_headers():
    """A third `FinanceOfficer` operator identifier."""
    return TEST_USERS["finance_second_approver_headers"]


@pytest.fixture
def finance_second_payer_headers():
    """A fourth `FinanceOfficer` operator identifier."""
    return TEST_USERS["finance_second_payer_headers"]


@pytest.fixture
def athlete_agent_headers():
    """`AthleteAgent` headers not bound to any registered agent.

    PRD §2.1 ties this role to a persisted `RepAgent`, so ownership-gated calls
    must instead use `make_athlete_agent_headers(agent["id"])`.
    """
    return TEST_USERS["athlete_agent_headers"]
