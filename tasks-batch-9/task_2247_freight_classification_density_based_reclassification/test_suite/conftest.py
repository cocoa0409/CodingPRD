"""Shared pytest fixtures for the LTL Freight Classification API suite.

The API client and every helper live in ``test_helpers``; this module is only the
thin pytest bridge that exposes them as fixtures.
"""

import pytest
from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The endpoint client for the contract under test."""
    return api_client


@pytest.fixture
def analyst_headers():
    """`PricingAnalyst` -- an opaque operator identifier."""
    return TEST_USERS["pricing_analyst_headers"]


@pytest.fixture
def inspector_headers():
    """`FreightInspector` -- recorded as `inspector_user_id` on a finding."""
    return TEST_USERS["freight_inspector_headers"]


@pytest.fixture
def auditor_headers():
    """`ClassificationAuditor` -- recorded as `issued_by_user_id` on a notice."""
    return TEST_USERS["classification_auditor_headers"]


@pytest.fixture
def reviewer_headers():
    """`DisputeReviewer` -- recorded as `reviewer_user_id` on a dispute."""
    return TEST_USERS["dispute_reviewer_headers"]


@pytest.fixture
def terminal_operator_headers():
    """`TerminalOperator` with a placeholder id.

    `X-User-ID` doubles as the acting terminal's `id`, so ownership-gated calls
    must build headers from a real terminal instead of using this fixture.
    """
    return TEST_USERS["terminal_operator_headers"]


@pytest.fixture
def shipper_headers():
    """`Shipper` with a placeholder id.

    `X-User-ID` doubles as the acting shipper account's `id`, so ownership-gated
    calls must build headers from a real account instead of using this fixture.
    """
    return TEST_USERS["shipper_headers"]
