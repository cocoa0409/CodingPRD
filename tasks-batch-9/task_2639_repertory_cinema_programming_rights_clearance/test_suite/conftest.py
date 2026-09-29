"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client, make_member_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def programmer_headers():
    """Programmer: scheduling, engagements, catalogue."""
    return TEST_USERS["programmer_headers"]


@pytest.fixture
def rights_manager_headers():
    """RightsManager who lodges licences."""
    return TEST_USERS["rights_manager_headers"]


@pytest.fixture
def rights_manager_two_headers():
    """A second RightsManager, for the separation-of-duties path."""
    return TEST_USERS["rights_manager_two_headers"]


@pytest.fixture
def technical_manager_headers():
    """TechnicalManager: print traffic, keys, booth verification."""
    return TEST_USERS["technical_manager_headers"]


@pytest.fixture
def box_office_headers():
    """BoxOfficeManager: sales windows, orders, refunds, memberships."""
    return TEST_USERS["box_office_headers"]


@pytest.fixture
def executive_director_headers():
    """ExecutiveDirector: confirmation, closure, settlement resolution."""
    return TEST_USERS["executive_director_headers"]


@pytest.fixture
def executive_director_two_headers():
    """A second ExecutiveDirector, for the settlement separation-of-duties path."""
    return TEST_USERS["executive_director_two_headers"]


@pytest.fixture
def member_headers():
    """Member headers not bound to any particular member row."""
    return TEST_USERS["member_headers"]


@pytest.fixture
def anonymous_headers():
    """A walk-up caller: no X-User-Role header at all."""
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def member_headers_for():
    """Build headers whose X-User-ID is a specific member's id."""
    return make_member_headers
