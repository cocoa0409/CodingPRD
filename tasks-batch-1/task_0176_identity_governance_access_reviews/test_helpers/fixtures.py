"""Composite setup helpers for the Identity Governance API.

These encapsulate the multi-step API call sequences that the difficulty and
corner test instances need to reach a specific system state, so test functions
can focus on the trigger + assertions. Every helper builds its preconditions
from scratch using only PRD-declared endpoints (the server starts empty before
each test) and uses get_success_data() so setup failures surface as clear
"Setup step failed" errors.

Identity-version threading: direct grants, disable, and enable are OCC-guarded
(PRD §2.8) and bump Identity.version, so helpers always re-read the identity's
version (or use the value returned by the prior mutating call) before the next
OCC-guarded call.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers
from .api_client import api_client
from .factories import (
    create_entitlement_payload, create_role_payload, create_sod_policy_payload,
    create_identity_payload, create_grant_payload, create_access_request_payload,
    create_campaign_payload,
)
from .test_users import TEST_USERS


# Canonical role headers (all roles opaque — see test_users.py).
_CATALOG = TEST_USERS["catalog_admin_headers"]
_MANAGER = TEST_USERS["access_manager_headers"]
_APPROVER = TEST_USERS["access_approver_headers"]
_CAMPAIGN = TEST_USERS["campaign_admin_headers"]
_CERTIFIER = TEST_USERS["certifier_headers"]


# ==========================================================================
# Catalog primitives
# ==========================================================================
def create_entitlement(*, is_privileged=False, risk_weight=10, **overrides) -> dict:
    """Create one ACTIVE entitlement. risk_weight defaults to 10 (PRD §3.1)."""
    payload = create_entitlement_payload(
        is_privileged=is_privileged, risk_weight=risk_weight, **overrides
    )
    return get_success_data(api_client.create_entitlement(payload, _CATALOG))


def create_role(entitlement_ids, **overrides) -> dict:
    """Create one ACTIVE role bundling the given entitlement ids."""
    payload = create_role_payload(entitlement_ids, **overrides)
    return get_success_data(api_client.create_role(payload, _CATALOG))


def create_sod_policy(entitlement_a_id, entitlement_b_id, *, severity="HARD", **overrides) -> dict:
    """Create one ACTIVE segregation-of-duties policy over a toxic pair."""
    payload = create_sod_policy_payload(
        entitlement_a_id, entitlement_b_id, severity=severity, **overrides
    )
    return get_success_data(api_client.create_sod_policy(payload, _CATALOG))


def create_identity(*, is_human=True, **overrides) -> dict:
    """Create one ACTIVE identity with all counters at zero."""
    payload = create_identity_payload(is_human=is_human, **overrides)
    return get_success_data(api_client.create_identity(payload, _MANAGER))


def get_identity(identity_id) -> dict:
    return get_success_data(api_client.get_identity(identity_id, _MANAGER))


# ==========================================================================
# Tier 1/3: Direct grants (create -> auto-activate), version threaded
# ==========================================================================
def direct_grant(identity_id, entitlement_id, expected_version, **overrides) -> dict:
    """Provision one direct grant against the identity at the supplied version.
    The grant is created in PROVISIONING and auto-activates to ACTIVE
    (PRD §3.2, §3.5)."""
    payload = create_grant_payload(entitlement_id, expected_version, **overrides)
    return get_success_data(api_client.create_grant(identity_id, payload, _MANAGER))


def grant_entitlement(identity, entitlement_id, **overrides) -> dict:
    """Direct-grant an entitlement to an identity using the identity's current
    version (re-reads it first), returning the new grant."""
    fresh = get_identity(identity["id"])
    return direct_grant(identity["id"], entitlement_id, fresh["version"], **overrides)


def setup_identity_with_grants(entitlement_specs):
    """Create a fresh identity and direct-grant each entitlement in turn,
    threading the identity version between OCC-guarded grant creates.

    entitlement_specs: list of dicts forwarded to create_entitlement
        (e.g. {"is_privileged": True, "risk_weight": 20}).
    Returns (identity_dict, [entitlement_dict...], [grant_dict...]).
    """
    identity = create_identity()
    entitlements = []
    grants = []
    version = identity["version"]
    for spec in entitlement_specs:
        ent = create_entitlement(**spec)
        entitlements.append(ent)
        grant = direct_grant(identity["id"], ent["id"], version)
        grants.append(grant)
        # Direct grant bumps Identity.version by 1 (PRD §3.2).
        version = get_identity(identity["id"])["version"]
    return get_identity(identity["id"]), entitlements, grants


# ==========================================================================
# Tier 2/3: Access-request workflow (raise -> submit [-> approve])
# ==========================================================================
def raise_request(identity_id, role_id, requester_user_id, **overrides) -> dict:
    """Raise a DRAFT access request as a specific AccessManager operator id."""
    headers = build_user_headers(requester_user_id, "AccessManager")
    payload = create_access_request_payload(identity_id, role_id, **overrides)
    return get_success_data(api_client.create_access_request(payload, headers))


def submit_request(request_id, requester_user_id) -> dict:
    """Submit a request as the same AccessManager operator that raised it."""
    headers = build_user_headers(requester_user_id, "AccessManager")
    return get_success_data(api_client.submit_access_request(request_id, headers))


def setup_submitted_request(*, identity=None, role_id=None, entitlement_specs=None,
                            requester_user_id="mgr-1", request_overrides=None):
    """Build a SUBMITTED access request ready for an approver action.

    If identity is None a fresh ACTIVE identity is created. If role_id is None a
    role is created bundling entitlements from entitlement_specs (default: one
    non-privileged risk-10 entitlement). Returns
    (identity_dict, role_dict, request_dict).
    """
    if identity is None:
        identity = create_identity()
    if role_id is None:
        specs = entitlement_specs or [{"risk_weight": 10}]
        ents = [create_entitlement(**s) for s in specs]
        role = create_role([e["id"] for e in ents])
        role_id = role["id"]
    else:
        role = get_success_data(api_client.get_role(role_id, _MANAGER))
    req = raise_request(identity["id"], role_id, requester_user_id,
                        **(request_overrides or {}))
    submit_request(req["id"], requester_user_id)
    req = get_success_data(api_client.get_access_request(req["id"], _MANAGER))
    return identity, role, req


def approve_request(request_id, approver_user_id, **payload) -> dict:
    """Approve a request as a specific AccessApprover operator id."""
    headers = build_user_headers(approver_user_id, "AccessApprover")
    return get_success_data(api_client.approve_access_request(request_id, payload, headers))


# ==========================================================================
# Tier 5: Certification campaign lifecycle
# ==========================================================================
def setup_launched_campaign(scope_role_id, *, window_start="2026-06-01T00:00:00Z",
                            window_end="2026-06-30T00:00:00Z") -> dict:
    """Create + launch a campaign scoped to a role. Returns the launched
    campaign (status ACTIVE)."""
    payload = create_campaign_payload(scope_role_id, window_start, window_end)
    camp = get_success_data(api_client.create_campaign(payload, _CAMPAIGN))
    return get_success_data(api_client.launch_campaign(camp["id"], _CAMPAIGN))


def item_for_grant(grant_id) -> dict:
    """Fetch the certification item that references a given grant."""
    data, _ = _list(api_client.list_certification_items(_CERTIFIER, params={"grant_id": grant_id}))
    assert data, f"no certification item found for grant {grant_id}"
    return data[0]


def setup_campaign_over_n_identical_grants(n, *, risk_weight=10, is_privileged=False):
    """Create one role bundling a single entitlement, direct-grant it to N fresh
    identities, then create + launch a campaign scoped to that role.

    Returns (campaign_dict, role_dict, entitlement_dict, [grant_dict...]).
    Each grant is for a distinct identity so item_count == n.
    """
    ent = create_entitlement(is_privileged=is_privileged, risk_weight=risk_weight)
    role = create_role([ent["id"]])
    grants = []
    for _ in range(n):
        identity = create_identity()
        grant = direct_grant(identity["id"], ent["id"], identity["version"])
        grants.append(grant)
    campaign = setup_launched_campaign(role["id"])
    return campaign, role, ent, grants


# ==========================================================================
# Helpers
# ==========================================================================
def _list(response):
    """Validate a paginated list response leniently and return (data, meta)."""
    body = response.json()
    assert 200 <= response.status_code < 300, (
        f"List call failed HTTP {response.status_code}: {response.text}"
    )
    return body["data"], body["meta"]


def list_identity_audit_events(identity_id, event_type=None) -> list:
    params = {"event_type": event_type} if event_type else None
    data, _ = _list(api_client.list_identity_audit_events(identity_id, _MANAGER, params=params))
    return data
