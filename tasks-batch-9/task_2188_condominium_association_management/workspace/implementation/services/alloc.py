"""Shared allocation participant ordering (PRD 3.2 step 2)."""
import db
import money


def participants(association_id):
    """Every Unit of the association -- no delinquency filter -- ordered by
    interest_bp DESC then created_at ASC."""
    units = [u for u in db.store["units"].values()
             if u["association_id"] == association_id]
    units.sort(key=lambda u: (-u["interest_bp"], u["created_at"], u["_seq"]))
    return units


def allocate(pool_cents, units):
    """Round half up per line, then distribute the drift one cent at a time by
    cycling through the participants in the pinned order.

    Returns (shares, base_shares, drift).
    """
    pairs = [(u["id"], u["interest_bp"]) for u in units]
    return money.cyclic_allocate(pool_cents, pairs)


def sa_round_pool(sa, round_index):
    """Pool for installment round `round_index` (0-based).

    Rounds 1..n-1 use round_half_up(total / installment_count); the FINAL round
    uses total minus the sum of the pools already posted so the installments sum
    to total_amount_cents exactly.
    """
    total = sa["total_amount_cents"]
    count = sa["installment_count"]
    per = money.round_half_up(total, count)
    if round_index >= count - 1:
        return total - per * (count - 1)
    return per


def sa_full_shares(sa):
    """This assessment's per-unit share of the FULL total_amount_cents, using the
    SA_INSTALLMENT allocation variant over the whole total (PRD 3.9 disclosure)."""
    units = participants(sa["association_id"])
    shares, _base, _drift = allocate(sa["total_amount_cents"], units)
    return {u["id"]: s for u, s in zip(units, shares)}
