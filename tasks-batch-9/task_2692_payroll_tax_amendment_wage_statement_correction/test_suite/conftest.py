"""Shared pytest fixtures.

The server restarts with an empty database before every test, so nothing is
shared between tests beyond the client itself: every scenario is rebuilt from
scratch through declared endpoints.
"""

import pytest

from test_helpers.api_client import ApiClient
from test_helpers import fixtures as fx


@pytest.fixture
def api() -> ApiClient:
    return ApiClient()


@pytest.fixture
def federal_case(api):
    """Federal 2025 Q1 scenario with all three discrepancies categorised."""
    return fx.federal_categorized(api)


@pytest.fixture
def prepared_amendment(api):
    """The same scenario carried through to a PREPARED amendment."""
    return fx.federal_prepared_amendment(api)


@pytest.fixture
def signed_amendment(api):
    return fx.federal_signed_amendment(api)


@pytest.fixture
def accepted_amendment(api):
    """Acceptance has fired, so the case sits in REMEDIATION_PENDING."""
    return fx.federal_accepted_amendment(api)


@pytest.fixture
def jurisdiction_case(api):
    """A single categorised JURISDICTION_ASSIGNMENT discrepancy of 400000 cents."""
    return fx.jurisdiction_scenario(api)


@pytest.fixture
def issued_statement(api):
    """A mailed corrected wage statement already in ISSUED."""
    return fx.jurisdiction_issued_statement(api)
