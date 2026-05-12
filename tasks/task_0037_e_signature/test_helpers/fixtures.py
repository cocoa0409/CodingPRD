"""Composite setup helpers for the E-Signature test suite.

The PRD's lifecycle has many interlocking phases -- Template (ACTIVE) ->
TemplateVersion (DRAFT -> PUBLISHED -> DEPRECATED) -> Contract (DRAFT ->
PENDING_SIGN -> PARTIALLY_SIGNED -> COMPLETED|VOIDED) -> SigningStep
(PENDING -> ACTIVE -> SIGNED|SKIPPED|REJECTED) -> SigningParty (WAITING ->
AUTHENTICATING -> SIGNED|DECLINED|SKIPPED) -> EvidencePackage (PENDING ->
GENERATING -> SEALED -> EXPORTED). Most interesting tests need the system
in a non-initial state.

Identity threading (PRD §2.1):

- TemplateAdmin / ContractInitiator / Signer / EvidenceArchivist are
  entity-backed: ownership/segregation-gated calls MUST use the
  per-instance make_*_headers() builders with the actual OrgUser.id.
  In particular:

    * The publisher's OrgUser.id is recorded on the TemplateVersion
      (PRD §3.1 / §3.3); contract activation is compared against it.

    * The initiator's OrgUser.id is recorded on the Contract as
      initiator_user_id (PRD §3.2); the seal action is compared against it.

    * The signer's OrgUser.id must equal the SigningParty.signer_user_id
      (PRD §3.5); /sign and /decline calls use it.

  Helpers below mint stable per-test OrgUser.id strings for each role and
  thread them through every dependent call.

Setup calls use get_success_data (lenient validator) so broken
preconditions surface as obvious errors, not confusing assertion failures.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    branch_condition,
    create_contract_payload,
    create_identity_verification_payload,
    create_reminder_rule_payload,
    create_signing_party_payload,
    create_signing_step_payload,
    create_template_payload,
    create_template_version_payload,
    factor_attempt,
    fire_reminder_payload,
    seal_evidence_payload,
    sign_party_payload,
    signature_position,
    unique_blob_sha256,
    unique_id,
    unique_idempotency_key,
    unique_org_id,
    unique_template_name,
    unique_token_value,
    unique_user_id,
    variable_field,
)
from .test_users import (
    TEST_USERS,
    make_contract_initiator_headers,
    make_evidence_archivist_headers,
    make_platform_admin_headers,
    make_signer_headers,
    make_system_sweeper_headers,
    make_template_admin_headers,
)


# ===========================================================================
# Time helpers (PRD §2.4 -- ISO 8601 UTC with three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_seconds(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(seconds=n))


def add_minutes(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(minutes=n))


def add_hours(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


# Default base instant; tests advance from here. Each test session gets a
# fresh wall clock; tests that need to advance the clock pin their own.
DEFAULT_NOW_ISO = "2026-05-10T00:00:00.000Z"


# ===========================================================================
# Test-driving wrappers (PRD §3.8, §4)
# ===========================================================================
_last_known_clock_iso: Optional[str] = None


def advance_clock(to_iso: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §4 mounts this as a PlatformAdmin-only
    test driver. PRD §3.8: 'The clock only moves forward -- a `to` value
    earlier than the current logical clock is rejected; a `to` value equal
    to the current logical clock is idempotent.'

    If the requested time is at or before the last known clock, this
    helper silently NO-OPs (idempotent) and returns an empty dict.
    """
    global _last_known_clock_iso
    if (_last_known_clock_iso is not None
            and parse_iso(to_iso) <= parse_iso(_last_known_clock_iso)):
        return {}
    res = api_client.advance_clock(
        to_iso, headers or TEST_USERS["platform_admin_headers"]
    )
    data = get_success_data(res)
    _last_known_clock_iso = to_iso
    return data


def current_clock_iso() -> str:
    """Best-effort mirror of the most recent clock instant we've advanced
    to. Falls back to bootstrapping from the server's actual clock by
    issuing a benign advance to the default base instant; the server
    returns its own current `now` in the response payload, which we then
    use as the test session's logical baseline."""
    global _last_known_clock_iso
    if _last_known_clock_iso is not None:
        return _last_known_clock_iso
    # Bootstrap: advance to DEFAULT_NOW_ISO. If the server's current
    # clock is already past that (wall-clock case), the server reports
    # its actual now in the response data; we adopt it as the baseline.
    res = api_client.advance_clock(
        DEFAULT_NOW_ISO, TEST_USERS["platform_admin_headers"]
    )
    data = get_success_data(res)
    server_now = data.get("now") or DEFAULT_NOW_ISO
    _last_known_clock_iso = server_now
    return _last_known_clock_iso


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /_sweep/run. PRD §3.8: 'A sweep-run capability runs the
    periodic sweep on demand, returning a small object indicating how many
    contracts auto-voided and how many reminders fired in this run.'"""
    return get_success_data(
        api_client.run_sweep(
            headers or TEST_USERS["platform_admin_headers"]
        )
    )


# ===========================================================================
# Tier 1 -- Single-entity creation
# ===========================================================================
def stable_user_id(prefix: str = "u") -> str:
    """Mint a stable OrgUser.id string used as X-User-ID. PRD §2.1: for
    entity-backed roles X-User-ID is the OrgUser.id; the platform compares
    resource fields (initiator_user_id, signer_user_id, ...) directly to
    this value."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_template(
    *,
    admin_id: Optional[str] = None,
    owner_org_id: Optional[str] = None,
    permission_scope: Optional[str] = None,
    category: str = "OTHER",
    name: Optional[str] = None,
) -> Tuple[Dict[str, Any], str, str]:
    """Create a Template owned by `owner_org_id` and acted by TemplateAdmin
    OrgUser.id `admin_id`. Returns (template, admin_id, owner_org_id).

    Both ids are minted if not provided so the caller can thread them into
    later ownership-gated calls.
    """
    admin_id = admin_id or stable_user_id("admin")
    owner_org_id = owner_org_id or unique_org_id()
    payload = create_template_payload(
        name=name or unique_template_name(),
        category=category,
        owner_org_id=owner_org_id,
        permission_scope=permission_scope,
    )
    res = api_client.create_template(
        payload, make_template_admin_headers(admin_id)
    )
    return get_success_data(res), admin_id, owner_org_id


def create_template_version(
    *,
    template_id: str,
    admin_id: str,
    page_count: int = 1,
    variable_fields: Optional[List[Dict[str, Any]]] = None,
    signature_positions: Optional[List[Dict[str, Any]]] = None,
    document_blob_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a DRAFT TemplateVersion under `template_id`."""
    payload = create_template_version_payload(
        document_blob_sha256=document_blob_sha256,
        page_count=page_count,
        variable_fields=variable_fields,
        signature_positions=signature_positions,
    )
    res = api_client.create_template_version(
        template_id, payload, make_template_admin_headers(admin_id)
    )
    return get_success_data(res)


def publish_template_version(
    *, template_id: str, version_id: str, admin_id: str,
) -> Dict[str, Any]:
    """PRD §3.1: publish requires DRAFT and >=1 signature_position."""
    res = api_client.publish_template_version(
        template_id, version_id,
        make_template_admin_headers(admin_id),
    )
    return get_success_data(res)


def create_published_template(
    *,
    admin_id: Optional[str] = None,
    owner_org_id: Optional[str] = None,
    permission_scope: Optional[str] = None,
    page_count: int = 1,
    variable_fields: Optional[List[Dict[str, Any]]] = None,
    signature_positions: Optional[List[Dict[str, Any]]] = None,
    category: str = "OTHER",
) -> Dict[str, Any]:
    """Convenience: Template + DRAFT TemplateVersion + publish.

    Returns dict with keys: template, version, admin_id, owner_org_id.
    """
    template, admin_id, owner_org_id = create_template(
        admin_id=admin_id, owner_org_id=owner_org_id,
        permission_scope=permission_scope, category=category,
    )
    version = create_template_version(
        template_id=template["id"], admin_id=admin_id,
        page_count=page_count,
        variable_fields=variable_fields,
        signature_positions=signature_positions,
    )
    published = publish_template_version(
        template_id=template["id"], version_id=version["id"],
        admin_id=admin_id,
    )
    return {
        "template": template,
        "version": published,
        "admin_id": admin_id,
        "owner_org_id": owner_org_id,
    }


# ---------------------------------------------------------------------------
# Tier 2 -- Contract creation in DRAFT
# ---------------------------------------------------------------------------
def create_contract_in_draft(
    *,
    template_version_id: str,
    initiator_id: Optional[str] = None,
    initiator_org_id: Optional[str] = None,
    title: Optional[str] = None,
    variable_values: Optional[Dict[str, Any]] = None,
    expires_at: Optional[str] = None,
    expires_at_offset_hours: float = 24.0,
    reinitiated_from_contract_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Create a Contract from a published TemplateVersion. Returns
    (contract, initiator_id) with initiator_id minted/threaded for
    downstream ownership-gated calls.

    expires_at defaults to current_clock_iso() + expires_at_offset_hours.
    """
    initiator_id = initiator_id or stable_user_id("init")
    if expires_at is None:
        base = current_clock_iso()
        expires_at = add_hours(base, expires_at_offset_hours)
    payload = create_contract_payload(
        template_version_id=template_version_id,
        title=title,
        variable_values=variable_values,
        expires_at=expires_at,
        reinitiated_from_contract_id=reinitiated_from_contract_id,
    )
    headers = make_contract_initiator_headers(initiator_id)
    if initiator_org_id is not None:
        # The PRD has no input field for initiator_org_id; it's copied from
        # the authenticated request (PRD §3.2). Many implementations attach
        # the org-id via an extra header (e.g., X-Org-ID) -- callers can
        # extend headers via overrides if they need that. We ship plain
        # headers here; tests that need cross-org comparison will use
        # whatever the implementation surfaces.
        headers = dict(headers)
        headers["X-Org-ID"] = initiator_org_id
    res = api_client.create_contract(payload, headers)
    return get_success_data(res), initiator_id


def append_signing_step(
    *,
    contract_id: str,
    initiator_id: str,
    step_index: int,
    mode: str = "PARALLEL_COUNTERSIGN",
    branch: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = create_signing_step_payload(
        step_index=step_index, mode=mode, branch_condition=branch,
    )
    res = api_client.create_signing_step(
        contract_id, payload,
        make_contract_initiator_headers(initiator_id),
    )
    return get_success_data(res)


def append_signing_party(
    *,
    contract_id: str,
    signing_step_id: str,
    initiator_id: str,
    signer_user_id: str,
    role_key: str = "PARTY_A",
    signer_type: str = "INDIVIDUAL",
    signer_org_id: Optional[str] = None,
    delegation_authorization_id: Optional[str] = None,
    required_auth_factors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload = create_signing_party_payload(
        role_key=role_key,
        signer_type=signer_type,
        signer_user_id=signer_user_id,
        signer_org_id=signer_org_id,
        delegation_authorization_id=delegation_authorization_id,
        required_auth_factors=required_auth_factors,
    )
    res = api_client.create_signing_party(
        contract_id, signing_step_id, payload,
        make_contract_initiator_headers(initiator_id),
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 3 -- Activation and a single signed party
# ---------------------------------------------------------------------------
def activate_contract(*, contract_id: str, initiator_id: str) -> Dict[str, Any]:
    """PRD §3.3: drives DRAFT -> PENDING_SIGN, pins fingerprint, activates
    step 1."""
    res = api_client.activate_contract(
        contract_id,
        make_contract_initiator_headers(initiator_id),
    )
    return get_success_data(res)


def create_identity_verification(
    *,
    subject_user_id: str,
    contract_id: Optional[str] = None,
    factors: Optional[List[Tuple[str, str]]] = None,
    actor_user_id: Optional[str] = None,
    actor_role: str = "Signer",
) -> Dict[str, Any]:
    """Create an IdentityVerification. `factors` is a list of
    (factor, outcome) tuples, default [(SMS, PASS)]. The acting role is
    Signer by default (the signer creates verifications for themself);
    callers can override with ContractInitiator if the PRD prose for a
    given test calls for that.
    """
    actor_user_id = actor_user_id or subject_user_id
    factors = factors or [("SMS", "PASS")]
    payload = create_identity_verification_payload(
        subject_user_id=subject_user_id,
        contract_id=contract_id,
        factors_attempted=[factor_attempt(f, o) for f, o in factors],
    )
    if actor_role == "Signer":
        headers = make_signer_headers(actor_user_id)
    else:
        headers = make_contract_initiator_headers(actor_user_id)
    res = api_client.create_identity_verification(payload, headers)
    return get_success_data(res)


def sign_party(
    *,
    party_id: str,
    signer_user_id: str,
    identity_verification_id: str,
    tsa_anchor_at: Optional[str] = None,
    tsa_provider: str = "tsa-default",
    tsa_token_value: Optional[str] = None,
    drift_seconds: float = 0.0,
) -> Dict[str, Any]:
    """POST /signing-parties/{id}/sign. tsa_anchor_at defaults to current
    clock; pass `drift_seconds` to engineer a particular drift band."""
    if tsa_anchor_at is None:
        tsa_anchor_at = add_seconds(current_clock_iso(), drift_seconds)
    payload = sign_party_payload(
        tsa_anchor_at=tsa_anchor_at,
        tsa_provider=tsa_provider,
        tsa_token_value=tsa_token_value,
        identity_verification_id=identity_verification_id,
    )
    res = api_client.sign_party(
        party_id, payload, make_signer_headers(signer_user_id)
    )
    return get_success_data(res)


def decline_party(
    *, party_id: str, signer_user_id: str,
) -> Dict[str, Any]:
    """POST /signing-parties/{id}/decline."""
    res = api_client.decline_party(
        party_id, make_signer_headers(signer_user_id)
    )
    return get_success_data(res)


# ===========================================================================
# Tier 4 -- Composite scenarios mirroring the PRD's reference flow
# ===========================================================================
def setup_single_party_contract(
    *,
    required_auth_factors: Optional[List[str]] = None,
    expires_at_offset_hours: float = 48.0,
    page_count: int = 1,
    variable_fields: Optional[List[Dict[str, Any]]] = None,
    signature_positions: Optional[List[Dict[str, Any]]] = None,
    variable_values: Optional[Dict[str, Any]] = None,
    permission_scope: Optional[str] = None,
    same_org_initiator: bool = True,
    initiator_id: Optional[str] = None,
    signer_user_id: Optional[str] = None,
    signer_type: str = "INDIVIDUAL",
    signer_org_id: Optional[str] = None,
    delegation_authorization_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a single-step single-party Contract sitting in DRAFT.

    Returns dict: template, version, admin_id, owner_org_id, contract,
    initiator_id, step, party, signer_user_id.
    """
    bundle = create_published_template(
        permission_scope=permission_scope,
        page_count=page_count,
        variable_fields=variable_fields,
        signature_positions=signature_positions,
    )
    init_org = (
        bundle["owner_org_id"] if same_org_initiator
        else unique_org_id()
    )
    contract, initiator_id = create_contract_in_draft(
        template_version_id=bundle["version"]["id"],
        initiator_id=initiator_id,
        initiator_org_id=init_org,
        variable_values=variable_values,
        expires_at_offset_hours=expires_at_offset_hours,
    )
    step = append_signing_step(
        contract_id=contract["id"],
        initiator_id=initiator_id,
        step_index=1,
        mode="PARALLEL_COUNTERSIGN",
    )
    signer_user_id = signer_user_id or stable_user_id("signer")
    party = append_signing_party(
        contract_id=contract["id"],
        signing_step_id=step["id"],
        initiator_id=initiator_id,
        signer_user_id=signer_user_id,
        role_key="PARTY_A",
        signer_type=signer_type,
        signer_org_id=signer_org_id,
        delegation_authorization_id=delegation_authorization_id,
        required_auth_factors=required_auth_factors or ["SMS"],
    )
    return {
        "template": bundle["template"],
        "version": bundle["version"],
        "admin_id": bundle["admin_id"],
        "owner_org_id": bundle["owner_org_id"],
        "initiator_org_id": init_org,
        "contract": contract,
        "initiator_id": initiator_id,
        "step": step,
        "party": party,
        "signer_user_id": signer_user_id,
    }


def setup_pending_sign_single_party(**kwargs: Any) -> Dict[str, Any]:
    """Build a single-step single-party Contract activated to PENDING_SIGN.

    Identical keys as setup_single_party_contract plus 'activated_contract'.
    """
    ctx = setup_single_party_contract(**kwargs)
    activated = activate_contract(
        contract_id=ctx["contract"]["id"],
        initiator_id=ctx["initiator_id"],
    )
    ctx["contract"] = activated
    return ctx


def setup_completed_single_party_contract(
    *,
    factors: Optional[List[Tuple[str, str]]] = None,
    drift_seconds: float = 0.0,
    required_auth_factors: Optional[List[str]] = None,
    permission_scope: Optional[str] = None,
    page_count: int = 1,
    variable_fields: Optional[List[Dict[str, Any]]] = None,
    signature_positions: Optional[List[Dict[str, Any]]] = None,
    variable_values: Optional[Dict[str, Any]] = None,
    expires_at_offset_hours: float = 48.0,
) -> Dict[str, Any]:
    """Drive a single-step single-party Contract all the way to COMPLETED.

    Default factors=[(SMS, PASS)] yields identity_strength=WEAK; pass
    [(CA_CERT, PASS), (BANK_CARD, PASS)] for EXTRA_STRONG, etc.

    Returns the same context dict plus 'verification' and 'signed_party'.
    """
    factors = factors or [("SMS", "PASS")]
    required_auth_factors = required_auth_factors or [
        f for f, o in factors if o == "PASS"
    ] or ["SMS"]
    ctx = setup_pending_sign_single_party(
        required_auth_factors=required_auth_factors,
        expires_at_offset_hours=expires_at_offset_hours,
        page_count=page_count,
        variable_fields=variable_fields,
        signature_positions=signature_positions,
        variable_values=variable_values,
        permission_scope=permission_scope,
    )
    verification = create_identity_verification(
        subject_user_id=ctx["signer_user_id"],
        contract_id=ctx["contract"]["id"],
        factors=factors,
    )
    signed = sign_party(
        party_id=ctx["party"]["id"],
        signer_user_id=ctx["signer_user_id"],
        identity_verification_id=verification["id"],
        drift_seconds=drift_seconds,
    )
    ctx["verification"] = verification
    ctx["signed_party"] = signed
    ctx["contract"] = get_contract(ctx["contract"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 -- Reads that wrap the API client with get_success_data
# ---------------------------------------------------------------------------
def get_contract(contract_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_contract(
            contract_id,
            headers or TEST_USERS["platform_admin_headers"],
        )
    )


def get_template_version(template_id: str, version_id: str,
                         headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_template_version(
            template_id, version_id,
            headers or TEST_USERS["platform_admin_headers"],
        )
    )


def get_evidence_package(contract_id: str,
                         headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_evidence_package(
            contract_id,
            headers or TEST_USERS["platform_admin_headers"],
        )
    )


def get_evidence_preview(contract_id: str,
                         headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_evidence_preview(
            contract_id,
            headers or TEST_USERS["platform_admin_headers"],
        )
    )


def list_audit_logs(contract_id: str,
                    headers: Optional[Dict[str, str]] = None,
                    params: Optional[Dict[str, Any]] = None,
                    ) -> List[Dict[str, Any]]:
    """PRD §4: GET /contracts/{id}/audit-logs ordered by occurred_at ASC.
    Walks pagination so callers can audit the full chain."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    out: List[Dict[str, Any]] = []
    p: Dict[str, Any] = dict(params or {})
    p.setdefault("limit", 100)
    p.setdefault("offset", 0)
    while True:
        res = api_client.list_contract_audit_logs(
            contract_id, headers, params=p
        )
        body = res.json()
        data = body.get("data", [])
        meta = body.get("meta", {})
        out.extend(data)
        if not meta.get("has_more"):
            break
        p["offset"] = p["offset"] + p["limit"]
    return out


def get_progress(contract_id: str, *, variant: Optional[str] = None,
                 headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    params: Optional[Dict[str, Any]] = None
    if variant is not None:
        params = {"variant": variant}
    return get_success_data(
        api_client.get_contract_progress(
            contract_id,
            headers or TEST_USERS["platform_admin_headers"],
            params=params,
        )
    )


def list_reminder_events(contract_id: str,
                         headers: Optional[Dict[str, str]] = None,
                         ) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["platform_admin_headers"]
    out: List[Dict[str, Any]] = []
    p: Dict[str, Any] = {"limit": 100, "offset": 0}
    while True:
        res = api_client.list_reminder_events(contract_id, headers, params=p)
        body = res.json()
        data = body.get("data", [])
        meta = body.get("meta", {})
        out.extend(data)
        if not meta.get("has_more"):
            break
        p["offset"] = p["offset"] + p["limit"]
    return out


# ===========================================================================
# Tier 6 -- Difficulty-design composite fixtures (one per
# scaffold_difficulty_design instance that needs non-trivial state)
# ===========================================================================
def setup_two_step_two_parties_each(
    *,
    expires_at_offset_hours: float = 72.0,
    permission_scope: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Contract with two steps, two parties each, both PARALLEL.

    Used by Rule 1 (chronological-vs-forward-looking divergence): after
    activate, S1 is ACTIVE with two AUTHENTICATING parties; S2 is PENDING
    with two WAITING parties. After both S1 parties sign, the chronological
    progress is 100 (S2 still PENDING and EXCLUDED) but forward-looking
    is 50 (4 included, 2 SIGNED).

    Returns dict with: bundle keys plus contract, initiator_id, steps,
    parties (list of all 4), signer_user_ids (list of 4).
    """
    bundle = create_published_template(
        permission_scope=permission_scope,
        page_count=1,
        variable_fields=[variable_field("subject")],
        signature_positions=[
            signature_position("PARTY_A_1", page=1, x=0.1, y=0.1),
            signature_position("PARTY_A_2", page=1, x=0.4, y=0.1),
            signature_position("PARTY_B_1", page=1, x=0.1, y=0.5),
            signature_position("PARTY_B_2", page=1, x=0.4, y=0.5),
        ],
    )
    contract, initiator_id = create_contract_in_draft(
        template_version_id=bundle["version"]["id"],
        initiator_org_id=bundle["owner_org_id"],
        expires_at_offset_hours=expires_at_offset_hours,
    )
    s1 = append_signing_step(
        contract_id=contract["id"],
        initiator_id=initiator_id,
        step_index=1,
        mode="PARALLEL_COUNTERSIGN",
    )
    s2 = append_signing_step(
        contract_id=contract["id"],
        initiator_id=initiator_id,
        step_index=2,
        mode="PARALLEL_COUNTERSIGN",
    )
    signer_ids = [stable_user_id(f"signer{i}") for i in range(4)]
    p1a = append_signing_party(
        contract_id=contract["id"],
        signing_step_id=s1["id"],
        initiator_id=initiator_id,
        signer_user_id=signer_ids[0],
        role_key="PARTY_A_1",
    )
    p1b = append_signing_party(
        contract_id=contract["id"],
        signing_step_id=s1["id"],
        initiator_id=initiator_id,
        signer_user_id=signer_ids[1],
        role_key="PARTY_A_2",
    )
    p2a = append_signing_party(
        contract_id=contract["id"],
        signing_step_id=s2["id"],
        initiator_id=initiator_id,
        signer_user_id=signer_ids[2],
        role_key="PARTY_B_1",
    )
    p2b = append_signing_party(
        contract_id=contract["id"],
        signing_step_id=s2["id"],
        initiator_id=initiator_id,
        signer_user_id=signer_ids[3],
        role_key="PARTY_B_2",
    )
    return {
        **bundle,
        "contract": contract,
        "initiator_id": initiator_id,
        "steps": [s1, s2],
        "parties": [p1a, p1b, p2a, p2b],
        "signer_user_ids": signer_ids,
    }


def setup_three_step_branched_contract(
    *,
    amount_value: int = 5000,
    branch_threshold: int = 10000,
    expires_at_offset_hours: float = 72.0,
) -> Dict[str, Any]:
    """Build a Contract with three steps:
    S1 (no branch, one party), S2 (branch on amount >= branch_threshold,
    one party), S3 (no branch, one party).

    Used by Rule 3 instance 'signing_step_diamond_with_branch_skip' and
    Rule 9 instance 'contract_completion_preserves_party_signed_count'.
    """
    bundle = create_published_template(
        page_count=1,
        variable_fields=[variable_field("amount", "number")],
        signature_positions=[
            signature_position("ROLE_S1", page=1, x=0.1, y=0.1),
            signature_position("ROLE_S2", page=1, x=0.1, y=0.3),
            signature_position("ROLE_S3", page=1, x=0.1, y=0.5),
        ],
    )
    contract, initiator_id = create_contract_in_draft(
        template_version_id=bundle["version"]["id"],
        initiator_org_id=bundle["owner_org_id"],
        variable_values={"amount": amount_value},
        expires_at_offset_hours=expires_at_offset_hours,
    )
    s1 = append_signing_step(
        contract_id=contract["id"], initiator_id=initiator_id,
        step_index=1, mode="PARALLEL_COUNTERSIGN",
    )
    s2 = append_signing_step(
        contract_id=contract["id"], initiator_id=initiator_id,
        step_index=2, mode="PARALLEL_COUNTERSIGN",
        branch=branch_condition(
            variable="amount", operator=">=",
            value=branch_threshold, on_false_skip=True,
        ),
    )
    s3 = append_signing_step(
        contract_id=contract["id"], initiator_id=initiator_id,
        step_index=3, mode="PARALLEL_COUNTERSIGN",
    )
    signer_ids = [stable_user_id(f"sig{i}") for i in range(3)]
    p1 = append_signing_party(
        contract_id=contract["id"], signing_step_id=s1["id"],
        initiator_id=initiator_id, signer_user_id=signer_ids[0],
        role_key="ROLE_S1",
    )
    p2 = append_signing_party(
        contract_id=contract["id"], signing_step_id=s2["id"],
        initiator_id=initiator_id, signer_user_id=signer_ids[1],
        role_key="ROLE_S2",
    )
    p3 = append_signing_party(
        contract_id=contract["id"], signing_step_id=s3["id"],
        initiator_id=initiator_id, signer_user_id=signer_ids[2],
        role_key="ROLE_S3",
    )
    return {
        **bundle,
        "contract": contract,
        "initiator_id": initiator_id,
        "steps": [s1, s2, s3],
        "parties": [p1, p2, p3],
        "signer_user_ids": signer_ids,
    }


def setup_decline_two_party_step(
    *, expires_at_offset_hours: float = 24.0,
) -> Dict[str, Any]:
    """Build a single-step Contract with two parties; activate to
    PENDING_SIGN.

    Used by Rule 4 instance 'party_declined_to_contract_voided_depth_3'
    and Rule 8 instance 'signing_party_sign_decline_window_collision'.
    """
    bundle = create_published_template(
        page_count=1,
        variable_fields=[variable_field("subject")],
        signature_positions=[
            signature_position("PARTY_A", page=1, x=0.1, y=0.1),
            signature_position("PARTY_B", page=1, x=0.4, y=0.1),
        ],
    )
    contract, initiator_id = create_contract_in_draft(
        template_version_id=bundle["version"]["id"],
        initiator_org_id=bundle["owner_org_id"],
        expires_at_offset_hours=expires_at_offset_hours,
    )
    step = append_signing_step(
        contract_id=contract["id"], initiator_id=initiator_id,
        step_index=1, mode="PARALLEL_COUNTERSIGN",
    )
    signer_ids = [stable_user_id("sigA"), stable_user_id("sigB")]
    p1 = append_signing_party(
        contract_id=contract["id"], signing_step_id=step["id"],
        initiator_id=initiator_id, signer_user_id=signer_ids[0],
        role_key="PARTY_A",
    )
    p2 = append_signing_party(
        contract_id=contract["id"], signing_step_id=step["id"],
        initiator_id=initiator_id, signer_user_id=signer_ids[1],
        role_key="PARTY_B",
    )
    activated = activate_contract(
        contract_id=contract["id"], initiator_id=initiator_id,
    )
    return {
        **bundle,
        "contract": activated,
        "initiator_id": initiator_id,
        "step": step,
        "parties": [p1, p2],
        "signer_user_ids": signer_ids,
    }


def setup_two_contracts_partition_divergence(
    *,
    page_count: int = 2,
    expires_at_offset_hours: float = 48.0,
) -> Dict[str, Any]:
    """Build two Contracts on the same TemplateVersion (page_count=2) with
    different variable_values.

    Used by Rule 2 instance 'document_fingerprint_nested_hash_order'.
    The 'date' variable is bound to a signature_position on page 1; the
    'amount' variable lives on page 2. Two contracts differ only on date,
    so per-page-1 hashes differ -> document_fingerprint_sha256 differ.
    """
    bundle = create_published_template(
        page_count=page_count,
        variable_fields=[
            variable_field("date"),
            variable_field("amount"),
        ],
        signature_positions=[
            # role_key is opaque; tests only need a position on each page.
            signature_position("DATE_FIELD", page=1, x=0.1, y=0.1),
            signature_position("AMOUNT_FIELD", page=2, x=0.1, y=0.1),
        ],
    )
    ca, init_a = create_contract_in_draft(
        template_version_id=bundle["version"]["id"],
        initiator_org_id=bundle["owner_org_id"],
        variable_values={"date": "2026-05-10", "amount": "100.00"},
        expires_at_offset_hours=expires_at_offset_hours,
    )
    cb, init_b = create_contract_in_draft(
        template_version_id=bundle["version"]["id"],
        initiator_org_id=bundle["owner_org_id"],
        variable_values={"date": "2026-05-11", "amount": "100.00"},
        expires_at_offset_hours=expires_at_offset_hours,
    )
    sa = append_signing_step(
        contract_id=ca["id"], initiator_id=init_a,
        step_index=1, mode="PARALLEL_COUNTERSIGN",
    )
    pa = append_signing_party(
        contract_id=ca["id"], signing_step_id=sa["id"],
        initiator_id=init_a, signer_user_id=stable_user_id("sa"),
        role_key="DATE_FIELD",
    )
    sb = append_signing_step(
        contract_id=cb["id"], initiator_id=init_b,
        step_index=1, mode="PARALLEL_COUNTERSIGN",
    )
    pb = append_signing_party(
        contract_id=cb["id"], signing_step_id=sb["id"],
        initiator_id=init_b, signer_user_id=stable_user_id("sb"),
        role_key="DATE_FIELD",
    )
    return {
        **bundle,
        "ca": ca, "cb": cb,
        "init_a": init_a, "init_b": init_b,
        "step_a": sa, "step_b": sb,
        "party_a": pa, "party_b": pb,
    }


def setup_reinitiation_chain(
    *,
    expires_at_offset_hours: float = 24.0,
) -> Dict[str, Any]:
    """Build three Contracts in PENDING_SIGN, each driven into VOIDED via
    a different path (auto-expire, manual void, decline).

    Used by Rule 3 instance 'contract_branching_with_voided_reinitiation'.
    Returns dict with contracts (3 voided + 1 reinit_payload-ready
    template/version).
    """
    bundle = create_published_template(
        page_count=1,
        variable_fields=[variable_field("subject")],
        signature_positions=[
            signature_position("PARTY_A", page=1)
        ],
    )
    init_org = bundle["owner_org_id"]
    contracts: List[Dict[str, Any]] = []
    initiators: List[str] = []
    parties: List[Dict[str, Any]] = []
    signers: List[str] = []
    # Use the SAME initiator across the three contracts so re-initiation
    # passes the 'same initiator_org_id' check. PRD §3.7: 'must belong to
    # the same initiator_org_id'.
    init_id = stable_user_id("init")
    for i in range(3):
        c, _ = create_contract_in_draft(
            template_version_id=bundle["version"]["id"],
            initiator_id=init_id,
            initiator_org_id=init_org,
            expires_at_offset_hours=expires_at_offset_hours,
        )
        s = append_signing_step(
            contract_id=c["id"], initiator_id=init_id,
            step_index=1, mode="PARALLEL_COUNTERSIGN",
        )
        sig_id = stable_user_id(f"sig{i}")
        p = append_signing_party(
            contract_id=c["id"], signing_step_id=s["id"],
            initiator_id=init_id, signer_user_id=sig_id,
            role_key="PARTY_A",
        )
        c = activate_contract(contract_id=c["id"], initiator_id=init_id)
        contracts.append(c)
        initiators.append(init_id)
        parties.append(p)
        signers.append(sig_id)
    return {
        **bundle,
        "init_org_id": init_org,
        "init_id": init_id,
        "contracts": contracts,
        "parties": parties,
        "signer_user_ids": signers,
    }


def setup_reminder_rule_in_pending_sign(
    *,
    interval_hours: int = 24,
    escalation_after_misses: int = 2,
    channels: Optional[List[str]] = None,
    expires_at_offset_hours: float = 200.0,
) -> Dict[str, Any]:
    """Build a single-party PENDING_SIGN Contract with a ReminderRule
    attached. Used by Rule 6 instance
    'reminder_due_inclusive_threshold_and_strict_escalation' and Rule 8
    instance 'reminder_idempotency_slot_overlap_inclusive'."""
    ctx = setup_pending_sign_single_party(
        expires_at_offset_hours=expires_at_offset_hours,
    )
    res = api_client.create_reminder_rule(
        ctx["contract"]["id"],
        create_reminder_rule_payload(
            interval_hours=interval_hours,
            channels=channels or ["SMS"],
            escalation_after_misses=escalation_after_misses,
        ),
        make_contract_initiator_headers(ctx["initiator_id"]),
    )
    rule = get_success_data(res)
    ctx["rule"] = rule
    return ctx


def setup_partially_signed_contract(
    *,
    expires_at_offset_hours: float = 96.0,
) -> Dict[str, Any]:
    """Drive a two-step contract to PARTIALLY_SIGNED: S1 SIGNED with one
    party, S2 still has WAITING parties.

    Used by Rule 9 instance 'contract_void_preserves_audit_log_chain'.
    """
    bundle = create_published_template(
        page_count=1,
        variable_fields=[variable_field("subject")],
        signature_positions=[
            signature_position("PARTY_A_1", page=1, x=0.1, y=0.1),
            signature_position("PARTY_B_1", page=1, x=0.1, y=0.4),
            signature_position("PARTY_B_2", page=1, x=0.4, y=0.4),
        ],
    )
    contract, init_id = create_contract_in_draft(
        template_version_id=bundle["version"]["id"],
        initiator_org_id=bundle["owner_org_id"],
        expires_at_offset_hours=expires_at_offset_hours,
    )
    s1 = append_signing_step(
        contract_id=contract["id"], initiator_id=init_id,
        step_index=1, mode="PARALLEL_COUNTERSIGN",
    )
    s2 = append_signing_step(
        contract_id=contract["id"], initiator_id=init_id,
        step_index=2, mode="PARALLEL_COUNTERSIGN",
    )
    sig_a1 = stable_user_id("sigA1")
    sig_b1 = stable_user_id("sigB1")
    sig_b2 = stable_user_id("sigB2")
    p1 = append_signing_party(
        contract_id=contract["id"], signing_step_id=s1["id"],
        initiator_id=init_id, signer_user_id=sig_a1,
        role_key="PARTY_A_1",
    )
    p_b1 = append_signing_party(
        contract_id=contract["id"], signing_step_id=s2["id"],
        initiator_id=init_id, signer_user_id=sig_b1,
        role_key="PARTY_B_1",
    )
    p_b2 = append_signing_party(
        contract_id=contract["id"], signing_step_id=s2["id"],
        initiator_id=init_id, signer_user_id=sig_b2,
        role_key="PARTY_B_2",
    )
    activate_contract(contract_id=contract["id"], initiator_id=init_id)
    iv1 = create_identity_verification(
        subject_user_id=sig_a1, contract_id=contract["id"],
        factors=[("SMS", "PASS")],
    )
    sign_party(
        party_id=p1["id"], signer_user_id=sig_a1,
        identity_verification_id=iv1["id"], drift_seconds=0.0,
    )
    return {
        **bundle,
        "contract": get_contract(contract["id"]),
        "initiator_id": init_id,
        "step1": s1,
        "step2": s2,
        "party_a1": p1,
        "party_b1": p_b1,
        "party_b2": p_b2,
        "signer_user_ids": [sig_a1, sig_b1, sig_b2],
    }


def setup_completed_with_evidence_in_generating(
    *,
    factors: Optional[List[Tuple[str, str]]] = None,
    drift_seconds: float = 0.0,
) -> Dict[str, Any]:
    """Drive a single-party Contract to COMPLETED so EvidencePackage is
    PENDING -> GENERATING. Used as a precondition for /evidence/seal
    tests.

    Returns the same context dict as setup_completed_single_party_contract
    plus 'archivist_id' (a fresh OrgUser.id distinct from initiator)
    suitable for a valid seal call.
    """
    ctx = setup_completed_single_party_contract(
        factors=factors, drift_seconds=drift_seconds,
    )
    ctx["archivist_id"] = stable_user_id("arch")
    return ctx


__all__ = [
    "iso_z",
    "parse_iso",
    "add_seconds",
    "add_minutes",
    "add_hours",
    "add_days",
    "DEFAULT_NOW_ISO",
    "advance_clock",
    "current_clock_iso",
    "run_sweep",
    "stable_user_id",
    "create_template",
    "create_template_version",
    "publish_template_version",
    "create_published_template",
    "create_contract_in_draft",
    "append_signing_step",
    "append_signing_party",
    "activate_contract",
    "create_identity_verification",
    "sign_party",
    "decline_party",
    "setup_single_party_contract",
    "setup_pending_sign_single_party",
    "setup_completed_single_party_contract",
    "get_contract",
    "get_template_version",
    "get_evidence_package",
    "get_evidence_preview",
    "list_audit_logs",
    "get_progress",
    "list_reminder_events",
    "setup_two_step_two_parties_each",
    "setup_three_step_branched_contract",
    "setup_decline_two_party_step",
    "setup_two_contracts_partition_divergence",
    "setup_reinitiation_chain",
    "setup_reminder_rule_in_pending_sign",
    "setup_partially_signed_contract",
    "setup_completed_with_evidence_in_generating",
]
