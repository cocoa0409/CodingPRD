"""Reimbursement claims: the two variants of reimbursement_claim_amount (PRD 3.9)."""

import calc
import cascades
from store import db, new_row, touch


def _inputs(case, variant, candidate=None):
    if candidate is None and case is not None:
        candidate = cascades.candidate_of(case)
    donor = cascades.donor_of_candidate(candidate) if candidate else None
    registry = cascades.registry_of_donor(donor) if donor else None
    attempts = candidate["ct_attempt_count"] if candidate else 0
    if variant == "PROVISIONAL":
        method = calc.PROVISIONAL_ASSUMED_METHOD
        window_days = calc.PROVISIONAL_ASSUMED_WINDOW_DAYS
        cancelled = False
    else:
        method = case["collection_method"] or calc.PROVISIONAL_ASSUMED_METHOD
        window_days = case["planned_window_days"]
        cancelled = False
        for booking in cascades.case_bookings(case["id"]):
            if booking["status"] == "CANCELLED" and \
                    booking["confirmed_at"] is not None:
                cancelled = True
    return registry, attempts, method, window_days, cancelled


def compute(case, variant, candidate=None):
    """Return the amount block plus the registry the claim bills."""
    registry, attempts, method, window_days, cancelled = _inputs(
        case, variant, candidate)
    is_domestic = bool(registry["is_domestic"]) if registry else True
    fx_rate = registry["fx_rate_to_usd"] if registry else 1
    amounts = calc.claim_amounts(variant, attempts, method, window_days,
                                is_domestic, fx_rate, cancelled)
    return registry, amounts


def provisional_total(candidate):
    """The total the budget rung compares against, before anything is written."""
    _registry, amounts = compute(None, "PROVISIONAL", candidate)
    return amounts["total_usd_cents"]


def create_provisional(case, patient, candidate=None):
    registry, amounts = compute(case, "PROVISIONAL", candidate)
    row = new_row(
        workup_case_id=case["id"],
        patient_id=patient["id"],
        billing_registry_id=registry["id"] if registry else None,
        status="PROVISIONAL",
        variant_applied="PROVISIONAL",
        currency_code=registry["currency_code"] if registry else None,
        fx_rate_snapshot=registry["fx_rate_to_usd"] if registry else None,
        finalized_at=None,
        void_reason=None,
        **amounts
    )
    db.claims[row["id"]] = row
    return row


def apply_final(claim, case):
    registry, amounts = compute(case, "FINAL")
    claim.update(amounts)
    claim["variant_applied"] = "FINAL"
    if registry is not None:
        claim["currency_code"] = registry["currency_code"]
        claim["fx_rate_snapshot"] = registry["fx_rate_to_usd"]
    claim["status"] = "FINALIZED"
    claim["finalized_at"] = db.now()
    touch(claim)
    return claim
