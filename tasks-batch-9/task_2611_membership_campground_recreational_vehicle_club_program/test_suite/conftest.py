"""Shared pytest fixtures for the RV club program suite."""

import pytest

from test_helpers import (
    ADMIN,
    ADMIN_2,
    GUEST,
    OFFICER,
    api_client,
)


@pytest.fixture(scope="session")
def api():
    return api_client


@pytest.fixture
def admin():
    """A ClubAdmin operator identity."""
    return ADMIN


@pytest.fixture
def admin_2():
    """A second, distinct ClubAdmin operator, for segregation of duties."""
    return ADMIN_2


@pytest.fixture
def officer():
    """A ComplianceOfficer operator identity."""
    return OFFICER


@pytest.fixture
def guest():
    """A TransientGuest public-booking identity."""
    return GUEST
