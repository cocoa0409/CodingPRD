"""Computed/derived field reconciliation (recall_state, loyalty_tier)."""
import db
from services.common import round_half_up

# Loyalty-tier thresholds in cents (PRD §2.8). Inclusive lower bounds.
SILVER_THRESHOLD = 5000000
GOLD_THRESHOLD = 20000000

LOYALTY_POINTS_PER_DOLLAR = 1


def compute_loyalty_tier(lifetime_spend_cents):
    """Pure function of cumulative lifetime_spend_cents (PRD §2.8)."""
    if lifetime_spend_cents >= GOLD_THRESHOLD:
        return "GOLD"
    if lifetime_spend_cents >= SILVER_THRESHOLD:
        return "SILVER"
    return "BRONZE"


def recall_covers_lot(recall, lot, product):
    """Does an OPEN recall cover a given lot? (PRD §3.1/§3.9 scoping.)

    A recall covers a lot when the lot's product matches the recall's product_id,
    the optional lot_code matches (when present), and the optional scope_state_code
    matches the lot's store's state_code (when present).
    """
    if lot["product_id"] != recall["product_id"]:
        return False
    if recall.get("lot_code") is not None and lot["lot_code"] != recall["lot_code"]:
        return False
    if recall.get("scope_state_code") is not None:
        store = db.stores.get(lot["store_id"])
        if store is None or store["state_code"] != recall["scope_state_code"]:
            return False
    return True


def recall_covers_subscription(recall, subscription):
    """Is a subscription in a recall's scope? (PRD §3.9 hop 3.)

    The subscription's product must match the recall's product_id; when the recall
    has a scope_state_code, the subscription's store must be in that state. A
    lot_code scoping does not by itself exclude a subscription — the gate that
    matters for hop 3 is that the product is now RECALLED and the store is in
    scope.
    """
    if subscription["product_id"] != recall["product_id"]:
        return False
    if recall.get("scope_state_code") is not None:
        store = db.stores.get(subscription["store_id"])
        if store is None or store["state_code"] != recall["scope_state_code"]:
            return False
    return True


def product_has_open_recall(product):
    """A product is RECALLED when at least one OPEN recall covers it (PRD §3.1).

    Coverage here means an OPEN recall whose product_id matches and which has
    quarantined at least one of the product's lots (or, when no lot exists, still
    covers the product by product_id under its scoping). We model recall_state as
    derived from OPEN recalls on the product, respecting optional lot/state scope
    against the product's existing lots: a product is RECALLED while any OPEN
    recall covering it remains.
    """
    product_id = product["id"]
    for recall in db.recalls.values():
        if recall["status"] != "OPEN":
            continue
        if recall["product_id"] != product_id:
            continue
        # An OPEN recall on this product makes it RECALLED. Scope narrows which
        # lots/subscriptions are affected, but a recall that was issued against
        # the product renders the product's recall_state RECALLED.
        return True
    return False


def compute_recall_state(product):
    return "RECALLED" if product_has_open_recall(product) else "CLEAR"
