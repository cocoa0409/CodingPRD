"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    ADMIN_1, ADMIN_2, ENG_1, INSP_1, INSP_2, INSP_3, INSP_9, PLANNER_1,
    TEST_USERS, ApiClient, api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle belongs to the runner."""
    return api_client


@pytest.fixture
def shop_admin_headers():
    return TEST_USERS["shop_admin_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def reliability_engineer_headers():
    return TEST_USERS["reliability_engineer_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def admin_1():
    return ADMIN_1


@pytest.fixture
def admin_2():
    return ADMIN_2


@pytest.fixture
def insp_1():
    return INSP_1


@pytest.fixture
def insp_2():
    return INSP_2


@pytest.fixture
def insp_3():
    return INSP_3


@pytest.fixture
def insp_9():
    return INSP_9


@pytest.fixture
def eng_1():
    return ENG_1


@pytest.fixture
def planner_1():
    return PLANNER_1
