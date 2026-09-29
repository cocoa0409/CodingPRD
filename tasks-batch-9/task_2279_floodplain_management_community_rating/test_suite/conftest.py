"""Pytest fixtures exposing the domain test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def coordinator_headers():
    """StateNfipCoordinator — an opaque operator identifier."""
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def coordinator_alt_headers():
    return TEST_USERS["coordinator_alt_headers"]


@pytest.fixture
def administrator_headers():
    """FloodplainAdministrator — an opaque operator identifier."""
    return TEST_USERS["administrator_headers"]


@pytest.fixture
def administrator_alt_headers():
    return TEST_USERS["administrator_alt_headers"]


@pytest.fixture
def appeals_board_headers():
    """AppealsBoardMember — an opaque operator identifier."""
    return TEST_USERS["appeals_board_headers"]


@pytest.fixture
def appeals_board_alt_headers():
    return TEST_USERS["appeals_board_alt_headers"]


@pytest.fixture
def property_owner_headers():
    """PropertyOwner fallback identity: use make_property_owner_headers(property_id)
    for any call that is ownership-gated."""
    return TEST_USERS["property_owner_headers"]
