"""Shared pytest wiring for the wireless site acquisition and zoning suite."""

from typing import Dict

import pytest

from test_helpers.api_client import ApiClient
from test_helpers.fixtures import (  # noqa: F401 - re-exported as pytest fixtures
    build_ready,
    clock,
    engaged,
    leased,
    qualified,
    reference_data,
    selected,
)
from test_helpers.test_users import (
    make_construction_manager_headers,
    make_environmental_reviewer_headers,
    make_program_director_headers,
    make_rf_engineer_headers,
    make_site_acquisition_agent_headers,
    make_structural_engineer_headers,
    make_zoning_planner_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """One client bound to the base URL the harness publishes."""
    return ApiClient()


@pytest.fixture()
def rf_engineer() -> Dict[str, str]:
    return make_rf_engineer_headers()


@pytest.fixture()
def agent() -> Dict[str, str]:
    """The `SiteAcquisitionAgent` who owns every candidate the suite creates."""
    return make_site_acquisition_agent_headers()


@pytest.fixture()
def zoning_planner() -> Dict[str, str]:
    return make_zoning_planner_headers()


@pytest.fixture()
def structural_engineer() -> Dict[str, str]:
    return make_structural_engineer_headers()


@pytest.fixture()
def environmental_reviewer() -> Dict[str, str]:
    return make_environmental_reviewer_headers()


@pytest.fixture()
def construction_manager() -> Dict[str, str]:
    return make_construction_manager_headers()


@pytest.fixture()
def program_director() -> Dict[str, str]:
    return make_program_director_headers()
