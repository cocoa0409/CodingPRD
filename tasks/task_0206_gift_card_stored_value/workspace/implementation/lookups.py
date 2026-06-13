"""Path-existence lookups (PRD §2.10): resolve a path id or raise
ERR_NOT_FOUND. Used after auth/role checks, before body validation."""

from db import db
from errors import err


def _get(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found.")
    return rec


def get_program(_id):
    return _get(db.programs, _id)


def get_state_rule(_id):
    return _get(db.state_rules, _id)


def get_campaign(_id):
    return _get(db.campaigns, _id)


def get_customer(_id):
    return _get(db.customers, _id)


def get_card(_id):
    return _get(db.cards, _id)


def get_ledger_entry(_id):
    return _get(db.ledger_entries, _id)


def get_hold(_id):
    return _get(db.holds, _id)


def get_redemption(_id):
    return _get(db.redemptions, _id)


def get_redemption_leg(_id):
    return _get(db.redemption_legs, _id)


def get_bulk_order(_id):
    return _get(db.bulk_orders, _id)


def get_replacement(_id):
    return _get(db.replacements, _id)


def get_refund(_id):
    return _get(db.refunds, _id)


def get_dormancy_waiver(_id):
    return _get(db.dormancy_waivers, _id)


def program_of_card(card):
    return db.programs[card["program_id"]]


def state_rule_for(program_id, state_code):
    """The StateRule matching (program_id, state_code), or None."""
    for r in db.state_rules.values():
        if r["program_id"] == program_id and r["state_code"] == state_code:
            return r
    return None
