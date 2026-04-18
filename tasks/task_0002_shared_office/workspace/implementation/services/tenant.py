"""Tenant access posture and outstanding balance recomputation."""
from datetime import timedelta

from clock import get_now, parse_iso
from db import db


def recompute_outstanding_balance(tenant_id: str):
    tenant = db.tenants.get(tenant_id)
    if not tenant:
        return
    total = 0
    for b in db.bills.values():
        if b["tenant_id"] == tenant_id and b["status"] in ("ISSUED", "OVERDUE"):
            total += b.get("total_due_cents", 0)
    tenant["outstanding_balance_cents"] = total


def recompute_access_posture(tenant_id: str):
    tenant = db.tenants.get(tenant_id)
    if not tenant:
        return
    now = get_now()

    # Order matters:
    if tenant.get("status") == "CLOSED":
        tenant["access_posture"] = "FROZEN"
        return

    # Any lease of this tenant in TERMINATION_REVIEWING?
    for lease in db.leases.values():
        if lease["tenant_id"] == tenant_id and lease["status"] == "TERMINATION_REVIEWING":
            tenant["access_posture"] = "RESTRICTED"
            return

    if tenant.get("status") == "TERMINATING":
        tenant["access_posture"] = "RESTRICTED"
        return

    # Any bill OVERDUE for > 30 days
    thirty_days = timedelta(days=30)
    for b in db.bills.values():
        if b["tenant_id"] == tenant_id and b["status"] == "OVERDUE":
            due_at = b.get("due_at")
            if due_at:
                due_dt = parse_iso(due_at)
                if (now - due_dt) > thirty_days:
                    tenant["access_posture"] = "FROZEN"
                    return

    if tenant.get("outstanding_balance_cents", 0) >= tenant.get("credit_limit_cents", 0):
        tenant["access_posture"] = "RESTRICTED"
        return

    tenant["access_posture"] = "OPEN"


def recompute_tenant(tenant_id: str):
    recompute_outstanding_balance(tenant_id)
    recompute_access_posture(tenant_id)
