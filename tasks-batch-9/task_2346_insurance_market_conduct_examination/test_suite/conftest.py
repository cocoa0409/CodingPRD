"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, make_insurer_respondent_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def market_analyst_headers():
    return TEST_USERS["market_analyst_headers"]


@pytest.fixture
def examiner_in_charge_headers():
    return TEST_USERS["examiner_in_charge_headers"]


@pytest.fixture
def examiner_in_charge_b_headers():
    return TEST_USERS["examiner_in_charge_b_headers"]


@pytest.fixture
def supervising_examiner_headers():
    return TEST_USERS["supervising_examiner_headers"]


@pytest.fixture
def supervising_examiner_b_headers():
    return TEST_USERS["supervising_examiner_b_headers"]


@pytest.fixture
def multistate_coordinator_headers():
    return TEST_USERS["multistate_coordinator_headers"]


@pytest.fixture
def insurer_respondent_headers():
    """Fallback carrier headers.

    Ownership-gated calls must instead use make_insurer_respondent_headers()
    with the acting carrier's own id.
    """
    return TEST_USERS["insurer_respondent_headers"]


@pytest.fixture
def respondent_headers_for():
    """Factory returning carrier headers for a given Insurer id."""
    return make_insurer_respondent_headers
