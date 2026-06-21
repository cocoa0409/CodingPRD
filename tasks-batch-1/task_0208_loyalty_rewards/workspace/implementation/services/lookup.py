"""Resource existence + ownership lookups (PRD §2.6, §2.1 ownership)."""
from db import db
from errors import err, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER


def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found: %s" % rid)
    return rec


def get_program(pid):
    return get_or_404(db.programs, pid)


def get_member(mid):
    return get_or_404(db.members, mid)


def get_partner(pid):
    return get_or_404(db.partners, pid)


def get_reward(rid):
    return get_or_404(db.rewards, rid)


def get_promotion(pid):
    return get_or_404(db.promotions, pid)


def get_redemption(rid):
    return get_or_404(db.redemptions, rid)


def get_referral(rid):
    return get_or_404(db.referrals, rid)


def get_transfer(tid):
    return get_or_404(db.transfers, tid)


def get_blackout(bid):
    return get_or_404(db.blackouts, bid)


def get_lot(lid):
    return get_or_404(db.lots, lid)


def get_transaction(tid):
    return get_or_404(db.transactions, tid)


def get_redemption_line(lid):
    return get_or_404(db.redemption_lines, lid)


def get_purchase_event(pid):
    return get_or_404(db.purchase_events, pid)


# ---------------------------------------------------------------------------
# Ownership (PRD §2.1, §3.11 priority 3 — after role check, before existence
# of *body* resources; path-resource existence is established by the get_*
# helpers above which run first when resolving the path).
# ---------------------------------------------------------------------------
def assert_member_owner(role, user_id, member_id):
    """A Member may act only on their own member-owned resource."""
    if role == "Member" and user_id != member_id:
        raise err(ERR_NOT_RESOURCE_OWNER,
                  "Member does not own the target resource")


def assert_partner_owner(role, user_id, partner_account_id):
    """A PartnerOperator may act only on their own partner account's resource."""
    if role == "PartnerOperator" and user_id != partner_account_id:
        raise err(ERR_NOT_RESOURCE_OWNER,
                  "PartnerOperator does not own the target resource")
