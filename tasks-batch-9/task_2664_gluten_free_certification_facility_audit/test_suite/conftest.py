"""Pytest bridge for the gluten-free certification API test suite.

The API server is restarted before every individual test, so each test observes
an empty store and a logical clock parked at its declared start instant. All
state a test needs is therefore built inside that test through the fixtures in
``test_helpers``.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    ApiErrorId,
    TEST_USERS,
    make_applicant_contact_headers,
)


@pytest.fixture
def api() -> ApiClient:
    """HTTP client bound to the API under test."""
    return ApiClient()


@pytest.fixture
def admin_headers():
    """ProgramAdministrator identity: owns the clock and the surveillance sweep."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def reviewer_headers():
    """CertificationReviewer identity rev-1."""
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def second_reviewer_headers():
    """CertificationReviewer identity rev-2, for segregation-of-duties pairings."""
    return TEST_USERS["reviewer_2_headers"]


@pytest.fixture
def auditor_headers():
    """FieldAuditor identity aud-1."""
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def second_auditor_headers():
    """FieldAuditor identity aud-2."""
    return TEST_USERS["auditor_2_headers"]


@pytest.fixture
def decision_maker_headers():
    """CertificationDecisionMaker identity dm-1."""
    return TEST_USERS["decision_maker_headers"]


@pytest.fixture
def second_decision_maker_headers():
    """CertificationDecisionMaker identity dm-2."""
    return TEST_USERS["decision_maker_2_headers"]


@pytest.fixture
def lab_headers():
    """LabTechnician identity lab-1."""
    return TEST_USERS["lab_technician_headers"]


@pytest.fixture
def applicant_headers_for():
    """Builder for ApplicantContact headers bound to a real applicant id."""
    return make_applicant_contact_headers


@pytest.fixture
def errors():
    """The error identifier catalogue."""
    return ApiErrorId
