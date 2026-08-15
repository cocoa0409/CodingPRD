"""pool_settlement_pricing: pinned evaluation order (rounding order is contractual).

1. net_pool_value = round2(realized_revenue - operating_costs)
2. final_rate_per_weighted_barrel = round4(net_pool_value / weighted_barrels_total)
   (zero weighted barrels -> final_rate 0, no distributions)
3. per member with weighted_barrels > 0 in this pool, member.created_at ASC:
     gross_amount  = round2(member_weighted * final_rate)
     retain_amount = round2(gross_amount * pool.retain_pct)
     advance_paid  = sum of advance_amount over the member's ACCEPTED,
                     non-VOIDED deliveries tagged to this pool
     cash_amount   = gross_amount - retain_amount - advance_paid
4. coop_equity_residual = net_pool_value - sum(gross_amount)  (may be negative)
"""
from decimal import Decimal

from db import store, touch, new_common
from services import coupling
from validation import round2, round4, to_decimal

ZERO = Decimal("0")


def _pool_weighted_for(delivery, pool_id):
    if delivery.get("main_pool_id") == pool_id:
        return to_decimal(delivery.get("_main_weighted", ZERO))
    if delivery.get("over_quota_pool_id") == pool_id:
        return to_decimal(delivery.get("_over_weighted", ZERO))
    return ZERO


def settle_pool(pool, realized_revenue, operating_costs):
    revenue = to_decimal(realized_revenue)
    costs = to_decimal(operating_costs)
    net_pool_value = round2(revenue - costs)
    weighted_total = to_decimal(pool["weighted_barrels_total"])

    distributions = []
    if weighted_total == ZERO:
        final_rate = Decimal("0")
    else:
        final_rate = round4(net_pool_value / weighted_total)

        # Group this pool's ACCEPTED, non-VOIDED delivery portions by member.
        per_member = {}
        for d in store.deliveries.values():
            if d["status"] != "ACCEPTED":
                continue
            if d.get("main_pool_id") != pool["id"] and d.get("over_quota_pool_id") != pool["id"]:
                continue
            entry = per_member.setdefault(d["member_id"], {"weighted": ZERO, "advance": ZERO})
            entry["weighted"] += _pool_weighted_for(d, pool["id"])
            entry["advance"] += to_decimal(d["advance_amount"])

        members = sorted(
            (m for m in store.members.values() if m["id"] in per_member),
            key=lambda m: (m["created_at"], m.get("_seq", 0)),
        )
        for member in members:
            sums = per_member[member["id"]]
            member_weighted = sums["weighted"]
            if member_weighted <= ZERO:
                continue
            gross = round2(member_weighted * final_rate)
            retain = round2(gross * to_decimal(pool["retain_pct"]))
            advance_paid = sums["advance"]
            cash = gross - retain - advance_paid
            dist = new_common({
                "pool_id": pool["id"],
                "member_id": member["id"],
                "weighted_barrels": member_weighted,
                "advance_paid": advance_paid,
                "gross_amount": gross,
                "retain_amount": retain,
                "cash_amount": cash,
                "status": "COMPUTED",
            })
            store.distributions[dist["id"]] = dist
            distributions.append(dist)

    residual = net_pool_value - sum((to_decimal(d["gross_amount"]) for d in distributions), ZERO)

    pool["realized_revenue"] = realized_revenue
    pool["operating_costs"] = operating_costs
    pool["final_rate_per_weighted_barrel"] = final_rate
    pool["coop_equity_residual"] = residual
    pool["status"] = "SETTLED"
    touch(pool)

    season = store.seasons.get(pool["season_id"])
    if season is not None:
        coupling.maybe_settle_season(season)

    return distributions
