"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    ANALYST,
    COUNSEL_1,
    COUNSEL_2,
    FIN_1,
    FIN_2,
    FIN_3,
    IPADMIN,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def analyst_headers():
    return ANALYST


@pytest.fixture
def counsel_headers():
    return COUNSEL_1


@pytest.fixture
def counsel2_headers():
    return COUNSEL_2


@pytest.fixture
def finance_headers():
    return FIN_1


@pytest.fixture
def finance2_headers():
    return FIN_2


@pytest.fixture
def finance3_headers():
    return FIN_3


@pytest.fixture
def ipadmin_headers():
    return IPADMIN


@pytest.fixture
def licensee_headers():
    return TEST_USERS["licensee_headers"]
