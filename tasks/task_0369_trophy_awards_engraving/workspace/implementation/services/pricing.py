"""Order pricing orchestration: per-line recompute + ESTIMATE/INVOICE passes."""
from db import db, now_dt
from errors import err
from services import calc


def order_lines_for(order_id):
    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    return sorted(lines, key=lambda l: (l["created_at"], l["id"]))


def active_rush_policy():
    actives = [p for p in db.rush_policies.values() if p.get("active")]
    return actives[0] if len(actives) == 1 else (actives[0] if actives else None), len(actives)


def recompute_lines(order):
    """Recompute char_count, line_subtotal_cents, volume_tier, volume_discount_cents
    for every line on the order (calc line_subtotal, volume_discount)."""
    lines = order_lines_for(order["id"])
    for line in lines:
        product = db.catalog_products[line["catalog_product_id"]]
        cc, subtotal = calc.line_subtotal(line, product)
        line["char_count"] = cc
        line["line_subtotal_cents"] = subtotal
        tier, discount = calc.volume_discount(line, product)
        line["volume_tier"] = tier
        line["volume_discount_cents"] = discount
    return lines


def product_max_standard_lead(lines):
    leads = [db.catalog_products[l["catalog_product_id"]]["standard_lead_days"] for l in lines]
    return max(leads) if leads else 1


def order_subtotal(lines):
    return sum(l["line_subtotal_cents"] - l["volume_discount_cents"] for l in lines)


def resolve_tier_for_order(order, lines, policy):
    """Returns (rush_tier, surcharge_pct). Raises ERR_DUE_DATE_INFEASIBLE if the
    due date is below the policy floor."""
    due = parse_due(order["due_date"])
    bd = calc.business_days_to_due(now_dt(), due)
    if bd < policy.get("rush_min_business_days", 1):
        raise err("ERR_DUE_DATE_INFEASIBLE", "Due date is not feasible under the active rush policy")
    max_lead = product_max_standard_lead(lines)
    return calc.resolve_rush_tier(bd, policy, max_lead)


def parse_due(value):
    """Parse an ISO datetime/date string into a tz-aware UTC datetime."""
    from datetime import datetime, timezone
    if isinstance(value, str):
        s = value
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # date-only
            dt = datetime.fromisoformat(s[:10])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return value
