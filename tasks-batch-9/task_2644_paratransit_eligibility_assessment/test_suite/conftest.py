"""Shared pytest fixtures for the paratransit eligibility compliance suite."""
import pytest

from test_helpers import ApiClient
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    EVALUATOR_HEADERS,
    REVIEWER_HEADERS,
    SPECIALIST_HEADERS,
    TRAINER_HEADERS,
)


@pytest.fixture
def api():
    """A fresh client per test, since the server is restarted between tests."""
    return ApiClient()


@pytest.fixture
def clerk():
    return CLERK_HEADERS


@pytest.fixture
def evaluator():
    return EVALUATOR_HEADERS


@pytest.fixture
def specialist():
    return SPECIALIST_HEADERS


@pytest.fixture
def reviewer():
    return REVIEWER_HEADERS


@pytest.fixture
def officer():
    return CONDUCT_OFFICER_HEADERS


@pytest.fixture
def trainer():
    return TRAINER_HEADERS


@pytest.fixture
def admin():
    return ADMIN_HEADERS
