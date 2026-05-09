"""Property.occupancy_status recomputation.

PRD §3.1: precedence rule —
  - any RESIDING tenant -> TENANT_OCCUPIED
  - else any RESIDING family/owner -> OWNER_OCCUPIED
  - else VACANT
"""
from __future__ import annotations

import db
from services.common import bump


def recompute_for_property(property_id: str) -> None:
    prop = db.properties.get(property_id)
    if prop is None:
        return

    residing = [
        r for r in db.residents.values()
        if r.get("property_id") == property_id and r.get("lifecycle_status") == "RESIDING"
    ]

    if any(r.get("relation_kind") == "TENANT" for r in residing):
        new_status = "TENANT_OCCUPIED"
    elif residing:  # any FAMILY (PRD doesn't surface owner-as-resident, but FAMILY counts)
        new_status = "OWNER_OCCUPIED"
    else:
        new_status = "VACANT"

    if prop.get("occupancy_status") != new_status:
        prop["occupancy_status"] = new_status
        bump(prop)
