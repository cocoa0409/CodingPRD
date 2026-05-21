"""Taxpayer aggregate maintenance.

Implements §2.9 cascade semantics:
- total_assessed_debt_cents = sum of current_balance_cents across taxpayer's liabilities
- collection_status derived posture, per §3.1
"""
from __future__ import annotations

from app.services.common import bump_version
from app.services.liabilities import liabilities_for_taxpayer
from app.store import STORE


def _derive_collection_status(taxpayer_id: str) -> str:
    liabs = liabilities_for_taxpayer(taxpayer_id)

    if not liabs:
        return "ACTIVE"

    # 1. PAID_IN_FULL iff every liability is PAID
    if all(l["status"] == "PAID" for l in liabs):
        return "PAID_IN_FULL"

    statuses = {l["status"] for l in liabs}

    # 2. If any covered liability is currently bound to an UNDER_REVIEW or SUBMITTED OIC → IN_OIC_REVIEW
    submitted_oic_liabs = set()
    accepted_oic_liabs = set()
    for oic in STORE.offers.values():
        if oic["taxpayer_id"] != taxpayer_id:
            continue
        if oic["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            submitted_oic_liabs.update(oic["liability_ids"])
        elif oic["status"] == "ACCEPTED":
            accepted_oic_liabs.update(oic["liability_ids"])

    if any(l["id"] in submitted_oic_liabs for l in liabs):
        return "IN_OIC_REVIEW"

    if "IN_COMPROMISE" in statuses:
        return "IN_COMPROMISE"

    if "CNC" in statuses:
        return "CNC"

    if "IN_AGREEMENT" in statuses:
        return "IN_AGREEMENT"

    return "ACTIVE"


def refresh_taxpayer_aggregates(taxpayer_id: str) -> None:
    """Recompute total_assessed_debt_cents and collection_status, bumping version on change."""
    tp = STORE.taxpayers.get(taxpayer_id)
    if tp is None:
        return
    liabs = liabilities_for_taxpayer(taxpayer_id)
    new_total = sum(l["current_balance_cents"] for l in liabs)
    new_status = _derive_collection_status(taxpayer_id)

    if tp.get("total_assessed_debt_cents") != new_total or tp.get("collection_status") != new_status:
        tp["total_assessed_debt_cents"] = new_total
        tp["collection_status"] = new_status
        bump_version(tp)
