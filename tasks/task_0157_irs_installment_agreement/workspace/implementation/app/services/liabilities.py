"""Tax liability balance & status helpers."""
from __future__ import annotations

from typing import Iterable, List

from app.services.common import bump_version
from app.store import STORE


def recompute_balance(liab: dict) -> None:
    """current_balance_cents = original + interest + penalty - applied (floored at 0)."""
    bal = (
        liab["original_assessed_amount_cents"]
        + liab.get("accrued_interest_cents", 0)
        + liab.get("accrued_penalty_cents", 0)
        - liab.get("payments_applied_cents", 0)
    )
    liab["current_balance_cents"] = max(0, bal)


def set_status(liab: dict, new_status: str) -> None:
    if liab.get("status") != new_status:
        liab["status"] = new_status
        bump_version(liab)


def liabilities_for_taxpayer(taxpayer_id: str) -> List[dict]:
    return [l for l in STORE.tax_liabilities.values() if l["taxpayer_id"] == taxpayer_id]


def get_liabilities(ids: Iterable[str]) -> List[dict]:
    out = []
    for lid in ids:
        l = STORE.tax_liabilities.get(lid)
        if l is not None:
            out.append(l)
    return out


def sum_balances(ids: Iterable[str]) -> int:
    return sum(STORE.tax_liabilities[lid]["current_balance_cents"] for lid in ids if lid in STORE.tax_liabilities)
