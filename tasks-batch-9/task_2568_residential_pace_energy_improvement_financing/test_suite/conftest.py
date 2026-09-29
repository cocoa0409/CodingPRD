"""Shared pytest wiring for the residential PACE financing suite.

The harness owns the server's lifecycle and restarts the application before
every single test, so each test starts against an empty database and no test
needs to clean up after itself.  All this module does is hand out a client and
a few pre-built scenarios.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import PaceApiClient  # noqa: E402
from test_helpers import fixtures  # noqa: E402


@pytest.fixture
def client():
    """A client pointed at the harness-managed server."""
    return PaceApiClient()


@pytest.fixture
def world(client):
    """Clock, catalog, enrolled contractor and one parcel with a senior lien."""
    return fixtures.seed_program(client)


@pytest.fixture
def draft(client, world):
    """The canonical two-measure DRAFT application."""
    return fixtures.draft_with_two_measures(client, world)


@pytest.fixture
def submitted(client, draft):
    """The canonical application, UNDER_REVIEW with every submit figure priced."""
    return fixtures.submitted_application(client, draft)


@pytest.fixture
def approved(client, submitted):
    """APPROVED, with consent recorded and the underwriter/approver split kept."""
    fixtures.underwritten_application(client, submitted)
    fixtures.consented_application(client, submitted)
    return fixtures.approved_application(client, submitted)


@pytest.fixture
def signed(client, approved):
    """A SIGNED agreement whose rescission window closes on 2026-08-18."""
    fixtures.issued_agreement(client, approved)
    return fixtures.signed_agreement(client, approved)


@pytest.fixture
def funded(client, world):
    """Origination through release: FUNDED, with cash in the contractor's ledger."""
    return fixtures.funded_project(client, world)


@pytest.fixture
def assessed(client, funded):
    """The funded deal carried onto the 2027 tax roll as an ASSESSED lien."""
    return fixtures.assessed_project(client, funded)
