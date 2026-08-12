"""Gates G1 (authentication) and G2 (role authorisation), plus the ownership
helpers used by gate G5. PRD 2.1 and 2.6."""

import functools

from flask import g, request

import constants as C
import store
from errors import ApiError, NOT_FOUND_BY_TYPE

# Rung 3 — GiftPurchaser is confined to Pipeline G.
PIPELINE_R_PREFIXES = ("/subscriptions", "/cycles", "/cycle-lines", "/children",
                       "/pause-records")


def authenticate():
    """Rungs 1 and 2, in that order."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is not None:
        role = role.strip()
    if user_id is not None:
        user_id = user_id.strip()
        if user_id == "":
            user_id = None

    # rung 1
    if not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role != "Anonymous" and not user_id:
        raise ApiError("ERR_UNAUTHENTICATED")
    # rung 2
    if role not in C.ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")

    g.role = role
    g.user_id = user_id


def _is_pipeline_r_path(path):
    for prefix in PIPELINE_R_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def authorize(roles, catalog_write=False):
    """Rungs 3, 4 and 5, in that order."""
    role = g.role
    # rung 3
    if role == "GiftPurchaser" and _is_pipeline_r_path(request.path):
        raise ApiError("ERR_GIFT_PURCHASER_SCOPE")
    # rung 4
    if catalog_write and role != "OpsAdmin":
        raise ApiError("ERR_CATALOG_WRITE_FORBIDDEN")
    # rung 5
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def api(bp, method, rule, roles, catalog_write=False):
    """Register a route, running gates G1 and G2 before the handler."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            authorize(roles, catalog_write)
            return fn(**kwargs)
        bp.add_url_rule(rule, endpoint=fn.__name__ + "__" + method.lower(),
                        view_func=wrapper, methods=[method])
        return fn
    return deco


# ---------------------------------------------------------------------------
# Gate G3 — existence, resolved left to right
# ---------------------------------------------------------------------------
def lookup(collection, row_id, type_name):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND_BY_TYPE[type_name])
    return row


def get_account(account_id):
    return lookup(store.db.accounts, account_id, "Account")


def get_child(child_id):
    return lookup(store.db.children, child_id, "Child")


def get_plan(plan_id):
    return lookup(store.db.plans, plan_id, "Plan")


def get_sku(sku_id):
    return lookup(store.db.skus, sku_id, "Sku")


def get_subscription(sub_id):
    return lookup(store.db.subscriptions, sub_id, "Subscription")


def get_cycle(cycle_id):
    return lookup(store.db.cycles, cycle_id, "Cycle")


def get_cycle_line(line_id):
    return lookup(store.db.cycle_lines, line_id, "CycleLine")


def get_registry(reg_id):
    return lookup(store.db.registries, reg_id, "Registry")


def get_registry_item(item_id):
    return lookup(store.db.registry_items, item_id, "RegistryItem")


def get_gift_order(gift_id):
    return lookup(store.db.gift_orders, gift_id, "GiftOrder")


def get_credit(credit_id):
    return lookup(store.db.credits, credit_id, "Credit")


def get_shipment(ship_id):
    return lookup(store.db.shipments, ship_id, "Shipment")


def get_loyalty(loyalty_id):
    return lookup(store.db.loyalty_accounts, loyalty_id, "LoyaltyAccount")


def get_referral(ref_id):
    return lookup(store.db.referrals, ref_id, "Referral")


def get_refund(refund_id):
    return lookup(store.db.refunds, refund_id, "Refund")


def get_pause(pause_id):
    return lookup(store.db.pause_records, pause_id, "PauseRecord")


# ---------------------------------------------------------------------------
# Gate G5 — ownership (rungs 12, 13, 14)
# ---------------------------------------------------------------------------
def account_of_subscription(sub):
    return sub["account_id"]


def account_of_cycle(cycle):
    sub = store.db.subscriptions.get(cycle["subscription_id"])
    return sub["account_id"] if sub else None


def account_of_line(line):
    cycle = store.db.cycles.get(line["cycle_id"])
    return account_of_cycle(cycle) if cycle else None


def require_account_owner(account_id):
    """Rung 12 — only bites when the acting role is AccountHolder."""
    if g.role == "AccountHolder" and g.user_id != account_id:
        raise ApiError("ERR_NOT_ACCOUNT_OWNER")


def require_registry_owner(owner_account_id):
    """Rung 13 — only bites when the acting role is RegistryOwner."""
    if g.role == "RegistryOwner" and g.user_id != owner_account_id:
        raise ApiError("ERR_NOT_REGISTRY_OWNER")


def require_gift_purchaser(purchaser_account_id):
    """Rung 14 — only bites when the acting role is GiftPurchaser."""
    if g.role == "GiftPurchaser" and g.user_id != purchaser_account_id:
        raise ApiError("ERR_NOT_GIFT_PURCHASER")
