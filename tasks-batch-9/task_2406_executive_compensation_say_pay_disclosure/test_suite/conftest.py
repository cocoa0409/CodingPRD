"""Shared pytest fixtures for the executive compensation and say-on-pay suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    CHAIR_ONE,
    CHAIR_TWO,
    COUNSEL_ONE,
    COUNSEL_TWO,
    IR_ONE,
    api_client,
    make_comp_committee_chair_headers,
    make_comp_consultant_headers,
    make_investor_relations_lead_headers,
    make_named_executive_officer_headers,
    make_securities_counsel_headers,
)


@pytest.fixture(autouse=True)
def _fresh_connection_pool():
    """Drop pooled sockets before every test.

    The API client keeps one module-level `requests.Session`, but the server
    under test is killed and rebooted on the same port between tests. A
    keep-alive socket left over from the previous server can outlive
    urllib3's liveness check and then fail mid-request with
    `ConnectionResetError(104)`. Clearing the pool first makes every test
    open a connection to the server that is actually running.
    """
    api_client.session.close()
    yield


@pytest.fixture(scope="session")
def api():
    """The API client for the service under test."""
    return api_client


@pytest.fixture
def comp_consultant_headers():
    """CompConsultant — designs programs, screens peer groups, submits results."""
    return make_comp_consultant_headers("consultant-001")


@pytest.fixture
def comp_committee_chair_headers():
    """CompCommitteeChair — approves, adjusts, certifies, orders recovery."""
    return make_comp_committee_chair_headers(CHAIR_ONE)


@pytest.fixture
def second_chair_headers():
    """A second CompCommitteeChair, for the separation-of-duties rules."""
    return make_comp_committee_chair_headers(CHAIR_TWO)


@pytest.fixture
def securities_counsel_headers():
    """SecuritiesCounsel — authors disclosure sections and declares restatements."""
    return make_securities_counsel_headers(COUNSEL_ONE)


@pytest.fixture
def second_counsel_headers():
    """A second SecuritiesCounsel, so an author never clears their own section."""
    return make_securities_counsel_headers(COUNSEL_TWO)


@pytest.fixture
def investor_relations_lead_headers():
    """InvestorRelationsLead — runs advisor screens and investor outreach."""
    return make_investor_relations_lead_headers(IR_ONE)


@pytest.fixture
def named_executive_officer_headers():
    """A NamedExecutiveOfficer with no executive row behind it.

    Ownership-gated officer calls must instead use
    `make_named_executive_officer_headers(executive["id"])` so the caller's user
    id is the executive the row belongs to.
    """
    return make_named_executive_officer_headers("officer-001")
