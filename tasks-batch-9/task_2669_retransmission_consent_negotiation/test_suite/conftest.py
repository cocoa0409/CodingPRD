"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def carriage_admin_headers():
    return TEST_USERS["carriage_admin_headers"]


@pytest.fixture
def group_counsel_headers():
    return TEST_USERS["group_counsel_headers"]


@pytest.fixture
def second_group_counsel_headers():
    return TEST_USERS["second_group_counsel_headers"]


@pytest.fixture
def network_representative_headers():
    return TEST_USERS["network_representative_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def station_group_negotiator_headers():
    return TEST_USERS["station_group_negotiator_headers"]


@pytest.fixture
def distributor_rep_headers():
    return TEST_USERS["distributor_rep_headers"]
