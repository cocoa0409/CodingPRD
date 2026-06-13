"""Policyholder ownership scoping (PRD §2.1).

When X-User-Role is Policyholder, X-User-ID is the acting Policyholder.id.
Ownership checks compare a resource's policyholder_id (directly, or through the
owning policy's policyholder_id) to X-User-ID, so a policyholder reads only
their own policies, claims, invoices, coverage lines, scheduled items,
additional insureds, and payments.

Underwriter and ClaimsAdjuster carry opaque ids and are not scoped.
"""
import db
from errors import err


def policy_owner(policy_id):
    pol = db.policies.get(policy_id)
    if pol is None:
        return None
    return pol.get("policyholder_id")


def _owner_for(kind, rec):
    """Resolve the owning policyholder_id for a record of a given kind."""
    if kind == "policyholder":
        return rec["id"]
    if kind == "bundle":
        return rec.get("policyholder_id")
    if kind == "policy":
        return rec.get("policyholder_id")
    if kind in ("coverage_line", "scheduled_item", "additional_insured",
                "premium_invoice", "claim"):
        return policy_owner(rec.get("policy_id"))
    if kind == "payment":
        inv = db.premium_invoices.get(rec.get("invoice_id"))
        if inv is None:
            return None
        return policy_owner(inv.get("policy_id"))
    if kind == "claim_item":
        claim = db.claims.get(rec.get("claim_id"))
        if claim is None:
            return None
        return policy_owner(claim.get("policy_id"))
    return None


def enforce_read(role, user_id, kind, rec):
    """For a Policyholder, ensure the record belongs to them, else ERR_NOT_FOUND.
    Per PRD §2.5 an out-of-scope single fetch surfaces as not-found."""
    if role != "Policyholder":
        return
    owner = _owner_for(kind, rec)
    if owner != user_id:
        raise err("ERR_NOT_FOUND", "Resource not found")


def scope_list(role, user_id, kind, records):
    """For a Policyholder, filter a list to only owned records."""
    if role != "Policyholder":
        return records
    return [r for r in records if _owner_for(kind, r) == user_id]
