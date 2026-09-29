"""Shared pytest fixtures for the Therapeutic Recreation Activity Program suite."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from test_helpers.api_client import ApiClient, api_client  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    AIDE_HEADERS,
    COMPLIANCE_B_HEADERS,
    COMPLIANCE_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    THERAPIST_B_HEADERS,
    THERAPIST_HEADERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client every test drives the API through."""
    return api_client


@pytest.fixture(scope="session")
def director():
    """An ActivityDirector: census, catalogue, fleet, logistics and dispositions."""
    return DIRECTOR_HEADERS


@pytest.fixture(scope="session")
def therapist():
    """A RecreationTherapist: assessments, plans and gate overrides."""
    return THERAPIST_HEADERS


@pytest.fixture(scope="session")
def therapist_b():
    """A second RecreationTherapist identity, for segregation-of-duties checks."""
    return THERAPIST_B_HEADERS


@pytest.fixture(scope="session")
def aide():
    """An ActivityAide: running sessions and documenting participation."""
    return AIDE_HEADERS


@pytest.fixture(scope="session")
def coordinator():
    """A VolunteerCoordinator: the whole volunteer surface."""
    return COORDINATOR_HEADERS


@pytest.fixture(scope="session")
def compliance():
    """A ComplianceOfficer who compiles survey packets."""
    return COMPLIANCE_HEADERS


@pytest.fixture(scope="session")
def compliance_b():
    """A second ComplianceOfficer identity, who may attest what the first compiled."""
    return COMPLIANCE_B_HEADERS
