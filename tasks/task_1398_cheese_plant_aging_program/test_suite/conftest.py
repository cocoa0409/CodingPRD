"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def milk_receiver_headers():
    return TEST_USERS["milk_receiver_headers"]


@pytest.fixture
def make_planner_headers():
    return TEST_USERS["make_planner_headers"]


@pytest.fixture
def cheesemaker_headers():
    return TEST_USERS["cheesemaker_headers"]


@pytest.fixture
def qa_grader_headers():
    return TEST_USERS["qa_grader_headers"]


@pytest.fixture
def aging_room_operator_headers():
    return TEST_USERS["aging_room_operator_headers"]


@pytest.fixture
def sales_planner_headers():
    return TEST_USERS["sales_planner_headers"]


@pytest.fixture
def cut_wrap_operator_headers():
    return TEST_USERS["cut_wrap_operator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]
