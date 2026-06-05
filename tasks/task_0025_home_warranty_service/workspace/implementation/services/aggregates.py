"""Contract-aggregate recomputation (scaffold §1.3 contract_payout_aggregate, PRD §2.10).

Aggregates are filtered by:
  - contract_id == Contract.id
  - status in the in-period set
  - created_at in [coverage_start_utc, coverage_end_utc)

claims_in_period_count counts {SUBMITTED, ASSESSED, DISPATCHED, RESOLVED, REJECTED}.
total_paid_out_cents sums (repair_cost_cents - final_copay_cents) over RESOLVED only.

Recomputation bumps the contract's updated_at + version (PRD §2.4: 'Recomputation
of derived fields ... counts as a mutation').
"""
from __future__ import annotations

from typing import Dict, Any

import db


IN_PERIOD_STATUSES = {"SUBMITTED", "ASSESSED", "DISPATCHED", "RESOLVED", "REJECTED"}


def _in_window(claim_created_at: str, start_iso: str, end_iso: str) -> bool:
    """Check claim.created_at is in half-open [start_iso, end_iso).

    Note: a Contract that has not yet been ACTIVE has no coverage_start_utc
    set, in which case this should never be called (claim filing requires
    ACTIVE/EXPIRING_SOON which only exist after activation). Defensive.
    """
    s = db.parse_iso_dt(start_iso)
    e = db.parse_iso_dt(end_iso)
    c = db.parse_iso_dt(claim_created_at)
    if s is None or e is None or c is None:
        return False
    return s <= c < e


def recompute_contract_aggregates(contract: Dict[str, Any]) -> None:
    """Recompute claims_in_period_count and total_paid_out_cents on Contract.

    Bumps updated_at + version once after recomputation (PRD §2.4).
    """
    start = contract.get("coverage_start_utc")
    end = contract.get("coverage_end_utc")
    if not start or not end:
        # No coverage window yet — counts stay at zero/initial values.
        contract["claims_in_period_count"] = 0
        contract["total_paid_out_cents"] = 0
        db.bump(contract)
        return

    cid = contract["id"]
    count = 0
    total_paid = 0
    for ct in db.claim_tickets.values():
        if ct.get("contract_id") != cid:
            continue
        if ct.get("status") not in IN_PERIOD_STATUSES:
            continue
        if not _in_window(ct["created_at"], start, end):
            continue
        count += 1
        if ct.get("status") == "RESOLVED":
            total_paid += int(ct.get("repair_cost_cents", 0)) - int(ct.get("final_copay_cents", 0))

    contract["claims_in_period_count"] = count
    contract["total_paid_out_cents"] = total_paid
    db.bump(contract)
