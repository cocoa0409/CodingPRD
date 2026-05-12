"""Tenant deposit ledger aggregation per §2.9."""
import db


def recompute_for_tenant(tenant_id: str) -> None:
    t = db.tenants.get(tenant_id)
    if t is None:
        return
    paid = 0
    refunded = 0
    retained = 0
    for d in db.deposits.values():
        lease = db.leases.get(d["lease_id"])
        if lease is None:
            continue
        if lease.get("tenant_id") != tenant_id:
            continue
        paid += int(d.get("collected_cents") or 0)
        refunded += int(d.get("refunded_cents") or 0)
        retained += int(d.get("retained_cents") or 0)
    t["total_deposit_paid_cents"] = paid
    t["total_deposit_refunded_cents"] = refunded
    t["total_deposit_retained_cents"] = retained


def recompute_all() -> None:
    for t in db.tenants.values():
        recompute_for_tenant(t["id"])
