"""Shared cross-cutting domain helpers: lookups, ownership, jar/card mechanics,
money rounding. These are used by the route modules to keep behavior consistent.
"""
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import err
from middleware import require_role


# --------------------------------------------------------------------------
# Money helpers (PRD §2.7): integer cents, single round_half_up at a division.
# --------------------------------------------------------------------------
def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) -> int. The single rounding for
    interest proration and order notional."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


# --------------------------------------------------------------------------
# Existence lookups (PRD §2.5: ERR_NOT_FOUND, path validated left-to-right).
# --------------------------------------------------------------------------
def get_family(fid):
    rec = db.families.get(fid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Family not found")
    return rec


def get_child(cid):
    rec = db.child_accounts.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Child account not found")
    return rec


def get_jar(jid):
    rec = db.jars.get(jid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Jar not found")
    return rec


def get_chore(chid):
    rec = db.chores.get(chid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Chore not found")
    return rec


def get_completion(coid):
    rec = db.chore_completions.get(coid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Chore completion not found")
    return rec


def get_card(cardid):
    rec = db.debit_cards.get(cardid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Debit card not found")
    return rec


def get_control(ctlid):
    rec = db.card_controls.get(ctlid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Card control not found")
    return rec


def get_transaction(txid):
    rec = db.transactions.get(txid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Transaction not found")
    return rec


def get_schedule(sid):
    rec = db.allowance_schedules.get(sid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Allowance schedule not found")
    return rec


def get_config(cfgid):
    rec = db.interest_match_configs.get(cfgid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Interest match config not found")
    return rec


def get_investment(iid):
    rec = db.investment_accounts.get(iid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Investment account not found")
    return rec


# --------------------------------------------------------------------------
# Child <-> jar / card helpers
# --------------------------------------------------------------------------
def child_jars(child_id):
    return [j for j in db.jars.values() if j["child_account_id"] == child_id]


def jar_of_type(child_id, jar_type):
    for j in db.jars.values():
        if j["child_account_id"] == child_id and j["jar_type"] == jar_type:
            return j
    return None


def card_of_child(child_id):
    for c in db.debit_cards.values():
        if c["child_account_id"] == child_id:
            return c
    return None


def config_of_child(child_id):
    for c in db.interest_match_configs.values():
        if c["child_account_id"] == child_id:
            return c
    return None


def investment_of_child(child_id):
    for a in db.investment_accounts.values():
        if a["child_account_id"] == child_id:
            return a
    return None


# --------------------------------------------------------------------------
# Card recompute (PRD §3.5): held_cents, funding_state, available_cents.
# Each call refreshes the card's derived money fields and funding dimension.
# --------------------------------------------------------------------------
def recompute_card(card):
    """Recompute held_cents, funding_state, available_cents from the SPEND jar
    and PENDING holds. Does NOT bump version (callers bump explicitly for the
    operations that the spec says advance version)."""
    child_id = card["child_account_id"]
    spend = jar_of_type(child_id, "SPEND")
    spend_balance = spend["balance_cents"] if spend else 0
    held = sum(
        t["amount_cents"]
        for t in db.transactions.values()
        if t["debit_card_id"] == card["id"] and t["status"] == "PENDING"
    )
    card["held_cents"] = held
    card["funding_state"] = "FUNDED" if spend_balance > 0 else "DRAINED"
    available = spend_balance - held
    card["available_cents"] = available if available > 0 else 0


def credit_jar(jar, amount_cents):
    """Credit a jar; bump lifetime_credited_cents and the jar's own
    updated_at/version (cascade independence, PRD §2.5). If SPEND, recompute
    the card."""
    jar["balance_cents"] += amount_cents
    jar["lifetime_credited_cents"] += amount_cents
    db.touch(jar)
    if jar["jar_type"] == "SPEND":
        card = card_of_child(jar["child_account_id"])
        if card:
            recompute_card(card)
            db.touch(card)


def debit_jar(jar, amount_cents, recompute=True):
    """Debit a jar (used by settle, invest fund). Never goes negative is
    guaranteed by callers. Bumps the jar; recomputes card if SPEND."""
    jar["balance_cents"] -= amount_cents
    db.touch(jar)
    if recompute and jar["jar_type"] == "SPEND":
        card = card_of_child(jar["child_account_id"])
        if card:
            recompute_card(card)
            db.touch(card)


# --------------------------------------------------------------------------
# Ownership (PRD §2.1, §2.9 priority 3: ERR_NOT_RESOURCE_OWNER).
# Parent: owns the Family whose primary_parent_id == X-User-ID, and all
#         descendants. Child: X-User-ID == the ChildAccount.id; owns resources
#         whose child_account_id matches. PlatformAdmin: not ownership-scoped.
# --------------------------------------------------------------------------
def _family_owned_by_parent(family, identity):
    return family.get("primary_parent_id") == identity.user_id


def check_family_owner(identity, family):
    if identity.role == "PlatformAdmin":
        return
    if identity.role == "Parent":
        if not _family_owned_by_parent(family, identity):
            raise err("ERR_NOT_RESOURCE_OWNER", "Parent does not own this family")
        return
    # Child has no family-level ownership for parent-only resources; but for
    # shared family reads we still require the child to belong to this family.
    if identity.role == "Child":
        child = db.child_accounts.get(identity.user_id)
        if child is None or child.get("family_id") != family["id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Child does not belong to this family")
        return
    raise err("ERR_NOT_RESOURCE_OWNER", "Not the resource owner")


def check_family_owner_for_child(identity, child):
    """Ownership for Parent/PlatformAdmin-only endpoints scoped to a child
    (e.g. transaction alerts, schedule runs, accruals). A Parent must own the
    child's family; PlatformAdmin is unscoped."""
    if identity.role == "PlatformAdmin":
        return
    if identity.role == "Parent":
        family = db.families.get(child.get("family_id"))
        if family is None or not _family_owned_by_parent(family, identity):
            raise err("ERR_NOT_RESOURCE_OWNER", "Parent does not own this child")
        return
    raise err("ERR_NOT_RESOURCE_OWNER", "Not the resource owner")


def check_child_owner(identity, child):
    """Ownership of a resource scoped to a ChildAccount."""
    if identity.role == "PlatformAdmin":
        return
    if identity.role == "Parent":
        family = db.families.get(child.get("family_id"))
        if family is None or not _family_owned_by_parent(family, identity):
            raise err("ERR_NOT_RESOURCE_OWNER", "Parent does not own this child")
        return
    if identity.role == "Child":
        if child["id"] != identity.user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Child is not this child account")
        return
    raise err("ERR_NOT_RESOURCE_OWNER", "Not the resource owner")


# --------------------------------------------------------------------------
# Status gates (PRD §2.8 / §2.9): family suspension before child archival.
# --------------------------------------------------------------------------
def gate_money_movement(child):
    """Check family-suspended then child-archived, in that order."""
    family = db.families.get(child.get("family_id"))
    if family is not None and family.get("status") == "SUSPENDED":
        raise err("ERR_FAMILY_SUSPENDED", "Family is suspended")
    if child.get("status") == "ARCHIVED":
        raise err("ERR_CHILD_ARCHIVED", "Child account is archived")
