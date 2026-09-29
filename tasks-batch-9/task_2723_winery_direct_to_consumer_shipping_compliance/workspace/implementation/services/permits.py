"""Permit observation, selection and the revocation cascade (PRD 3.2)."""
import clock
from store import db, touch, ordered

NON_REVOKED = ("PENDING", "ACTIVE", "RENEWAL_FILED", "EXPIRED")
_PREFERENCE = {"ACTIVE": 1, "EXPIRED": 2, "RENEWAL_FILED": 3, "PENDING": 4}


def permits_for(winery_id, state_code):
    rows = [p for p in db.state_permits.values()
            if p["winery_id"] == winery_id and p["state_code"] == state_code]
    return ordered(rows)


def observe_expiry(permit):
    """ACTIVE -> EXPIRED the moment the system looks at a lapsed permit."""
    if permit["status"] != "ACTIVE":
        return False
    expires = clock.parse_date(permit["expiration_date"])
    if expires is not None and clock.today() > expires:
        permit["status"] = "EXPIRED"
        touch(permit)
        return True
    return False


def observe_expiry_for(winery_id, state_code=None):
    changed = False
    for permit in db.state_permits.values():
        if permit["winery_id"] != winery_id:
            continue
        if state_code is not None and permit["state_code"] != state_code:
            continue
        if observe_expiry(permit):
            changed = True
    return changed


def covers_today(permit):
    start = clock.parse_date(permit["effective_date"])
    end = clock.parse_date(permit["expiration_date"])
    day = clock.today()
    if start is not None and day < start:
        return False
    if end is not None and day > end:
        return False
    return True


def select_permit(winery_id, state_code):
    """The permit screening judges, after expiry has been observed.

    An ACTIVE permit covering the clock date wins; then any ACTIVE permit; then
    EXPIRED (which fails the lapse rule); then RENEWAL_FILED and PENDING (which
    fail the in-force rule). created_at ASC breaks any remaining tie.
    """
    observe_expiry_for(winery_id, state_code)
    candidates = [p for p in permits_for(winery_id, state_code) if p["status"] in NON_REVOKED]
    if not candidates:
        return None

    def rank(p):
        base = _PREFERENCE.get(p["status"], 9)
        if p["status"] == "ACTIVE" and covers_today(p):
            base = 0
        return (base, p.get("created_at") or "", p.get("_seq") or 0)

    candidates.sort(key=rank)
    return candidates[0]


def overlaps(new_start, new_end, permit):
    """Closed intervals; sharing a single endpoint date already counts."""
    start = clock.parse_date(permit["effective_date"])
    end = clock.parse_date(permit["expiration_date"])
    if start is None or end is None:
        return False
    return new_start <= end and start <= new_end


def revoke_cascade(permit):
    """Three tiers, each firing because the previous one did (PRD 3.2)."""
    from services import derive
    winery = db.wineries.get(permit["winery_id"])
    suspended_orders = []
    for order in ordered(list(db.orders.values())):
        if order["winery_id"] != permit["winery_id"]:
            continue
        if order["ship_to_state_code"] != permit["state_code"]:
            continue
        if order["compliance_status"] != "CLEARED":
            continue
        if order["fulfillment_status"] != "UNFULFILLED":
            continue
        order["compliance_status"] = "SUSPENDED_PERMIT"
        order["rejection_error_id"] = "ERR_PERMIT_NOT_ACTIVE"
        touch(order)
        suspended_orders.append(order)

    touched_subscription = False
    for order in suspended_orders:
        sub_id = order.get("club_subscription_id")
        if not sub_id:
            continue
        sub = db.club_subscriptions.get(sub_id)
        if sub is None or sub["status"] != "ACTIVE":
            continue
        sub["status"] = "SUSPENDED_COMPLIANCE"
        sub["next_run_date"] = None
        touch(sub)
        touched_subscription = True

    if touched_subscription and winery is not None:
        # tier 3: suspended_subscription_count is recomputed and the row bumps
        derive.bump_winery(winery)
    return suspended_orders
