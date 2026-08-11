"""calculations.menu_item_rating_rollup -- STORED, recomputed on every review
create, respond, hide and unhide (PRD 3.10)."""

from fractions import Fraction

import config
from db import DB
from tsutil import round_half_up


def recompute(menu_item):
    if menu_item is None:
        return
    visible = [r for r in DB.coll("reviews").values()
               if r.get("menu_item_id") == menu_item["id"]
               and r.get("counts_toward_rollup")]
    count = len(visible)
    menu_item["rating_count"] = count
    if count < config.RATING_ROLLUP_MIN_REVIEWS:
        menu_item["rating_avg"] = None
    else:
        total = sum(r.get("rating") or 0 for r in visible)
        menu_item["rating_avg"] = float(
            round_half_up(Fraction(total, count),
                          config.RATING_AVG_PRECISION_DECIMALS)
        )
