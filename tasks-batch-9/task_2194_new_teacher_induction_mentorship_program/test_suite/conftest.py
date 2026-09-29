"""Shared pytest configuration for the induction mentorship compliance suite.

The API server is restarted before every individual test, so no fixture here
attempts to clean up after itself: every test builds the district state it needs
from an empty database through the documented endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers error/status map)
from test_helpers.api_client import InductionApiClient  # noqa: E402
from test_helpers.fixtures import build_program, create_cohort, create_site  # noqa: E402


@pytest.fixture
def api() -> InductionApiClient:
    """A client pointed at the API under test."""
    return InductionApiClient()


@pytest.fixture
def site(api: InductionApiClient) -> dict:
    """A single open district site."""
    return create_site(api)


@pytest.fixture
def cohort(api: InductionApiClient) -> dict:
    """A single forming induction cohort."""
    return create_cohort(api)


@pytest.fixture
def program(api: InductionApiClient) -> dict:
    """Site, cohort, certified mentor, enrolled novice and an ACTIVE match."""
    return build_program(api)


@pytest.fixture
def proposed_program(api: InductionApiClient) -> dict:
    """The same relationship left in PROPOSED rather than activated."""
    return build_program(api, activate=False)


@pytest.fixture
def program_factory(api: InductionApiClient):
    """A builder for variant programs (caps, subjects, activation)."""

    def _build(**kwargs):
        return build_program(api, **kwargs)

    return _build
