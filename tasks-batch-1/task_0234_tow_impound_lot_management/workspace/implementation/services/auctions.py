"""Auction proceeds waterfall aggregation (scaffold auction_proceeds_distribution
/ PRD §3.9)."""
import db
from services import calc


def sold_orders_for(auction_id):
    """AUCTIONED orders linked to this auction, ordered created_at ASC (_seq)."""
    orders = [o for o in db.tow_orders.values()
              if o.get("auction_id") == auction_id and o["status"] == "AUCTIONED"]
    orders.sort(key=lambda o: o["_seq"])
    return orders


def recompute_distribution(auction):
    """Recompute gross/distributed/lien_payoff/surplus aggregates across all sold
    orders of the auction. Uses each order's recorded sale price (_sale_price_cents)
    and its accrued_storage_cents at sale time."""
    gross = 0
    distributed = 0
    lien_payoff = 0
    surplus = 0
    for order in sold_orders_for(auction["id"]):
        lot = db.impound_lots.get(order["lot_id"])
        price = order.get("_sale_price_cents", 0)
        rec, lien, surp = calc.waterfall(order, lot, price)
        gross += price
        distributed += rec
        lien_payoff += lien
        surplus += surp
    auction["gross_proceeds_cents"] = gross
    auction["distributed_cents"] = distributed
    auction["lien_payoff_cents"] = lien_payoff
    auction["surplus_to_owner_cents"] = surplus
    return auction
