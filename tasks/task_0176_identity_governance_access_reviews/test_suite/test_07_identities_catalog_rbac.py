"""Catalog & identity CRUD surface, computed identity fields, listing envelope,
audit immutability, terminal/deprovision state rules, optimistic-concurrency on
direct grants, and the role-based access controls.

Derived from PRD §3.1 (catalog), §3.2 (identities, orphan, deprovision), §2.3
(pagination), §2.4 (audit immutability), §2.8 (OCC), §2.1/§2.6 (RBAC and auth).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_entitlement_payload, create_role_payload, create_identity_payload,
    create_grant_payload, create_access_request_payload,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, build_user_headers,
    is_valid_uuid, assert_audit_event,
    fixtures,
)

CATALOG = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["access_manager_headers"]
CERTIFIER = TEST_USERS["certifier_headers"]


# --------------------------------------------------------------------------
# Entitlement catalog
# --------------------------------------------------------------------------
def test_create_entitlement_returns_201_with_defaults(api):
    """PRD §3.1: "Two optional attributes shape its risk behavior: is_privileged,
    a boolean that defaults to false ... and risk_weight, the base risk points
    holding it contributes, which defaults to 10".
    PRD §3.1: "Every entitlement carries a status that begins as ACTIVE".

    Creating an entitlement with only name+system_code -> 201; status ACTIVE,
    is_privileged false, risk_weight 10.

    Design: Corner/entities/create_entitlement_returns_201_with_defaults
    """
    data = validate_success(api.create_entitlement(
        create_entitlement_payload(name="Reader", system_code="SYS_R"), CATALOG), 201)
    assert data["status"] == "ACTIVE", data["status"]
    assert data["is_privileged"] is False, data["is_privileged"]
    assert data["risk_weight"] == 10, data["risk_weight"]


def test_get_entitlement_not_found(api):
    """PRD §2.5: "any referenced resource id supplied in the request body that does
    not resolve to an existing resource is rejected with ERR_NOT_FOUND."
    PRD §5: ERR_NOT_FOUND -> 404.

    GET /entitlements/{random-uuid} -> 404 ERR_NOT_FOUND.

    Design: Corner/entities/get_entitlement_not_found
    """
    resp = api.get_entitlement(NON_EXISTENT_UUID, CATALOG)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_entitlement_missing_required_field_rejected(api):
    """PRD §2.6: "Malformed bodies or missing required fields are rejected with
    ERR_VALIDATION".
    PRD §3.1: "An entitlement is created with a catalog display name and a
    system_code naming the target system it provisions into".

    POST /entitlements omitting system_code -> 400 ERR_VALIDATION.

    Design: Corner/entities/create_entitlement_missing_required_returns_validation
    """
    resp = api.create_entitlement({"name": "NoCode"}, CATALOG)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# --------------------------------------------------------------------------
# Identity system & computed fields
# --------------------------------------------------------------------------
def test_new_identity_is_system_minted_with_zero_counters(api):
    """PRD §3.2: "A new identity starts with status equal to ACTIVE and all of its
    computed counters and scores at zero."
    PRD §2.4: "id, a server-minted UUID with no type prefix".

    POST /identities -> bare-UUID id, all counters/scores 0.

    Design: Corner/entities/identity_id_is_system_minted_uuid_no_prefix
    """
    data = validate_success(api.create_identity(
        create_identity_payload(display_name="Fresh", email="fresh@x.com"), MANAGER), 201)
    assert is_valid_uuid(data["id"]), data["id"]
    assert data["active_grant_count"] == 0, data["active_grant_count"]
    assert data["privileged_entitlement_count"] == 0, data["privileged_entitlement_count"]
    assert data["effective_risk_score"] == 0, data["effective_risk_score"]


def test_nonhuman_identity_with_no_grants_is_orphan(api):
    """PRD §3.2: "it is true exactly when the identity's status is ACTIVE, its
    is_human is false, and its active_grant_count is zero ... A non-human identity
    with no grants is therefore orphaned the moment it is created".

    A non-human ACTIVE identity with zero grants has is_orphan == true.

    Design: Corner/entities/orphan_account_computed_for_nonhuman_with_no_grants
    """
    data = validate_success(api.create_identity(
        create_identity_payload(display_name="svc-batch", email="svc@x.com",
                                is_human=False), MANAGER), 201)
    got = validate_success(api.get_identity(data["id"], MANAGER), 200)
    assert got["is_orphan"] is True, got["is_orphan"]


def test_list_identities_paginated_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields limit, offset,
    total_count, and has_more inside the meta object of the envelope."

    With two identities, GET /identities?limit=1 returns one item, total_count 2,
    has_more true, response_type array.

    Design: Corner/entities/list_identities_paginated_envelope
    """
    validate_success(api.create_identity(
        create_identity_payload(display_name="A", email="a@x.com"), MANAGER), 201)
    validate_success(api.create_identity(
        create_identity_payload(display_name="B", email="b@x.com"), MANAGER), 201)

    data, meta = validate_paginated(api.list_identities(MANAGER, params={"limit": 1, "offset": 0}))
    assert len(data) == 1, len(data)
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]


def test_audit_event_is_immutable_no_version_field(api):
    """PRD §2.4: "An audit evidence record carries only id and created_at. Because
    audit evidence is append-only and immutable once written, it has no updated_at
    and no version field at all".

    An IDENTITY_DISABLED audit event exists after a disable and carries no version
    field.

    Design: Corner/entities/audit_event_is_immutable_no_version_field
    """
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Aud", email="aud@x.com"), MANAGER), 201)
    validate_success(api.disable_identity(identity["id"],
        {"expected_identity_version": identity["version"]}, MANAGER), 200)

    data, _meta = validate_paginated(api.list_identity_audit_events(
        identity["id"], MANAGER, params={"event_type": "IDENTITY_DISABLED"}))
    assert len(data) >= 1, "expected an IDENTITY_DISABLED audit event"
    event = data[0]
    assert event["event_type"] == "IDENTITY_DISABLED", event["event_type"]
    assert "version" not in event, "AuditEvent must not carry a version field"
    assert_audit_event(event)


# --------------------------------------------------------------------------
# Identity terminal / deprovision state rules
# --------------------------------------------------------------------------
def test_deprovision_active_identity_with_grant_blocked_by_state(api):
    """PRD §3.2: "Deprovisioning moves a DISABLED identity to the terminal
    DEPROVISIONED status; it is permitted only from DISABLED (otherwise
    ERR_INVALID_STATE)".

    Deprovisioning an ACTIVE identity holding a grant is rejected by the state gate
    -> 409 ERR_INVALID_STATE (the identity must be DISABLED first;
    ERR_IDENTITY_HAS_ACTIVE_GRANTS guards the DISABLED-with-grants path).

    Design: Corner/validations/deprovision_with_active_grants_rejected
    """
    de = validate_success(api.create_entitlement(
        create_entitlement_payload(name="DepE", system_code="DE", risk_weight=10), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Depi", email="depi@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(de["id"], identity["version"]), MANAGER), 201)

    resp = api.deprovision_identity(identity["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_deprovisioned_identity_is_terminal(api):
    """PRD §3.2: "Deprovisioning moves a DISABLED identity to the terminal
    DEPROVISIONED status".
    PRD §2.6: "if the target resource is not in a state from which the requested
    transition is defined, the request is rejected with ERR_INVALID_STATE."

    A DEPROVISIONED identity cannot be enabled -> 409 ERR_INVALID_STATE.

    Design: Corner/state_machines/deprovisioned_identity_is_terminal
    """
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Term", email="term@x.com"), MANAGER), 201)
    disabled = validate_success(api.disable_identity(identity["id"],
        {"expected_identity_version": identity["version"]}, MANAGER), 200)
    validate_success(api.deprovision_identity(identity["id"], MANAGER), 200)

    resp = api.enable_identity(identity["id"], {"expected_identity_version": disabled["version"]}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------
# Optimistic concurrency on direct grants (PRD §2.8)
# --------------------------------------------------------------------------
def test_direct_grant_with_correct_version_succeeds_and_bumps(api):
    """PRD §3.2: "When a direct grant is created it begins life in the provisioning
    stage and immediately activates, as described in §3.5, incrementing the
    identity's version by one as part of the operation."

    A direct grant with the correct expected_identity_version succeeds (201) and
    the identity's version increases by 1.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_grant_succeeds_and_bumps
    """
    occe = validate_success(api.create_entitlement(
        create_entitlement_payload(name="Occ", system_code="OC", risk_weight=10), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Occi", email="occ@x.com"), MANAGER), 201)
    before = identity["version"]
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(occe["id"], before), MANAGER), 201)

    got = validate_success(api.get_identity(identity["id"], MANAGER), 200)
    assert got["version"] == before + 1, f"expected {before + 1}, got {got['version']}"


def test_direct_grant_with_stale_version_rejected(api):
    """PRD §2.8: "The server compares that value to the identity's current version;
    if they do not match — because another writer has advanced the identity's
    version since the caller read it — the request is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    After a first direct grant bumps the version, a second grant still carrying the
    pre-bump expected_identity_version -> 412 ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_grant_rejected
    """
    st1 = validate_success(api.create_entitlement(
        create_entitlement_payload(name="St1", system_code="ST1", risk_weight=10), CATALOG), 201)
    st2 = validate_success(api.create_entitlement(
        create_entitlement_payload(name="St2", system_code="ST2", risk_weight=10), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Sti", email="sti@x.com"), MANAGER), 201)
    stale = identity["version"]
    validate_success(api.create_grant(identity["id"],
        create_grant_payload(st1["id"], stale), MANAGER), 201)

    resp = api.create_grant(identity["id"], create_grant_payload(st2["id"], stale), MANAGER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# --------------------------------------------------------------------------
# RBAC and authentication
# --------------------------------------------------------------------------
def test_certifier_cannot_create_entitlement(api):
    """PRD §2.1: "When an authenticated operator attempts an operation their role
    is not permitted to perform, the request is rejected with ERR_FORBIDDEN_ROLE."
    PRD §4: POST /entitlements is authorized for CatalogAdmin only.

    A Certifier calling POST /entitlements -> 403 ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/certifier_cannot_create_entitlement
    """
    resp = api.create_entitlement(
        create_entitlement_payload(name="Nope", system_code="NO"), CERTIFIER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_access_manager_cannot_approve_request(api):
    """PRD §2.1: "An AccessApprover decides access requests".
    PRD §4: POST /access-requests/{id}/approve is authorized for AccessApprover only.
    PRD §2.1: "When an authenticated operator attempts an operation their role is
    not permitted to perform, the request is rejected with ERR_FORBIDDEN_ROLE."

    An AccessManager calling approve -> 403 ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/access_manager_cannot_approve_request
    """
    eam = validate_success(api.create_entitlement(
        create_entitlement_payload(name="EntAm", system_code="EAM", risk_weight=10), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([eam["id"]], name="RoleAm"), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Ami", email="ami@x.com"), MANAGER), 201)
    mgr = build_user_headers("mgr-f", "AccessManager")
    req = validate_success(api.create_access_request(
        create_access_request_payload(identity["id"], role["id"]), mgr), 201)
    validate_success(api.submit_access_request(req["id"], mgr), 200)

    resp = api.approve_access_request(req["id"], {}, mgr)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: X-User-ID ... and X-User-Role ... If either header is missing, the
    request is rejected with ERR_UNAUTHENTICATED."

    A request with no auth headers -> 401 ERR_UNAUTHENTICATED.

    Design: Corner/rbac/unauthenticated_request_rejected
    """
    resp = api.get_identity(NON_EXISTENT_UUID, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
