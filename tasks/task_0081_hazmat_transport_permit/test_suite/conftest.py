"""Pytest fixture bridge for the hazmat-transport-permit test suite.

The outer ``prd-bench-local-runner`` harness sets the ``API_BASE_URL``
environment variable and the ``PYTHONPATH`` so that ``test_helpers`` is
importable, then invokes ``pytest`` against the ``test_suite/``
directory.  This file is the small bridge from the test-helpers'
module-level objects (the singleton ``api_client``, the
``TEST_USERS`` shared-constant header dict, the per-instance header
builders) into the named pytest-fixture mechanism the test functions'
parameter list resolves against.

The session-scoped ``api`` fixture hands out the singleton
``ApiClient``.  The function-scoped autouse ``_admin_reset_between_tests``
fixture wipes the server's in-memory state before each test by
hitting the test-harness-only ``POST /v1/_admin/reset`` endpoint, so a
test never observes the previous test's natural-key collisions or
leftover rows.  The per-role-headers fixtures expose the four
shared-constant entries from ``TEST_USERS`` so a test whose
ownership-predicate-irrelevant assertion (the auth-tier rejections,
the existence-tier 404s, the body-shape ``ERR_VALIDATION`` cases) can
take a headers parameter without composing one inline.

The eight scenario-builder fixtures wrap the corresponding helpers from
``test_helpers.fixtures`` so tests can spell the lifecycle prefix as a
fixture parameter rather than a procedural setup-block at the top of
each test.  The fixtures' scopes are deliberately function-scoped (the
default) so the auto-reset between tests doesn't leave a stale
scenario carrying ids that no longer resolve on the server side.
"""

from __future__ import annotations

import os
from typing import Dict

import pytest


def pytest_configure(config):
    """Register the ``worked_example`` custom mark that
    ``test_worked_examples.py`` tags each PRD-difficulty-file-
    worked-example test function with.  The marker's single
    string argument is the canonical id in the
    ``<rule_id_bucket>::<short_label>`` form drawn from the
    ``scaffold_difficulty_design.worked_examples_by_rule_id``
    index in the difficulty YAML.
    """
    config.addinivalue_line(
        "markers",
        'worked_example(id): the worked-example id-string in the form '
        '"<rule_id_bucket>::<short_label>" the test function exercises, drawn from '
        'the difficulty file\'s priority-queue of test recipes.',
    )


from test_helpers import (
    ApiClient,
    HazmatScenario,
    TwoTenantScenario,
    api_client,
    bootstrap_company_operator_headers,
    company_operator_headers,
    driver_headers,
    regulator_headers,
    test_harness_headers,
    setup_active_permit,
    setup_approved_company,
    setup_draft_company,
    setup_inflight_trip,
    setup_qualified_carrier,
    setup_submitted_company,
    setup_two_tenants,
    admin_reset,
)


# ─── Session-scoped: the API client ────────────────────────────────────


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The session-scoped HTTP-client singleton.  Reads
    ``API_BASE_URL`` from the environment, falling back to
    ``http://localhost:10000`` if unset.  The base URL the local-
    runner sets for the per-test subprocess is the host:port of the
    in-Docker server-under-test.
    """
    base_url = os.environ.get("API_BASE_URL")
    if base_url is None:
        # Honour the framework's default if the env var is unset; the
        # client constructor reads the same env var so an explicit
        # construction here is the same as the module-level default.
        return api_client
    return ApiClient(base_url=base_url)


# ─── Function-scoped autouse: between-test reset ──────────────────────


@pytest.fixture(autouse=True)
def _admin_reset_between_tests(api: ApiClient):
    """Before every test, wipe the server's in-memory state by hitting
    the test-harness-only ``POST /v1/_admin/reset`` endpoint.  The
    helper swallows a non-2xx silently so the absence of the reset
    endpoint doesn't block the entire suite; the relevant tests then
    fail with a clearer "stale-state from previous test" symptom that
    points the fix-loop's diagnostic step at the missing affordance.
    """
    admin_reset(api)
    yield
    # Post-test cleanup — best-effort wipe so a test that crashed
    # mid-action doesn't leave half-state for the next session-scoped
    # readout.  The next test's pre-yield reset is the canonical
    # cleanup; the post-yield call is redundant but harmless.
    # Disabled by default since the pre-yield call is sufficient.
    # admin_reset(api)


# ─── Per-role-headers fixtures (the opaque-identity constants) ─────────


@pytest.fixture
def regulator_officer_headers() -> Dict[str, str]:
    """Header pair for the ``RegulatorOfficer`` opaque-identity role.
    Suitable for any test whose action is a regulator-side endpoint
    invocation (the company-approve, the inspection-append, the
    permit-issue-and-verify-and-void, the manual-penalty-and-uphold,
    the driver-endorsement-refresh).  The regulator is cross-tenant
    exempt per the regulatory-mandate convention of PRD §2.6 so the
    same constant headers reach every tenant's rows."""
    return regulator_headers()


@pytest.fixture
def test_harness_role_headers() -> Dict[str, str]:
    """Header pair for the ``TestHarness`` opaque-identity role.
    Allow-set is the two test-mode-only endpoints
    ``POST /v1/_clock/advance`` and ``POST /v1/_sweep/run`` plus the
    administrative ``POST /v1/_admin/reset`` and the
    ``POST /v1/_admin/wallet-topup`` out-of-band affordances.  A
    test-harness request hitting a business-logic endpoint is the
    default-deny ``ERR_ROLE_NOT_PERMITTED`` 403 case."""
    return test_harness_headers()


@pytest.fixture
def bootstrap_co_headers() -> Dict[str, str]:
    """Header pair for the very-first ``POST /v1/companies``
    bootstrap call.  The ``X-User-ID`` is the bootstrap-token
    identifier the PRD's §2.6 names as the exception to the
    entity-backed-id-resolves auth-tier check; on every subsequent
    call the client uses the minted company-id-based header pair from
    ``company_operator_headers(company['id'])``."""
    return bootstrap_company_operator_headers()


# A note on the entity-backed per-instance header builders:
# ``company_operator_headers(company_id)`` and
# ``driver_headers(driver_id)`` are functions of the entity-id, so
# they cannot be expressed as static-zero-argument pytest fixtures.
# Tests that need them call the underlying helper from
# ``test_helpers`` directly (the standard import path is ``from
# test_helpers import company_operator_headers, driver_headers``).
# The convention is the same one the PRD-bench unit-test-generator
# skill spec's §1.7 prescribes.


def make_co_headers(company_id: str) -> Dict[str, str]:
    """Plain-function helper exposed at the conftest level so
    test files that prefer the "all fixtures are pytest fixtures"
    aesthetic can import the symbol without going through the
    ``test_helpers`` barrel.  The function is the same one as
    ``test_helpers.test_users.company_operator_headers``."""
    return company_operator_headers(company_id)


def make_driver_headers(driver_id: str) -> Dict[str, str]:
    """Companion helper for the Driver-role self-only header pair."""
    return driver_headers(driver_id)


# ─── Scenario-builder fixtures wrapping the test_helpers helpers ──────


@pytest.fixture
def draft_company(api: ApiClient) -> Dict:
    """A freshly-minted TransportCompany in ``DRAFT``.  No wallet
    top-up, no children entities — the minimum precondition the
    company-submit endpoint's same-row state guard reads."""
    return setup_draft_company(api)


@pytest.fixture
def submitted_company(api: ApiClient) -> Dict:
    """A TransportCompany in ``SUBMITTED`` — the state the regulator's
    approve action reads from."""
    return setup_submitted_company(api)


@pytest.fixture
def approved_company(api: ApiClient) -> Dict:
    """A TransportCompany in ``APPROVED`` with the wallet topped up to
    the canonical convenience-large balance.  The standard
    parent-must-be-``APPROVED`` gate on the child-create endpoints
    (drivers, vehicles, routes) is satisfied."""
    return setup_approved_company(api)


@pytest.fixture
def qualified_carrier(api: ApiClient) -> HazmatScenario:
    """An APPROVED company with one driver (attested), one vehicle
    (with a fresh ``PASSED`` inspection), and one approved route.
    The wallet is topped up.  The permit aggregate is not yet in the
    picture — the standard precondition for the
    ``POST /v1/permits`` application call."""
    return setup_qualified_carrier(api)


@pytest.fixture
def active_permit(api: ApiClient) -> HazmatScenario:
    """The "permit issued and ACTIVE" baseline.  The
    ``HazmatScenario.permit`` field is the active permit row, the
    server's logical clock has been advanced just past the permit's
    ``valid_from`` so the within-window leg of the validity chain is
    green.  Tests that exercise the trip lifecycle, the GPS-stream,
    the renewal/void-issue, and the verify-compliance dual-variant
    axis use this fixture as the lifecycle-precondition."""
    return setup_active_permit(api)


@pytest.fixture
def inflight_trip(api: ApiClient) -> HazmatScenario:
    """The "trip in-flight" baseline.  The scenario's ``trips`` list
    has a single ``IN_TRANSIT`` trip on the first driver and the
    first vehicle of the carrier's roster; the trip's
    ``actual_departure_at`` is the server-side clock-at-the-depart
    moment and the right edge of the in-flight window is the
    current logical-clock value.  GPS-ingest tests use this fixture
    as the precondition for the
    ``POST /v1/trips/{trip_id}/gps-reports`` action."""
    return setup_inflight_trip(api)


@pytest.fixture
def two_tenants(api: ApiClient) -> TwoTenantScenario:
    """Two independent fully-qualified carriers, each with an
    APPROVED company, the wallet topped up, a driver, a vehicle,
    a route, and an ACTIVE permit.  The two tenants' rows are
    completely disjoint at the id level so the cross-tenant
    predicate of PRD §2.6 fires on a request from one tenant's
    operator addressing a row owned by the other.  The
    fixture is the precondition for every cross-tenant-isolation
    test in ``test_authentication_and_authorization.py`` and
    ``test_rbac_matrix.py``."""
    return setup_two_tenants(api)


# ─── A convenience parametrize-data fixture for the omnibus RBAC test ─


# The omnibus RBAC matrix test in ``test_rbac_matrix.py`` consumes the
# ``ApiClient.ENDPOINT_TABLE`` class attribute as its
# (method, path-template, name) source list and the four role-name
# strings as the columns.  No additional conftest fixture is needed —
# the test file imports the table directly from the test_helpers'
# ``api_client`` module.

# ─── A small "free helper" the test files share ───────────────────────


@pytest.fixture
def non_existent_uuid() -> str:
    """The all-zero UUID, used as the canonical "the resource id is
    syntactically valid but resolves to no row" sentinel on the
    existence-tier 404 tests.  The framework's
    ``prd_bench_local_runner.testing.NON_EXISTENT_UUID`` is the
    same value; this fixture exposes it under the local name.

    Note the auth-tier's priority-110 entity-backed-id-resolves
    leg fires ``ERR_UNAUTHENTICATED`` 401 (not the existence-tier
    404) when the *requester's* X-User-ID is the non-existent UUID,
    while the existence-tier 404 fires on a non-resolving id in the
    URL path or in the body's foreign-key reference — the two
    cases are at different tiers per PRD §2.7.
    """
    from prd_bench_local_runner.testing import NON_EXISTENT_UUID
    return NON_EXISTENT_UUID
