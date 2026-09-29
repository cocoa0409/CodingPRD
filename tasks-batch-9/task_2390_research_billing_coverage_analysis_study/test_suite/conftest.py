"""Shared pytest fixtures for the Research Billing Coverage Analysis suite.

The server is restarted with an empty database before every individual test, so
each test builds every precondition it needs from scratch through the API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import TEST_USERS, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The API client, pointed at the harness-provided base URL."""
    return api_client


@pytest.fixture
def manager_headers():
    """A ResearchBillingManager: budgets, invoices, amendments and operations."""
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager_two_headers():
    """A second ResearchBillingManager — the budget-execution counterparty."""
    return TEST_USERS["manager_two_headers"]


@pytest.fixture
def analyst_headers():
    """A CoverageAnalyst: coverage grids and calendar generations."""
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst_two_headers():
    """A second CoverageAnalyst."""
    return TEST_USERS["analyst_two_headers"]


@pytest.fixture
def reviewer_headers():
    """A ComplianceReviewer: determinations, approvals, publication, charge review."""
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def reviewer_two_headers():
    """A second ComplianceReviewer."""
    return TEST_USERS["reviewer_two_headers"]


@pytest.fixture
def coordinator_headers():
    """A StudyCoordinator: subjects, subject visits and interface-posted charges."""
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def coordinator_seven_headers():
    """A second StudyCoordinator."""
    return TEST_USERS["coordinator_seven_headers"]


@pytest.fixture
def liaison_headers():
    """An AuditLiaison: opening audit findings."""
    return TEST_USERS["liaison_headers"]


@pytest.fixture
def liaison_two_headers():
    """A second AuditLiaison — the finding-response counterparty."""
    return TEST_USERS["liaison_two_headers"]
