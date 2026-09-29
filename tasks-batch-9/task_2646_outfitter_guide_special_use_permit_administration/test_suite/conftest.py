"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_outfitter_representative_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped client. Server lifecycle is the runner's responsibility."""
    return api_client


@pytest.fixture
def admin_headers():
    """A ProgramAdministrator: the only role that may move the logical clock,
    open a use area or run the nightly sweep."""
    return TEST_USERS["program_administrator_headers"]


@pytest.fixture
def specialist_headers():
    """A PermitSpecialist: screens applications, closes solicitations and accepts
    use reports."""
    return TEST_USERS["permit_specialist_headers"]


@pytest.fixture
def specialist_alt_headers():
    """A second PermitSpecialist identity, for duty-separation scenarios."""
    return TEST_USERS["permit_specialist_alt_headers"]


@pytest.fixture
def officer_headers():
    """An AuthorizedOfficer: issues permits, evaluates performance and takes
    enforcement action."""
    return TEST_USERS["authorized_officer_headers"]


@pytest.fixture
def officer_alt_headers():
    """A second AuthorizedOfficer identity, for duty-separation scenarios."""
    return TEST_USERS["authorized_officer_alt_headers"]


@pytest.fixture
def unowned_holder_headers():
    """An OutfitterRepresentative identity that owns nothing. Safe only for
    calls that never reach an ownership check."""
    return TEST_USERS["outfitter_representative_headers"]


@pytest.fixture
def holder_headers_for():
    """Factory returning the headers of one specific outfitter's representative."""
    return make_outfitter_representative_headers
