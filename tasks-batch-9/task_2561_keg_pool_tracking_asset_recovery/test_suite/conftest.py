"""Shared pytest fixtures for the keg pool asset recovery suite.

The harness relaunches the API server before every individual test, so each
test begins against an empty database.  Nothing is shared between tests except
the stateless HTTP client and the per-role request headers.
"""

import pytest

from test_helpers import api_client
from test_helpers.test_users import (
    ANALYST_USER_ID,
    POOL_OPERATOR_USER_ID,
    SECOND_ANALYST_USER_ID,
    SECOND_POOL_OPERATOR_USER_ID,
    SECOND_TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    THIRD_ANALYST_USER_ID,
)


@pytest.fixture(scope="session")
def api():
    """The HTTP client, one method per endpoint the PRD declares."""
    return api_client


@pytest.fixture
def operator():
    """Headers for the pool operations desk."""
    return TEST_USERS["pool_operator_headers"]


@pytest.fixture
def second_operator():
    """A second, differently identified pool operator."""
    return TEST_USERS["second_pool_operator_headers"]


@pytest.fixture
def technician():
    """Headers for the wash-line and pressure-test crew."""
    return TEST_USERS["technician_headers"]


@pytest.fixture
def second_technician():
    """A second technician, for the release segregation rule."""
    return TEST_USERS["second_technician_headers"]


@pytest.fixture
def analyst():
    """Headers for the loss, theft and recovery desk."""
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def second_analyst():
    """A second analyst, for the resolution segregation rule."""
    return TEST_USERS["second_analyst_headers"]


@pytest.fixture
def third_analyst():
    """A third analyst identifier."""
    return TEST_USERS["third_analyst_headers"]


@pytest.fixture
def unknown_brewer():
    """Brewer headers whose identifier names no stored brewer row."""
    return TEST_USERS["unknown_brewer_headers"]


@pytest.fixture
def unknown_distributor():
    """Distributor headers whose identifier names no stored distributor row."""
    return TEST_USERS["unknown_distributor_headers"]


@pytest.fixture
def operator_user_id():
    return POOL_OPERATOR_USER_ID


@pytest.fixture
def second_operator_user_id():
    return SECOND_POOL_OPERATOR_USER_ID


@pytest.fixture
def technician_user_id():
    return TECHNICIAN_USER_ID


@pytest.fixture
def second_technician_user_id():
    return SECOND_TECHNICIAN_USER_ID


@pytest.fixture
def analyst_user_id():
    return ANALYST_USER_ID


@pytest.fixture
def second_analyst_user_id():
    return SECOND_ANALYST_USER_ID


@pytest.fixture
def third_analyst_user_id():
    return THIRD_ANALYST_USER_ID
