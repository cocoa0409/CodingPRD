"""Path-id resolution helpers — strictly left-to-right per PRD §2.5.

Each helper raises ERR_NOT_FOUND when an id fails to resolve, including
cross-tenant nesting (e.g., a household whose community_id does not match
the URL's community).
"""

from __future__ import annotations

from db import db
from errors import ERR_NOT_FOUND, raise_api_error


def get_community(community_id: str) -> dict:
    c = db.communities.get(community_id)
    if c is None:
        raise_api_error(ERR_NOT_FOUND, f"Community {community_id} not found.")
    return c


def get_household(community_id: str, household_id: str) -> dict:
    get_community(community_id)
    h = db.households.get(household_id)
    if h is None or h.get("community_id") != community_id:
        raise_api_error(ERR_NOT_FOUND, f"Household {household_id} not found.")
    return h


def get_resident(community_id: str, household_id: str, resident_id: str) -> dict:
    get_household(community_id, household_id)
    r = db.residents.get(resident_id)
    if r is None or r.get("household_id") != household_id:
        raise_api_error(ERR_NOT_FOUND, f"Resident {resident_id} not found.")
    return r


def get_resident_by_id(resident_id: str) -> dict | None:
    return db.residents.get(resident_id)


def get_disposal(community_id: str, household_id: str, disposal_id: str) -> dict:
    get_household(community_id, household_id)
    d = db.disposals.get(disposal_id)
    if d is None or d.get("household_id") != household_id:
        raise_api_error(ERR_NOT_FOUND, f"Disposal {disposal_id} not found.")
    return d


def get_point_rule(community_id: str, rule_id: str) -> dict:
    get_community(community_id)
    r = db.point_rules.get(rule_id)
    if r is None or r.get("community_id") != community_id:
        raise_api_error(ERR_NOT_FOUND, f"PointRule {rule_id} not found.")
    return r


def get_mall_item(community_id: str, item_id: str) -> dict:
    get_community(community_id)
    it = db.mall_items.get(item_id)
    if it is None or it.get("community_id") != community_id:
        raise_api_error(ERR_NOT_FOUND, f"MallItem {item_id} not found.")
    return it


def get_redemption_order(community_id: str, order_id: str) -> dict:
    get_community(community_id)
    o = db.redemption_orders.get(order_id)
    if o is None:
        raise_api_error(ERR_NOT_FOUND, f"RedemptionOrder {order_id} not found.")
    # Verify cross-tenant via household lookup
    hh = db.households.get(o.get("household_id", ""))
    if hh is None or hh.get("community_id") != community_id:
        raise_api_error(ERR_NOT_FOUND, f"RedemptionOrder {order_id} not found.")
    return o


def get_violation(community_id: str, violation_id: str) -> dict:
    get_community(community_id)
    v = db.violations.get(violation_id)
    if v is None or v.get("community_id") != community_id:
        raise_api_error(ERR_NOT_FOUND, f"Violation {violation_id} not found.")
    return v


def get_ranking_period(community_id: str, period_id: str) -> dict:
    get_community(community_id)
    p = db.ranking_periods.get(period_id)
    if p is None or p.get("community_id") != community_id:
        raise_api_error(ERR_NOT_FOUND, f"RankingPeriod {period_id} not found.")
    return p
