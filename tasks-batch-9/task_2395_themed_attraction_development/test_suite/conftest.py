"""Shared pytest fixtures for the themed attraction development suite."""
import pytest

from test_helpers import NO_IDENTITY_HEADERS, TEST_USERS, api_client


@pytest.fixture
def api():
    """The API client, pointed at the running service."""
    return api_client


@pytest.fixture
def owner_rep_headers():
    """An OwnerRep: the paying owner's representative."""
    return TEST_USERS["owner_rep_headers"]


@pytest.fixture
def second_owner_rep_headers():
    """A second OwnerRep operator identifier, for segregation of duties."""
    return TEST_USERS["second_owner_rep_headers"]


@pytest.fixture
def creative_director_headers():
    """A CreativeDirector: the designer of record."""
    return TEST_USERS["creative_director_headers"]


@pytest.fixture
def ride_engineer_headers():
    """A RideEngineer."""
    return TEST_USERS["ride_engineer_headers"]


@pytest.fixture
def show_programmer_headers():
    """A ShowProgrammer."""
    return TEST_USERS["show_programmer_headers"]


@pytest.fixture
def third_party_reviewer_headers():
    """An independent ThirdPartyReviewer."""
    return TEST_USERS["third_party_reviewer_headers"]


@pytest.fixture
def contractor_pm_headers():
    """A ContractorPM: the installation contractor."""
    return TEST_USERS["contractor_pm_headers"]


@pytest.fixture
def program_admin_headers():
    """A ProgramAdmin, who holds the logical-clock capability."""
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def no_identity_headers():
    """Headers carrying neither X-User-ID nor X-User-Role."""
    return NO_IDENTITY_HEADERS
