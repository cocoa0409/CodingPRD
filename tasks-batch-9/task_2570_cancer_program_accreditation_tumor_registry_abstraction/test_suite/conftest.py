"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ACCREDITATION_COORDINATOR,
    ACCREDITATION_COORDINATOR_2,
    COC_SURVEYOR,
    COC_SURVEYOR_2,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    REGISTRY_MANAGER_2,
    STATE_REGISTRY_LIAISON,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return PLATFORM_ADMIN


@pytest.fixture
def registry_manager_headers():
    return REGISTRY_MANAGER


@pytest.fixture
def registry_manager_2_headers():
    return REGISTRY_MANAGER_2


@pytest.fixture
def accreditation_coordinator_headers():
    return ACCREDITATION_COORDINATOR


@pytest.fixture
def accreditation_coordinator_2_headers():
    return ACCREDITATION_COORDINATOR_2


@pytest.fixture
def state_registry_liaison_headers():
    return STATE_REGISTRY_LIAISON


@pytest.fixture
def coc_surveyor_headers():
    return COC_SURVEYOR


@pytest.fixture
def coc_surveyor_2_headers():
    return COC_SURVEYOR_2
