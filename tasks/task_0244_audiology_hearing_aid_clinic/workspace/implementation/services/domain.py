"""Cross-cutting domain helpers: entity lookup, ledger append, and the
allowance-pool recomputation cascade shared by purchase / return / replace.
"""

from db import db
import errors


# --- lookups -----------------------------------------------------------------
def get_or_404(collection, _id):
    obj = collection.get(_id)
    if obj is None:
        raise errors.not_found()
    return obj


# --- ledger ------------------------------------------------------------------
def append_ledger(patient_id, source_kind, source_ref_id, amount_cents, memo=None):
    """Append an immutable LedgerEntry. Carries only id + created_at (no
    updated_at / version, PRD §2.4)."""
    entry = {
        "patient_id": patient_id,
        "source_kind": source_kind,
        "source_ref_id": source_ref_id,
        "amount_cents": amount_cents,
        "memo": memo,
    }
    db.stamp_create(entry, with_version=False)
    db.ledger[entry["id"]] = entry
    return entry


# --- allowance pool recompute (cascade) --------------------------------------
def recompute_consumed_allowance(benefit):
    """Recompute consumed_allowance_cents as the sum of allowance_applied_cents
    across this patient's orders whose status is PURCHASED or WARRANTY_ACTIVE
    (PRD §3.1 / §3.4 / §3.5). Then bump the benefit (cascade hop) and flip its
    lifecycle status (a further hop, applied to the same entity write).

    Status flips:
      - consumed >= total  -> EXHAUSTED  (on purchase)
      - was EXHAUSTED and consumed < total -> ACTIVE (on return release)
    Returns the benefit.
    """
    total = 0
    for order in db.orders.values():
        if order.get("allowance_benefit_id") == benefit["id"] and order["status"] in ("PURCHASED", "WARRANTY_ACTIVE"):
            total += order.get("allowance_applied_cents") or 0
    benefit["consumed_allowance_cents"] = total

    # Lifecycle transitions driven by the recomputed consumption. EXPIRED is a
    # separate lifecycle concern (period_end) and is not toggled here.
    if benefit["status"] == "ACTIVE" and total >= benefit["total_allowance_cents"]:
        benefit["status"] = "EXHAUSTED"
    elif benefit["status"] == "EXHAUSTED" and total < benefit["total_allowance_cents"]:
        benefit["status"] = "ACTIVE"

    db.touch(benefit)
    return benefit
