"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_body_engineer_headers,
    make_customer_committee_rep_headers,
    make_program_admin_headers,
    make_purchasing_officer_headers,
    make_third_party_tester_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """A ProgramAdmin: programs, bays, slot lines, reservations, trips, sweep."""
    return make_program_admin_headers()


@pytest.fixture
def purchasing_headers():
    """A PurchasingOfficer: specifications, dispositions, awards, change orders."""
    return make_purchasing_officer_headers()


@pytest.fixture
def engineer_headers():
    """A BodyEngineer: compliance-matrix responses."""
    return make_body_engineer_headers()


@pytest.fixture
def tester_headers():
    """A ThirdPartyTester: certification submissions and signed results."""
    return make_third_party_tester_headers()


@pytest.fixture
def committee_headers_for():
    """Builds CustomerCommitteeRep headers for one program.

    That role's ``X-User-ID`` is the id of the program whose committee it speaks
    for, so the headers can only be built once the program exists.
    """
    return make_customer_committee_rep_headers
