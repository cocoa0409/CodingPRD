"""Pytest wiring for the water treatment equipment manufacturing API suite."""

import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_application_engineer_headers,
    make_commissioning_engineer_headers,
    make_contracts_administrator_headers,
    make_design_reviewer_headers,
    make_engineer_of_record_headers,
    make_fabrication_manager_headers,
    make_owner_representative_headers,
    make_platform_admin_headers,
    make_quality_engineer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared HTTP client, pointed at the running instance under test."""
    return api_client


@pytest.fixture
def admin_headers():
    return make_platform_admin_headers()


@pytest.fixture
def engineer_headers():
    return make_application_engineer_headers()


@pytest.fixture
def reviewer_headers():
    return make_design_reviewer_headers()


@pytest.fixture
def fabrication_headers():
    return make_fabrication_manager_headers()


@pytest.fixture
def quality_headers():
    return make_quality_engineer_headers()


@pytest.fixture
def commissioning_headers():
    return make_commissioning_engineer_headers()


@pytest.fixture
def engineer_of_record_headers():
    return make_engineer_of_record_headers()


@pytest.fixture
def owner_headers():
    return make_owner_representative_headers()


@pytest.fixture
def contracts_headers():
    return make_contracts_administrator_headers()
