"""Federal tax lien release & withdrawal cascades."""
from __future__ import annotations

from typing import Optional

from app.services.common import bump_version
from app.store import STORE
from app.timeutil import now_iso


def release_check(*, dominant_cause: Optional[str] = None) -> None:
    """Cascade: any FILED lien whose every covered liability is PAID or EXPIRED → RELEASED.

    `dominant_cause` is the reason hint for the caller's trigger:
      - 'PAID_IN_FULL' when every covering liability is PAID
      - 'CSED_EXPIRED' when at least one covering liability reached EXPIRED via statute
      - 'OIC_ACCEPTED' when the trigger was an OIC acceptance
    The actual reason is decided per-lien from its covering liabilities' statuses.
    """
    for lien in STORE.liens.values():
        if lien["status"] != "FILED":
            continue
        liab_ids = lien["liability_ids"]
        liabs = [STORE.tax_liabilities[lid] for lid in liab_ids if lid in STORE.tax_liabilities]
        if not liabs:
            continue
        if not all(l["status"] in ("PAID", "EXPIRED") for l in liabs):
            continue

        reason = _resolve_reason(liabs, dominant_cause)
        lien["status"] = "RELEASED"
        lien["released_at"] = now_iso()
        lien["release_reason"] = reason
        bump_version(lien)


def _resolve_reason(liabs, dominant_cause: Optional[str]) -> str:
    statuses = {l["status"] for l in liabs}
    if dominant_cause == "OIC_ACCEPTED":
        return "OIC_ACCEPTED"
    if "EXPIRED" in statuses:
        return "CSED_EXPIRED"
    return "PAID_IN_FULL"
