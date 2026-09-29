"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers.fixtures import (  # noqa: F401  (imported for fixture discovery)
    allocatable_plant,
    canonical_clock,
    certified_platform,
    draft_family,
    family_with_platform,
    probation_supplier,
    production_ready_plant,
    released_model,
    released_order_plant,
    supersession_pair,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plant_admin_headers():
    return TEST_USERS["plant_admin_headers"]


@pytest.fixture
def certification_engineer_headers():
    return TEST_USERS["certification_engineer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def channel_partner_headers():
    return TEST_USERS["channel_partner_headers"]


@pytest.fixture
def second_certification_engineer_headers():
    return TEST_USERS["second_certification_engineer_headers"]


@pytest.fixture
def second_compliance_officer_headers():
    return TEST_USERS["second_compliance_officer_headers"]


@pytest.fixture
def second_quality_engineer_headers():
    return TEST_USERS["second_quality_engineer_headers"]


@pytest.fixture
def second_channel_partner_headers():
    return TEST_USERS["second_channel_partner_headers"]
