"""Shared pytest fixtures for the elevator modernization delivery suite."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_helpers import (  # noqa: E402
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api():
    """The HTTP client for the API under test."""
    return api_client


@pytest.fixture
def project_manager_headers():
    return dict(TEST_USERS["project_manager_headers"])


@pytest.fixture
def survey_technician_headers():
    return dict(TEST_USERS["survey_technician_headers"])


@pytest.fixture
def service_manager_headers():
    return dict(TEST_USERS["service_manager_headers"])


@pytest.fixture
def system_operator_headers():
    return dict(TEST_USERS["system_operator_headers"])


@pytest.fixture
def building_representative_headers():
    """A building representative bound to no project — for scope-mismatch checks."""
    return dict(TEST_USERS["building_representative_headers"])


@pytest.fixture
def ahj_inspector_headers():
    """An inspector bound to no jurisdiction — for scope-mismatch checks."""
    return dict(TEST_USERS["ahj_inspector_headers"])
