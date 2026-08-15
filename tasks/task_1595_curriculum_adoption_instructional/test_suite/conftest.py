"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def district_admin_headers():
    return TEST_USERS["district_admin_headers"]


@pytest.fixture
def curriculum_director_headers():
    return TEST_USERS["curriculum_director_headers"]


@pytest.fixture
def instructional_specialist_headers():
    return TEST_USERS["instructional_specialist_headers"]


@pytest.fixture
def board_secretary_headers():
    return TEST_USERS["board_secretary_headers"]


@pytest.fixture
def procurement_officer_headers():
    return TEST_USERS["procurement_officer_headers"]


@pytest.fixture
def warehouse_manager_headers():
    return TEST_USERS["warehouse_manager_headers"]


@pytest.fixture
def teacher_headers():
    return TEST_USERS["teacher_headers"]


@pytest.fixture
def committee_member_headers():
    return TEST_USERS["committee_member_headers"]


@pytest.fixture
def community_member_headers():
    return TEST_USERS["community_member_headers"]
