"""Owner.voting_status recomputation.

Per PRD §3.5: an owner with at least one fee bill in OVERDUE on any of their
properties is INELIGIBLE_DELINQUENT. Otherwise (and if they own at least one
property) they're ELIGIBLE. Owners with no properties are INELIGIBLE_NO_PROPERTY.
"""
from __future__ import annotations

import db
from services.common import bump


def _properties_for(owner_id: str) -> list[dict]:
    return [p for p in db.properties.values() if p.get("owner_id") == owner_id]


def recompute_for_owner(owner_id: str) -> None:
    owner = db.owners.get(owner_id)
    if owner is None:
        return
    props = _properties_for(owner_id)

    if not props:
        new_status = "INELIGIBLE_NO_PROPERTY"
    else:
        property_ids = {p["id"] for p in props}
        any_overdue = any(
            b.get("status") == "OVERDUE" and b.get("property_id") in property_ids
            for b in db.fee_bills.values()
        )
        if any_overdue:
            new_status = "INELIGIBLE_DELINQUENT"
        else:
            new_status = "ELIGIBLE"

    if owner.get("voting_status") != new_status:
        owner["voting_status"] = new_status
        bump(owner)
