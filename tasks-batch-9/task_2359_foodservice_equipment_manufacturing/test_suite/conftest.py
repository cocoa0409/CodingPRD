"""Shared pytest fixtures for the Foodservice Equipment Manufacturing suite."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def compliance_engineer() -> dict:
    return TEST_USERS["compliance_engineer"]


@pytest.fixture
def listing_reviewer() -> dict:
    return TEST_USERS["listing_reviewer"]


@pytest.fixture
def application_engineer() -> dict:
    return TEST_USERS["application_engineer"]


@pytest.fixture
def engineering_approver() -> dict:
    return TEST_USERS["engineering_approver"]


@pytest.fixture
def production_planner() -> dict:
    return TEST_USERS["production_planner"]


@pytest.fixture
def connected_ops_engineer() -> dict:
    return TEST_USERS["connected_ops_engineer"]


@pytest.fixture
def channel_manager() -> dict:
    return TEST_USERS["channel_manager"]


@pytest.fixture
def warranty_adjudicator() -> dict:
    return TEST_USERS["warranty_adjudicator"]


@pytest.fixture
def platform_admin() -> dict:
    return TEST_USERS["platform_admin"]
