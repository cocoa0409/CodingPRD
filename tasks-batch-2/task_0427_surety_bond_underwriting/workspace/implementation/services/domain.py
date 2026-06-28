"""Cross-entity domain operations: mutation bookkeeping, exposure accounting,
loss accumulation, and cascades (PRD §2.4, §2.6, §2.7).

Every server change to a resource refreshes its updated_at and increments its
version (PRD §2.4) — including derived-field recomputations cascading from
another entity's change. touch() is the single chokepoint that guarantees this.
"""

from db import db, now_ts


def touch(record):
    """Refresh updated_at and bump version on any mutation (PRD §2.4)."""
    record["updated_at"] = now_ts()
    record["version"] += 1


def bond_net_retained(bond):
    """net_retained_cents = penal_sum_cents - ceded_penal_sum_cents (PRD §2.6)."""
    return bond["penal_sum_cents"] - bond["ceded_penal_sum_cents"]


def recompute_bond_ceded(bond):
    """ceded_penal_sum_cents = sum of ceded amounts over the bond's ACTIVE
    cessions (PRD §2.6)."""
    total = 0
    for c in db.cessions.values():
        if c["bond_id"] == bond["id"] and c["status"] == "ACTIVE":
            total += c["ceded_penal_sum_cents"]
    bond["ceded_penal_sum_cents"] = total
    return total


def recompute_bond_incurred_loss(bond):
    """incurred_loss_cents over the bond's claims (PRD §2.7):
      FILED/INVESTIGATING -> reserve_cents
      PAID                -> max(0, paid_loss_cents - salvage_cents)
      DENIED              -> 0
    """
    total = 0
    for c in db.claims.values():
        if c["bond_id"] != bond["id"]:
            continue
        st = c["status"]
        if st in ("FILED", "INVESTIGATING"):
            total += c["reserve_cents"]
        elif st == "PAID":
            net = (c["paid_loss_cents"] or 0) - (c["salvage_cents"] or 0)
            if net < 0:
                net = 0
            total += net
        # DENIED contributes nothing
    bond["incurred_loss_cents"] = total
    return total


def program_committed_sum(program_id):
    """aggregate_committed_cents = sum of net_retained_cents over bonds whose
    program_id matches and whose status is ISSUED or ACTIVE (PRD §2.6)."""
    total = 0
    for b in db.bonds.values():
        if b["program_id"] == program_id and b["status"] in ("ISSUED", "ACTIVE"):
            total += bond_net_retained(b)
    return total


def program_available(program):
    return program["aggregate_limit_cents"] - program["aggregate_committed_cents"]


def program_cumulative_loss(program_id):
    """Sum of incurred_loss_cents over all the program's bonds (PRD §2.7)."""
    total = 0
    for b in db.bonds.values():
        if b["program_id"] == program_id:
            total += b["incurred_loss_cents"]
    return total
