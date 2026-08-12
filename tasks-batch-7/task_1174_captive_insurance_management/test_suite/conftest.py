"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def captive_manager_headers():
    return TEST_USERS["captive_manager_headers"]


@pytest.fixture
def domicile_regulator_headers():
    return TEST_USERS["domicile_regulator_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def actuary_headers():
    return TEST_USERS["actuary_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def board_director_headers():
    return TEST_USERS["board_director_headers"]


@pytest.fixture
def tax_advisor_headers():
    return TEST_USERS["tax_advisor_headers"]
