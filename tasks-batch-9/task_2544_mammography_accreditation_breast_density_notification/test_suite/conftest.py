"""Pytest fixtures exposing the test_helpers infrastructure.

Every test runs against a freshly started server with an empty database, so all
state fixtures are function-scoped and rebuild their world from scratch through
the service's own endpoints.
"""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    ma_policy_payload,
    setup_core,
    setup_core_funded,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


# ---------------------------------------------------------------------------
# Role headers
# ---------------------------------------------------------------------------


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def qa_headers():
    return TEST_USERS["qa_headers"]


# ---------------------------------------------------------------------------
# Worlds
# ---------------------------------------------------------------------------


@pytest.fixture
def core():
    """Clock at its startup instant, a CT policy, a facility, a unit and three people."""
    return setup_core()


@pytest.fixture
def funded_core():
    """The base world with 1000000 cents of prepaid credit already deposited."""
    return setup_core_funded()


@pytest.fixture
def ma_core():
    """The same world under a `STATE_DENSE_ONLY` cost-sharing home policy."""
    return setup_core(policy_payload_fn=ma_policy_payload)
