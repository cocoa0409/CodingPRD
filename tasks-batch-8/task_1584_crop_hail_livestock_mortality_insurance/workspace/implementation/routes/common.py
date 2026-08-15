"""Path-chain resolution helpers (PRD 2.6: left-to-right, first miss 404s)."""

from __future__ import annotations

import db
from errors import raise_err, ERR_NOT_FOUND
from util import get_or_404


def resolve_carrier(carrier_id: str) -> dict:
    return get_or_404(db.carriers, carrier_id, "Carrier")


def resolve_grower(carrier_id: str, grower_id: str) -> dict:
    grower = get_or_404(db.growers, grower_id, "Grower")
    if grower["carrier_id"] != carrier_id:
        raise_err(ERR_NOT_FOUND, f"Grower not found: {grower_id}")
    return grower


def resolve_adjuster(carrier_id: str, adjuster_id: str) -> dict:
    adjuster = get_or_404(db.adjusters, adjuster_id, "Adjuster")
    if adjuster["carrier_id"] != carrier_id:
        raise_err(ERR_NOT_FOUND, f"Adjuster not found: {adjuster_id}")
    return adjuster


def resolve_rate_table(carrier_id: str, rate_table_id: str) -> dict:
    row = get_or_404(db.rate_tables, rate_table_id, "RateTable")
    if row["carrier_id"] != carrier_id:
        raise_err(ERR_NOT_FOUND, f"RateTable not found: {rate_table_id}")
    return row


def resolve_federal(carrier_id: str, fci_id: str) -> dict:
    fed = get_or_404(db.federal_policies, fci_id, "FederalCropPolicy")
    if fed["carrier_id"] != carrier_id:
        raise_err(ERR_NOT_FOUND, f"FederalCropPolicy not found: {fci_id}")
    return fed


def resolve_policy(carrier_id: str, policy_id: str) -> dict:
    policy = get_or_404(db.policies, policy_id, "Policy")
    if policy["carrier_id"] != carrier_id:
        raise_err(ERR_NOT_FOUND, f"Policy not found: {policy_id}")
    return policy


def resolve_unit(policy_id: str, unit_id: str) -> dict:
    unit = get_or_404(db.coverage_units, unit_id, "CoverageUnit")
    if unit["policy_id"] != policy_id:
        raise_err(ERR_NOT_FOUND, f"CoverageUnit not found: {unit_id}")
    return unit


def resolve_claim(policy_id: str, claim_id: str) -> dict:
    claim = get_or_404(db.claims, claim_id, "Claim")
    if claim["policy_id"] != policy_id:
        raise_err(ERR_NOT_FOUND, f"Claim not found: {claim_id}")
    return claim


def resolve_payment(claim_id: str, payment_id: str) -> dict:
    payment = get_or_404(db.indemnity_payments, payment_id, "IndemnityPayment")
    if payment["claim_id"] != claim_id:
        raise_err(ERR_NOT_FOUND, f"IndemnityPayment not found: {payment_id}")
    return payment
