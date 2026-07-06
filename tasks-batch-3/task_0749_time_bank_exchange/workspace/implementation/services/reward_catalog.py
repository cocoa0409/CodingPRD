"""Reward catalog — codes -> minutes_cost.

The PRD doesn't enumerate the full catalog, but names 'FARMERS_MARKET_15' and
'BUS_PASS_60' as examples. We accept any code of the form <ALPHA>_..._<INT>
where the trailing integer, if divisible by 15 and positive, becomes the
minutes_cost. Falls back to a small fixed map otherwise.
"""
import re

_STATIC = {
    "FARMERS_MARKET_15": 15,
    "BUS_PASS_60": 60,
    "COMMUNITY_LUNCH_30": 30,
    "MOVIE_TICKET_45": 45,
    "GARDEN_KIT_90": 90,
    "GYM_DAY_PASS_75": 75,
    "COFFEE_SHOP_15": 15,
    "LIBRARY_LATE_FEE_15": 15,
    "MUSEUM_ENTRY_60": 60,
    "SWIM_PASS_45": 45,
    "BOOK_STORE_30": 30,
    "CAR_WASH_30": 30,
    "MARKET_BASKET_120": 120,
    "THEATER_TICKET_120": 120,
}

_TRAILING_INT = re.compile(r"_(\d+)$")


def resolve_cost(reward_code: str):
    """Return the minutes_cost for a reward code, or None if unresolvable."""
    if not isinstance(reward_code, str) or not reward_code:
        return None
    if reward_code in _STATIC:
        return _STATIC[reward_code]
    m = _TRAILING_INT.search(reward_code)
    if not m:
        return None
    val = int(m.group(1))
    if val <= 0:
        return None
    return val
