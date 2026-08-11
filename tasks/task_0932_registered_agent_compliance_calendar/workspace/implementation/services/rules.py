"""Effective-dated jurisdiction rules (PRD 2.6)."""

from errors import ApiError
from store import DB


def candidates(state_code, determination_date):
    """effective_from is inclusive; effective_to is EXCLUSIVE, so a
    determination date equal to a row's effective_to falls to its successor."""
    found = []
    for rule in DB.state_rules.values():
        if rule["state_code"] != state_code:
            continue
        if rule["effective_from"] > determination_date:
            continue
        if rule["effective_to"] is not None and determination_date >= rule["effective_to"]:
            continue
        found.append(rule)
    return found


def select_or_none(state_code, determination_date):
    found = candidates(state_code, determination_date)
    if not found:
        return None
    # latest effective_from wins; the more recently created row breaks the tie
    found.sort(key=lambda r: (r["effective_from"], r["_seq"]), reverse=True)
    return found[0]


def select(state_code, determination_date):
    rule = select_or_none(state_code, determination_date)
    if rule is None:
        raise ApiError("ERR_NO_EFFECTIVE_STATE_RULE")
    return rule


def open_row(state_code):
    """The row currently open (effective_to null) for a jurisdiction."""
    rows = [
        r
        for r in DB.state_rules.values()
        if r["state_code"] == state_code and r["effective_to"] is None
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["effective_from"], r["_seq"]), reverse=True)
    return rows[0]
