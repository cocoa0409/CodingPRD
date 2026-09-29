"""Shared pytest fixtures for the User Research Program Operations suite."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client every test drives the server through."""
    return api_client


@pytest.fixture
def stakeholder_headers():
    return TEST_USERS["stakeholder"]


@pytest.fixture
def other_stakeholder_headers():
    return TEST_USERS["other_stakeholder"]


@pytest.fixture
def researcher_headers():
    return TEST_USERS["researcher"]


@pytest.fixture
def other_researcher_headers():
    return TEST_USERS["other_researcher"]


@pytest.fixture
def research_lead_headers():
    return TEST_USERS["research_lead"]


@pytest.fixture
def other_research_lead_headers():
    return TEST_USERS["other_research_lead"]


@pytest.fixture
def privacy_officer_headers():
    return TEST_USERS["privacy_officer"]


@pytest.fixture
def research_ops_admin_headers():
    return TEST_USERS["research_ops_admin"]
