"""Payment allocation waterfall (§3.5, calc payment_allocation).

Deterministic ordering:
  1. csed_effective_date ASC
  2. tax_year ASC
  3. liability.id ASC

For each target liability in order: applied = min(remaining, current_balance).
"""
from __future__ import annotations

from typing import Iterable, List, Tuple

from app.services.common import bump_version
from app.services.liabilities import recompute_balance, set_status
from app.store import STORE
from app.timeutil import parse_iso


def sort_targets(liab_ids: Iterable[str]) -> List[dict]:
    liabs = [STORE.tax_liabilities[lid] for lid in liab_ids if lid in STORE.tax_liabilities]
    liabs.sort(key=lambda l: (parse_iso(l["csed_effective_date"]), l["tax_year"], l["id"]))
    return liabs


def allocate(amount_cents: int, liab_ids: Iterable[str]) -> Tuple[List[dict], int]:
    """Apply `amount_cents` against the targets in pinned order.

    Returns:
      (allocation_rows, remaining_surplus)
    The caller decides whether the surplus is rejected (INSTALLMENT/OIC_INSTALLMENT)
    or accepted (LUMP_SUM).
    """
    targets = sort_targets(liab_ids)
    rows = []
    remaining = amount_cents
    for liab in targets:
        if remaining <= 0:
            rows.append({"liability_id": liab["id"], "applied_cents": 0})
            continue
        bal = liab["current_balance_cents"]
        applied = min(remaining, bal)
        if applied > 0:
            liab["payments_applied_cents"] = liab.get("payments_applied_cents", 0) + applied
            recompute_balance(liab)
            bump_version(liab)
        rows.append({"liability_id": liab["id"], "applied_cents": applied})
        remaining -= applied
    return rows, remaining


def settle_to_paid_if_zero(liab_ids: Iterable[str]) -> List[dict]:
    """For each target liability whose balance is 0, transition to PAID. Return changed list."""
    changed = []
    for lid in liab_ids:
        liab = STORE.tax_liabilities.get(lid)
        if liab is None:
            continue
        if liab["current_balance_cents"] == 0 and liab["status"] in ("OPEN", "IN_AGREEMENT", "IN_COMPROMISE"):
            set_status(liab, "PAID")
            changed.append(liab)
    return changed
