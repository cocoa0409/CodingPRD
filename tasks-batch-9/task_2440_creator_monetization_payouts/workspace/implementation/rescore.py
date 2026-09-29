"""Money re-scoring cascade shared by content re-rating and upheld appeals."""
import calc
import ledger
from store import db, sort_rows


def rescore_content(item, statuses=("ACCRUED", "BELOW_MINIMUM"),
                    variant="RESCORE_ON_RERATING"):
    """Hops 2 and 3 of the demonetization cascade (PRD 3.4).

    Every ACCRUED / BELOW_MINIMUM event of this item on a suitability-sensitive
    product is re-scored in occurred_at ASC, created_at ASC order, and the
    signed delta is written to the ledger so balance_after_cents is a
    deterministic sequence.
    """
    rating = item["suitability_rating"]
    rows = []
    for event in db.rows("revenue_events"):
        if event["content_item_id"] != item["id"]:
            continue
        if event["status"] not in statuses:
            continue
        product = db.get("products", event["product_id"])
        if product is None or not product["suitability_sensitive"]:
            continue
        rows.append((event, product))
    rows.sort(key=lambda pair: (pair[0]["occurred_at"], pair[0]["created_at"],
                               pair[0]["_seq"]))
    for event, product in rows:
        creator = db.get("creators", event["creator_id"])
        previous = event["creator_share_cents"]
        effective, share, status = calc.revenue_share_split(
            event["gross_amount_cents"], product, creator, rating,
            variant)
        event["suitability_rating_at_accrual"] = rating
        event["effective_share_bps"] = effective
        event["creator_share_cents"] = share
        if event["status"] != status:
            event["status"] = status
            event["last_status_change_at"] = db.now
        db.touch(event)
        delta = share - previous
        if delta < 0:
            ledger.append(event["creator_id"], "ACCRUAL_REVERSAL", delta,
                          "REVENUE_EVENT", event["id"])
        elif delta > 0:
            ledger.append(event["creator_id"], "ACCRUAL_RESTORE", delta,
                          "REVENUE_EVENT", event["id"])
    return sort_rows([pair[0] for pair in rows], lambda r: (r["occurred_at"],))
