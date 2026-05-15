"""Per-role authentication-header builders for the hazmat-transport-permit
test layer.

The PRD's §2.1 names the two-header contract: every request carries the
``X-User-ID`` opaque-or-entity-backed identifier string and the
``X-User-Role`` role-name string drawn from the four canonical role names
``CompanyOperator``, ``RegulatorOfficer``, ``Driver``, ``TestHarness``.
The two entity-backed roles (``CompanyOperator`` and ``Driver``) interpret
the ``X-User-ID`` as the primary-key id of a TransportCompany or Driver
row respectively; the implementation's auth-middleware looks the row up
and rejects a non-resolving id with ``ERR_UNAUTHENTICATED`` 401 on the
priority-110 entity-backed-id-resolves leg.  The two opaque roles
(``RegulatorOfficer`` and ``TestHarness``) accept any non-empty string as
the ``X-User-ID``, on the principle that the regulator's individual
officer identity and the test-harness's runner-string identity are not
tied to any persisted entity table.

The cross-tenant predicate of PRD §2.6 fires when an
``entity_backed:TransportCompany`` request's ``X-User-ID`` does not equal
the addressed row's effective owning-company id, and similarly the
driver's self-only predicate of priority 531 fires when a ``Driver``
request's ``X-User-ID`` does not equal the path's ``{driver_id}``.  The
``company_operator_headers`` and ``driver_headers`` factories below
therefore take the entity's id as the explicit argument — this is the
"X-User-ID equals the entity's id, the auth-middleware looks the row up,
the cross-tenant check fires on a mismatch" contract — and the
fixture-side discipline is "after the create-call mints the row's id,
thread it back into the header builder for every subsequent
ownership-gated call on that row".  A test that hard-codes a constant
``X-User-ID`` regardless of the entity-row it targets defeats the
cross-tenant isolation invariant by giving every request from
"company-A's operator" the same identity as the request from "company-B's
operator", which is the canonical fixture-bug the standard test pattern
guards against.

The two opaque-role builders are zero-argument and return the same
constant header pair across every test, because the opaque roles'
identity is not entity-keyed.  The ``TEST_USERS`` shared-constant mapping
holds the opaque-role headers (safe for any test) and the
shared-constant entity-backed-role headers (safe only for tests whose
success does not depend on row-ownership — the missing-auth, the
unknown-role, the role-deny-default, the entity-not-found-at-the-existence-tier
test cases all fall in this category).  Tests whose assertion is
ownership-gated MUST call the per-instance builder with the actual
entity-id.

The bootstrap-identity exception of PRD §2.6's last paragraph applies on
the company-create endpoint, where the operator has no company id yet and
the server mints the row's id from a fresh UUID on the server side.  The
``bootstrap_company_operator_headers`` helper provides the canonical
bootstrap-token identifier the regulator-side onboarding flow would have
issued out-of-band; the scaffold's prose notes the create-of-self
endpoint is exempt from the entity-backed-id-resolves auth leg.
"""

from typing import Callable, Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_COMPANY_OPERATOR,
    ROLE_DRIVER,
    ROLE_REGULATOR_OFFICER,
    ROLE_TEST_HARNESS,
)


# ─── Opaque-role canonical identifier strings ───────────────────────────

#: The opaque-identifier string the test layer's regulator role sends as
#: its ``X-User-ID`` value.  Any non-empty string would do; the
#: convention is the role name prefixed with ``opaque:`` and a stable
#: numeric suffix so the audit-trail fields the regulator's actions
#: stamp (``inspector_id`` on a VehicleInspection, ``approved_by`` on a
#: TransportRoute, ``issued_by`` on a Permit, ``upheld_by`` on a Penalty)
#: have a deterministic value across the test suite.
OPAQUE_REGULATOR_ID: str = "regulator-officer-1"

#: The opaque-identifier string the test harness's clock-and-sweep role
#: sends as its ``X-User-ID`` value.  Recognised by the auth-middleware
#: as the canonical test-runner identity on the two test-mode-only
#: endpoints ``/v1/_clock/advance`` and ``/v1/_sweep/run`` and the
#: between-test ``/v1/_admin/reset`` and wallet-topup affordances.
OPAQUE_TEST_HARNESS_ID: str = "test-harness-runner-1"

#: The arbitrary string the company-create bootstrap request sends as
#: its ``X-User-ID`` value before the new row's server-minted id is
#: known.  The server's auth-middleware accepts this opaque identifier
#: on the company-create endpoint specifically (the bootstrap exception
#: of §2.6's last paragraph) and the client replaces this string with
#: the response body's ``data.id`` field on every subsequent call.
BOOTSTRAP_COMPANY_OPERATOR_ID: str = "bootstrap-company-operator-1"

#: An equivalent bootstrap identifier for the rare case where a test
#: needs a Driver-role request before the test has the driver's id in
#: hand — this is not the standard pattern (the standard is to create
#: the driver first via the operator's role and then use the minted
#: driver-id), but the helper exists for symmetry with the company-side
#: bootstrap convention.
BOOTSTRAP_DRIVER_ID: str = "bootstrap-driver-1"


#: The four canonical role-name strings in the order they appear in the
#: scaffold's §1.7 RBAC matrix's column header.
ROLE_NAMES = (
    ROLE_COMPANY_OPERATOR,
    ROLE_REGULATOR_OFFICER,
    ROLE_DRIVER,
    ROLE_TEST_HARNESS,
)


# ─── Per-instance entity-backed-role header builders ────────────────────


def company_operator_headers(company_id: str) -> Dict[str, str]:
    """Build the auth-header pair for a CompanyOperator-role request
    acting on the named TransportCompany row.

    The ``X-User-ID`` value MUST equal the addressed company's primary-key
    id.  A mismatch is what the cross-tenant predicate of PRD §2.6 fires
    ``ERR_CROSS_TENANT_ACCESS`` 403 on; a non-resolving id is what the
    priority-110 entity-backed-id-resolves auth leg fires
    ``ERR_UNAUTHENTICATED`` 401 on.

    The fixtures in ``test_helpers/fixtures.py`` thread the
    just-minted company id through this builder for every ownership-gated
    call following a successful company-create.

    The function deliberately takes a single positional ``str`` argument
    so a mis-call passing a different shape (a tuple, a dict, the
    response object itself) raises immediately rather than producing a
    silently-wrong ``X-User-ID`` string.
    """
    if not isinstance(company_id, str) or not company_id:
        raise ValueError(
            "company_operator_headers requires a non-empty company-id "
            f"string; got {company_id!r}"
        )
    return build_user_headers(company_id, ROLE_COMPANY_OPERATOR)


def driver_headers(driver_id: str) -> Dict[str, str]:
    """Build the auth-header pair for a Driver-role request acting on
    the named Driver row.

    The ``X-User-ID`` value MUST equal the addressed driver's primary-key
    id, per the entity-backed-identity contract of PRD §2.1 on the
    Driver role.  The Driver-role's allow-set is the three self-only
    read endpoints (``GET /v1/drivers/{driver_id}``, ``GET /v1/trips/{id}``
    when the trip's ``driver_id`` matches, and the
    ``GET /v1/drivers/{driver_id}/penalty-summary`` self-summary read).
    A Driver-role request hitting one of these endpoints with an
    ``X-User-ID`` that doesn't match the path's id is the
    priority-531 self-only-deny case returning
    ``ERR_CROSS_TENANT_ACCESS`` 403 (the same error id the operator's
    cross-tenant predicate emits, with the meaning generalized from
    "wrong-company-tenant" to "wrong-individual-identity").

    Like ``company_operator_headers``, the function enforces the
    non-empty-string shape on the argument.
    """
    if not isinstance(driver_id, str) or not driver_id:
        raise ValueError(
            "driver_headers requires a non-empty driver-id string; "
            f"got {driver_id!r}"
        )
    return build_user_headers(driver_id, ROLE_DRIVER)


# ─── Opaque-role zero-argument header constants ────────────────────────


def regulator_headers() -> Dict[str, str]:
    """Build the auth-header pair for a RegulatorOfficer-role request.

    The ``X-User-ID`` is the opaque ``OPAQUE_REGULATOR_ID`` string; the
    regulator's identity is not tied to any persisted entity table so the
    priority-110 entity-backed-id-resolves auth leg is a no-op for this
    role.  The regulator is cross-tenant exempt per the regulatory-mandate
    convention of PRD §2.6, so a regulator's request reaches every
    tenant's rows regardless of which tenant owns the addressed row.
    """
    return build_user_headers(OPAQUE_REGULATOR_ID, ROLE_REGULATOR_OFFICER)


def test_harness_headers() -> Dict[str, str]:
    """Build the auth-header pair for a TestHarness-role request.

    The role's allow-set is the two test-mode endpoints
    ``POST /v1/_clock/advance`` and ``POST /v1/_sweep/run`` plus the
    out-of-band administrative affordances ``POST /v1/_admin/reset`` and
    the wallet-topup helper documented in
    ``test_helpers/api_client.py``.  The role is rejected at the auth
    tier in a production deployment with the test-harness middleware
    disabled, but the benchmark's test deployment recognises it.
    """
    return build_user_headers(OPAQUE_TEST_HARNESS_ID, ROLE_TEST_HARNESS)


def bootstrap_company_operator_headers() -> Dict[str, str]:
    """Build the auth-header pair for the very first company-create
    request, where the operator has no TransportCompany id yet.

    Per PRD §2.6's bootstrap-exemption paragraph the
    ``POST /v1/companies`` endpoint accepts the request's
    ``X-User-ID`` as the would-be operator identifier without
    enforcing the entity-backed-id-resolves leg, then the response's
    body carries the server-minted ``id`` which the client switches
    its ``X-User-ID`` to on every subsequent call.

    Calling this helper outside the company-create endpoint produces a
    request the auth-tier rejects with ``ERR_UNAUTHENTICATED`` 401 on
    the priority-110 entity-backed-id-resolves leg, because the
    bootstrap identifier does not correspond to any TransportCompany
    row.
    """
    return build_user_headers(BOOTSTRAP_COMPANY_OPERATOR_ID, ROLE_COMPANY_OPERATOR)


# ─── Shared-constant header dict for ownership-agnostic tests ───────────

#: The shared-constant mapping the framework's pytest-style fixture
#: bridge in ``test_suite/conftest.py`` exposes.  Entries for the
#: opaque-identity roles are the canonical headers; entries for the
#: entity-backed roles are the bootstrap-identifier headers, suitable
#: for tests that exercise the auth-tier rejections (missing-headers,
#: unknown-role, non-resolving-id) and the existence-tier
#: not-found-by-bad-id tests where no real entity-row is in the picture.
#: Tests whose success depends on the row-ownership predicate threading
#: the entity-id into the header MUST call the per-instance builder
#: above rather than indexing this mapping.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "regulator_officer_headers": regulator_headers(),
    "test_harness_headers": test_harness_headers(),
    "bootstrap_company_operator_headers": bootstrap_company_operator_headers(),
    "bootstrap_driver_headers": build_user_headers(BOOTSTRAP_DRIVER_ID, ROLE_DRIVER),
}


# ─── Convenience: a single "build headers for an arbitrary role name" ──


def headers_for_role(role_name: str, user_id: str) -> Dict[str, str]:
    """Return the header dict for the named role with the given
    ``X-User-ID``.  The role-name string must be one of the four
    canonical strings in ``ROLE_NAMES``; an unknown role-name produces
    a request the auth-tier rejects with ``ERR_UNAUTHENTICATED`` 401.

    This is the building block the omnibus RBAC-matrix test file uses
    to walk the 37×4 cell table parametrically without per-cell
    boilerplate.
    """
    if role_name not in ROLE_NAMES:
        raise ValueError(
            f"unknown role name {role_name!r}; expected one of {ROLE_NAMES}"
        )
    return build_user_headers(user_id, role_name)


#: The role-name to builder-function mapping the omnibus RBAC test uses
#: as the dispatch table.  Note the entity-backed-role entries take the
#: entity-id argument and the opaque-role entries are zero-argument; the
#: RBAC test wraps both shapes uniformly via a small adapter lambda.
ROLE_BUILDERS: Dict[str, Callable] = {
    ROLE_COMPANY_OPERATOR: company_operator_headers,
    ROLE_DRIVER: driver_headers,
    ROLE_REGULATOR_OFFICER: lambda _unused="": regulator_headers(),
    ROLE_TEST_HARNESS: lambda _unused="": test_harness_headers(),
}


__all__ = [
    "OPAQUE_REGULATOR_ID",
    "OPAQUE_TEST_HARNESS_ID",
    "BOOTSTRAP_COMPANY_OPERATOR_ID",
    "BOOTSTRAP_DRIVER_ID",
    "ROLE_NAMES",
    "ROLE_BUILDERS",
    "company_operator_headers",
    "driver_headers",
    "regulator_headers",
    "test_harness_headers",
    "bootstrap_company_operator_headers",
    "headers_for_role",
    "TEST_USERS",
]
