"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def mill_planner_headers():
    return TEST_USERS["mill_planner_headers"]


@pytest.fixture
def extrusion_operator_headers():
    return TEST_USERS["extrusion_operator_headers"]


@pytest.fixture
def dye_house_operator_headers():
    return TEST_USERS["dye_house_operator_headers"]


@pytest.fixture
def qa_lab_technician_headers():
    return TEST_USERS["qa_lab_technician_headers"]


@pytest.fixture
def qa_lab_technician_2_headers():
    return TEST_USERS["qa_lab_technician_2_headers"]


@pytest.fixture
def certification_officer_headers():
    return TEST_USERS["certification_officer_headers"]


@pytest.fixture
def dealer_buyer_headers():
    return TEST_USERS["dealer_buyer_headers"]


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]
