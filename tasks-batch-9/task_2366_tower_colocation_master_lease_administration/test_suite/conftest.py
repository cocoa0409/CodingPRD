"""Shared pytest fixtures for the Tower Colocation Master Lease API suite.

The runner starts a fresh server with an empty database before every test and
injects ``API_BASE_URL``, so nothing here needs to manage process lifecycle or
clean up state; each test builds exactly the world it needs.
"""

import pytest

from test_helpers import api_errors  # noqa: F401  (registers the PRD §5 status map)
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    ENGINEER_HEADERS,
    OTHER_AUDITOR_HEADERS,
    OTHER_ENGINEER_HEADERS,
)


@pytest.fixture()
def api() -> ApiClient:
    """The API under test, aimed at the base URL the runner provides."""
    return ApiClient()


@pytest.fixture()
def admin_headers():
    """Headers for the ``PortfolioAdmin`` operator role."""
    return ADMIN_HEADERS


@pytest.fixture()
def engineer_headers():
    """Headers for the ``StructuralEngineer`` operator role."""
    return ENGINEER_HEADERS


@pytest.fixture()
def other_engineer_headers():
    """A second ``StructuralEngineer`` identifier, for segregation-of-duties work."""
    return OTHER_ENGINEER_HEADERS


@pytest.fixture()
def auditor_headers():
    """Headers for the ``ComplianceAuditor`` operator role."""
    return AUDITOR_HEADERS


@pytest.fixture()
def other_auditor_headers():
    """A second ``ComplianceAuditor`` identifier."""
    return OTHER_AUDITOR_HEADERS
