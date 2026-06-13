"""PartyOrder posture recomputation and version bump (PRD §3.4, §3.9).

confirmed_member_count and posture are computed; the stored party only carries
posture_explicit for the sticky LOCKED/DISSOLVED states. When a member confirm
or cancel changes membership, we bump the party's version by 1.
"""
import db
from services import views


def recompute_after_member_change(party):
    """Recompute confirmed_member_count/posture (derived in views) and bump version.

    READY<->FORMING flips are automatic via derive_posture; this records the
    mutation (version += 1, updated_at refresh) the PRD pins on member
    confirm/cancel for party-linked reservations.
    """
    db.touch(party)
