"""Transport ledger reconciliation, patient responsibility, and the automatic
billing-dimension advancement cascade (PRD §3.7–§3.10, SCAFFOLD §1.2/§1.3).

Pinned reconciliation order (PRD §3.9):
    1. total_billed_cents   = sum(Charge.billed_amount_cents)
    2. total_allowed_cents  = sum(posted RemittanceLine reported/derived allowed)
    3. total_paid_cents     = sum(Payment.amount_cents)  (PAYER + PATIENT)
    4. total_writeoff_cents = sum(Adjustment.amount_cents)
                              + sum(RemittanceLine.contractual_adjustment_cents)
    5. patient_responsibility_cents = patient_responsibility calc
    6. balance_cents = max(total_billed - total_paid - total_writeoff, 0)
"""

from db import store
from services.common import touch


def charges_for(transport_id):
    return [c for c in store.charges.values() if c["transport_id"] == transport_id]


def claims_for(transport_id):
    return [c for c in store.claims.values() if c["transport_id"] == transport_id]


def payments_for(transport_id):
    return [p for p in store.payments.values() if p["transport_id"] == transport_id]


def adjustments_for(transport_id):
    return [a for a in store.adjustments.values() if a["transport_id"] == transport_id]


def remittance_lines_for_transport(transport_id):
    claim_ids = {c["id"] for c in claims_for(transport_id)}
    return [r for r in store.remittance_lines.values() if r["claim_id"] in claim_ids]


def primary_claim(transport_id):
    """The current (non-superseded) sequence_rank==1 claim, if any.

    A superseded prior primary is CLOSED; we want the live rank-1 claim. Among
    rank-1 claims, prefer one that is not CLOSED; otherwise the latest.
    """
    rank1 = [c for c in claims_for(transport_id) if c["sequence_rank"] == 1]
    if not rank1:
        return None
    live = [c for c in rank1 if c["status"] != "CLOSED"]
    if live:
        return sorted(live, key=lambda c: c.get("_seq", 0))[-1]
    return sorted(rank1, key=lambda c: c.get("_seq", 0))[-1]


def compute_patient_responsibility(transport):
    """patient_responsibility = max(total_billed - payer_paid - patient_paid - writeoffs, 0)."""
    tid = transport["id"]
    payer_paid = sum(p["amount_cents"] for p in payments_for(tid) if p["source"] == "PAYER")
    patient_paid = sum(p["amount_cents"] for p in payments_for(tid) if p["source"] == "PATIENT")
    adj_writeoffs = sum(a["amount_cents"] for a in adjustments_for(tid))
    contractual = sum(
        r.get("contractual_adjustment_cents", 0) or 0
        for r in remittance_lines_for_transport(tid)
    )
    writeoffs = adj_writeoffs + contractual
    return max(transport["total_billed_cents"] - payer_paid - patient_paid - writeoffs, 0)


def reconcile_transport_ledger(transport):
    """Recompute the family of derived totals in the pinned order.

    Bumps the transport's updated_at + version (a financial posting touched it).
    """
    tid = transport["id"]

    # (1) total_billed
    total_billed = sum(c["billed_amount_cents"] for c in charges_for(tid))
    transport["total_billed_cents"] = total_billed

    # (2) total_allowed = sum of posted remittance-line reported/derived allowed
    total_allowed = sum(
        (r.get("_allowed_applied_cents", 0) or 0)
        for r in remittance_lines_for_transport(tid)
    )
    transport["total_allowed_cents"] = total_allowed

    # (3) total_paid (PAYER + PATIENT)
    total_paid = sum(p["amount_cents"] for p in payments_for(tid))
    transport["total_paid_cents"] = total_paid

    # (4) total_writeoff = adjustments + contractual adjustments
    adj_writeoffs = sum(a["amount_cents"] for a in adjustments_for(tid))
    contractual = sum(
        (r.get("contractual_adjustment_cents", 0) or 0)
        for r in remittance_lines_for_transport(tid)
    )
    transport["total_writeoff_cents"] = adj_writeoffs + contractual

    # (5) patient_responsibility
    transport["patient_responsibility_cents"] = compute_patient_responsibility(transport)

    # (6) balance = max(billed - paid - writeoff, 0)
    transport["balance_cents"] = max(
        total_billed - total_paid - transport["total_writeoff_cents"], 0
    )

    touch(transport)


def patient_coverages(transport):
    patient = store.patients.get(transport["patient_id"])
    if not patient:
        return []
    return patient.get("coverages") or []


def sequence_exhausted(transport_id):
    """The payer sequence is exhausted (PRD §3.8) when:
      (1) no claim remains in {DRAFT, SUBMITTED, APPEALED}, AND
      (2) there is no further payer to bill — i.e. no patient coverage entry at
          policy_rank == (latest settled claim's sequence_rank + 1).
    """
    claims = claims_for(transport_id)
    for c in claims:
        if c["status"] in ("DRAFT", "SUBMITTED", "APPEALED"):
            return False

    settled = [c for c in claims if c["status"] in ("PAID", "DENIED")]
    if not settled:
        # No active and no settled claims: nothing in flight, treat as exhausted.
        return True

    latest_rank = max(c["sequence_rank"] for c in settled)
    transport = store.transports.get(transport_id)
    coverages = patient_coverages(transport) if transport else []
    next_rank = latest_rank + 1
    has_next_payer = any(cov.get("policy_rank") == next_rank for cov in coverages)
    # If a further payer exists in the coverage list, the sequence is NOT yet
    # exhausted — the biller is expected to submit the downstream claim.
    return not has_next_payer


def close_settled_claims(transport):
    """When the sequence is exhausted and the transport leaves BILLING_IN_PROGRESS:
       - a settled PAID claim -> CLOSED
       - a settled DENIED claim with no further coverage at policy_rank
         (sequence_rank + 1) -> CLOSED
    """
    coverages = patient_coverages(transport)
    ranks_present = {cov.get("policy_rank") for cov in coverages}
    for c in claims_for(transport["id"]):
        if c["status"] == "PAID":
            c["status"] = "CLOSED"
            touch(c)
        elif c["status"] == "DENIED":
            if (c["sequence_rank"] + 1) not in ranks_present:
                c["status"] = "CLOSED"
                touch(c)


def advance_billing_dimension(transport):
    """Drive the automatic billing-dimension transitions after a posting.

    BILLING_IN_PROGRESS -> BILLED   when the payer sequence is exhausted
    BILLED              -> CLOSED   when patient_responsibility == 0
    BILLED              -> PATIENT_BALANCE when patient_responsibility > 0
    PATIENT_BALANCE     -> CLOSED   when patient_responsibility reaches 0
    """
    status = transport["billing_status"]

    if status == "BILLING_IN_PROGRESS":
        if sequence_exhausted(transport["id"]):
            # leave BILLING_IN_PROGRESS -> BILLED; settle claims first.
            close_settled_claims(transport)
            transport["billing_status"] = "BILLED"
            touch(transport)
            status = "BILLED"

    if status == "BILLED":
        if transport["patient_responsibility_cents"] == 0:
            transport["billing_status"] = "CLOSED"
            touch(transport)
        else:
            transport["billing_status"] = "PATIENT_BALANCE"
            touch(transport)
        status = transport["billing_status"]

    if status == "PATIENT_BALANCE":
        if transport["patient_responsibility_cents"] == 0:
            transport["billing_status"] = "CLOSED"
            touch(transport)
