"""Shared pytest fixtures for the utility relocation and betterment suite."""
import sys
from pathlib import Path

import pytest

# The helper package lives beside test_suite/ in the task root.
_TASK_ROOT = Path(__file__).resolve().parent.parent
if str(_TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(_TASK_ROOT))

from test_helpers import (  # noqa: E402
    ApiClient,
    TEST_USERS,
    api_client,
    make_utility_owner_rep_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def program_admin_headers() -> dict:
    return dict(TEST_USERS["program_admin_headers"])


@pytest.fixture
def utility_coordinator_headers() -> dict:
    return dict(TEST_USERS["utility_coordinator_headers"])


@pytest.fixture
def right_of_way_adjudicator_headers() -> dict:
    return dict(TEST_USERS["right_of_way_adjudicator_headers"])


@pytest.fixture
def second_adjudicator_headers() -> dict:
    return dict(TEST_USERS["second_adjudicator_headers"])


@pytest.fixture
def agreement_officer_headers() -> dict:
    return dict(TEST_USERS["agreement_officer_headers"])


@pytest.fixture
def external_auditor_headers() -> dict:
    return dict(TEST_USERS["external_auditor_headers"])


@pytest.fixture
def construction_engineer_headers() -> dict:
    return dict(TEST_USERS["construction_engineer_headers"])


@pytest.fixture
def owner_rep_headers():
    """Factory for the entity-backed role: pass the registered utility owner id."""
    return make_utility_owner_rep_headers
