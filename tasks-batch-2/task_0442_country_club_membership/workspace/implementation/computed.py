"""Derived/computed fields, recomputed from the underlying ledger (PRD §2.9).

These derive values rather than relying on blindly-adjusted stored counters, so
read responses always reflect the true ledger state. Side-effect code also calls
the recompute helpers to keep the stored copies consistent for cross-entity gates.
"""
import db


def category_active_member_count(category_id):
    """Count Memberships in this category whose account_status IN {ACTIVE, SUSPENDED}
    (PRD §3.1)."""
    return sum(
        1
        for m in db.memberships.values()
        if m["category_id"] == category_id
        and m["account_status"] in ("ACTIVE", "SUSPENDED")
    )


def membership_charge_balance(membership_id):
    """Outstanding charge balance (PRD §1.1): sum of unsettled (POSTED) Chit
    amounts minus payments applied; never below 0.

    POSTED chits are outstanding; SETTLED (paid) and VOIDED (reversed) are not.
    `payment_credit_cents` is the running leftover from payments that have been
    applied but have not yet fully settled the next chit (PRD §3.6: "the member's
    charge_balance_cents is reduced by the payment amount_cents").
    """
    total = 0
    for c in db.chits.values():
        if c["membership_id"] == membership_id and c["status"] == "POSTED":
            total += c["amount_cents"]
    m = db.memberships.get(membership_id)
    if m:
        total -= m.get("payment_credit_cents", 0)
    if total < 0:
        total = 0
    return total


def membership_fb_spend_period(membership_id):
    """Sum of DINING chit amounts (counts_toward_fb=true) posted in the club's
    current billing_period_index for this membership; VOIDED excluded (PRD §3.5)."""
    m = db.memberships.get(membership_id)
    if not m:
        return 0
    club = db.clubs.get(m["club_id"])
    if not club:
        return 0
    period = club["billing_period_index"]
    total = 0
    for c in db.chits.values():
        if (
            c["membership_id"] == membership_id
            and c.get("counts_toward_fb")
            and c["period_index"] == period
            and c["status"] in ("POSTED", "SETTLED")
        ):
            total += c["amount_cents"]
    return total


def membership_guest_visits_used(membership_id):
    """Count of GuestPass rows sponsored by this membership with status CHECKED_IN
    in the club's current billing_period_index (PRD §3.5)."""
    m = db.memberships.get(membership_id)
    if not m:
        return 0
    club = db.clubs.get(m["club_id"])
    if not club:
        return 0
    period = club["billing_period_index"]
    total = 0
    for gp in db.guest_passes.values():
        if (
            gp["sponsor_membership_id"] == membership_id
            and gp["status"] == "CHECKED_IN"
            and gp.get("checked_in_period_index") == period
        ):
            total += 1
    return total


def refresh_membership_computeds(membership_id):
    """Sync the stored copies of computed fields used by cross-entity gates."""
    m = db.memberships.get(membership_id)
    if not m:
        return
    m["charge_balance_cents"] = membership_charge_balance(membership_id)
    m["fb_spend_period_cents"] = membership_fb_spend_period(membership_id)
    m["guest_visits_used_period"] = membership_guest_visits_used(membership_id)


def refresh_category_count(category_id):
    cat = db.categories.get(category_id)
    if not cat:
        return
    cat["active_member_count"] = category_active_member_count(category_id)
