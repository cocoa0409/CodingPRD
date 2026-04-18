"""Find the governing lease for a tenant's workstation reservations."""
from db import db


def governing_lease(tenant_id: str):
    """Return the tenant's ACTIVE lease with the latest term_start_date (tie-break: greatest id)."""
    candidates = [l for l in db.leases.values()
                  if l["tenant_id"] == tenant_id and l["status"] == "ACTIVE"]
    if not candidates:
        return None
    candidates.sort(key=lambda l: (l["term_start_date"], l["id"]), reverse=True)
    return candidates[0]
