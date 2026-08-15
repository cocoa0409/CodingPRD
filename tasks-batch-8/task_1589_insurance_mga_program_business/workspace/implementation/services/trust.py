"""Fiduciary trust accounting (PRD section 2.8) and the carrier remittance
waterfall (scaffold calculation trust_remittance).

trust_balance_cents is exactly the sum of amount_cents over the program's
TrustLedgerEntry rows. Entry signs are pinned: COLLECTION positive; REFUND,
CLAIM_PAYMENT and CARRIER_REMITTANCE negative.
"""
from decimal import Decimal

from db import STORE, new_ledger_entity
from services.pricing import round_cents

HOLDBACK_TIER_THRESHOLD_CENTS = 100000
HOLDBACK_PCT_HIGH = Decimal("0.10")
HOLDBACK_PCT_LOW = Decimal("0.02")


def post_entry(program, entry_type, amount_cents, policy=None, claim=None,
               basis_cents=None, memo=None):
    """Append an immutable ledger entry. Updates the program trust balance and,
    for policy-linked entries (COLLECTION/REFUND), the policy's collected_cents.
    Callers touch() mutated entities at the end of their own operation."""
    program["trust_balance_cents"] += amount_cents
    e = new_ledger_entity()
    e.update({
        "program_id": program["id"],
        "policy_id": policy["id"] if policy is not None else None,
        "claim_id": claim["id"] if claim is not None else None,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "basis_cents": basis_cents,
        "running_balance_cents": program["trust_balance_cents"],
        "memo": memo,
    })
    STORE.trust_ledger[e["id"]] = e
    if policy is not None:
        policy["collected_cents"] += amount_cents
    return e


def remittance_basis_cents(program_id):
    """sum(COLLECTION amounts) - sum(basis_cents of prior CARRIER_REMITTANCE)."""
    collections = 0
    prior_bases = 0
    for e in STORE.trust_ledger.values():
        if e["program_id"] != program_id:
            continue
        if e["entry_type"] == "COLLECTION":
            collections += e["amount_cents"]
        elif e["entry_type"] == "CARRIER_REMITTANCE":
            prior_bases += e["basis_cents"] or 0
    return collections - prior_bases


def compute_remittance(program):
    """Pinned evaluation order (breaks the circular dependency):

    basis     = unremitted collections
    commission = round_half_up(basis * commission_rate_pct)
    net_before_holdback = basis - commission
    holdback_pct keys on net_before_holdback: >= 100000 -> 0.10 else 0.02
    holdback  = round_half_up(net_before_holdback * holdback_pct)
    remittance = net_before_holdback - holdback

    Returns (basis_cents, remittance_cents).
    """
    basis = remittance_basis_cents(program["id"])
    commission = round_cents(Decimal(basis) * Decimal(str(program["commission_rate_pct"])))
    net = basis - commission
    pct = HOLDBACK_PCT_HIGH if net >= HOLDBACK_TIER_THRESHOLD_CENTS else HOLDBACK_PCT_LOW
    holdback = round_cents(Decimal(net) * pct)
    return basis, net - holdback
