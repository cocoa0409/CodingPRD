"""Composite setup helpers for the Copyright Licensing API.

Fixtures are the place where multi-step preambles live. Tests focus on
assertions, not plumbing.

Design principles
-----------------
* Every fixture uses get_success_data() (lenient) so setup failures yield
  clear "Setup failed" errors, not assertion noise.
* Identity threading is mandatory: every ownership-gated call uses
  make_rights_holder_headers(rh["id"]) — never the shared TEST_USERS
  constant — because PRD §2.1 compares X-User-ID byte-equal to the
  resource's foreign-key field for every RightsHolder ownership check.
* Time strategy: the platform is event-driven and time-gated. Tests use
  POST /_clock/advance to move the logical clock forward. Term dates in
  the far future (2099+) sidestep accidental clock interactions when a
  test does not advance the clock.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client, ApiClient
from .factories import (
    create_rights_holder_payload,
    create_work_payload,
    create_license_payload,
    round_payload,
    create_contract_payload,
    signature_payload,
    royalty_statement_payload,
    create_infringement_payload,
    respond_payload,
    resolve_payload,
    emit_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_rights_holder_headers,
    make_admin_headers,
)


ADMIN_HEADERS = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def iso_z(dt: datetime) -> str:
    """Serialize a datetime as ISO 8601 UTC with .000Z fractional seconds."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def add_months_iso(start_iso: str, months: int) -> str:
    """Return start_iso + months calendar months, formatted ISO 8601 UTC.

    This is calendar-month arithmetic; PRD §3.7 says MONTHLY periods must
    align with the license's settlement_period. For most setups we anchor
    on the 1st of the month so the boundary is clean.
    """
    dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    return iso_z(dt.replace(year=year, month=month))


def unique_email(prefix: str = "rh") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


def unique_doc_id(prefix: str = "doc") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_event_id(prefix: str = "evt") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# Global counter to allocate distinct future term windows per setup call.
# PRD §3.3 requires term_start strictly in the future relative to the current
# logical clock at the moment of license creation. Earlier tests may have
# advanced the clock to a previously-used 'far-future' constant, so we cannot
# share a single hard-coded date across tests. Each helper that does not
# receive an explicit term_start asks for the next slot.
_TERM_SLOT_COUNTER = [0]
# Anchor far past every test in the suite. setup_effective_license will then
# advance the clock to its slot's term_start; subsequent tests pick a fresher
# slot to remain strictly in the future.
_TERM_BASE_YEAR = 2200


def _next_term_window() -> Tuple[str, str, str]:
    """Allocate (term_start, term_end, effective_date_target) one year apart.

    Returns three ISO 8601 timestamps. term_start is `_TERM_BASE_YEAR + slot`,
    term_end is one year later, effective_date_target equals term_start.
    Slots are 1-year-wide so successive tests do not collide.
    """
    _TERM_SLOT_COUNTER[0] += 1
    slot = _TERM_SLOT_COUNTER[0]
    start_year = _TERM_BASE_YEAR + slot
    end_year = start_year + 1
    ts = f"{start_year:04d}-01-01T00:00:00.000Z"
    te = f"{end_year:04d}-01-01T00:00:00.000Z"
    return ts, te, ts


# ---------------------------------------------------------------------------
# Tier 1: RightsHolder + Work creation/registration
# ---------------------------------------------------------------------------

def create_rights_holder(api: ApiClient = api_client, **overrides) -> Dict[str, Any]:
    """Create a RightsHolder via PlatformAdmin. Returns the entity dict.

    Per PRD §3.1, both PlatformAdmin and RightsHolder may create rights
    holders. We use admin to avoid bootstrapping issues."""
    payload = create_rights_holder_payload(**{
        "contact_email": unique_email(),
        **overrides,
    })
    resp = api.create_rights_holder(payload, ADMIN_HEADERS)
    return get_success_data(resp)


def create_two_rights_holders(api: ApiClient = api_client) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Convenience: returns (RH_A, RH_B) — both INDIVIDUAL, distinct ids."""
    rh_a = create_rights_holder(api, legal_name="Alice Author")
    rh_b = create_rights_holder(api, legal_name="Bob Buyer")
    return rh_a, rh_b


def create_draft_work(api: ApiClient,
                       owner: Dict[str, Any],
                       co_owners: Optional[List[Dict[str, Any]]] = None,
                       primary_share_bps: int = 10000,
                       **overrides) -> Dict[str, Any]:
    """Create a Work in DRAFT owned by `owner`.

    The acting RightsHolder is `owner` (PRD §3.1 — POST /works role is
    RightsHolder, the caller becomes primary_owner_id when omitted; we
    explicitly set primary_owner_id and use owner-headers for ownership
    threading).
    """
    headers = make_rights_holder_headers(owner["id"])
    payload = create_work_payload(
        primary_owner_id=owner["id"],
        co_owners=co_owners,
        primary_share_bps=primary_share_bps,
        ownership_proof_doc_id=unique_doc_id(),
        **overrides,
    )
    resp = api.create_work(payload, headers)
    return get_success_data(resp)


def submit_work(api: ApiClient, work: Dict[str, Any], owner: Dict[str, Any]) -> Dict[str, Any]:
    """Move a DRAFT Work to UNDER_REVIEW. The owner is the acting principal."""
    headers = make_rights_holder_headers(owner["id"])
    resp = api.submit_work(work["id"], headers, payload={"version": work["version"]})
    return get_success_data(resp)


def approve_work_registration(api: ApiClient, work: Dict[str, Any]) -> Dict[str, Any]:
    """Emit COPYRIGHT_AUTHORITY:REGISTRATION_APPROVED so Work moves to REGISTERED.

    PRD §3.2: registration is granted by external event; Work transitions
    UNDER_REVIEW → REGISTERED with certificate_id minted.
    """
    payload = emit_event_payload(
        source="COPYRIGHT_AUTHORITY",
        event_type="REGISTRATION_APPROVED",
        ref_entity="Work",
        ref_id=work["id"],
        payload={},
        external_event_id=unique_event_id("reg-approve"),
    )
    resp = api.emit_event(payload, ADMIN_HEADERS)
    get_success_data(resp)
    # Re-read work to get updated REGISTERED state
    resp = api.get_work(work["id"], ADMIN_HEADERS)
    return get_success_data(resp)


def reject_work_registration(api: ApiClient, work: Dict[str, Any]) -> Dict[str, Any]:
    """Emit COPYRIGHT_AUTHORITY:REGISTRATION_REJECTED so Work moves to REJECTED."""
    payload = emit_event_payload(
        source="COPYRIGHT_AUTHORITY",
        event_type="REGISTRATION_REJECTED",
        ref_entity="Work",
        ref_id=work["id"],
        payload={},
        external_event_id=unique_event_id("reg-reject"),
    )
    resp = api.emit_event(payload, ADMIN_HEADERS)
    get_success_data(resp)
    resp = api.get_work(work["id"], ADMIN_HEADERS)
    return get_success_data(resp)


def create_registered_work(api: ApiClient = api_client,
                            owner: Optional[Dict[str, Any]] = None,
                            co_owners: Optional[List[Dict[str, Any]]] = None,
                            primary_share_bps: int = 10000,
                            **overrides) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Walk Work from DRAFT → UNDER_REVIEW → REGISTERED.

    Returns (registered_work, owner). If `owner` is not supplied a fresh
    RightsHolder is created.
    """
    if owner is None:
        owner = create_rights_holder(api, legal_name="Primary Owner")
    work = create_draft_work(api, owner, co_owners=co_owners,
                             primary_share_bps=primary_share_bps, **overrides)
    work = submit_work(api, work, owner)
    work = approve_work_registration(api, work)
    return work, owner


# ---------------------------------------------------------------------------
# Tier 2: License creation + negotiation
# ---------------------------------------------------------------------------

def create_offered_license(api: ApiClient,
                            work: Dict[str, Any],
                            licensor: Dict[str, Any],
                            licensee: Dict[str, Any],
                            *,
                            term_start: Optional[str] = None,
                            term_end: Optional[str] = None,
                            territory: Optional[List[str]] = None,
                            media_types: Optional[List[str]] = None,
                            exclusivity: str = "NON_EXCLUSIVE",
                            revenue_share_bps: int = 1500,
                            minimum_guarantee_cents: int = 0,
                            advance_cents: int = 0,
                            settlement_period: str = "MONTHLY",
                            **overrides) -> Dict[str, Any]:
    """Create a License in OFFERED. Licensor is the acting RightsHolder
    (PRD §3.3 — must be primary_owner or co_owner of the work)."""
    if term_start is None or term_end is None:
        ts, te, _ = _next_term_window()
        if term_start is None:
            term_start = ts
        if term_end is None:
            term_end = te
    headers = make_rights_holder_headers(licensor["id"])
    payload = create_license_payload(
        work_id=work["id"],
        licensor_id=licensor["id"],
        licensee_id=licensee["id"],
        territory=territory,
        term_start=term_start,
        term_end=term_end,
        media_types=media_types,
        exclusivity=exclusivity,
        revenue_share_bps=revenue_share_bps,
        minimum_guarantee_cents=minimum_guarantee_cents,
        advance_cents=advance_cents,
        settlement_period=settlement_period,
        **overrides,
    )
    resp = api.create_license(payload, headers)
    return get_success_data(resp)


def submit_round(api: ApiClient,
                 license_data: Dict[str, Any],
                 caller: Dict[str, Any],
                 *,
                 action: str,
                 clause_diff: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Submit a NegotiationRound (COUNTER, ACCEPT, or WITHDRAW) as `caller`.

    `caller` must be the RightsHolder whose id will be the X-User-ID; for
    a counter, caller must be the opposite party from previous round.
    Returns the persisted NegotiationRound.
    """
    headers = make_rights_holder_headers(caller["id"])
    body = round_payload(action=action,
                         clause_diff=clause_diff,
                         version=license_data.get("version"))
    resp = api.submit_round(license_data["id"], body, headers)
    return get_success_data(resp)


def accept_offered_license(api: ApiClient,
                            license_data: Dict[str, Any],
                            licensee: Dict[str, Any]) -> Dict[str, Any]:
    """Accept a license that's still in OFFERED. Returns the License after
    re-fetch (so caller observes status=ACCEPTED, pinned_work_version, etc.)."""
    submit_round(api, license_data, licensee, action="ACCEPT")
    resp = api.get_license(license_data["id"], ADMIN_HEADERS)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: Contract creation + signing
# ---------------------------------------------------------------------------

def create_pending_contract(api: ApiClient,
                             license_data: Dict[str, Any],
                             *,
                             licensor: Dict[str, Any],
                             licensee: Dict[str, Any],
                             effective_date_target: Optional[str] = None,
                             signing_order: Optional[List[str]] = None,
                             parent_contract_id: Optional[str] = None) -> Dict[str, Any]:
    """Create a Contract in PENDING_SIGNATURES. Caller is the licensor."""
    if effective_date_target is None:
        # Default: target the underlying license's term_start (boundary inclusive
        # per PRD §3.5: term_start <= effective_date_target < term_end).
        effective_date_target = license_data.get("term_start")
    if signing_order is None:
        signing_order = [licensor["id"], licensee["id"]]
    headers = make_rights_holder_headers(licensor["id"])
    payload = create_contract_payload(
        license_id=license_data["id"],
        signing_order=signing_order,
        effective_date_target=effective_date_target,
        parent_contract_id=parent_contract_id,
    )
    resp = api.create_contract(payload, headers)
    return get_success_data(resp)


def sign_contract_in_order(api: ApiClient,
                            contract: Dict[str, Any],
                            signers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Submit one Signature per element of `signers` in order. Each caller
    is the corresponding signer (entity-backed identity threading).

    Returns the Contract after all signatures (FULLY_SIGNED if all signers
    submitted)."""
    contract_id = contract["id"]
    for signer in signers:
        # Re-read contract to get fresh version for each signature
        resp = api.get_contract(contract_id, ADMIN_HEADERS)
        cur = get_success_data(resp)
        headers = make_rights_holder_headers(signer["id"])
        body = signature_payload(signer_id=signer["id"], version=cur.get("version"))
        resp = api.submit_signature(contract_id, body, headers)
        get_success_data(resp)
    resp = api.get_contract(contract_id, ADMIN_HEADERS)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: Effective-date clock advance
# ---------------------------------------------------------------------------

def advance_clock_to(api: ApiClient, instant_iso: str) -> None:
    """Advance the logical clock to `instant_iso`. PRD §3.6: this is the
    test-driving capability that fires SIGNED → EFFECTIVE auto-transitions."""
    resp = api.advance_clock(instant_iso, ADMIN_HEADERS)
    get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: Composite — create-and-make-effective shortcut
# ---------------------------------------------------------------------------

def setup_effective_license(api: ApiClient = api_client,
                             *,
                             licensor: Optional[Dict[str, Any]] = None,
                             licensee: Optional[Dict[str, Any]] = None,
                             work: Optional[Dict[str, Any]] = None,
                             term_start: Optional[str] = None,
                             term_end: Optional[str] = None,
                             effective_date_target: Optional[str] = None,
                             territory: Optional[List[str]] = None,
                             media_types: Optional[List[str]] = None,
                             exclusivity: str = "NON_EXCLUSIVE",
                             revenue_share_bps: int = 1500,
                             minimum_guarantee_cents: int = 0,
                             advance_cents: int = 0,
                             settlement_period: str = "MONTHLY",
                             **license_overrides) -> Dict[str, Any]:
    """Full path: create RH_A (licensor) + RH_B (licensee), register Work,
    create License, accept, contract, sign both, advance clock to
    effective_date_target so License becomes EFFECTIVE.

    Returns dict: {licensor, licensee, work, license, contract}.
    """
    if licensor is None:
        licensor = create_rights_holder(api, legal_name="Licensor RH")
    if licensee is None:
        licensee = create_rights_holder(api, legal_name="Licensee RH")
    if work is None:
        work, _ = create_registered_work(api, owner=licensor)

    # Allocate a fresh future window if any of the three timestamps were not
    # supplied. This avoids the "term_start must be in the future" failure
    # caused by a previous test having advanced the clock to (or past) a
    # shared 2099-style constant. PRD §3.3 requires term_start strictly
    # after the current logical clock at the moment of license creation.
    if term_start is None or term_end is None or effective_date_target is None:
        ts_default, te_default, edt_default = _next_term_window()
        if term_start is None:
            term_start = ts_default
        if term_end is None:
            term_end = te_default
        if effective_date_target is None:
            effective_date_target = term_start

    license_data = create_offered_license(
        api, work, licensor, licensee,
        term_start=term_start, term_end=term_end,
        territory=territory, media_types=media_types,
        exclusivity=exclusivity,
        revenue_share_bps=revenue_share_bps,
        minimum_guarantee_cents=minimum_guarantee_cents,
        advance_cents=advance_cents,
        settlement_period=settlement_period,
        **license_overrides,
    )
    license_data = accept_offered_license(api, license_data, licensee)

    contract = create_pending_contract(
        api, license_data,
        licensor=licensor, licensee=licensee,
        effective_date_target=effective_date_target,
    )
    contract = sign_contract_in_order(api, contract, [licensor, licensee])

    # Advance clock to effective_date_target so SIGNED → EFFECTIVE fires.
    advance_clock_to(api, effective_date_target)

    # Re-read latest state
    license_data = get_success_data(api.get_license(license_data["id"], ADMIN_HEADERS))
    contract = get_success_data(api.get_contract(contract["id"], ADMIN_HEADERS))

    return {
        "licensor": licensor,
        "licensee": licensee,
        "work": work,
        "license": license_data,
        "contract": contract,
    }


def setup_signed_license(api: ApiClient = api_client,
                          *,
                          licensor: Optional[Dict[str, Any]] = None,
                          licensee: Optional[Dict[str, Any]] = None,
                          work: Optional[Dict[str, Any]] = None,
                          term_start: Optional[str] = None,
                          term_end: Optional[str] = None,
                          effective_date_target: Optional[str] = None,
                          **license_overrides) -> Dict[str, Any]:
    """Same as setup_effective_license but stops AT SIGNED — clock NOT advanced."""
    if licensor is None:
        licensor = create_rights_holder(api, legal_name="Licensor RH")
    if licensee is None:
        licensee = create_rights_holder(api, legal_name="Licensee RH")
    if work is None:
        work, _ = create_registered_work(api, owner=licensor)

    if term_start is None or term_end is None or effective_date_target is None:
        ts_default, te_default, edt_default = _next_term_window()
        if term_start is None:
            term_start = ts_default
        if term_end is None:
            term_end = te_default
        if effective_date_target is None:
            effective_date_target = term_start

    license_data = create_offered_license(
        api, work, licensor, licensee,
        term_start=term_start, term_end=term_end,
        **license_overrides,
    )
    license_data = accept_offered_license(api, license_data, licensee)

    contract = create_pending_contract(
        api, license_data,
        licensor=licensor, licensee=licensee,
        effective_date_target=effective_date_target,
    )
    contract = sign_contract_in_order(api, contract, [licensor, licensee])

    license_data = get_success_data(api.get_license(license_data["id"], ADMIN_HEADERS))
    contract = get_success_data(api.get_contract(contract["id"], ADMIN_HEADERS))

    return {
        "licensor": licensor,
        "licensee": licensee,
        "work": work,
        "license": license_data,
        "contract": contract,
    }


def setup_accepted_license(api: ApiClient = api_client,
                            *,
                            licensor: Optional[Dict[str, Any]] = None,
                            licensee: Optional[Dict[str, Any]] = None,
                            work: Optional[Dict[str, Any]] = None,
                            **license_overrides) -> Dict[str, Any]:
    """License accepted but no contract created yet. Returns
    {licensor, licensee, work, license}."""
    if licensor is None:
        licensor = create_rights_holder(api, legal_name="Licensor RH")
    if licensee is None:
        licensee = create_rights_holder(api, legal_name="Licensee RH")
    if work is None:
        work, _ = create_registered_work(api, owner=licensor)

    license_data = create_offered_license(
        api, work, licensor, licensee, **license_overrides,
    )
    license_data = accept_offered_license(api, license_data, licensee)
    return {
        "licensor": licensor,
        "licensee": licensee,
        "work": work,
        "license": license_data,
    }


# ---------------------------------------------------------------------------
# Tier 6: Royalty statement creation + settlement + reversal
# ---------------------------------------------------------------------------

def create_final_statement(api: ApiClient,
                            license_data: Dict[str, Any],
                            licensor: Dict[str, Any],
                            *,
                            period_start_at: str,
                            period_end_at: str,
                            gross_revenue_cents: int) -> Dict[str, Any]:
    """Create a FINAL royalty statement under licensor identity."""
    headers = make_rights_holder_headers(licensor["id"])
    body = royalty_statement_payload(
        period_start_at=period_start_at,
        period_end_at=period_end_at,
        gross_revenue_cents=gross_revenue_cents,
        variant="FINAL",
    )
    resp = api.create_royalty_statement(license_data["id"], body, headers)
    return get_success_data(resp)


def create_provisional_statement(api: ApiClient,
                                  license_data: Dict[str, Any],
                                  licensor: Dict[str, Any],
                                  *,
                                  period_start_at: str,
                                  period_end_at: str,
                                  gross_revenue_cents: int) -> Dict[str, Any]:
    """Create a PROVISIONAL royalty statement under licensor identity."""
    headers = make_rights_holder_headers(licensor["id"])
    body = royalty_statement_payload(
        period_start_at=period_start_at,
        period_end_at=period_end_at,
        gross_revenue_cents=gross_revenue_cents,
        variant="PROVISIONAL",
    )
    resp = api.create_royalty_statement(license_data["id"], body, headers)
    return get_success_data(resp)


def settle_statement(api: ApiClient, statement: Dict[str, Any]) -> Dict[str, Any]:
    """Emit PAYMENT_RECEIVED matching net_payable_cents to settle a DRAFT statement."""
    payload = emit_event_payload(
        source="PAYMENT",
        event_type="PAYMENT_RECEIVED",
        ref_entity="RoyaltyStatement",
        ref_id=statement["id"],
        payload={"amount_cents": statement["net_payable_cents"], "currency": "USD"},
        external_event_id=unique_event_id("pay"),
    )
    resp = api.emit_event(payload, ADMIN_HEADERS)
    get_success_data(resp)


def reverse_statement(api: ApiClient,
                       license_data: Dict[str, Any],
                       licensor: Dict[str, Any],
                       settled_statement: Dict[str, Any],
                       *,
                       refund_cents: int,
                       period_start_at: str,
                       period_end_at: str) -> Dict[str, Any]:
    """Two-step reversal: create reversal entry then emit PAYMENT_REFUNDED.

    Returns the reversal-entry RoyaltyStatement.
    """
    headers = make_rights_holder_headers(licensor["id"])
    body = royalty_statement_payload(
        period_start_at=period_start_at,
        period_end_at=period_end_at,
        gross_revenue_cents=0,
        variant="FINAL",
        reversal_of_id=settled_statement["id"],
        refund_cents=refund_cents,
    )
    resp = api.create_royalty_statement(license_data["id"], body, headers)
    reversal_entry = get_success_data(resp)

    refund_event = emit_event_payload(
        source="PAYMENT",
        event_type="PAYMENT_REFUNDED",
        ref_entity="RoyaltyStatement",
        ref_id=reversal_entry["id"],
        payload={"amount_cents": refund_cents, "currency": "USD"},
        external_event_id=unique_event_id("refund"),
    )
    resp = api.emit_event(refund_event, ADMIN_HEADERS)
    get_success_data(resp)
    return reversal_entry


# ---------------------------------------------------------------------------
# Tier 7: InfringementCase lifecycle
# ---------------------------------------------------------------------------

def create_reported_infringement(api: ApiClient,
                                  work: Dict[str, Any],
                                  reporter: Dict[str, Any],
                                  alleged_infringer: Dict[str, Any],
                                  *,
                                  evidence_doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """File an infringement case (REPORTED stage). Caller is reporter."""
    headers = make_rights_holder_headers(reporter["id"])
    payload = create_infringement_payload(
        work_id=work["id"],
        alleged_infringer_id=alleged_infringer["id"],
        evidence_doc_ids=evidence_doc_ids if evidence_doc_ids is not None else ["ev-1"],
    )
    resp = api.create_infringement_case(payload, headers)
    return get_success_data(resp)


def verify_infringement(api: ApiClient, case: Dict[str, Any]) -> Dict[str, Any]:
    """REPORTED → OWNERSHIP_VERIFIED via PlatformAdmin."""
    resp = api.verify_ownership(case["id"], ADMIN_HEADERS,
                                payload={"version": case["version"]})
    return get_success_data(resp)


def respond_to_infringement(api: ApiClient,
                             case: Dict[str, Any],
                             alleged_infringer: Dict[str, Any],
                             *,
                             response_text: str = "I deny these claims.") -> Dict[str, Any]:
    """OWNERSHIP_VERIFIED → RESPONSE_RECEIVED. Caller is alleged_infringer."""
    headers = make_rights_holder_headers(alleged_infringer["id"])
    body = respond_payload(response_text=response_text, version=case["version"])
    resp = api.respond_infringement(case["id"], body, headers)
    return get_success_data(resp)


def escalate_infringement(api: ApiClient,
                           case: Dict[str, Any],
                           reporter: Dict[str, Any]) -> Dict[str, Any]:
    """RESPONSE_RECEIVED → UNDER_ARBITRATION (issues takedown)."""
    headers = make_rights_holder_headers(reporter["id"])
    resp = api.escalate_infringement(case["id"], headers,
                                       payload={"version": case["version"]})
    return get_success_data(resp)


def setup_under_arbitration_case(api: ApiClient = api_client,
                                  *,
                                  reporter: Optional[Dict[str, Any]] = None,
                                  alleged_infringer: Optional[Dict[str, Any]] = None,
                                  work: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Full case walk REPORTED → OWNERSHIP_VERIFIED → RESPONSE_RECEIVED →
    UNDER_ARBITRATION. Returns dict {reporter, alleged_infringer, work, case}.
    """
    if reporter is None:
        reporter = create_rights_holder(api, legal_name="Reporter RH")
    if alleged_infringer is None:
        alleged_infringer = create_rights_holder(api, legal_name="Alleged Infringer RH")
    if work is None:
        work, _ = create_registered_work(api, owner=reporter)

    case = create_reported_infringement(api, work, reporter, alleged_infringer)
    case = verify_infringement(api, case)
    case = respond_to_infringement(api, case, alleged_infringer)
    case = escalate_infringement(api, case, reporter)
    return {
        "reporter": reporter,
        "alleged_infringer": alleged_infringer,
        "work": work,
        "case": case,
    }


def setup_takedown_cascade_scenario(api: ApiClient = api_client) -> Dict[str, Any]:
    """Full setup for the depth-3 takedown cascade test (Rule 4 instance 1):
    Work → registered, License → EFFECTIVE with licensee = alleged_infringer,
    Contract EFFECTIVE, then InfringementCase up through RESPONSE_RECEIVED
    (escalation NOT yet performed — caller decides when to escalate).

    Returns dict {licensor, alleged_infringer, work, license, contract, case}.
    """
    licensor = create_rights_holder(api, legal_name="RH_A")
    alleged = create_rights_holder(api, legal_name="RH_B")
    work, _ = create_registered_work(api, owner=licensor)

    bundle = setup_effective_license(
        api,
        licensor=licensor,
        licensee=alleged,
        work=work,
    )
    case = create_reported_infringement(api, work, licensor, alleged)
    case = verify_infringement(api, case)
    case = respond_to_infringement(api, case, alleged)

    return {
        "licensor": licensor,
        "alleged_infringer": alleged,
        "work": work,
        "license": bundle["license"],
        "contract": bundle["contract"],
        "case": case,
    }


# ---------------------------------------------------------------------------
# Tier 8: Specialized fixtures derived from the difficulty design
# ---------------------------------------------------------------------------

def setup_royalty_dual_variant_scenario(api: ApiClient = api_client) -> Dict[str, Any]:
    """Difficulty Rule 1 instance 1 (royalty_provisional_vs_final): EFFECTIVE
    license with revenue_share_bps=1500, minimum_guarantee_cents=200000,
    advance_cents=50000, settlement_period=MONTHLY.

    Returns the bundle from setup_effective_license. Term dates are picked
    from the next available future slot (PRD §3.3 — term_start strictly
    after the current logical clock).
    """
    return setup_effective_license(
        api,
        revenue_share_bps=1500,
        minimum_guarantee_cents=200_000,
        advance_cents=50_000,
        settlement_period="MONTHLY",
    )


def setup_rounding_order_license(api: ApiClient = api_client) -> Dict[str, Any]:
    """Difficulty Rule 2 instance 2 (royalty_rounding_order_pinned_mode_b):
    EFFECTIVE license with revenue_share_bps=3333, MG=0, advance=0. Term
    dates are picked from the next available future slot.
    """
    return setup_effective_license(
        api,
        revenue_share_bps=3333,
        minimum_guarantee_cents=0,
        advance_cents=0,
        settlement_period="MONTHLY",
    )


# ---------------------------------------------------------------------------
# Tier 9: Convenience read helpers
# ---------------------------------------------------------------------------

def get_work(api: ApiClient, work_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_work(work_id, ADMIN_HEADERS))


def get_license(api: ApiClient, license_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_license(license_id, ADMIN_HEADERS))


def get_contract(api: ApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contract(contract_id, ADMIN_HEADERS))


def get_infringement_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_infringement_case(case_id, ADMIN_HEADERS))


def get_royalty_statement(api: ApiClient, license_id: str, statement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_royalty_statement(license_id, statement_id, ADMIN_HEADERS))


def list_rights_chain_events(api: ApiClient, work_id: str) -> List[Dict[str, Any]]:
    """Read every page of /works/{id}/rights-chain (PRD §3.2 — public endpoint)."""
    out: List[Dict[str, Any]] = []
    offset = 0
    limit = 100
    while True:
        resp = api.get_rights_chain(work_id, headers=None,
                                     params={"limit": limit, "offset": offset})
        body = resp.json()
        data = body.get("data") or []
        out.extend(data)
        meta = body.get("meta") or {}
        if not meta.get("has_more"):
            break
        offset += limit
    return out


def list_audit_logs_filtered(api: ApiClient,
                              *,
                              subject_entity: Optional[str] = None,
                              subject_id: Optional[str] = None,
                              change_type: Optional[str] = None,
                              limit: int = 100) -> List[Dict[str, Any]]:
    """Read audit logs via PlatformAdmin, optionally filtering."""
    params: Dict[str, Any] = {"limit": limit, "offset": 0}
    if subject_entity is not None:
        params["subject_entity"] = subject_entity
    if subject_id is not None:
        params["subject_id"] = subject_id
    if change_type is not None:
        params["change_type"] = change_type
    out: List[Dict[str, Any]] = []
    while True:
        resp = api.list_audit_logs(ADMIN_HEADERS, params=params)
        body = resp.json()
        data = body.get("data") or []
        out.extend(data)
        meta = body.get("meta") or {}
        if not meta.get("has_more"):
            break
        params["offset"] = params.get("offset", 0) + params.get("limit", limit)
    return out


def list_negotiation_rounds(api: ApiClient, license_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    offset = 0
    limit = 100
    while True:
        resp = api.list_rounds(license_id, ADMIN_HEADERS,
                                params={"limit": limit, "offset": offset})
        body = resp.json()
        data = body.get("data") or []
        out.extend(data)
        meta = body.get("meta") or {}
        if not meta.get("has_more"):
            break
        offset += limit
    return out
