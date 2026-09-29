"""Pytest fixtures exposing the test_helpers infrastructure.

The API server lifecycle is owned by the local runner, which relaunches the
process before every individual test, so each test starts against an empty
database and builds every precondition it needs through the public API.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture
def api() -> ApiClient:
    """API client bound to the running server, with a per-test HTTP session.

    The runner replaces the server process before every test, so any socket
    kept alive from the previous test now points at a dead process; the client
    therefore opens a fresh session for each test.
    """
    api_client.reset_session()
    return api_client


@pytest.fixture
def metallurgy_engineer_headers() -> dict:
    """A `MetallurgyEngineer`: powder grades and the blend-batch route."""
    return TEST_USERS["metallurgy_engineer_headers"]


@pytest.fixture
def geometry_engineer_headers() -> dict:
    """A `GeometryEngineer`: insert geometries and tool products."""
    return TEST_USERS["geometry_engineer_headers"]


@pytest.fixture
def coating_engineer_headers() -> dict:
    """A `CoatingEngineer`: coating recipes and chamber runs."""
    return TEST_USERS["coating_engineer_headers"]


@pytest.fixture
def application_engineer_headers() -> dict:
    """An `ApplicationEngineer`: dossiers, trials and orders."""
    return TEST_USERS["application_engineer_headers"]


@pytest.fixture
def quality_approver_headers() -> dict:
    """A `QualityApprover`: quality decisions, quarantine and voids."""
    return TEST_USERS["quality_approver_headers"]


@pytest.fixture
def production_planner_headers() -> dict:
    """A `ProductionPlanner`: the logical clock, wheels, customers and jobs."""
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def customer_headers() -> dict:
    """The `Customer` role's fallback identity, for calls that are not ownership-gated.

    `Customer` is entity-backed, so any ownership-gated call must instead use
    ``make_customer_headers(customer["id"])``.
    """
    return TEST_USERS["customer_headers"]
