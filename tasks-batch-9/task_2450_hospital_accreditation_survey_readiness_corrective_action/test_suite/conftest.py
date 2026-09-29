"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def director_headers():
    """AccreditationDirector — chapters, standards, units, windows, clock."""
    return TEST_USERS["director_headers"]


@pytest.fixture
def standard_owner_headers():
    """StandardOwner — evidence filing and submission, ESC authorship."""
    return TEST_USERS["standard_owner_headers"]


@pytest.fixture
def second_standard_owner_headers():
    """A second StandardOwner principal, for ownership-negative probes."""
    return TEST_USERS["second_standard_owner_headers"]


@pytest.fixture
def evidence_validator_headers():
    """EvidenceValidator — independent review of filed evidence."""
    return TEST_USERS["evidence_validator_headers"]


@pytest.fixture
def tracer_surveyor_headers():
    """TracerSurveyor — the mock tracer program."""
    return TEST_USERS["tracer_surveyor_headers"]


@pytest.fixture
def safety_officer_headers():
    """SafetyOfficer — rounding, ticketing, verification."""
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def external_surveyor_headers():
    """ExternalSurveyor — findings, escalation and response decisions."""
    return TEST_USERS["external_surveyor_headers"]


@pytest.fixture
def unit_manager_headers():
    """UnitManager with a placeholder identity — only for calls that do not
    exercise unit scoping. Scope-gated calls must use
    make_unit_manager_headers(unit["id"])."""
    return TEST_USERS["unit_manager_headers"]
