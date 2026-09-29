"""Pytest bridge to the shared helper package.

The runner owns the server lifecycle, so every test starts against an empty
database and builds whatever state it needs through documented endpoints.
"""
import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The shared relicensing API client."""
    return api_client


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def licensee_headers():
    return TEST_USERS["licensee_headers"]


@pytest.fixture
def licensee_b_headers():
    return TEST_USERS["licensee_b_headers"]


@pytest.fixture
def licensee_reporter_headers():
    return TEST_USERS["licensee_reporter_headers"]


@pytest.fixture
def licensee_certifier_headers():
    return TEST_USERS["licensee_certifier_headers"]


@pytest.fixture
def state_certifier_headers():
    return TEST_USERS["state_certifier_headers"]


@pytest.fixture
def agency_reviewer_headers():
    return TEST_USERS["agency_reviewer_headers"]


@pytest.fixture
def stakeholder_headers():
    return TEST_USERS["stakeholder_headers"]
