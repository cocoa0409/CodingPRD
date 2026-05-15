"""Authentication and authorization middleware.

The PRD §2.1 H3 paragraph names the contract: every request must carry
`X-User-ID` and `X-User-Role` headers; the role must be one of the four
canonical strings `CompanyOperator`, `RegulatorOfficer`, `Driver`, and
`TestHarness`; the entity-backed roles (`CompanyOperator`'s id is a
TransportCompany id, `Driver`'s id is a Driver id) must resolve to an
existing row in the appropriate entity table; the auth-tier failure is the
unified `ERR_UNAUTHENTICATED` 401 covering both the "missing or unparseable
header" case and the "the id names a non-existent backing entity" case;
the special-case "the very first `POST /v1/companies` request whose
`X-User-ID` does not yet correspond to a TransportCompany" is the bootstrap
exemption the §2.6 H3 paragraph names, where the auth-tier accepts any
non-empty `X-User-ID` and the server mints a fresh id in the response.

The RBAC matrix lookup at priority 200 — the §2.7's authorization tier —
fires `ERR_ROLE_NOT_PERMITTED` 403 on a cell that is the default-deny for
the requesting role. The cross-tenant ownership predicate at priority 530
(or the driver-self-only variant at 531) fires `ERR_CROSS_TENANT_ACCESS`
403 on a cell that is the conditional-allow whose per-row ownership
condition fails — the standard cross-tenant scenario from §2.6.

This module exports the central `current_principal()` accessor the handler-
side code reads to find the requester's role and id after the auth tier has
passed, and the `require_role(*roles)` decorator the per-endpoint handler
function wraps itself in to declare the endpoint's RBAC allow-set. The
per-endpoint cross-tenant ownership predicate is invoked by the handler
code itself (the predicate is per-resource — a permit's owner is the
permit's `company_id`, a trip's owner is the trip's parent permit's
`company_id`, etc. — and the handler is the one with the path-id and the
loaded resource row in hand, so the cross-tenant check is a per-handler
helper call rather than a generic middleware step). The standard pattern
is the handler calls `auth.require_role_and_tenant(allowed_roles, owner_id)`
after the URL-path-id has been resolved to a row whose owner-id is known.

The deferred-tool note: the auth tier's role-recognition-and-entity-
resolution is the same in production and in test mode (the test harness's
`TestHarness` role is rejected at the auth tier in a production
deployment by configuration, while it is the allow-only role on the two
`/_clock/advance` and `/_sweep/run` endpoints in test mode). The
`TestHarness` row's identity is opaque per the scaffold's-§1.7-roles-table
"identity: opaque" note, so the `X-User-ID` is accepted as the literal
non-empty string with no entity-table lookup.

The convention "the global request-id middleware in the envelope module
runs first, the auth middleware runs second" matters because the
error-envelope's `meta.api_request_id` is the same id across the auth
failure and the success paths, so the request-id stamp must precede the
auth check. Flask's `before_request` ordering is per-registration-time:
both hooks are registered in `create_app()` (the envelope's hook is
registered by `register_meta_hooks`, the auth's hook is registered by this
module's `register_auth_middleware`), and the registration order in the
factory function determines the firing order. The envelope's hook is
registered first by `__init__.py`'s `create_app` body, then the auth's
hook second, matching the desired ordering.

The endpoints in the test-harness-only allow-set (`/v1/_clock/advance`,
`/v1/_sweep/run`, and the conventional `/v1/_admin/reset`) require the
`TestHarness` role; the regular business endpoints reject `TestHarness`
with `ERR_ROLE_NOT_PERMITTED` 403 per the scaffold's-§1.7 matrix's
otherwise-uniform-deny TestHarness column. The `_admin/reset` endpoint is
the standard PRD-bench between-test-state-wipe affordance the test
fixtures invoke, scoped to TestHarness, that calls the three reset hooks
on the singletons (`init_store`, `init_clock`, `init_idempotency_registry`).

The §2.6's-bootstrap-exemption on `POST /v1/companies` is the special case
where the `X-User-ID` need not resolve to an existing TransportCompany row.
The auth-tier's "the entity-backed id must resolve" check is skipped on this
one endpoint-and-role pair; the handler's body-validation then proceeds with
the body's fields and the server mints a fresh UUID for the new company
row. Subsequent calls from the same operator carry the minted UUID as the
`X-User-ID`. The auth-tier's allow-list of "endpoints where the bootstrap
exemption applies" is the singleton set `{"POST /v1/companies"}` and is
hard-coded in the auth-middleware's "is-this-the-bootstrap-call" predicate.
"""

from __future__ import annotations

from typing import Optional

from flask import Flask, g, request

from .config import (
    CANONICAL_ROLES,
    HEADER_USER_ID,
    HEADER_USER_ROLE,
)
from .errors import APIError
from .store import find, table


# ---------------------------------------------------------------------------
# RBAC matrix
#
# Each entry's key is the canonical `"METHOD /full/path/pattern"` string
# matching Flask's url_map's `(methods, rule)` pair (the path is the
# parameterized URL pattern with the path-parameters in `<...>` braces as
# Flask renders them). Each entry's value is the set of role names allowed
# on the endpoint per the scaffold's §1.7 `rbac_matrix` block. A role
# outside the allow-set on the endpoint gets the `ERR_ROLE_NOT_PERMITTED`
# 403 at priority 200; a role in the allow-set whose per-row ownership
# predicate (the cross-tenant-or-self-only check) fails at the handler-side
# gets the `ERR_CROSS_TENANT_ACCESS` 403 at priority 530-or-531.
#
# The cross-tenant-ownership conditional-allow cells on the operator's-side
# reads-and-writes are listed in the allow-set the same as the regulator's
# unconditional-allow cells; the conditional check is the handler-side
# per-resource ownership-predicate the handler invokes after the §2.7
# existence tier has resolved the path-id to a row.
#
# The five canonical RBAC-deviation cells the §1.7-and-the-PRD-§2.6-paragraph
# enumerate are realized as the operator's-cross-tenant-403 on the "the
# addressed row exists but belongs to a different tenant" path and the
# driver's-self-only-403 on the three driver-self-read endpoints. The
# TestHarness-allow cells on the two test-mode endpoints are the dedicated
# allow-cells in an otherwise-all-deny TestHarness column.
# ---------------------------------------------------------------------------

# Allow-set per endpoint. The keys are the canonical `"METHOD /v1/<path>"`
# strings; the values are the frozensets of role names allowed on the
# endpoint. The handler decorator `require_role(*roles)` uses this table
# to assert the request's role is in the cell's allow-set.

RBAC_MATRIX: dict[str, frozenset[str]] = {
    # --- Companies: 6 endpoints from scaffold §1.5 (POST, GET-by-id, GET-list,
    # submit, approve, revoke). The submit-and-the-revoke-and-the-create-on-
    # children cells are the operator-and-regulator split. ---
    "POST /v1/companies": frozenset({"CompanyOperator"}),
    "GET /v1/companies/<company_id>": frozenset(
        {"CompanyOperator", "RegulatorOfficer"}
    ),
    "GET /v1/companies": frozenset({"CompanyOperator", "RegulatorOfficer"}),
    "POST /v1/companies/<company_id>/submit": frozenset({"CompanyOperator"}),
    "POST /v1/companies/<company_id>/approve": frozenset({"RegulatorOfficer"}),
    "POST /v1/companies/<company_id>/revoke": frozenset({"RegulatorOfficer"}),
    # --- Drivers: 3 endpoints (create-under-company, get-by-id, refresh-
    # endorsement). The create is operator-only; the read is the three-role
    # set with the cross-tenant-or-self-only condition; the refresh-
    # endorsement is regulator-only. ---
    "POST /v1/companies/<company_id>/drivers": frozenset({"CompanyOperator"}),
    "GET /v1/drivers/<driver_id>": frozenset(
        {"CompanyOperator", "RegulatorOfficer", "Driver"}
    ),
    "POST /v1/drivers/<driver_id>/refresh-endorsement": frozenset(
        {"RegulatorOfficer"}
    ),
    # --- Vehicles: 2 endpoints (create-under-company, get-by-id). ---
    "POST /v1/companies/<company_id>/vehicles": frozenset({"CompanyOperator"}),
    "GET /v1/vehicles/<vehicle_id>": frozenset(
        {"CompanyOperator", "RegulatorOfficer"}
    ),
    # --- VehicleInspections: 2 endpoints (append, list). The append is
    # regulator-only (the audit-integrity convention); the list is the
    # operator-and-regulator pair, with the operator's transitive-tenant
    # check via the parent vehicle's company. ---
    "POST /v1/vehicles/<vehicle_id>/inspections": frozenset(
        {"RegulatorOfficer"}
    ),
    "GET /v1/vehicles/<vehicle_id>/inspections": frozenset(
        {"CompanyOperator", "RegulatorOfficer"}
    ),
    # --- Routes: 5 endpoints (create-under-company, get-by-id, submit,
    # approve, reject). Operator handles the create-and-the-submit; the
    # regulator handles approve-and-reject; the get-by-id is the shared
    # read with the operator's transitive-tenant predicate. ---
    "POST /v1/companies/<company_id>/routes": frozenset({"CompanyOperator"}),
    "GET /v1/routes/<route_id>": frozenset(
        {"CompanyOperator", "RegulatorOfficer"}
    ),
    "POST /v1/routes/<route_id>/submit": frozenset({"CompanyOperator"}),
    "POST /v1/routes/<route_id>/approve": frozenset({"RegulatorOfficer"}),
    "POST /v1/routes/<route_id>/reject": frozenset({"RegulatorOfficer"}),
    # --- Permits: 7 endpoints (create-application, get-by-id, get-list,
    # issue, verify-compliance, renew, void-issue). The application-create
    # and the renewal are operator-side; the issue and the verify-compliance
    # and the void-issue are regulator-side; the read endpoints are the
    # shared operator-and-regulator pair. ---
    "POST /v1/permits": frozenset({"CompanyOperator"}),
    "GET /v1/permits/<permit_id>": frozenset(
        {"CompanyOperator", "RegulatorOfficer"}
    ),
    "GET /v1/permits": frozenset({"CompanyOperator", "RegulatorOfficer"}),
    "POST /v1/permits/<permit_id>/issue": frozenset({"RegulatorOfficer"}),
    "POST /v1/permits/<permit_id>/verify-compliance": frozenset(
        {"RegulatorOfficer"}
    ),
    "POST /v1/permits/<permit_id>/renew": frozenset({"CompanyOperator"}),
    "POST /v1/permits/<permit_id>/void-issue": frozenset({"RegulatorOfficer"}),
    # --- Trips: 5 endpoints (create-under-permit, get-by-id, depart, arrive,
    # abort). The driver-side read on the trip-row is the third RBAC-
    # deviation cell beyond the get-driver-by-id and the get-driver-penalty-
    # summary cells (the driver may read a trip whose `driver_id` is its own
    # id, the self-only condition at priority 531). The operator-only writes
    # cover the create-depart-arrive-abort quartet. ---
    "POST /v1/permits/<permit_id>/trips": frozenset({"CompanyOperator"}),
    "GET /v1/trips/<trip_id>": frozenset(
        {"CompanyOperator", "RegulatorOfficer", "Driver"}
    ),
    "POST /v1/trips/<trip_id>/depart": frozenset({"CompanyOperator"}),
    "POST /v1/trips/<trip_id>/arrive": frozenset({"CompanyOperator"}),
    "POST /v1/trips/<trip_id>/abort": frozenset({"CompanyOperator"}),
    # --- GPS reports: 2 endpoints (append, list). The append is the
    # operator's fleet-back-end's-side write; the list is the shared
    # operator-and-regulator read with the operator's transitive-tenant
    # check on the trip's parent permit's owning company. The driver-role
    # has no gps-read access per the scaffold's-§1.7 cell-prose's "the
    # driver's window into their own performance is the penalty-summary
    # endpoint" data-minimization choice. ---
    "POST /v1/trips/<trip_id>/gps-reports": frozenset({"CompanyOperator"}),
    "GET /v1/trips/<trip_id>/gps-reports": frozenset(
        {"CompanyOperator", "RegulatorOfficer"}
    ),
    # --- Penalties: 3 endpoints (create-manual, uphold-appeal, get-driver-
    # summary). The manual-create and the uphold are regulator-only; the
    # summary read is the three-role set with the operator's-transitive-
    # tenant and the driver's-self-only conditions. The fourth RBAC-
    # deviation cell — the driver's-self-only-on-the-penalty-summary —
    # lives on this endpoint per the scaffold's-§1.4 priority-531 rule
    # and the §2.6 driver-self-only paragraph. ---
    "POST /v1/penalties": frozenset({"RegulatorOfficer"}),
    "POST /v1/penalties/<penalty_id>/uphold": frozenset({"RegulatorOfficer"}),
    "GET /v1/drivers/<driver_id>/penalty-summary": frozenset(
        {"CompanyOperator", "RegulatorOfficer", "Driver"}
    ),
    # --- Test-harness mode endpoints: the clock-advance, the sweep-run,
    # and the conventional admin-reset (the between-test state-wipe the
    # PRD-bench fixture framework relies on). All three are TestHarness-
    # exclusive. ---
    "POST /v1/_clock/advance": frozenset({"TestHarness"}),
    "POST /v1/_sweep/run": frozenset({"TestHarness"}),
    "POST /v1/_admin/reset": frozenset({"TestHarness"}),
}


# The list of (method, path-pattern) pairs in the URL-map after the
# blueprints are registered, exposed here as the canonical 37-endpoint
# enumeration for the test-harness's matrix-coverage walk. The list is
# implicitly the keys of `RBAC_MATRIX` above.
ENDPOINT_KEYS: tuple[str, ...] = tuple(sorted(RBAC_MATRIX.keys()))


# The map from each role to its allow-set as the union of the per-endpoint
# allow-cells the role appears in. Useful for the test layer's "every role
# has the expected number of allow-cells" sanity check.
def role_allowed_endpoints(role: str) -> list[str]:
    """The list of endpoint keys the given role is allowed on."""
    return [key for key, allow in RBAC_MATRIX.items() if role in allow]


# The bootstrap-exempt endpoint for the company-create's first-call self-
# identity case. Per the §2.6 H3 paragraph's "the operator's very first
# request `POST /v1/companies` carries an `X-User-ID` that does not yet
# correspond to a TransportCompany row" rule, the auth-tier's "the
# entity-backed `X-User-ID` must resolve" check is skipped on this single
# endpoint-and-role pair so the create-of-self-identity case is workable.
# Subsequent calls from the same operator carry the minted UUID and the
# standard auth-tier-resolve rule applies.
_BOOTSTRAP_ENDPOINTS: frozenset[str] = frozenset({"POST /v1/companies"})


def _endpoint_key() -> str:
    """The current request's `"METHOD /pattern"` key for the RBAC matrix
    lookup. Flask exposes the matched URL rule via `request.url_rule.rule`
    (which is the parameterized pattern with `<...>` braces), and
    `request.method` is the HTTP verb. The combination is the canonical
    key used in the matrix and in the endpoint-coverage report.
    """
    method = request.method
    if request.url_rule is None:
        return f"{method} {request.path}"
    rule = request.url_rule.rule
    return f"{method} {rule}"


def _attach_principal_to_g(role: str, user_id: str) -> None:
    """Attach the resolved principal to Flask's `g` request-scoped storage
    so the handler-side code can read the caller's role and id via
    `current_principal()`. The standard convention is `g.principal_role`
    and `g.principal_id` and (for the entity-backed roles) `g.principal_entity`
    holding the resolved row reference.
    """
    g.principal_role = role
    g.principal_id = user_id


def _resolve_entity_backed_id(role: str, user_id: str) -> Optional[dict]:
    """Look up the entity row backing the requester's `X-User-ID` for the
    two entity-backed roles. Returns the row dict if found, or None if
    the id does not resolve, in which case the auth tier's
    `ERR_UNAUTHENTICATED` 401 fires per the §2.7-and-the-PRD-§2.1
    H3 paragraph's "a credential naming a non-existent backing entity is
    itself invalid" rule.

    The mapping role-to-entity-table is the scaffold-§1.7-roles' identity-
    kind discriminator's "entity_backed:<EntityName>" form:
        CompanyOperator -> TransportCompany row keyed by id
        Driver          -> Driver row keyed by id
    The two opaque roles (`RegulatorOfficer` and `TestHarness`) accept any
    non-empty string as the id without an entity lookup.
    """
    if role == "CompanyOperator":
        return find("TransportCompany", user_id)
    if role == "Driver":
        return find("Driver", user_id)
    return None  # opaque roles


def _check_auth() -> None:
    """The Flask `before_request` hook for the auth-tier checks. Fires
    `ERR_UNAUTHENTICATED` 401 on (a) missing-or-empty `X-User-Role` or
    `X-User-ID` headers, (b) a role-string outside the four-canonical
    set, or (c) for the two entity-backed roles, an id that does not
    resolve to an existing row in the role's-table.

    The endpoint-key-lookup for the RBAC `ERR_ROLE_NOT_PERMITTED` 403 at
    priority 200 fires next, gating the request on the role's presence
    in the endpoint's allow-cell. The per-resource cross-tenant 403 at
    priority 530-or-531 is the handler-side check on the loaded resource
    row (the helper `assert_cross_tenant_ownership` below is the
    canonical per-handler invocation).

    The auth tier runs unconditionally on every request: even the
    "the URL doesn't match any blueprint route" 404 path goes through
    this hook on Flask's request-pipeline. We let the 404-handler
    deal with the un-routed request by checking `request.url_rule is
    None` and skipping the auth-tier check on that specific case so a
    request to a non-existent URL gets the 404 envelope rather than an
    auth-tier 401-because-the-headers-are-missing failure. The
    canonical PRD-bench convention is that the not-found-route case is
    a framework-level 404 outside the §5 catalogue, and the test layer
    does not exercise it on the canonical endpoint set.
    """
    # Skip the no-route case so the 404 framework handler emits its
    # envelope rather than fighting the auth tier.
    if request.url_rule is None:
        return

    role = request.headers.get(HEADER_USER_ROLE, "").strip()
    user_id = request.headers.get(HEADER_USER_ID, "").strip()
    if not role or not user_id:
        raise APIError(
            "ERR_UNAUTHENTICATED",
            "Missing or empty X-User-ID or X-User-Role header.",
            details={"required_headers": [HEADER_USER_ID, HEADER_USER_ROLE]},
        )
    if role not in CANONICAL_ROLES:
        raise APIError(
            "ERR_UNAUTHENTICATED",
            f"Unrecognized role string {role!r}; expected one of "
            f"{sorted(CANONICAL_ROLES)}.",
            details={"role": role, "canonical_roles": sorted(CANONICAL_ROLES)},
        )

    # The entity-backed-roles' id-resolution step at priority 110 of
    # the §2.7 H3 priority table. The bootstrap exemption on the
    # `POST /v1/companies` endpoint skips the id-resolution for the
    # CompanyOperator role, on the §2.6's first-time-create convention.
    endpoint_key = _endpoint_key()
    if role in ("CompanyOperator", "Driver"):
        is_bootstrap = endpoint_key in _BOOTSTRAP_ENDPOINTS and role == "CompanyOperator"
        if not is_bootstrap:
            entity_row = _resolve_entity_backed_id(role, user_id)
            if entity_row is None:
                raise APIError(
                    "ERR_UNAUTHENTICATED",
                    f"X-User-ID {user_id!r} does not resolve to a {role}'s "
                    f"backing entity row.",
                    details={"role": role, "user_id": user_id},
                )
            g.principal_entity = entity_row

    _attach_principal_to_g(role, user_id)

    # The RBAC tier check at priority 200 — the role-allow-set lookup
    # against the canonical 37-cell matrix. A miss is the generic
    # `ERR_ROLE_NOT_PERMITTED` 403; a hit is the conditional-allow that
    # the handler then refines with the per-resource cross-tenant
    # ownership predicate at priority 530-or-531 (which is the
    # `ERR_CROSS_TENANT_ACCESS` 403, a separate error id with the same
    # HTTP status as the generic role-deny, distinguishable by the
    # specific id-string).
    allow_set = RBAC_MATRIX.get(endpoint_key)
    if allow_set is None:
        # An endpoint absent from the matrix is a coverage gap — the
        # test layer's matrix walk would flag this. The default is to
        # deny, on the principle "default deny is the safer fallback".
        raise APIError(
            "ERR_ROLE_NOT_PERMITTED",
            f"No RBAC entry for endpoint {endpoint_key!r}; default deny.",
            details={"endpoint": endpoint_key, "role": role},
        )
    if role not in allow_set:
        raise APIError(
            "ERR_ROLE_NOT_PERMITTED",
            f"Role {role!r} is not in the allow-set for endpoint "
            f"{endpoint_key!r}.",
            details={
                "endpoint": endpoint_key,
                "role": role,
                "allowed_roles": sorted(allow_set),
            },
        )


def register_auth_middleware(app: Flask) -> None:
    """Attach the auth-tier `before_request` hook to the Flask app. Called
    once from `create_app()` after the envelope's request-id stamp hook so
    the request-id is present on `flask.g` by the time the auth tier emits
    its error envelopes via the `APIError` handler.
    """
    app.before_request(_check_auth)


# ---------------------------------------------------------------------------
# Per-handler cross-tenant ownership-predicate helpers. The handler-side
# code calls these after the existence-tier has resolved the path-id to a
# row whose owning-tenant id can be computed. The predicate fires the
# `ERR_CROSS_TENANT_ACCESS` 403 at priority 530-or-531 (the latter for the
# driver-self-only-on-the-three-driver-self-endpoints variant).
#
# The §2.6 H3 paragraph names the canonical owning-tenant resolution for
# each entity kind: a TransportCompany's owning-tenant is its own id; a
# Driver's is the driver's `company_id`; a Vehicle's is the vehicle's
# `company_id`; a VehicleInspection's is the parent Vehicle's; a
# TransportRoute's is the route's `company_id`; a Permit's is the permit's
# `company_id`; a Trip's is the parent Permit's; a GPSReport's is the
# parent Trip's parent Permit's; a Penalty's is the subject's owning-tenant
# (the driver's `company_id` for a `DRIVER` subject, the vehicle's
# `company_id` for a `VEHICLE` subject, the company itself for a `COMPANY`
# subject).
# ---------------------------------------------------------------------------


def current_principal() -> tuple[str, str]:
    """The `(role, user_id)` pair of the current request's authenticated
    principal, as set by the auth tier's `before_request` hook. Raises
    `APIError(ERR_UNAUTHENTICATED, 401)` if called outside an
    authenticated request scope (which would be a defensive bug in the
    handler-side code since the auth hook fires on every request).
    """
    role = getattr(g, "principal_role", None)
    user_id = getattr(g, "principal_id", None)
    if not role or not user_id:
        raise APIError(
            "ERR_UNAUTHENTICATED",
            "No authenticated principal on the request context.",
        )
    return role, user_id


def resolve_owning_tenant(entity_name: str, row: dict) -> Optional[str]:
    """Compute the canonical owning-tenant TransportCompany id for the
    given row, walking the transitive parent chain per the §2.6 H3
    paragraph's per-entity rules. Returns the owning company's id as a
    string, or None if the row has no owning tenant (the TransportCompany
    entity's row's owning-tenant is its own id, so the function returns
    `row["id"]` on that case; an unknown entity name returns None and the
    caller's cross-tenant check is then a no-op).
    """
    if entity_name == "TransportCompany":
        return row.get("id")
    if entity_name == "Driver":
        return row.get("company_id")
    if entity_name == "Vehicle":
        return row.get("company_id")
    if entity_name == "VehicleInspection":
        # Walk up to the parent vehicle.
        parent_vehicle = find("Vehicle", row.get("vehicle_id"))
        return parent_vehicle.get("company_id") if parent_vehicle else None
    if entity_name == "TransportRoute":
        return row.get("company_id")
    if entity_name == "Permit":
        return row.get("company_id")
    if entity_name == "Trip":
        parent_permit = find("Permit", row.get("permit_id"))
        return parent_permit.get("company_id") if parent_permit else None
    if entity_name == "GPSReport":
        parent_trip = find("Trip", row.get("trip_id"))
        if not parent_trip:
            return None
        parent_permit = find("Permit", parent_trip.get("permit_id"))
        return parent_permit.get("company_id") if parent_permit else None
    if entity_name == "Penalty":
        subject_type = row.get("subject_type")
        subject_id = row.get("subject_id")
        if subject_type == "DRIVER":
            driver = find("Driver", subject_id)
            return driver.get("company_id") if driver else None
        if subject_type == "VEHICLE":
            vehicle = find("Vehicle", subject_id)
            return vehicle.get("company_id") if vehicle else None
        if subject_type == "COMPANY":
            return subject_id  # the subject is itself the company
    return None


def assert_cross_tenant_ownership(
    entity_name: str, row: dict, *, driver_self_only_path_id: Optional[str] = None
) -> None:
    """Enforce the cross-tenant ownership predicate. The standard
    operator-side check is "the operator's `X-User-ID` equals the row's
    owning-tenant id from `resolve_owning_tenant`". The driver-self-only
    variant (priority 531) on the three driver-self-read endpoints
    requires the Driver-role's `X-User-ID` equals the path's `{driver_id}`
    field (or the trip's `driver_id` field on the trip-read endpoint).

    The function does the right thing for each role per the §2.6 H3
    paragraph's "the regulator and the test-harness roles are exempt" rule:
    the regulator is always allowed (the regulatory-mandate exemption);
    the test-harness role is in practice only allowed on the two test-
    mode endpoints which are not tenanted; the operator is checked
    against the owning-tenant id; the driver is checked against the
    self-id path (with the explicit `driver_self_only_path_id` argument
    naming the value the driver's `X-User-ID` must match — typically the
    URL path's `{driver_id}` parameter or the row's-`driver_id` field on
    the trip-read).

    A failed check raises `APIError(ERR_CROSS_TENANT_ACCESS, 403)`.
    """
    role, user_id = current_principal()

    # Regulator and test-harness exempt.
    if role in ("RegulatorOfficer", "TestHarness"):
        return

    if role == "Driver":
        # The driver-self-only check: the path-id-or-target-id must equal
        # the requester's id.
        target = driver_self_only_path_id
        if target is None:
            # The default for a Driver-role request is the row's `id`
            # field interpreted as a driver-id — used by the driver-row
            # read endpoint where the row's own `id` is the path
            # parameter.
            target = row.get("id")
        if target != user_id:
            raise APIError(
                "ERR_CROSS_TENANT_ACCESS",
                f"Driver self-only check failed: requester id "
                f"{user_id!r} does not equal target driver id "
                f"{target!r}.",
                details={
                    "requester_id": user_id,
                    "target_id": target,
                    "rule": "driver-self-only",
                },
            )
        return

    # CompanyOperator branch: the standard cross-tenant ownership-by-
    # transitive-parent rule.
    if role == "CompanyOperator":
        owning_tenant = resolve_owning_tenant(entity_name, row)
        if owning_tenant is None:
            # Ambiguous case — the resolution returned None, which means
            # the entity's owning tenant cannot be determined from the
            # in-memory row alone. We treat the None case as "the
            # tenant is unresolvable, default to deny" so a buggy state
            # is not silently allowed.
            raise APIError(
                "ERR_CROSS_TENANT_ACCESS",
                f"Cannot resolve owning tenant for {entity_name} row "
                f"{row.get('id')!r}.",
                details={
                    "entity": entity_name,
                    "row_id": row.get("id"),
                },
            )
        if owning_tenant != user_id:
            raise APIError(
                "ERR_CROSS_TENANT_ACCESS",
                f"Operator id {user_id!r} does not own the {entity_name} "
                f"row whose tenant is {owning_tenant!r}.",
                details={
                    "operator_id": user_id,
                    "owning_tenant": owning_tenant,
                    "entity": entity_name,
                    "row_id": row.get("id"),
                },
            )
        return

    # Defensive fallback for any unhandled role.
    raise APIError(
        "ERR_ROLE_NOT_PERMITTED",
        f"Cross-tenant check on role {role!r} is unimplemented.",
    )


def assert_cross_tenant_company_id_match(company_id_path_param: str) -> None:
    """A specialized cross-tenant check the company-children-create
    endpoints (drivers/vehicles/routes under a `{company_id}` URL path)
    invoke. The operator's `X-User-ID` must equal the URL path's
    `{company_id}` literally. The regulator-and-test-harness roles are
    exempt (the regulator's RBAC cell for these endpoints is default-deny
    so the function is reached only by an `CompanyOperator` role, but the
    helper checks all four roles uniformly for defensive consistency).
    """
    role, user_id = current_principal()
    if role in ("RegulatorOfficer", "TestHarness"):
        return
    if role == "Driver":
        # Driver shouldn't reach these endpoints — the RBAC matrix's allow-
        # set does not include them. The RBAC tier fires before this
        # helper. Defensive defense.
        raise APIError(
            "ERR_CROSS_TENANT_ACCESS",
            "Driver role cannot access company-scoped children endpoints.",
            details={"role": role, "company_id": company_id_path_param},
        )
    if role == "CompanyOperator":
        if user_id != company_id_path_param:
            raise APIError(
                "ERR_CROSS_TENANT_ACCESS",
                f"Operator id {user_id!r} does not equal the path's "
                f"company_id {company_id_path_param!r}.",
                details={
                    "operator_id": user_id,
                    "path_company_id": company_id_path_param,
                },
            )


def lookup_path_resource(
    entity_name: str, path_id: str, not_found_id: str
) -> dict:
    """Combined existence-tier-and-find helper. The handler-side code calls
    this with the URL path's id parameter for the standard "the URL path's
    resource must resolve to a row in the named entity's table" check
    (priority 300 of the §2.7 H3 ordering). A non-resolvable path id raises
    the appropriate `ERR_<ENTITY>_NOT_FOUND` 404. The lookup is under the
    global `STATE_LOCK` of the `store` module.

    The returned row is the live mutable dict — the handler may write into
    its fields on the success path's-state-transition side-effects.
    """
    row = find(entity_name, path_id)
    if row is None:
        raise APIError(
            not_found_id,
            f"No such {entity_name} with id {path_id!r}.",
            details={"entity": entity_name, "id": path_id},
        )
    return row


def assert_role_in(*allowed: str) -> None:
    """Tier-2 RBAC explicit check the handler can call when the matrix
    layer's allow-set check is unambiguous and the handler wants a
    sanity-fail message naming the expected role-set. The `_check_auth`
    hook is the canonical pre-handler check using `RBAC_MATRIX`; this
    helper is here for cases where a handler wants the redundant
    in-handler assertion. The standard pattern is the matrix-tier hook
    is the single source of the role-allow-decision and the handler-side
    code does not re-check.
    """
    role, _ = current_principal()
    if role not in set(allowed):
        raise APIError(
            "ERR_ROLE_NOT_PERMITTED",
            f"Role {role!r} not in allowed set {sorted(allowed)!r}.",
            details={"role": role, "allowed_roles": sorted(allowed)},
        )
