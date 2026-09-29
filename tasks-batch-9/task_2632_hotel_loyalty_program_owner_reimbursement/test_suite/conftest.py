"""Pytest fixtures exposing the loyalty programme test infrastructure.

The runner puts the task root on ``PYTHONPATH``, so ``test_helpers`` imports
directly. Importing it also registers the error-id to HTTP-status map, which is
why every ``validate_error`` call in this suite cross-checks the status code
without naming it.

The harness restarts the API server before each test, so every test starts from
an empty database and builds its own preconditions through the programme's own
endpoints.
"""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    fixtures,
    make_admin_headers,
    make_auditor_headers,
    make_care_agent_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's business."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    """ProgramAdministrator - the role that enrols, activates and adjudicates."""
    return make_admin_headers()


@pytest.fixture
def auditor_headers() -> dict:
    """ProgramAuditor - read-only assurance."""
    return make_auditor_headers()


@pytest.fixture
def care_agent_headers() -> dict:
    """MemberCareAgent - runs the complaint queue."""
    return make_care_agent_headers()


@pytest.fixture
def hotel_owner_headers() -> dict:
    """HotelOwner headers with no particular property behind them. Tests that
    reach an ownership check must build headers from the property's own id."""
    return TEST_USERS["hotel_owner_headers"]


@pytest.fixture
def member_headers() -> dict:
    """Member headers with no particular member behind them. Tests that reach an
    ownership check must build headers from the member's own id."""
    return TEST_USERS["member_headers"]


@pytest.fixture(autouse=True)
def logical_clock_at_default(api):
    """Pin the logical clock before every test.

    Several derived figures - the elite-night calendar year, the partner's
    month-to-date volume, the annual blackout allowance - read the logical
    clock, so a test that moves the clock must not leak that instant into the
    next one. The server restarts between tests, but pinning the instant makes
    each test's date arithmetic explicit rather than incidental.
    """
    fixtures.reset_clock(api)
    yield
