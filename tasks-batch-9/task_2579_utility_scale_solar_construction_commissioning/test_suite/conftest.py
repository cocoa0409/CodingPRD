"""Shared pytest fixtures for the Utility-Scale Solar EPC suite.

The runner starts the server under test and publishes its base URL through the
``API_BASE_URL`` environment variable before the first test executes, so the
client is built once per session and reused.

PRD 2.1 requires every request to carry `X-User-ID` and `X-User-Role`. All eight
roles are opaque identities — the accompanying `X-User-ID` is never compared
against any entity's `id` — so a session-wide header set per role is safe. Where
a test needs two distinct operators of the same role, because PRD 2.10 compares
one recorded operator identifier against another, it uses the ``*_alt`` fixtures
or the explicit ``make_*_headers`` builders.
"""

import pytest

from test_helpers import api_client
from test_helpers.fixtures import (
    accepted_area,
    energized_project,
    ready_project,
)
from test_helpers.test_users import (
    CIVIL_SUPERINTENDENT,
    COMMISSIONING_ENGINEER,
    EPC_PROJECT_MANAGER,
    EPC_PROJECT_MANAGER_ALT,
    INSTALLATION_FOREMAN,
    INSTALLATION_FOREMAN_ALT,
    LABOR_COMPLIANCE_OFFICER,
    LABOR_COMPLIANCE_OFFICER_ALT,
    OWNER_ENGINEER,
    OWNER_ENGINEER_ALT,
    PROCUREMENT_COORDINATOR,
    UTILITY_COORDINATOR,
)


@pytest.fixture(scope="session")
def api():
    """The endpoint surface of PRD section 4."""
    return api_client


# ---------------------------------------------------------------------------
# One caller per role of PRD 2.1
# ---------------------------------------------------------------------------
@pytest.fixture
def epc_headers():
    """An `EpcProjectManager`, who owns the project, its scope and its claims."""
    return dict(EPC_PROJECT_MANAGER)


@pytest.fixture
def civil_headers():
    """A `CivilSuperintendent`, who runs earthwork under the stormwater permit."""
    return dict(CIVIL_SUPERINTENDENT)


@pytest.fixture
def procurement_headers():
    """A `ProcurementCoordinator`, who runs the laydown yard and deliveries."""
    return dict(PROCUREMENT_COORDINATOR)


@pytest.fixture
def foreman_headers():
    """An `InstallationForeman`, who drives piles, wires strings and tests them."""
    return dict(INSTALLATION_FOREMAN)


@pytest.fixture
def utility_headers():
    """A `UtilityCoordinator`, who runs the substation and its outage windows."""
    return dict(UTILITY_COORDINATOR)


@pytest.fixture
def commissioning_headers():
    """A `CommissioningEngineer`, who schedules, samples and finalizes tests."""
    return dict(COMMISSIONING_ENGINEER)


@pytest.fixture
def owner_headers():
    """An `OwnerEngineer`, who accepts civil work, punch closures and milestones."""
    return dict(OWNER_ENGINEER)


@pytest.fixture
def labor_headers():
    """A `LaborComplianceOfficer`, who posts certified payroll and runs compliance."""
    return dict(LABOR_COMPLIANCE_OFFICER)


# ---------------------------------------------------------------------------
# Second operators of the same role, for the comparisons of PRD 2.10
# ---------------------------------------------------------------------------
@pytest.fixture
def epc_headers_alt():
    """A second `EpcProjectManager`, distinct from the one who files claims."""
    return dict(EPC_PROJECT_MANAGER_ALT)


@pytest.fixture
def foreman_headers_alt():
    """A second `InstallationForeman`, distinct from the closure submitter."""
    return dict(INSTALLATION_FOREMAN_ALT)


@pytest.fixture
def owner_headers_alt():
    """A second `OwnerEngineer`, distinct from the one who decides."""
    return dict(OWNER_ENGINEER_ALT)


@pytest.fixture
def labor_headers_alt():
    """A second `LaborComplianceOfficer`, who may certify what the first posted."""
    return dict(LABOR_COMPLIANCE_OFFICER_ALT)


# ---------------------------------------------------------------------------
# Composite state every part of the suite reuses
# ---------------------------------------------------------------------------
@pytest.fixture
def project(api):
    """A project on the commercial baseline the suite computes its figures from."""
    from test_helpers.fixtures import create_project

    return create_project(api)


@pytest.fixture
def accepted_grading_area(api, project):
    """A grading area cleared, graded and accepted, so it can carry blocks."""
    return accepted_area(api, project["id"])


@pytest.fixture
def ready_plant(api):
    """A plant built through to the point where the project reports itself ready."""
    return ready_project(api)


@pytest.fixture
def energized_plant(api):
    """A ready plant whose substation is energized, with the clock inside the
    approved backfeed window."""
    return energized_project(api)
