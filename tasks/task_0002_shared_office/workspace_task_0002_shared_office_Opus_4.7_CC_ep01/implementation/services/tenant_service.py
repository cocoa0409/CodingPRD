from datetime import timedelta

from db import db


def recompute_outstanding_balance(tenant: dict):
    total = 0
    for b in db.bills.values():
        if b["tenant_id"] == tenant["id"] and b["status"] in ("ISSUED", "OVERDUE"):
            total += b["total_due_cents"]
    tenant["outstanding_balance_cents"] = total


def compute_access_posture(tenant: dict) -> str:
    # Ladder per PRD §2.10
    if tenant["status"] == "CLOSED":
        return "FROZEN"

    # Any lease of this tenant in TERMINATION_REVIEWING?
    for lease in db.leases.values():
        if lease["tenant_id"] == tenant["id"] and lease["status"] == "TERMINATION_REVIEWING":
            return "RESTRICTED"

    if tenant["status"] == "TERMINATING":
        return "RESTRICTED"

    # Any OVERDUE bill with due_at passed by strictly more than 30 days?
    from util import parse_iso
    now = db.now()
    for b in db.bills.values():
        if b["tenant_id"] == tenant["id"] and b["status"] == "OVERDUE":
            due_at = parse_iso(b["due_at"]) if b.get("due_at") else None
            if due_at is not None:
                if (now - due_at) > timedelta(days=30):
                    return "FROZEN"

    if tenant["outstanding_balance_cents"] >= tenant["credit_limit_cents"]:
        return "RESTRICTED"

    return "OPEN"


def refresh_tenant(tenant: dict):
    recompute_outstanding_balance(tenant)
    tenant["access_posture"] = compute_access_posture(tenant)


def tenant_view(tenant: dict) -> dict:
    return {
        "id": tenant["id"],
        "created_at": tenant["created_at"],
        "updated_at": tenant["updated_at"],
        "version": tenant["version"],
        "legal_name": tenant["legal_name"],
        "credit_limit_cents": tenant["credit_limit_cents"],
        "status": tenant["status"],
        "access_posture": tenant["access_posture"],
        "outstanding_balance_cents": tenant["outstanding_balance_cents"],
    }
