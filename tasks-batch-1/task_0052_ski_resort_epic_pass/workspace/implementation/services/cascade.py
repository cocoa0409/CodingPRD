"""Pass-level cascades: cancel RESERVED buddy tickets and recompute remaining."""
from db import db

from services.common import touch
from services.serialize import compute_buddy_remaining


def cancel_reserved_buddy_tickets(pass_id):
    """Move every RESERVED buddy ticket of this pass to CANCELLED.

    Each cancelled ticket is itself a mutation (version + updated_at bump).
    """
    for b in db.buddy_tickets.values():
        if b["pass_id"] == pass_id and b["status"] == "RESERVED":
            b["status"] = "CANCELLED"
            touch(b)


def recompute_buddy_remaining(pass_rec):
    pass_rec["buddy_tickets_remaining"] = compute_buddy_remaining(pass_rec)
