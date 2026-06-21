"""Cross-cutting business helpers reused across routes."""
import datetime

import db
import errors
import computed
from timeutil import parse_iso


# ---------------------------------------------------------------------------
# Chit posting (PRD §3.5). Posting debits charge_balance (via the recomputed
# derivation) and bumps Membership.version. Used by direct chit POST,
# activation initiation chit, and guest check-in guest-fee chit.
# ---------------------------------------------------------------------------
def post_chit(club_id, membership_id, amount_cents, kind, bump_membership=True):
    rec = db.base_record(common_fields=True)
    club = db.clubs[club_id]
    rec.update(
        {
            "club_id": club_id,
            "membership_id": membership_id,
            "amount_cents": amount_cents,
            "kind": kind,
            "counts_toward_fb": (kind == "DINING"),
            "period_index": club["billing_period_index"],
            "status": "POSTED",
        }
    )
    db.chits[rec["id"]] = rec
    # Recompute membership computed fields (charge_balance, fb_spend) (PRD §3.5)
    computed.refresh_membership_computeds(membership_id)
    if bump_membership:
        m = db.memberships.get(membership_id)
        if m:
            db.touch(m)
    return rec


# ---------------------------------------------------------------------------
# Activation side effects (PRD §3.2). Shared by activate endpoint and
# waitlist-accept cascade.
# ---------------------------------------------------------------------------
def apply_activation(membership):
    """Move a PENDING membership to ACTIVE with all activation side effects.
    Caller must have already enforced the capacity gate and state precondition."""
    club = db.clubs[membership["club_id"]]
    category = db.categories[membership["category_id"]]
    membership["account_status"] = "ACTIVE"
    membership["activated_period_index"] = club["billing_period_index"]
    # Initiation chit (EVENT, does not count toward F&B); debits charge_balance.
    post_chit(
        club_id=membership["club_id"],
        membership_id=membership["id"],
        amount_cents=category["initiation_fee_cents"],
        kind="EVENT",
        bump_membership=False,
    )
    computed.refresh_membership_computeds(membership["id"])
    db.touch(membership)
    # Recompute category active_member_count (+1) and bump category version.
    computed.refresh_category_count(category["id"])
    db.touch(category)


# ---------------------------------------------------------------------------
# Waitlist promotion cascade (PRD §3.2/§3.3/§3.7). Promote the earliest WAITING
# entry for a category to OFFERED when a seat frees / a slot opens.
# ---------------------------------------------------------------------------
def promote_earliest_waiting(category_id, club):
    waiting = [
        w
        for w in db.waitlist_entries.values()
        if w["category_id"] == category_id and w["status"] == "WAITING"
    ]
    if not waiting:
        return None
    waiting.sort(key=lambda w: w["_seq"])  # earliest by created_at
    entry = waiting[0]
    entry["status"] = "OFFERED"
    entry["offered_period_index"] = club["billing_period_index"]
    db.touch(entry)
    return entry


# ---------------------------------------------------------------------------
# Reservation overlap / turnaround / seat-capacity (PRD §3.4).
# ---------------------------------------------------------------------------
def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) intersects [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def check_resource_conflict(resource, start_dt, end_dt, party_size, exclude_reservation_id=None):
    """Raise ERR_RESOURCE_CONFLICT if the window collides with CONFIRMED
    reservations on this resource per the resource kind rules (PRD §3.4)."""
    kind = resource["kind"]
    confirmed = [
        r
        for r in db.reservations.values()
        if r["resource_id"] == resource["id"]
        and r["status"] == "CONFIRMED"
        and r["id"] != exclude_reservation_id
    ]
    if kind in ("TEE_TIME", "COURT"):
        # Exclusive occupancy; pad the requested window by turnaround on each side.
        buffer = datetime.timedelta(minutes=resource.get("turnaround_minutes", 0) or 0)
        padded_start = start_dt - buffer
        padded_end = end_dt + buffer
        for r in confirmed:
            r_start = parse_iso(r["starts_at"])
            r_end = parse_iso(r["ends_at"])
            if _overlaps(padded_start, padded_end, r_start, r_end):
                raise errors.resource_conflict()
    else:  # DINING_TABLE: overlapping seats must not exceed seat_capacity
        seat_capacity = resource.get("seat_capacity", 1)
        overlapping_seats = party_size
        for r in confirmed:
            r_start = parse_iso(r["starts_at"])
            r_end = parse_iso(r["ends_at"])
            if _overlaps(start_dt, end_dt, r_start, r_end):
                overlapping_seats += r.get("party_size", 1)
        if overlapping_seats > seat_capacity:
            raise errors.resource_conflict()


# ---------------------------------------------------------------------------
# Owner check helper (PRD §2.1, validation priority 4).
# ---------------------------------------------------------------------------
def assert_owner(role, user_id, owner_id):
    """For a Member, the resource's membership FK must equal X-User-ID."""
    if role == "Member" and user_id != owner_id:
        raise errors.not_resource_owner()
