"""Registration, commissioning lifecycle, RBAC, auth, and listing.

Covers queue B (Corner) instances for entities, the notary state machine entry,
RBAC denial, authentication, fiscal bond-minimum gate, and list envelopes.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_jurisdiction,
    assert_notary,
    assert_audit_event,
    create_jurisdiction_payload,
    register_notary_payload,
    create_bond_payload,
    TEST_USERS,
    make_notary_headers,
)
import test_helpers as th

CA = TEST_USERS["commission_authority_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ===========================================================================
# Entity creation / defaults / system fields
# ===========================================================================
def test_create_jurisdiction_returns_201_with_echoed_fields(api):
    """PRD §3.1: "A `CommissionAuthority` operator creates a jurisdiction by
    supplying its two-letter `state_code` (uppercase, exactly two characters,
    and unique across all jurisdictions), a `ron_allowed` flag declaring whether
    Remote Online Notarization is permitted there, a `bond_minimum_cents` figure
    giving the smallest surety bond face value that will support a commission, a
    `commission_term_months` value that must be one of 48, 60, 96, or 120 months"
    PRD §4: "Operations that create a new, stand-alone resource — a jurisdiction,
    a fee schedule row, a notary, a bond, a renewal, a session, a signer, a
    document, a journal entry, or a complaint — return `201 Created`."

    Design: Corner/entities/create_jurisdiction_returns_201_with_fields
    """
    payload = create_jurisdiction_payload(
        state_code="CA", ron_allowed=True, bond_minimum_cents=1_500_000,
        commission_term_months=48, renewal_grace_days=30,
        session_act_fee_cap_cents=2000, ron_surcharge_cap_cents=2500,
    )
    data = validate_success(api.create_jurisdiction(payload, CA), expected_status=201)
    assert_jurisdiction(data)
    assert data["state_code"] == "CA"
    assert data["commission_term_months"] == 48
    assert data["version"] == 1


def test_get_notary_not_found_returns_404(api):
    """PRD §2.8: "The server validates path identifiers left to right and rejects
    the request with `ERR_NOT_FOUND` at the first identifier in the path that does
    not resolve to an existing record."

    Design: Corner/entities/get_notary_not_found_returns_404
    """
    resp = api.get_notary("00000000-0000-4000-8000-000000000000", CA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_register_notary_missing_email_returns_400(api):
    """PRD §3.2: "The applicant provides the `jurisdiction_id` of the commissioning
    state, a `full_name`, an `email` that must be unique across all notaries, and
    an optional `enotary_requested` flag"
    PRD §2.9: "a missing required field, a wrongly typed value, or an enum value
    outside its declared set yields `ERR_INVALID_REQUEST` (400)"

    Design: Corner/entities/create_notary_missing_required_email_returns_400
    """
    jx = validate_success(api.create_jurisdiction(create_jurisdiction_payload(state_code="NY"), CA), 201)
    resp = api.register_notary({"jurisdiction_id": jx["id"], "full_name": "No Email"}, ANON)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_register_notary_enotary_requested_defaults_false(api):
    """PRD §3.2: "an optional `enotary_requested` flag indicating that they wish to
    be authorized for RON; when omitted, `enotary_requested` is `false`. A freshly
    registered notary begins in `APPLIED` status with `enotary_authorized` set to
    `false`"

    Design: Corner/entities/notary_enotary_requested_defaults_false
    """
    jx = validate_success(api.create_jurisdiction(create_jurisdiction_payload(state_code="WA"), CA), 201)
    data = validate_success(api.register_notary(register_notary_payload(jx["id"], email="def@x.com"), ANON), 201)
    assert data["enotary_requested"] is False
    assert data["enotary_authorized"] is False
    assert data["status"] == "APPLIED"


def test_register_notary_forces_system_fields(api):
    """PRD §3.2: "A freshly registered notary begins in `APPLIED` status with
    `enotary_authorized` set to `false` ... The computed fields `risk_score` and
    `lifetime_fees_collected_cents` both begin at 0."

    Design: Corner/entities/notary_status_system_field_ignores_input
    """
    jx = validate_success(api.create_jurisdiction(create_jurisdiction_payload(state_code="OR"), CA), 201)
    data = validate_success(api.register_notary(register_notary_payload(jx["id"], email="sys@x.com"), ANON), 201)
    assert data["status"] == "APPLIED"
    assert data["risk_score"] == 0
    assert data["lifetime_fees_collected_cents"] == 0


def test_new_notary_initial_state_is_applied_version_one(api):
    """PRD §3.2: "A freshly registered notary begins in `APPLIED` status"
    PRD §2.4: "The `version` field is an integer that starts at 1 and increments
    by one on every mutation"

    Design: Corner/state_machines/new_notary_initial_state_is_applied
    """
    jx = validate_success(api.create_jurisdiction(create_jurisdiction_payload(state_code="TX"), CA), 201)
    data = validate_success(api.register_notary(register_notary_payload(jx["id"], email="init@x.com"), ANON), 201)
    assert data["status"] == "APPLIED"
    assert data["version"] == 1


def test_audit_event_is_append_only_no_version_field(api):
    """PRD §2.4: "Audit events are an append-only trail and carry only `id` and
    `created_at`; they have neither an `updated_at` field nor a `version` field,
    because once written they are never modified."
    PRD §3.2: "A commissioning event is written to the audit trail."

    Design: Corner/entities/audit_event_is_immutable_no_version_field
    """
    ctx = th.setup_commissioned_notary(notary_overrides={"email": "audit@x.com"})
    data, meta = validate_paginated(api.list_notary_audit_events(ctx["notary"]["id"], CA))
    assert len(data) >= 1, "commissioning should append at least one audit event"
    for ev in data:
        assert_audit_event(ev)
    assert any(ev["action"] == "NOTARY_COMMISSIONED" for ev in data), (
        "expected a NOTARY_COMMISSIONED audit event"
    )


# ===========================================================================
# Notary state machine corners
# ===========================================================================
def test_commission_already_commissioned_returns_invalid_state(api):
    """PRD §3.2: "Commissioning advances a notary from `APPLIED` to `COMMISSIONED`
    ... it requires the notary to be in `APPLIED` status, failing otherwise with
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/commission_already_commissioned_notary_returns_invalid_state
    """
    ctx = th.setup_commissioned_notary(notary_overrides={"email": "twice@x.com"})
    resp = api.commission_notary(ctx["notary"]["id"], CA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_reinstate_revoked_notary_returns_invalid_state(api):
    """PRD §3.9: "A `SUSPENDED` notary may be reinstated to `ACTIVE` by a
    `CommissionAuthority` operator. Reinstatement requires the notary to be
    `SUSPENDED` (else `ERR_INVALID_STATE`)"
    PRD §3.2: "`REJECTED` and `REVOKED` are the terminal states of the notary
    lifecycle."

    Design: Corner/state_machines/revoked_notary_is_terminal_no_reinstate
    """
    ctx = th.setup_revoked_notary()
    assert ctx["notary"]["status"] == "REVOKED"
    resp = api.reinstate_notary(ctx["notary"]["id"], CA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ===========================================================================
# Fiscal gate: bond below minimum
# ===========================================================================
def test_activate_bond_below_minimum_returns_bond_below_minimum(api):
    """PRD §3.2: "Activating a bond moves it from `PENDING` to `ACTIVE`: ... it
    requires `face_value_cents` to be at least the commissioning jurisdiction's
    `bond_minimum_cents` — a shortfall is rejected with `ERR_BOND_BELOW_MINIMUM`."

    Design: Corner/validations/commission_with_bond_below_minimum_returns_bond_below_minimum
    """
    jx = th.create_jurisdiction(state_code="TX", bond_minimum_cents=500_000)
    notary = th.register_notary(jx["id"], email="low@x.com")
    bond = th.create_bond(notary["id"], jx["id"], face_value_cents=400_000)
    resp = api.activate_bond(bond["id"], CA)
    validate_error(resp, ApiErrorId.ERR_BOND_BELOW_MINIMUM.value, expected_status=409)
    refreshed = validate_success(api.get_bond(bond["id"], CA))
    assert refreshed["status"] == "PENDING"


# ===========================================================================
# RBAC + auth
# ===========================================================================
def test_notary_cannot_commission_returns_unauthorized(api):
    """PRD §2.1: "A request that is well-authenticated but attempts an operation
    its role is not permitted to perform is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.2: "Commissioning advances a notary from `APPLIED` to `COMMISSIONED`
    and is performed by a `CommissionAuthority` operator."

    Design: Corner/rbac/notary_cannot_commission_returns_unauthorized
    """
    caller = th.setup_active_notary(notary_overrides={"email": "caller@x.com"})["notary"]
    jx2 = th.create_jurisdiction(state_code="NV")
    target = th.register_notary(jx2["id"], email="target@x.com")
    resp = api.commission_notary(target["id"], make_notary_headers(caller["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
    refreshed = validate_success(api.get_notary(target["id"], CA))
    assert refreshed["status"] == "APPLIED"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that presents an
    `X-User-Role` value outside this known set, is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_on_protected_endpoint_returns_unauthenticated
    """
    resp = api.list_complaints({})  # no auth headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


# ===========================================================================
# Listing / pagination envelope
# ===========================================================================
def test_list_notaries_returns_paginated_array(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_notaries_pagination_envelope
    """
    jx = th.create_jurisdiction(state_code="TX")
    th.register_notary(jx["id"], email="p1@x.com")
    th.register_notary(jx["id"], email="p2@x.com")
    data, meta = validate_paginated(api.list_notaries(CA))
    assert isinstance(data, list)
    assert meta["total_count"] >= 2
    assert "has_more" in meta
    assert meta["limit"] == 10  # default limit


def test_filtered_list_bonds_by_notary_id(api):
    """PRD §3.9 / §4: "GET | `/bonds` | List bonds | CommissionAuthority, Notary".
    PRD §2.3: "list results are ordered by their `created_at` timestamp in
    ascending order."
    PRD §3.2: "A `CommissionAuthority` operator creates a `Bond` for the notary by
    supplying the `notary_id`"

    Design: Corner/endpoints/filtered_list_bonds_by_notary_id
    """
    jx = th.create_jurisdiction(state_code="TX")
    notary = th.register_notary(jx["id"], email="fb@x.com")
    bond = th.create_bond(notary["id"], jx["id"])
    # also create an unrelated notary+bond to confirm filtering
    other = th.register_notary(jx["id"], email="other@x.com")
    th.create_bond(other["id"], jx["id"])
    data, meta = validate_paginated(api.list_bonds(CA, params={"notary_id": notary["id"]}))
    assert all(b["notary_id"] == notary["id"] for b in data), "filter must scope to notary_id"
    assert any(b["id"] == bond["id"] for b in data), "filtered list must contain the bond"
