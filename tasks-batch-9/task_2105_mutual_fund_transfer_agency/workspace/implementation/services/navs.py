"""NAV strike helpers."""
import db
from money import q3, q4


def find_for(share_class_id, valuation_date):
    for record in db.store.nav_records.values():
        if record["share_class_id"] == share_class_id and record["valuation_date"] == valuation_date:
            return record
    return None


def strike(share_class, total_net_assets):
    """calculation nav_per_share_strike."""
    snapshot = q3(share_class["total_shares_outstanding"])
    if snapshot == 0:
        nav = q4(share_class["seed_nav_per_share"])
    else:
        nav = q4(total_net_assets / snapshot)
    return snapshot, nav
