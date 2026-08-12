"""Append-only entitlement ledger (PRD §2.10)."""

import derive
import rows


def append(account_id, member_id, resource_type, entry_type, amount, reason_code,
           source_reference, cycle_id=None):
    """Append one movement, booked into the account's single OPEN cycle."""
    if cycle_id is None:
        cycle = derive.open_cycle(account_id)
        cycle_id = cycle["id"] if cycle else None
    return rows.new_row(
        "ledger",
        {
            "account_id": account_id,
            "member_id": member_id,
            "cycle_id": cycle_id,
            "resource_type": resource_type,
            "entry_type": entry_type,
            "amount": amount,
            "reason_code": reason_code,
            "source_reference": source_reference,
        },
        common=False,
    )


def grant_cycle(account, cycle, plan):
    """Three GRANT entries, one per resource type (PRD §3.1, §3.9)."""
    quotas = (
        ("PROFILE", plan["profile_quota_per_cycle"]),
        ("SCAN", plan["scan_quota_per_cycle"]),
        ("REMOVAL", plan["removal_quota_per_cycle"]),
    )
    for resource, amount in quotas:
        append(
            account_id=account["id"],
            member_id=None,
            resource_type=resource,
            entry_type="GRANT",
            amount=int(amount),
            reason_code="CYCLE_GRANT",
            source_reference=cycle["id"],
            cycle_id=cycle["id"],
        )
