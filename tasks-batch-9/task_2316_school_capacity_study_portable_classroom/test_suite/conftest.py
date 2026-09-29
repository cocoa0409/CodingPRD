"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ASSET_HEADERS,
    CERTIFIER_HEADERS,
    OFFICIAL_HEADERS,
    PERMIT_HEADERS,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
)
from test_helpers.fixtures import (  # noqa: F401  (re-exported as pytest fixtures)
    api,
    campus,
    draft_request,
    installed_request,
    permitted_request,
    request_context,
    scheduled_request,
)


@pytest.fixture
def admin_headers():
    return ADMIN_HEADERS


@pytest.fixture
def planner_headers():
    return PLANNER_HEADERS


@pytest.fixture
def certifier_headers():
    return CERTIFIER_HEADERS


@pytest.fixture
def permit_coordinator_headers():
    return PERMIT_HEADERS


@pytest.fixture
def building_official_headers():
    return OFFICIAL_HEADERS


@pytest.fixture
def scheduler_headers():
    return SCHEDULER_HEADERS


@pytest.fixture
def asset_manager_headers():
    return ASSET_HEADERS
