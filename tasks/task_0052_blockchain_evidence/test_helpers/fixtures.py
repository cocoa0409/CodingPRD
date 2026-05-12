"""Composite setup helpers for the Blockchain Evidence test suite.

Most interesting test claims require the system to be in a specific
state reached through 5–15 API calls (create customer + recharge + pay
+ create evidence + notarization + notary-callback + submit + chain
confirm). These helpers encapsulate those preambles so test bodies stay
focused on assertions.

Identity threading (PRD §2.1):
- Customer is ENTITY-BACKED: 'When X-User-Role is Customer, X-User-ID
  is the id of the acting Customer.' Every ownership-gated call by a
  Customer principal MUST use make_customer_headers(customer['id']),
  never a shared fallback string.
- NotaryOfficer, JudicialOfficer, PlatformAdmin are OPAQUE.

Setup helpers use get_success_data (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion
failure inside the test body.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import (
    BASE_FEE_BY_TYPE,
    PERIOD_MULTIPLIER,
    CHAIN_CONFIRMATION_THRESHOLD,
    preservation_fee_cents,
    judicial_surcharge_cents,
)
from .factories import (
    chain_confirm_payload,
    chain_fail_payload,
    clock_payload,
    create_batch_payload,
    create_certificate_payload,
    create_customer_payload,
    create_evidence_payload,
    create_invoice_payload,
    create_judicial_package_payload,
    create_recharge_payload,
    create_timestamp_notarization_payload,
    create_verification_payload,
    judicial_ack_payload,
    notary_callback_payload,
    payment_event_payload,
    random_payment_ref,
    random_sha256_hex,
    unique_suffix,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_judicial_officer_headers,
    make_notary_officer_headers,
)


# ===========================================================================
# Shared admin headers — opaque PlatformAdmin, safe as a module constant.
# ===========================================================================
ADMIN = TEST_USERS["platform_admin_headers"]
ADMIN_ALT = TEST_USERS["platform_admin_headers_alt"]
NOTARY = TEST_USERS["notary_officer_headers"]
JUDICIAL = TEST_USERS["judicial_officer_headers"]
JUDICIAL_ALT = TEST_USERS["judicial_officer_headers_alt"]


# ===========================================================================
# Clock helpers (PRD §3.10)
# ===========================================================================
def advance_clock(to_iso: str,
                  headers: Optional[Dict[str, str]] = None) -> None:
    """PRD §3.10: 'the clock-advance capability writes the server's
    logical clock to a supplied to_iso8601 instant'."""
    get_success_data(api_client.advance_clock(
        clock_payload(to_iso), headers or ADMIN,
    ))


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.4: 'the expiry sweep capability flips every CONFIRMED
    evidence whose expires_at has passed into EXPIRED'."""
    return get_success_data(api_client.run_sweep(headers or ADMIN))


def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision, Z-suffixed."""
    return dt.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ===========================================================================
# Customer creation + wallet topup
# ===========================================================================
def create_customer(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'PlatformAdmin bootstraps a Customer record carrying
    an email and a display_name'."""
    res = api_client.create_customer(
        create_customer_payload(**overrides), ADMIN,
    )
    return get_success_data(res)


def recharge_and_pay(customer: Dict[str, Any],
                     amount_cents: int = 1_000_000) -> Dict[str, Any]:
    """PRD §3.1 round trip: open a PENDING Recharge (Customer principal),
    then PlatformAdmin delivers a payment event with status SUCCESS.

    The Recharge POST is ownership-gated (per priority-3 check) — so we
    pass make_customer_headers(customer['id'])."""
    headers = make_customer_headers(customer["id"])
    ref = random_payment_ref()
    rch = get_success_data(api_client.create_recharge(
        create_recharge_payload(
            customer_id=customer["id"],
            amount_cents=amount_cents,
            external_payment_ref=ref,
        ),
        headers,
    ))
    get_success_data(api_client.deliver_payment_event(
        payment_event_payload(external_payment_ref=ref, status="SUCCESS"),
        ADMIN,
    ))
    return rch


def create_customer_with_balance(balance_cents: int = 1_000_000,
                                  **customer_overrides: Any
                                  ) -> Dict[str, Any]:
    """Create a Customer and credit `balance_cents` to its wallet."""
    customer = create_customer(**customer_overrides)
    if balance_cents > 0:
        recharge_and_pay(customer, amount_cents=balance_cents)
    return get_customer(customer["id"])


def get_customer(customer_id: str) -> Dict[str, Any]:
    """Re-read a customer (admin headers; opaque role, no ownership)."""
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


# ===========================================================================
# Evidence creation (PRD §3.2)
# ===========================================================================
def create_evidence(customer: Dict[str, Any],
                    **overrides: Any) -> Dict[str, Any]:
    """Create an Evidence in PENDING for `customer`.

    Per PRD §2.10 priority-3 ownership check, the request uses
    make_customer_headers(customer['id']) so X-User-ID == customer.id.
    """
    payload = create_evidence_payload(
        customer_id=customer["id"], **overrides,
    )
    res = api_client.create_evidence(
        payload, make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def get_evidence(evidence_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_evidence(
        evidence_id, headers or ADMIN,
    ))


def create_notarization(evidence: Dict[str, Any],
                        *,
                        tsa_provider: str = "RFC3161_TSA_A",
                        complete: bool = True,
                        ) -> Dict[str, Any]:
    """Create a TimestampNotarization for `evidence`. When complete=True,
    drive the notary callback so trusted_time and tsa_token are
    populated (PRD §3.2: 'the platform completes the notarization
    asynchronously via the notary callback, which populates
    trusted_time ... and tsa_token').
    """
    # Created by the Customer principal (PRD §4 shared with NotaryOfficer).
    customer_id = evidence["customer_id"]
    payload = create_timestamp_notarization_payload(
        evidence_id=evidence["id"], tsa_provider=tsa_provider,
    )
    notar = get_success_data(api_client.create_timestamp_notarization(
        payload, make_customer_headers(customer_id),
    ))
    if complete:
        trusted_time = iso_z(datetime.now(timezone.utc))
        get_success_data(api_client.deliver_notary_callback(
            notary_callback_payload(
                timestamp_notarization_id=notar["id"],
                trusted_time=trusted_time,
            ),
            ADMIN,
        ))
    return notar


# ===========================================================================
# Single-evidence anchoring (PRD §3.3)
# ===========================================================================
def submit_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """POST /evidences/{id}/submit as the owning Customer."""
    headers = make_customer_headers(evidence["customer_id"])
    return get_success_data(api_client.submit_evidence(
        evidence["id"], headers,
    ))


def resubmit_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_customer_headers(evidence["customer_id"])
    return get_success_data(api_client.resubmit_evidence(
        evidence["id"], headers,
    ))


def latest_onchain_tx_for_evidence(evidence_id: str) -> Dict[str, Any]:
    """Read the Evidence row's most recent OnChainTx by querying the
    audit log for EVIDENCE_SUBMITTED / EVIDENCE_RESUBMITTED events and
    matching their detail.tx_id.

    The OnChainTx is created as a SUBMITTING side-effect; the audit-log
    snapshot captures its id in the detail payload. We use this rather
    than guessing because PRD §3.10 explicitly grants `tx_id` (the
    OnChainTx.id) as the chain-confirm input.
    """
    # Pull audit logs for this evidence.
    audit_rows, _meta = validate_paginated(api_client.list_audit_logs(
        ADMIN, params={"target_entity": "Evidence", "target_id": evidence_id},
    ))
    # Filter to submission events ordered by created_at; the latest is last.
    submission_events = [
        r for r in audit_rows
        if r.get("event_type") in (
            "EVIDENCE_SUBMITTED", "EVIDENCE_RESUBMITTED",
        )
    ]
    submission_events.sort(key=lambda r: r.get("created_at", ""))
    if not submission_events:
        raise RuntimeError(
            f"No EVIDENCE_SUBMITTED/RESUBMITTED audit row for "
            f"Evidence {evidence_id}"
        )
    detail = submission_events[-1].get("detail") or {}
    tx_id = detail.get("tx_id") or detail.get("on_chain_tx_id") or (
        detail.get("after") or {}).get("tx_id"
    )
    if not tx_id:
        # Fallback: list OnChainTx is not part of the public API, so the
        # detail snapshot is the only way for tests to discover the tx
        # id. Surface a clear setup error.
        raise RuntimeError(
            f"Audit detail snapshot does not include tx_id: "
            f"{submission_events[-1]!r}"
        )
    return {"id": tx_id}


def latest_onchain_tx_for_batch(batch_id: str) -> Dict[str, Any]:
    """Discover the latest OnChainTx for a Batch via its BATCH_CONFIRMED
    or earlier submission audit rows. PRD §2.12: 'each AuditLog row
    records ... target_entity ... target_id ... detail JSON object'."""
    # Try audit rows of target_entity=Batch first.
    rows, _ = validate_paginated(api_client.list_audit_logs(
        ADMIN, params={"target_entity": "Batch", "target_id": batch_id},
    ))
    rows.sort(key=lambda r: r.get("created_at", ""))
    for r in reversed(rows):
        detail = r.get("detail") or {}
        tx_id = detail.get("tx_id") or detail.get("on_chain_tx_id") or (
            detail.get("after") or {}).get("tx_id"
        )
        if tx_id:
            return {"id": tx_id}
    # Fallback to OnChainTx rows
    rows, _ = validate_paginated(api_client.list_audit_logs(
        ADMIN, params={"target_entity": "OnChainTx"},
    ))
    rows = [r for r in rows if (r.get("detail") or {}).get(
        "batch_id") == batch_id]
    rows.sort(key=lambda r: r.get("created_at", ""))
    if rows:
        return {"id": rows[-1].get("target_id")}
    raise RuntimeError(f"No OnChainTx audit row for Batch {batch_id}")


def chain_confirm(tx_id: str,
                  *,
                  block_height: int = 1_000_000,
                  confirmations: int = 12,
                  ) -> Dict[str, Any]:
    """PRD §3.10: 'chain-confirm capability ... naming the affected
    tx_id and reporting the observed block_height and confirmations.'"""
    return get_success_data(api_client.chain_confirm(
        chain_confirm_payload(
            tx_id=tx_id,
            block_height=block_height,
            confirmations=confirmations,
        ),
        ADMIN,
    ))


def chain_fail(tx_id: str,
               *,
               reason: str = "simulated chain failure") -> Dict[str, Any]:
    return get_success_data(api_client.chain_fail(
        chain_fail_payload(tx_id=tx_id, reason=reason),
        ADMIN,
    ))


# ===========================================================================
# Full single-evidence pipeline shortcuts
# ===========================================================================
def bring_evidence_to_submitting(
    *,
    balance_cents: int = 1_000_000,
    evidence_overrides: Optional[Dict[str, Any]] = None,
    customer: Optional[Dict[str, Any]] = None,
    attach_notarization: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    """Customer (balance) + Evidence + optional Notarization, then
    POST /submit. Returns (customer, evidence_after_submit, notar)."""
    if customer is None:
        customer = create_customer_with_balance(balance_cents)
    evidence = create_evidence(customer, **(evidence_overrides or {}))
    notar = None
    if attach_notarization:
        notar = create_notarization(evidence)
    evidence = submit_evidence(evidence)
    return customer, evidence, notar


def bring_evidence_to_confirmed(
    *,
    balance_cents: int = 1_000_000,
    evidence_overrides: Optional[Dict[str, Any]] = None,
    customer: Optional[Dict[str, Any]] = None,
    confirmations: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive an Evidence end-to-end: create + notarize + submit + chain
    confirm so the Evidence ends in CONFIRMED. Returns (customer,
    evidence_after_confirm).

    Default confirmations is the ETHEREUM threshold (12).
    """
    customer, evidence, _notar = bring_evidence_to_submitting(
        balance_cents=balance_cents,
        evidence_overrides=evidence_overrides,
        customer=customer,
    )
    chain_id = evidence["chain_id"]
    needed = CHAIN_CONFIRMATION_THRESHOLD[chain_id]
    conf = confirmations if confirmations is not None else needed
    tx = latest_onchain_tx_for_evidence(evidence["id"])
    chain_confirm(tx["id"], confirmations=conf)
    evidence = get_evidence(evidence["id"])
    return customer, evidence


def bring_evidence_to_failed(
    *,
    balance_cents: int = 1_000_000,
    evidence_overrides: Optional[Dict[str, Any]] = None,
    customer: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Submit + chain-fail → evidence in FAILED."""
    customer, evidence, _notar = bring_evidence_to_submitting(
        balance_cents=balance_cents,
        evidence_overrides=evidence_overrides,
        customer=customer,
    )
    tx = latest_onchain_tx_for_evidence(evidence["id"])
    chain_fail(tx["id"])
    return customer, get_evidence(evidence["id"])


# ===========================================================================
# Certificate (PRD §3.6)
# ===========================================================================
def create_certificate(evidence: Dict[str, Any],
                       *,
                       template_code: str = "STANDARD",
                       use_admin: bool = False,
                       ) -> Dict[str, Any]:
    """Issue a Certificate against a CONFIRMED Evidence. Default caller
    is the owning Customer (shared with PlatformAdmin per PRD §4)."""
    headers = (
        ADMIN if use_admin
        else make_customer_headers(evidence["customer_id"])
    )
    res = api_client.create_certificate(
        create_certificate_payload(
            evidence_id=evidence["id"], template_code=template_code,
        ),
        headers,
    )
    return get_success_data(res)


# ===========================================================================
# Batch (PRD §3.5)
# ===========================================================================
def create_pending_evidences(customer: Dict[str, Any],
                              count: int,
                              *,
                              evidence_overrides: Optional[Dict[str, Any]] = None,
                              ) -> List[Dict[str, Any]]:
    """Create `count` PENDING evidences for the same customer."""
    out: List[Dict[str, Any]] = []
    overrides = evidence_overrides or {}
    for _i in range(count):
        out.append(create_evidence(customer, **overrides))
    return out


def create_batch(customer: Dict[str, Any],
                 evidence_ids: List[str],
                 *,
                 chain_id: str = "ETHEREUM",
                 ) -> Dict[str, Any]:
    headers = make_customer_headers(customer["id"])
    payload = create_batch_payload(
        customer_id=customer["id"],
        evidence_ids=evidence_ids,
        chain_id=chain_id,
    )
    return get_success_data(api_client.create_batch(payload, headers))


def submit_batch(customer: Dict[str, Any],
                 batch_id: str) -> Dict[str, Any]:
    headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.submit_batch(batch_id, headers))


def bring_batch_to_submitting(
    *,
    member_count: int = 10,
    evidence_overrides: Optional[Dict[str, Any]] = None,
    balance_cents: int = 100_000,
    customer: Optional[Dict[str, Any]] = None,
    chain_id: str = "ETHEREUM",
    attach_notarization: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Create a batch + submit it. Returns (customer, batch, evidences)."""
    if customer is None:
        customer = create_customer_with_balance(balance_cents)
    evidences = create_pending_evidences(
        customer, member_count, evidence_overrides=evidence_overrides,
    )
    if attach_notarization:
        for ev in evidences:
            create_notarization(ev)
    batch = create_batch(
        customer, [e["id"] for e in evidences], chain_id=chain_id,
    )
    batch = submit_batch(customer, batch["id"])
    return customer, batch, evidences


def bring_batch_to_confirmed(
    *,
    member_count: int = 10,
    evidence_overrides: Optional[Dict[str, Any]] = None,
    balance_cents: int = 100_000,
    customer: Optional[Dict[str, Any]] = None,
    chain_id: str = "ETHEREUM",
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Walk a batch through PENDING → SUBMITTING → CONFIRMED."""
    customer, batch, evidences = bring_batch_to_submitting(
        member_count=member_count,
        evidence_overrides=evidence_overrides,
        balance_cents=balance_cents,
        customer=customer,
        chain_id=chain_id,
    )
    needed = CHAIN_CONFIRMATION_THRESHOLD[chain_id]
    tx = latest_onchain_tx_for_batch(batch["id"])
    chain_confirm(tx["id"], confirmations=needed)
    batch = get_success_data(api_client.get_batch(batch["id"], ADMIN))
    return customer, batch, evidences


# ===========================================================================
# JudicialPackage (PRD §3.7)
# ===========================================================================
def create_judicial_package(evidence: Dict[str, Any],
                             *,
                             authority_code: str = "COURT_BJ",
                             include_original_data: Any = "__OMIT__",
                             officer_headers: Optional[Dict[str, str]] = None,
                             **overrides: Any,
                             ) -> Dict[str, Any]:
    """PRD §3.7: a JudicialOfficer opens a DRAFT package for an
    Evidence. Authority code drives the surcharge multiplier."""
    payload = create_judicial_package_payload(
        evidence_id=evidence["id"],
        authority_code=authority_code,
        include_original_data=include_original_data,
        **overrides,
    )
    return get_success_data(api_client.create_judicial_package(
        payload, officer_headers or JUDICIAL,
    ))


def seal_judicial_package(package_id: str,
                          *,
                          officer_headers: Optional[Dict[str, str]] = None,
                          ) -> Dict[str, Any]:
    return get_success_data(api_client.seal_judicial_package(
        package_id, officer_headers or JUDICIAL,
    ))


def deliver_judicial_package(package_id: str,
                              *,
                              officer_headers: Optional[Dict[str, str]] = None,
                              ) -> Dict[str, Any]:
    return get_success_data(api_client.deliver_judicial_package(
        package_id, officer_headers or JUDICIAL,
    ))


def setup_sealed_judicial_package(
    *,
    authority_code: str = "COURT_BJ",
    include_original_data: bool = False,
    balance_cents: int = 100_000,
    evidence_overrides: Optional[Dict[str, Any]] = None,
    customer: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive evidence to CONFIRMED, issue an ISSUED Certificate, then
    create + seal a JudicialPackage. Returns
    (customer, evidence, certificate, sealed_package)."""
    customer, evidence = bring_evidence_to_confirmed(
        balance_cents=balance_cents,
        evidence_overrides=evidence_overrides,
        customer=customer,
    )
    cert = create_certificate(evidence)
    pkg = create_judicial_package(
        evidence,
        authority_code=authority_code,
        include_original_data=include_original_data,
    )
    sealed = seal_judicial_package(pkg["id"])
    return customer, evidence, cert, sealed


# ===========================================================================
# Audit log read helper
# ===========================================================================
def list_audit_logs(*,
                    event_type: Optional[str] = None,
                    target_entity: Optional[str] = None,
                    target_id: Optional[str] = None,
                    limit: int = 100,
                    ) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": limit}
    if event_type:
        params["event_type"] = event_type
    if target_entity:
        params["target_entity"] = target_entity
    if target_id:
        params["target_id"] = target_id
    rows, _meta = validate_paginated(
        api_client.list_audit_logs(ADMIN, params=params),
    )
    return rows


__all__ = [
    "ADMIN",
    "ADMIN_ALT",
    "NOTARY",
    "JUDICIAL",
    "JUDICIAL_ALT",
    "advance_clock",
    "run_sweep",
    "iso_z",
    "create_customer",
    "recharge_and_pay",
    "create_customer_with_balance",
    "get_customer",
    "create_evidence",
    "get_evidence",
    "create_notarization",
    "submit_evidence",
    "resubmit_evidence",
    "latest_onchain_tx_for_evidence",
    "latest_onchain_tx_for_batch",
    "chain_confirm",
    "chain_fail",
    "bring_evidence_to_submitting",
    "bring_evidence_to_confirmed",
    "bring_evidence_to_failed",
    "create_certificate",
    "create_pending_evidences",
    "create_batch",
    "submit_batch",
    "bring_batch_to_submitting",
    "bring_batch_to_confirmed",
    "create_judicial_package",
    "seal_judicial_package",
    "deliver_judicial_package",
    "setup_sealed_judicial_package",
    "list_audit_logs",
]
