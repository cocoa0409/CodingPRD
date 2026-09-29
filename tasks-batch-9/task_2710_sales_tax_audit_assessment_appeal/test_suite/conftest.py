"""Shared pytest fixtures for the sales-tax audit API suite.

The harness relaunches the API server and empties the database before every
individual test, so no fixture here may assume state left by another test:
every scenario is rebuilt from scratch through the documented endpoints.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    TEST_USERS,
    api_client,
    make_appeals_officer_headers,
    make_collections_agent_headers,
    make_field_auditor_headers,
    make_selection_analyst_headers,
    make_supervisor_headers,
    make_taxpayer_headers,
    make_tribunal_judge_headers,
)


@pytest.fixture(scope="session")
def api():
    """The API client bound to the running server."""
    return api_client


@pytest.fixture
def selection_analyst_headers():
    """A SelectionAnalyst: loads information returns and works the lead queue."""
    return TEST_USERS["selection_analyst_headers"]


@pytest.fixture
def field_auditor_headers():
    """The FieldAuditor assigned as lead auditor by every fixture chain."""
    return TEST_USERS["field_auditor_headers"]


@pytest.fixture
def other_field_auditor_headers():
    """A second FieldAuditor, for scenarios needing two distinct examiners."""
    return TEST_USERS["other_field_auditor_headers"]


@pytest.fixture
def audit_supervisor_headers():
    """The AuditSupervisor who closes fieldwork and drives the notice."""
    return TEST_USERS["audit_supervisor_headers"]


@pytest.fixture
def appeals_officer_headers():
    """An AppealsOfficer for the informal conference and administrative appeal."""
    return TEST_USERS["appeals_officer_headers"]


@pytest.fixture
def other_appeals_officer_headers():
    """A second AppealsOfficer, for the rung above one already decided."""
    return TEST_USERS["other_appeals_officer_headers"]


@pytest.fixture
def tax_tribunal_judge_headers():
    """A TaxTribunalJudge for the last rung of the ladder."""
    return TEST_USERS["tax_tribunal_judge_headers"]


@pytest.fixture
def collections_agent_headers():
    """A CollectionsAgent for referral, arrangements and payments."""
    return TEST_USERS["collections_agent_headers"]


@pytest.fixture
def taxpayer_headers():
    """A Taxpayer identity not tied to any registered permit holder.

    Ownership-gated paths must instead build headers from the real record id
    with `make_taxpayer_headers(taxpayer["id"])`.
    """
    return TEST_USERS["taxpayer_headers"]


@pytest.fixture
def taxpayer_headers_for():
    """Build `Taxpayer` headers for a given permit-holder record id."""
    return make_taxpayer_headers


@pytest.fixture
def headers_for_operator():
    """Builders for each operator role under a chosen opaque operator id."""
    return {
        "SelectionAnalyst": make_selection_analyst_headers,
        "FieldAuditor": make_field_auditor_headers,
        "AuditSupervisor": make_supervisor_headers,
        "AppealsOfficer": make_appeals_officer_headers,
        "TaxTribunalJudge": make_tribunal_judge_headers,
        "CollectionsAgent": make_collections_agent_headers,
    }
