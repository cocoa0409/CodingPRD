"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def permit_reviewer_headers():
    return TEST_USERS["permit_reviewer_headers"]


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def public_participant_headers():
    return TEST_USERS["public_participant_headers"]


@pytest.fixture
def bond_specialist_headers():
    """The specialist identity that accepts financial security."""
    return TEST_USERS["bond_specialist_headers"]


@pytest.fixture
def bond_specialist_decider_headers():
    """A second, distinct specialist identity that decides release applications."""
    return TEST_USERS["bond_specialist_decider_headers"]
