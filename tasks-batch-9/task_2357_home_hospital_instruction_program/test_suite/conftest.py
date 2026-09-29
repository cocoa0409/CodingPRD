"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def program_administrator_headers():
    return TEST_USERS["program_administrator_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def second_case_manager_headers():
    return TEST_USERS["second_case_manager_headers"]


@pytest.fixture
def nurse_reviewer_headers():
    return TEST_USERS["nurse_reviewer_headers"]


@pytest.fixture
def homebound_teacher_headers():
    return TEST_USERS["homebound_teacher_headers"]


@pytest.fixture
def classroom_teacher_headers():
    return TEST_USERS["classroom_teacher_headers"]
