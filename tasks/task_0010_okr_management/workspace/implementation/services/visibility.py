"""Confidentiality / visibility filter for objectives."""

import db


def is_visible(objective: dict, actor_id: str, actor_role: str) -> bool:
    if not objective.get("confidential"):
        return True
    if actor_role in ("PlatformAdmin", "HRBP"):
        return True
    if objective.get("owner_user_id") == actor_id:
        return True
    obj_id = objective["id"]
    for co in db.co_ownerships.values():
        if (co.get("objective_id") == obj_id
                and co.get("co_owner_user_id") == actor_id
                and co.get("status") == "ACTIVE"):
            return True
    for g in db.access_grants.values():
        if (g.get("objective_id") == obj_id
                and g.get("user_id") == actor_id
                and g.get("status") == "ACTIVE"):
            return True
    return False
