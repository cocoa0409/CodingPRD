"""Shared pytest fixtures for the pump manufacturing and hydraulic testing suite.

The harness restarts the API server before every individual test, so each test
begins against an empty database with the logical clock at its mandatory startup
default of 2026-08-01T00:00:00Z.  Every precondition below is therefore built
from scratch through the documented endpoints.

Seven of the eight roles have opaque identities and get a fixed header dict.
`FoundryPartner` is entity-backed: its `X-User-ID` must be the identifier of the
Foundry row it acts for, so it is exposed as a factory rather than a constant.
"""

import pytest

from test_helpers import (
    APPLICATION_ENGINEER,
    HYDRAULIC_APPROVER,
    OTHER_APPLICATION_ENGINEER,
    OTHER_HYDRAULIC_APPROVER,
    OTHER_QUALITY_INSPECTOR,
    OTHER_WARRANTY_ADJUDICATOR,
    PLATFORM_ADMIN,
    PRODUCTION_PLANNER,
    QUALITY_INSPECTOR,
    TEST_ENGINEER,
    WARRANTY_ADJUDICATOR,
    api_client,
    make_foundry_partner_headers,
)


@pytest.fixture
def api():
    """The API client bound to the running server."""
    return api_client


@pytest.fixture
def admin_headers():
    """PlatformAdmin caller: owns foundries, models, patterns, configs and kits."""
    return PLATFORM_ADMIN


@pytest.fixture
def engineer_headers():
    """ApplicationEngineer caller: duty applications, selections, warranty claims."""
    return APPLICATION_ENGINEER


@pytest.fixture
def other_engineer_headers():
    """A second ApplicationEngineer, for checks that bind a user rather than a role."""
    return OTHER_APPLICATION_ENGINEER


@pytest.fixture
def approver_headers():
    """HydraulicApprover caller: approves selections."""
    return HYDRAULIC_APPROVER


@pytest.fixture
def other_approver_headers():
    """A second HydraulicApprover."""
    return OTHER_HYDRAULIC_APPROVER


@pytest.fixture
def inspector_headers():
    """QualityInspector caller: inspects lots and dispositions defects."""
    return QUALITY_INSPECTOR


@pytest.fixture
def other_inspector_headers():
    """A second QualityInspector, for separation-of-duty checks."""
    return OTHER_QUALITY_INSPECTOR


@pytest.fixture
def test_engineer_headers():
    """TestEngineer caller: test runs, measured points, evaluation and certification."""
    return TEST_ENGINEER


@pytest.fixture
def planner_headers():
    """ProductionPlanner caller: build orders, packages, kit allocations."""
    return PRODUCTION_PLANNER


@pytest.fixture
def adjudicator_headers():
    """WarrantyAdjudicator caller: adjudicates and settles claims."""
    return WARRANTY_ADJUDICATOR


@pytest.fixture
def other_adjudicator_headers():
    """A second WarrantyAdjudicator, for separation-of-duty checks."""
    return OTHER_WARRANTY_ADJUDICATOR


@pytest.fixture
def foundry_partner_headers_factory():
    """Build FoundryPartner headers whose X-User-ID is a real foundry id."""
    return make_foundry_partner_headers
