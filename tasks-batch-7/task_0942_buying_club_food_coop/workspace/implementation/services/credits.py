"""Store credit: the expiry sweep, the soonest-expiry-first draw, and minting."""

from core import clock
from core.constants import VOLUNTEER_CREDIT_EXPIRY_DAYS
from core.store import DB, ordered, touch


def grants_of(member_id):
    return ordered([g for g in DB.credit_grants.values() if g["member_id"] == member_id])


def sweep(member_id):
    """Every grant whose expires_at the clock has reached or passed moves to
    EXPIRED.  remaining_cents is left untouched as a record of the forfeit."""
    now = clock.now()
    for grant in grants_of(member_id):
        if grant["status"] not in ("ACTIVE", "PARTIALLY_CONSUMED"):
            continue
        expires = clock.parse(grant["expires_at"])
        if expires is not None and now >= expires:
            grant["status"] = "EXPIRED"
            touch(grant)


def eligible_grants(member_id):
    """ACTIVE / PARTIALLY_CONSUMED grants the clock has not yet reached,
    ordered by expires_at ASC then created_at ASC."""
    now = clock.now()
    rows = []
    for grant in grants_of(member_id):
        if grant["status"] not in ("ACTIVE", "PARTIALLY_CONSUMED"):
            continue
        expires = clock.parse(grant["expires_at"])
        if expires is None or now >= expires:
            continue
        rows.append(grant)
    return sorted(rows, key=lambda g: (clock.parse(g["expires_at"]),
                                       g["created_at"], g["_seq"]))


def available(member_id):
    return sum(g["remaining_cents"] for g in eligible_grants(member_id))


def draw(member_id, want):
    """credit_consumption_fifo.  Returns the total actually taken."""
    if want <= 0:
        return 0
    taken = 0
    for grant in eligible_grants(member_id):
        if taken >= want:
            break
        take = min(grant["remaining_cents"], want - taken)
        if take <= 0:
            continue
        grant["remaining_cents"] -= take
        grant["status"] = "CONSUMED" if grant["remaining_cents"] == 0 else "PARTIALLY_CONSUMED"
        touch(grant)
        taken += take
    return taken


def mint(member_id, amount_cents, expires_at_iso, source, source_member_order_id=None):
    return DB.insert("CreditGrant", {
        "member_id": member_id,
        "source_member_order_id": source_member_order_id,
        "source": source,
        "amount_cents": amount_cents,
        "remaining_cents": amount_cents,
        "expires_at": expires_at_iso,
        "status": "ACTIVE",
    })


def default_expiry_iso():
    """180 days after the current clock reading, rendered by the one renderer."""
    return clock.render(clock.CLOCK.plus_days(VOLUNTEER_CREDIT_EXPIRY_DAYS))
