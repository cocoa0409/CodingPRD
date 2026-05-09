"""Composite setup helpers for the Flight Delay Claims API.

Design principles
-----------------
* Every fixture uses get_success_data() so setup failures yield clear
  "Setup failed" errors, not assertion noise.
* All roles are opaque per PRD §2.1 — the server records X-User-ID where a
  state machine demands it (assigned_reviewer_id, assigned_approver_id,
  payout_operator_id, assigned_batch_approver_id, assigned_batch_executor_id)
  but does not compare it to any entity id. SoD is enforced by comparing
  these recorded values to the X-User-ID on later calls. Fixtures therefore
  thread DISTINCT operator ids through the reviewer / approver / batch
  approver / batch executor / payout operator steps so SoD passes.
* Helpers that walk the lifecycle return tuples of dicts so test functions
  can assert downstream side effects (e.g. policy.reserve_balance_cents).
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client, ApiClient
from .factories import (
    create_insurer_payload,
    create_policy_payload,
    create_flight_payload,
    create_ticket_payload,
    create_claim_payload,
    claim_segment_input,
    flight_event_payload,
    submit_review_payload,
    approve_claim_payload,
    reject_claim_payload,
    create_batch_payload,
    approve_batch_payload,
    reject_batch_payload,
    execute_batch_payload,
    suspend_policy_payload,
    clock_advance_to_payload,
    clock_advance_delta_payload,
    unique_doc_id,
    unique_pnr,
    unique_source_event_id,
)
from .test_users import (
    TEST_USERS,
    make_claims_admin_headers,
    make_policy_admin_headers,
    make_claims_reviewer_headers,
    make_claims_approver_headers,
    make_batch_approver_headers,
    make_batch_executor_headers,
    make_payout_operator_headers,
    make_system_headers,
    make_auditor_headers,
)
from .constants import (
    QUORUM_WINDOW_MS,
    DEFAULT_DEDUCTIBLE_CENTS,
    DEFAULT_POLICY_LIMIT_CENTS,
    DEFAULT_QUOTA_TOTAL_CENTS,
    DEFAULT_CURRENCY,
)


# ---------------------------------------------------------------------------
# Operator id helpers — distinct ids for SoD-sensitive steps.
# ---------------------------------------------------------------------------

def fresh_operator_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Insurer
# ---------------------------------------------------------------------------

def create_insurer(*, name: str = "Test Insurer", currency: str = DEFAULT_CURRENCY) -> Dict[str, Any]:
    """Create an insurer with the test clock at 0 (PRD §2.6: 'now_epoch_ms ...
    begins at 0 on insurer creation')."""
    resp = api_client.create_insurer(
        create_insurer_payload(name=name, currency=currency),
        TEST_USERS["claims_admin_headers"],
    )
    return get_success_data(resp)


def advance_clock_to(insurer_id: str, to_epoch_ms: int) -> Dict[str, Any]:
    resp = api_client.advance_clock(
        insurer_id,
        clock_advance_to_payload(to_epoch_ms=to_epoch_ms),
        TEST_USERS["claims_admin_headers"],
    )
    return get_success_data(resp)


def advance_clock_by(insurer_id: str, delta_ms: int) -> Dict[str, Any]:
    resp = api_client.advance_clock(
        insurer_id,
        clock_advance_delta_payload(delta_ms=delta_ms),
        TEST_USERS["claims_admin_headers"],
    )
    return get_success_data(resp)


def run_sweep(insurer_id: str) -> Dict[str, Any]:
    resp = api_client.run_sweep(insurer_id, TEST_USERS["claims_admin_headers"])
    return get_success_data(resp)


def get_insurer(insurer_id: str) -> Dict[str, Any]:
    resp = api_client.get_insurer(insurer_id, TEST_USERS["claims_admin_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def create_policy(
    insurer_id: str,
    *,
    policy_holder_doc_id: Optional[str] = None,
    delay_basis: str = "DEPARTURE",
    payout_mode: str = "FIXED",
    reimbursement_rate_bps: int = 0,
    deductible_cents: int = DEFAULT_DEDUCTIBLE_CENTS,
    policy_limit_cents: int = DEFAULT_POLICY_LIMIT_CENTS,
    claim_quota_total_cents: int = DEFAULT_QUOTA_TOTAL_CENTS,
    waiting_period_ms: int = 0,
    excluded_delay_causes: Optional[List[str]] = None,
    effective_from_epoch_ms: int = 0,
    effective_to_epoch_ms: int = 10_000_000_000_000,
    **overrides,
) -> Dict[str, Any]:
    payload = create_policy_payload(
        policy_holder_doc_id=policy_holder_doc_id,
        delay_basis=delay_basis,
        payout_mode=payout_mode,
        reimbursement_rate_bps=reimbursement_rate_bps,
        deductible_cents=deductible_cents,
        policy_limit_cents=policy_limit_cents,
        claim_quota_total_cents=claim_quota_total_cents,
        waiting_period_ms=waiting_period_ms,
        excluded_delay_causes=excluded_delay_causes,
        effective_from_epoch_ms=effective_from_epoch_ms,
        effective_to_epoch_ms=effective_to_epoch_ms,
        **overrides,
    )
    resp = api_client.create_policy(insurer_id, payload, TEST_USERS["policy_admin_headers"])
    return get_success_data(resp)


def get_policy(insurer_id: str, policy_id: str) -> Dict[str, Any]:
    resp = api_client.get_policy(insurer_id, policy_id, TEST_USERS["policy_admin_headers"])
    return get_success_data(resp)


def get_risk_view(insurer_id: str, policy_id: str) -> Dict[str, Any]:
    resp = api_client.get_risk_view(insurer_id, policy_id, TEST_USERS["policy_admin_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Flight + multi-source quorum
# ---------------------------------------------------------------------------

def create_flight(
    insurer_id: str,
    *,
    scheduled_departure_epoch_ms: int = 10_000_000,
    scheduled_arrival_epoch_ms: int = 15_000_000,
    **overrides,
) -> Dict[str, Any]:
    payload = create_flight_payload(
        scheduled_departure_epoch_ms=scheduled_departure_epoch_ms,
        scheduled_arrival_epoch_ms=scheduled_arrival_epoch_ms,
        **overrides,
    )
    resp = api_client.create_flight(insurer_id, payload, TEST_USERS["claims_admin_headers"])
    return get_success_data(resp)


def get_flight(insurer_id: str, flight_id: str) -> Dict[str, Any]:
    resp = api_client.get_flight(insurer_id, flight_id, TEST_USERS["claims_admin_headers"])
    return get_success_data(resp)


def ingest_event(
    insurer_id: str,
    flight_id: str,
    *,
    source: str,
    reported_status: str,
    reported_actual_departure_epoch_ms: Optional[int] = None,
    reported_actual_arrival_epoch_ms: Optional[int] = None,
    reported_cause: Optional[str] = None,
    source_event_id: Optional[str] = None,
    report_epoch_ms: int = 0,
) -> Dict[str, Any]:
    payload = flight_event_payload(
        source=source,
        reported_status=reported_status,
        reported_actual_departure_epoch_ms=reported_actual_departure_epoch_ms,
        reported_actual_arrival_epoch_ms=reported_actual_arrival_epoch_ms,
        reported_cause=reported_cause,
        source_event_id=source_event_id or unique_source_event_id(),
        report_epoch_ms=report_epoch_ms,
    )
    resp = api_client.ingest_flight_event(
        insurer_id, flight_id, payload, TEST_USERS["claims_admin_headers"]
    )
    return get_success_data(resp)


def finalize_flight_landed(
    insurer_id: str,
    flight_id: str,
    *,
    actual_departure_epoch_ms: int,
    actual_arrival_epoch_ms: int,
    cause: Optional[str] = "AIRLINE",
) -> Dict[str, Any]:
    """Push two quorum events (AIRLINE + AVIATION_AUTHORITY) reporting LANDED
    so the flight transitions to LANDED via PRD §2.7 quorum.

    Per PRD §2.7: 'A quorum exists for a particular reported status when at
    least two distinct sources report it, and at least one of those distinct
    sources is AIRLINE or AVIATION_AUTHORITY.'
    """
    ingest_event(
        insurer_id, flight_id,
        source="AIRLINE",
        reported_status="DELAYED",
        reported_actual_departure_epoch_ms=actual_departure_epoch_ms,
        reported_actual_arrival_epoch_ms=actual_arrival_epoch_ms,
        reported_cause=cause,
    )
    ingest_event(
        insurer_id, flight_id,
        source="AVIATION_AUTHORITY",
        reported_status="DELAYED",
        reported_actual_departure_epoch_ms=actual_departure_epoch_ms,
        reported_actual_arrival_epoch_ms=actual_arrival_epoch_ms,
        reported_cause=cause,
    )
    return get_flight(insurer_id, flight_id)


def finalize_flight_cancelled(
    insurer_id: str,
    flight_id: str,
    *,
    cause: Optional[str] = "AIRLINE",
) -> Dict[str, Any]:
    ingest_event(
        insurer_id, flight_id,
        source="AIRLINE",
        reported_status="CANCELLED",
        reported_cause=cause,
    )
    ingest_event(
        insurer_id, flight_id,
        source="AVIATION_AUTHORITY",
        reported_status="CANCELLED",
        reported_cause=cause,
    )
    return get_flight(insurer_id, flight_id)


# ---------------------------------------------------------------------------
# Ticket
# ---------------------------------------------------------------------------

def create_ticket(
    insurer_id: str,
    *,
    flight_id: str,
    passenger_doc_id: Optional[str] = None,
    pnr_code: Optional[str] = None,
    policy_id: Optional[str] = None,
    passenger_name: str = "Alice Example",
) -> Dict[str, Any]:
    payload = create_ticket_payload(
        flight_id=flight_id,
        passenger_doc_id=passenger_doc_id or unique_doc_id(),
        pnr_code=pnr_code or unique_pnr(),
        policy_id=policy_id,
        passenger_name=passenger_name,
    )
    resp = api_client.create_ticket(insurer_id, payload, TEST_USERS["policy_admin_headers"])
    return get_success_data(resp)


def get_ticket(insurer_id: str, ticket_id: str) -> Dict[str, Any]:
    resp = api_client.get_ticket(insurer_id, ticket_id, TEST_USERS["policy_admin_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

def create_claim(
    insurer_id: str,
    policy_id: str,
    *,
    ticket_ids: List[str],
    segments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    payload = create_claim_payload(ticket_ids=ticket_ids, segments=segments)
    resp = api_client.create_claim(
        insurer_id, policy_id, payload, TEST_USERS["claims_reviewer_headers"]
    )
    return get_success_data(resp)


def get_claim(insurer_id: str, claim_id: str) -> Dict[str, Any]:
    resp = api_client.get_claim(insurer_id, claim_id, TEST_USERS["claims_reviewer_headers"])
    return get_success_data(resp)


def submit_review(
    insurer_id: str,
    claim_id: str,
    *,
    reviewer_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Submit a claim for review with a fresh reviewer id (default).

    Returns (claim_dict, reviewer_id). Tests can re-use the reviewer_id when
    they need to call return_to_match (PRD §3.4: only the recorded
    assigned_reviewer_id may return_to_match).
    """
    rid = reviewer_id or fresh_operator_id("rev")
    resp = api_client.submit_review(
        insurer_id,
        claim_id,
        submit_review_payload(assigned_reviewer_id=rid),
        make_claims_reviewer_headers(rid),
    )
    return get_success_data(resp), rid


def return_to_match(insurer_id: str, claim_id: str, *, reviewer_id: str) -> Dict[str, Any]:
    resp = api_client.return_to_match(
        insurer_id, claim_id, make_claims_reviewer_headers(reviewer_id)
    )
    return get_success_data(resp)


def approve_claim(
    insurer_id: str,
    claim_id: str,
    *,
    approver_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Approve with a fresh approver id distinct from any reviewer id used
    earlier (PRD §3.4: 'The approver's X-User-ID must differ from the claim's
    assigned_reviewer_id (otherwise ERR_SOD_VIOLATION).')."""
    aid = approver_id or fresh_operator_id("apr")
    resp = api_client.approve_claim(
        insurer_id,
        claim_id,
        approve_claim_payload(assigned_approver_id=aid),
        make_claims_approver_headers(aid),
    )
    return get_success_data(resp), aid


def reject_claim(
    insurer_id: str,
    claim_id: str,
    *,
    rejection_reason: str,
    reviewer_id: Optional[str] = None,
) -> Dict[str, Any]:
    rid = reviewer_id or fresh_operator_id("rev")
    resp = api_client.reject_claim(
        insurer_id,
        claim_id,
        reject_claim_payload(rejection_reason=rejection_reason),
        make_claims_reviewer_headers(rid),
    )
    return get_success_data(resp)


def settle_claim(
    insurer_id: str,
    claim_id: str,
    *,
    operator_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    pid = operator_id or fresh_operator_id("po")
    resp = api_client.settle_claim(
        insurer_id, claim_id, make_payout_operator_headers(pid)
    )
    return get_success_data(resp), pid


def reverse_claim(insurer_id: str, claim_id: str) -> Dict[str, Any]:
    resp = api_client.reverse_claim(
        insurer_id, claim_id, TEST_USERS["claims_admin_headers"]
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Batch lifecycle
# ---------------------------------------------------------------------------

def create_batch(
    insurer_id: str,
    *,
    flight_id: str,
    claim_ids: List[str],
) -> Dict[str, Any]:
    resp = api_client.create_payout_batch(
        insurer_id,
        create_batch_payload(flight_id=flight_id, claim_ids=claim_ids),
        TEST_USERS["batch_approver_headers"],
    )
    return get_success_data(resp)


def approve_batch(
    insurer_id: str,
    batch_id: str,
    *,
    approver_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Approve with a fresh BatchApprover id distinct from every claim's
    assigned_approver_id (PRD §3.8: 'a per-claim approver cannot serve as the
    batch approver for a batch containing that claim')."""
    bid = approver_id or fresh_operator_id("ba")
    resp = api_client.approve_batch(
        insurer_id,
        batch_id,
        approve_batch_payload(assigned_batch_approver_id=bid),
        make_batch_approver_headers(bid),
    )
    return get_success_data(resp), bid


def reject_batch(
    insurer_id: str,
    batch_id: str,
    *,
    reason: str = "test reject",
) -> Dict[str, Any]:
    resp = api_client.reject_batch(
        insurer_id,
        batch_id,
        reject_batch_payload(reason=reason),
        TEST_USERS["batch_approver_headers"],
    )
    return get_success_data(resp)


def execute_batch(
    insurer_id: str,
    batch_id: str,
    *,
    executor_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Execute with a fresh BatchExecutor id distinct from the
    assigned_batch_approver_id (PRD §3.9: 'must differ from the recorded
    assigned_batch_approver_id (otherwise ERR_SOD_VIOLATION)')."""
    xid = executor_id or fresh_operator_id("bx")
    resp = api_client.execute_batch(
        insurer_id,
        batch_id,
        execute_batch_payload(assigned_batch_executor_id=xid),
        make_batch_executor_headers(xid),
    )
    return get_success_data(resp), xid


def retry_exceptions(insurer_id: str, batch_id: str, *, executor_id: str) -> Dict[str, Any]:
    resp = api_client.retry_exceptions(
        insurer_id, batch_id, make_batch_executor_headers(executor_id)
    )
    return get_success_data(resp)


def mark_exception(
    insurer_id: str,
    claim_id: str,
    *,
    operator_id: Optional[str] = None,
    reason: str = "banking failure",
) -> Tuple[Dict[str, Any], str]:
    pid = operator_id or fresh_operator_id("po")
    resp = api_client.mark_exception(
        insurer_id, claim_id,
        make_payout_operator_headers(pid),
        {"reason": reason},
    )
    return get_success_data(resp), pid


# ---------------------------------------------------------------------------
# Audit / outbox
# ---------------------------------------------------------------------------

def list_audit_logs(insurer_id: str, **params) -> List[Dict[str, Any]]:
    resp = api_client.list_audit_logs(
        insurer_id, TEST_USERS["claims_admin_headers"], params or None
    )
    payload = get_success_data(resp)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "items" in payload:
        return payload["items"]
    return payload  # framework normalises this to a list


def list_outbox_events(insurer_id: str, **params) -> List[Dict[str, Any]]:
    resp = api_client.list_outbox_events(
        insurer_id, TEST_USERS["claims_admin_headers"], params or None
    )
    payload = get_success_data(resp)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "items" in payload:
        return payload["items"]
    return payload


# ---------------------------------------------------------------------------
# Composite scenarios — the meat of fixtures.py
# ---------------------------------------------------------------------------

def setup_basic_insurer_with_policy(
    *,
    delay_basis: str = "DEPARTURE",
    payout_mode: str = "FIXED",
    reimbursement_rate_bps: int = 0,
    deductible_cents: int = DEFAULT_DEDUCTIBLE_CENTS,
    policy_limit_cents: int = DEFAULT_POLICY_LIMIT_CENTS,
    claim_quota_total_cents: int = DEFAULT_QUOTA_TOTAL_CENTS,
    waiting_period_ms: int = 0,
    excluded_delay_causes: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    insurer = create_insurer()
    policy = create_policy(
        insurer["id"],
        delay_basis=delay_basis,
        payout_mode=payout_mode,
        reimbursement_rate_bps=reimbursement_rate_bps,
        deductible_cents=deductible_cents,
        policy_limit_cents=policy_limit_cents,
        claim_quota_total_cents=claim_quota_total_cents,
        waiting_period_ms=waiting_period_ms,
        excluded_delay_causes=excluded_delay_causes,
    )
    return insurer, policy


def setup_flight_with_delay(
    insurer_id: str,
    *,
    scheduled_departure_epoch_ms: int = 10_000_000,
    scheduled_arrival_epoch_ms: int = 15_000_000,
    departure_delay_minutes: int = 200,
    arrival_delay_minutes: Optional[int] = None,
    cause: Optional[str] = "AIRLINE",
) -> Dict[str, Any]:
    """Create a flight, advance the clock past arrival, and finalize it via
    quorum. Returns the LANDED flight.

    If arrival_delay_minutes is None it equals departure_delay_minutes (no
    in-air time make-up).
    """
    if arrival_delay_minutes is None:
        arrival_delay_minutes = departure_delay_minutes
    flight = create_flight(
        insurer_id,
        scheduled_departure_epoch_ms=scheduled_departure_epoch_ms,
        scheduled_arrival_epoch_ms=scheduled_arrival_epoch_ms,
    )
    actual_dep = scheduled_departure_epoch_ms + departure_delay_minutes * 60_000
    actual_arr = scheduled_arrival_epoch_ms + arrival_delay_minutes * 60_000
    # Advance the clock past arrival so the flight is event-finalisable.
    advance_clock_to(insurer_id, actual_arr + 1)
    flight = finalize_flight_landed(
        insurer_id,
        flight["id"],
        actual_departure_epoch_ms=actual_dep,
        actual_arrival_epoch_ms=actual_arr,
        cause=cause,
    )
    return flight


def setup_basic_claim_in_matched(
    *,
    delay_basis: str = "DEPARTURE",
    payout_mode: str = "FIXED",
    reimbursement_rate_bps: int = 0,
    deductible_cents: int = DEFAULT_DEDUCTIBLE_CENTS,
    policy_limit_cents: int = DEFAULT_POLICY_LIMIT_CENTS,
    claim_quota_total_cents: int = DEFAULT_QUOTA_TOTAL_CENTS,
    waiting_period_ms: int = 0,
    excluded_delay_causes: Optional[List[str]] = None,
    departure_delay_minutes: int = 200,
    arrival_delay_minutes: Optional[int] = None,
    cause: Optional[str] = "AIRLINE",
    claimed_actual_loss_cents: int = 0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build the canonical lifecycle preamble:
    insurer → policy → flight (LANDED via quorum) → ticket (ATTACHED) →
    claim (auto-MATCHED).

    Returns (insurer, policy, flight, ticket, claim).
    """
    insurer, policy = setup_basic_insurer_with_policy(
        delay_basis=delay_basis,
        payout_mode=payout_mode,
        reimbursement_rate_bps=reimbursement_rate_bps,
        deductible_cents=deductible_cents,
        policy_limit_cents=policy_limit_cents,
        claim_quota_total_cents=claim_quota_total_cents,
        waiting_period_ms=waiting_period_ms,
        excluded_delay_causes=excluded_delay_causes,
    )
    flight = setup_flight_with_delay(
        insurer["id"],
        departure_delay_minutes=departure_delay_minutes,
        arrival_delay_minutes=arrival_delay_minutes,
        cause=cause,
    )
    ticket = create_ticket(
        insurer["id"],
        flight_id=flight["id"],
        passenger_doc_id=policy["policy_holder_doc_id"],
        passenger_name=policy["policy_holder_name"],
    )
    segments = None
    if claimed_actual_loss_cents:
        segments = [claim_segment_input(
            ticket_id=ticket["id"],
            claimed_actual_loss_cents=claimed_actual_loss_cents,
        )]
    claim = create_claim(
        insurer["id"], policy["id"],
        ticket_ids=[ticket["id"]],
        segments=segments,
    )
    return insurer, policy, flight, ticket, claim


def setup_claim_under_review(
    **kwargs,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """Full preamble + submit_review.

    Returns (insurer, policy, flight, ticket, claim_under_review, reviewer_id).
    """
    insurer, policy, flight, ticket, claim = setup_basic_claim_in_matched(**kwargs)
    reviewed, reviewer_id = submit_review(insurer["id"], claim["id"])
    return insurer, policy, flight, ticket, reviewed, reviewer_id


def setup_claim_approved(
    **kwargs,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], str, str]:
    """Full preamble + submit_review + approve.

    Returns (insurer, policy, flight, ticket, approved_claim, reviewer_id,
    approver_id). The reviewer_id and approver_id are distinct so SoD passes
    (PRD §3.4).
    """
    insurer, policy, flight, ticket, reviewed, reviewer_id = setup_claim_under_review(**kwargs)
    approved, approver_id = approve_claim(insurer["id"], reviewed["id"])
    return insurer, policy, flight, ticket, approved, reviewer_id, approver_id


def setup_claim_in_executing(
    **kwargs,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], str, str, str, str,
]:
    """Full preamble through PayoutBatch.execute so claim is in EXECUTING.

    Returns (insurer, policy, flight, ticket, claim, batch, reviewer_id,
    approver_id, batch_approver_id, batch_executor_id) — all four operator
    ids distinct so every SoD check passes.
    """
    insurer, policy, flight, ticket, approved, rid, aid = setup_claim_approved(**kwargs)
    batch = create_batch(
        insurer["id"],
        flight_id=flight["id"],
        claim_ids=[approved["id"]],
    )
    _, ba_id = approve_batch(insurer["id"], batch["id"])
    _, bx_id = execute_batch(insurer["id"], batch["id"])
    claim_now = get_claim(insurer["id"], approved["id"])
    batch_now = api_client.get_payout_batch(
        insurer["id"], batch["id"], TEST_USERS["claims_admin_headers"]
    )
    batch_now = get_success_data(batch_now)
    return (
        insurer, policy, flight, ticket, claim_now, batch_now,
        rid, aid, ba_id, bx_id,
    )


def setup_claim_paid(
    **kwargs,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], str, str, str, str, str,
]:
    """Full preamble through claim.payout_status = PAID.

    Returns (insurer, policy, flight, ticket, claim_paid, batch, reviewer_id,
    approver_id, batch_approver_id, batch_executor_id, payout_operator_id).
    PayoutOperator id is distinct from the approver id so SoD passes (PRD §3.9).
    """
    (
        insurer, policy, flight, ticket, claim_exec, batch_exec,
        rid, aid, ba_id, bx_id,
    ) = setup_claim_in_executing(**kwargs)
    paid, po_id = settle_claim(insurer["id"], claim_exec["id"])
    # After settle, the batch may auto-transition to SETTLED.
    batch_now = get_success_data(api_client.get_payout_batch(
        insurer["id"], batch_exec["id"], TEST_USERS["claims_admin_headers"]
    ))
    return (
        insurer, policy, flight, ticket, paid, batch_now,
        rid, aid, ba_id, bx_id, po_id,
    )


# ---------------------------------------------------------------------------
# Difficulty-design specific composite fixtures (SCAFFOLD_DIFFICULTY_DESIGN.yaml)
# ---------------------------------------------------------------------------

def setup_dual_basis_pair(
    *,
    departure_delay_minutes: int = 200,
    arrival_delay_minutes: int = 90,
) -> Dict[str, Any]:
    """Difficulty rule 1 / instance 1 (delay_basis_departure_vs_arrival).

    Two policies (P_DEP, P_ARR) on the same passenger doc, one flight whose
    aircraft made up time in air. Returns a dict containing both claims so
    both delay variants can be observed on the same flight.
    """
    insurer = create_insurer()
    doc = unique_doc_id()
    policy_dep = create_policy(
        insurer["id"], policy_holder_doc_id=doc, delay_basis="DEPARTURE",
        payout_mode="FIXED", deductible_cents=2500, policy_limit_cents=150000,
        claim_quota_total_cents=1_000_000, waiting_period_ms=0,
    )
    policy_arr = create_policy(
        insurer["id"], policy_holder_doc_id=doc, delay_basis="ARRIVAL",
        payout_mode="FIXED", deductible_cents=2500, policy_limit_cents=150000,
        claim_quota_total_cents=1_000_000, waiting_period_ms=0,
    )
    # Flight with deliberate in-air make-up.
    flight = create_flight(
        insurer["id"],
        scheduled_departure_epoch_ms=10_000_000,
        scheduled_arrival_epoch_ms=15_000_000,
    )
    actual_dep = 10_000_000 + departure_delay_minutes * 60_000
    actual_arr = 15_000_000 + arrival_delay_minutes * 60_000
    advance_clock_to(insurer["id"], actual_arr + 1)
    flight = finalize_flight_landed(
        insurer["id"], flight["id"],
        actual_departure_epoch_ms=actual_dep,
        actual_arrival_epoch_ms=actual_arr,
        cause="AIRLINE",
    )
    # Auto-match needs unique ATTACHED tickets per policy. PRD §3.3 says
    # auto-match picks the unique ACTIVE policy whose policy_holder_doc_id ==
    # passenger_doc_id, but here two policies share the doc → policy_id must
    # be supplied to bind directly.
    t_dep = create_ticket(
        insurer["id"], flight_id=flight["id"], passenger_doc_id=doc,
        policy_id=policy_dep["id"],
    )
    t_arr = create_ticket(
        insurer["id"], flight_id=flight["id"], passenger_doc_id=doc,
        policy_id=policy_arr["id"],
    )
    c_dep = create_claim(
        insurer["id"], policy_dep["id"], ticket_ids=[t_dep["id"]],
    )
    c_arr = create_claim(
        insurer["id"], policy_arr["id"], ticket_ids=[t_arr["id"]],
    )
    return {
        "insurer": insurer,
        "policy_dep": policy_dep,
        "policy_arr": policy_arr,
        "flight": flight,
        "ticket_dep": t_dep,
        "ticket_arr": t_arr,
        "claim_dep": c_dep,
        "claim_arr": c_arr,
    }


def setup_pessimistic_vs_optimistic_pair() -> Dict[str, Any]:
    """Difficulty rule 1 / instance 2 (optimistic_vs_pessimistic_reserve_balance).

    One policy, two LANDED flights, two claims; first goes APPROVED, second
    stays UNDER_REVIEW so risk_view's pessimistic exceeds optimistic.
    """
    insurer, policy = setup_basic_insurer_with_policy(
        delay_basis="DEPARTURE", payout_mode="FIXED",
        deductible_cents=2500, policy_limit_cents=150000,
        claim_quota_total_cents=10_000_000,
    )
    f1 = setup_flight_with_delay(
        insurer["id"], departure_delay_minutes=200, cause="AIRLINE",
    )
    f2 = setup_flight_with_delay(
        insurer["id"], departure_delay_minutes=200, cause="AIRLINE",
        scheduled_departure_epoch_ms=20_000_000,
        scheduled_arrival_epoch_ms=25_000_000,
    )
    t1 = create_ticket(
        insurer["id"], flight_id=f1["id"],
        passenger_doc_id=policy["policy_holder_doc_id"],
        passenger_name=policy["policy_holder_name"],
    )
    t2 = create_ticket(
        insurer["id"], flight_id=f2["id"],
        passenger_doc_id=policy["policy_holder_doc_id"],
        passenger_name=policy["policy_holder_name"],
    )
    c1 = create_claim(insurer["id"], policy["id"], ticket_ids=[t1["id"]])
    c2 = create_claim(insurer["id"], policy["id"], ticket_ids=[t2["id"]])
    c1, _ = submit_review(insurer["id"], c1["id"])
    c2, _ = submit_review(insurer["id"], c2["id"])
    c1, _aid = approve_claim(insurer["id"], c1["id"])
    return {
        "insurer": insurer,
        "policy": policy,
        "claim_approved": c1,
        "claim_under_review": c2,
        "flight_1": f1,
        "flight_2": f2,
    }


def setup_three_segment_actual_loss_claim(
    *,
    losses: Optional[List[int]] = None,
    rate_bps: int = 5000,
    deductible_cents: int = 2500,
    policy_limit_cents: int = 150000,
    departure_delay_minutes: int = 200,
) -> Dict[str, Any]:
    """Difficulty rule 2 / instance 2 (multi_segment_rounding_order_pinned_per_then_sum).

    Three flights, three tickets, one claim with three ACTUAL_LOSS segments.
    """
    losses = losses or [4501, 4502, 4503]
    insurer, policy = setup_basic_insurer_with_policy(
        delay_basis="DEPARTURE", payout_mode="ACTUAL_LOSS",
        reimbursement_rate_bps=rate_bps,
        deductible_cents=deductible_cents,
        policy_limit_cents=policy_limit_cents,
        claim_quota_total_cents=10_000_000,
    )
    flights, tickets = [], []
    base_dep = 10_000_000
    base_arr = 15_000_000
    for i in range(3):
        f = setup_flight_with_delay(
            insurer["id"],
            departure_delay_minutes=departure_delay_minutes,
            cause="AIRLINE",
            scheduled_departure_epoch_ms=base_dep + i * 100_000_000,
            scheduled_arrival_epoch_ms=base_arr + i * 100_000_000,
        )
        flights.append(f)
        t = create_ticket(
            insurer["id"], flight_id=f["id"],
            passenger_doc_id=policy["policy_holder_doc_id"],
            passenger_name=policy["policy_holder_name"],
        )
        tickets.append(t)
    segments = [
        claim_segment_input(ticket_id=tickets[i]["id"], claimed_actual_loss_cents=losses[i])
        for i in range(3)
    ]
    claim = create_claim(
        insurer["id"], policy["id"],
        ticket_ids=[t["id"] for t in tickets],
        segments=segments,
    )
    return {
        "insurer": insurer,
        "policy": policy,
        "flights": flights,
        "tickets": tickets,
        "claim": claim,
    }


def setup_capped_three_segment_paid_claim(
    *,
    departure_delay_minutes: int = 360,
) -> Dict[str, Any]:
    """Difficulty rule 2 / instance 3 (reinsurance_waterfall_circular_pinned_order).

    Three flights with TIER_C delays, single claim, drives all the way to PAID
    so a ReinsuranceAllocation row is appended. Cap at policy_limit_cents
    forces final_payout_cents = 150000.
    """
    insurer, policy = setup_basic_insurer_with_policy(
        delay_basis="DEPARTURE", payout_mode="FIXED",
        deductible_cents=2500, policy_limit_cents=150000,
        claim_quota_total_cents=10_000_000,
    )
    flights, tickets = [], []
    base_dep = 10_000_000
    base_arr = 15_000_000
    for i in range(3):
        f = setup_flight_with_delay(
            insurer["id"],
            departure_delay_minutes=departure_delay_minutes,
            cause="AIRLINE",
            scheduled_departure_epoch_ms=base_dep + i * 100_000_000,
            scheduled_arrival_epoch_ms=base_arr + i * 100_000_000,
        )
        flights.append(f)
        t = create_ticket(
            insurer["id"], flight_id=f["id"],
            passenger_doc_id=policy["policy_holder_doc_id"],
            passenger_name=policy["policy_holder_name"],
        )
        tickets.append(t)
    claim = create_claim(
        insurer["id"], policy["id"],
        ticket_ids=[t["id"] for t in tickets],
    )
    claim, rid = submit_review(insurer["id"], claim["id"])
    claim, aid = approve_claim(insurer["id"], claim["id"])
    batch = create_batch(insurer["id"], flight_id=flights[0]["id"], claim_ids=[claim["id"]])
    _, ba_id = approve_batch(insurer["id"], batch["id"])
    _, bx_id = execute_batch(insurer["id"], batch["id"])
    paid, po_id = settle_claim(insurer["id"], claim["id"])
    return {
        "insurer": insurer,
        "policy": policy,
        "flights": flights,
        "tickets": tickets,
        "claim": paid,
        "batch_id": batch["id"],
        "operator_ids": {
            "reviewer": rid, "approver": aid,
            "batch_approver": ba_id, "batch_executor": bx_id,
            "payout_operator": po_id,
        },
    }


def setup_ticket_attached(
    *,
    pnr_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Difficulty rule 8 / instance 2 setup base — single ATTACHED ticket."""
    insurer, policy = setup_basic_insurer_with_policy()
    flight = create_flight(insurer["id"])
    ticket = create_ticket(
        insurer["id"], flight_id=flight["id"],
        passenger_doc_id=policy["policy_holder_doc_id"],
        passenger_name=policy["policy_holder_name"],
        pnr_code=pnr_code,
    )
    return {"insurer": insurer, "policy": policy, "flight": flight, "ticket": ticket}


def setup_claim_with_pending_flight() -> Dict[str, Any]:
    """Difficulty rule 4 / instance 2 (flight_cancellation_three_hop_eligibility_cascade).

    Build a claim still in MATCHED on a SCHEDULED flight (no quorum events
    yet). Used to drive the cascade by ingesting CANCELLED quorum events.
    """
    insurer, policy = setup_basic_insurer_with_policy(
        delay_basis="DEPARTURE", payout_mode="FIXED",
        deductible_cents=2500, policy_limit_cents=150000,
        claim_quota_total_cents=10_000_000,
        excluded_delay_causes=[],
    )
    flight = create_flight(
        insurer["id"],
        scheduled_departure_epoch_ms=10_000_000,
        scheduled_arrival_epoch_ms=15_000_000,
    )
    ticket = create_ticket(
        insurer["id"], flight_id=flight["id"],
        passenger_doc_id=policy["policy_holder_doc_id"],
        passenger_name=policy["policy_holder_name"],
    )
    claim = create_claim(insurer["id"], policy["id"], ticket_ids=[ticket["id"]])
    return {
        "insurer": insurer, "policy": policy,
        "flight": flight, "ticket": ticket, "claim": claim,
    }
