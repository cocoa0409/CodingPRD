"""Commission statement calculations (PRD 3.7, scaffold calculations 1.3)."""
from db import db
from services.money import round_half_up
from services.timeutil import parse_iso, in_period

BAND1_CAP = 500000
BAND2_CAP = 1500000
BAND1_RATE = 0.08
BAND2_RATE = 0.12
BAND3_RATE = 0.15
HOST_SHRINK_SHARE = 0.50


def host_machine_ids(host_site_id):
    return {m["id"] for m in db.machines.values() if m["host_site_id"] == host_site_id}


def period_settled_sales(host_site_id, start_dt, end_dt):
    """SETTLED sales on this host's machines whose sale (created_at) is in period."""
    machine_ids = host_machine_ids(host_site_id)
    return [s for s in db.sales.values()
            if s["machine_id"] in machine_ids
            and s["settlement_status"] == "SETTLED"
            and in_period(s["created_at"], start_dt, end_dt)]


def compute_gross_sales(host_site_id, start_dt, end_dt):
    return sum(s["gross_cents"] for s in period_settled_sales(host_site_id, start_dt, end_dt))


def _slot_category(slot_id):
    slot = db.slots.get(slot_id)
    if slot is None:
        return None
    product = db.products.get(slot["product_id"])
    return product["category"] if product else None


def compute_gross_commission(host, start_dt, end_dt, gross_sales_cents):
    """FLAT or TIERED commission (PRD 3.7)."""
    if host["commission_model"] == "FLAT":
        return round_half_up(gross_sales_cents * host["flat_commission_pct"])

    # TIERED — FRESH_FOOD sales excluded from the tiered base.
    sales = period_settled_sales(host["id"], start_dt, end_dt)
    tiered_base = sum(s["gross_cents"] for s in sales
                      if _slot_category(s["slot_id"]) != "FRESH_FOOD")

    c = 0.0
    c += min(tiered_base, BAND1_CAP) * BAND1_RATE
    if tiered_base > BAND1_CAP:
        c += (min(tiered_base, BAND2_CAP) - BAND1_CAP) * BAND2_RATE
    if tiered_base > BAND2_CAP:
        c += (tiered_base - BAND2_CAP) * BAND3_RATE
    return round_half_up(c)  # sum-then-round, once at the end


def compute_shrink_chargeback(host_site_id, start_dt, end_dt):
    """Round each RECONCILED visit's chargeback to cents, THEN sum (round-then-sum).

    Visit selection: RECONCILED visits on host's machines whose reconcile time
    (updated_at) falls in [period_start, period_end).
    """
    machine_ids = host_machine_ids(host_site_id)
    total = 0
    for v in db.visits.values():
        if v["status"] != "RECONCILED":
            continue
        if v["machine_id"] not in machine_ids:
            continue
        if not in_period(v["updated_at"], start_dt, end_dt):
            continue
        total += round_half_up(v["shrink_value_cents"] * HOST_SHRINK_SHARE)
    return total


def recompute_amounts(statement):
    """Recompute the four amounts on a statement in place (live read or finalize)."""
    host = db.host_sites.get(statement["host_site_id"])
    start_dt = parse_iso(statement["period_start"])
    end_dt = parse_iso(statement["period_end"])

    gross_sales = compute_gross_sales(statement["host_site_id"], start_dt, end_dt)
    gross_commission = compute_gross_commission(host, start_dt, end_dt, gross_sales)
    shrink_chargeback = compute_shrink_chargeback(statement["host_site_id"], start_dt, end_dt)

    raw_net = gross_commission - shrink_chargeback
    net = max(raw_net, host["monthly_guarantee_cents"])

    statement["gross_sales_cents"] = gross_sales
    statement["gross_commission_cents"] = gross_commission
    statement["shrink_chargeback_cents"] = shrink_chargeback
    statement["net_commission_cents"] = net
    return statement
