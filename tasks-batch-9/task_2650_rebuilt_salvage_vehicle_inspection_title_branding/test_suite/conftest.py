"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_inspector_headers,
    make_rebuilder_headers,
)
from test_helpers.fixtures import reset_clock


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture(autouse=True)
def logical_clock_at_epoch():
    """Every test starts with the logical clock at its documented initial reading.

    A ProgramAdmin may move the clock forward or backward, so a test that drove
    time forward leaves nothing behind for the next one.
    """
    reset_clock()
    yield


# --- one fixture per role -------------------------------------------------
@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def second_program_admin_headers():
    return TEST_USERS["second_program_admin_headers"]


@pytest.fixture
def state_title_clerk_headers():
    return TEST_USERS["state_title_clerk_headers"]


@pytest.fixture
def second_state_title_clerk_headers():
    return TEST_USERS["second_state_title_clerk_headers"]


@pytest.fixture
def insurer_adjuster_headers():
    return TEST_USERS["insurer_adjuster_headers"]


@pytest.fixture
def hearing_officer_headers():
    return TEST_USERS["hearing_officer_headers"]


@pytest.fixture
def second_hearing_officer_headers():
    return TEST_USERS["second_hearing_officer_headers"]


@pytest.fixture
def fraud_investigator_headers():
    return TEST_USERS["fraud_investigator_headers"]


@pytest.fixture
def second_fraud_investigator_headers():
    return TEST_USERS["second_fraud_investigator_headers"]


@pytest.fixture
def rebuilder_headers():
    """Rebuilder identity with no bound entity.

    Only safe for calls that never reach an ownership check; anything that acts on
    a specific application must use `make_rebuilder_headers(rebuilder_id)`.
    """
    return TEST_USERS["rebuilder_headers"]


@pytest.fixture
def inspector_headers():
    """Inspector identity with no bound entity.

    Only safe for calls that never reach an assignment check; anything that acts on
    a specific attempt must use `make_inspector_headers(inspector_id)`.
    """
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def rebuilder_headers_for():
    """Factory returning Rebuilder identity headers bound to a rebuilder id."""
    return make_rebuilder_headers


@pytest.fixture
def inspector_headers_for():
    """Factory returning Inspector identity headers bound to an inspector id."""
    return make_inspector_headers
