"""Business logic: logical clock, calculations, derived fields, serializers."""
import re
import uuid
from datetime import datetime, timedelta, timezone, time as dtime
from decimal import Decimal, ROUND_HALF_UP

from db import db

UTC = timezone.utc
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ACCRUING_STATUSES = ("INSTALLED", "RETURN_REQUESTED")
INVOICE_OUTSTANDING_STATUSES = ("OPEN", "OVERDUE", "PARTIALLY_PAID", "DISPUTED")
COMMITTED_STOP_STATUSES = ("PLANNED", "EN_ROUTE", "ARRIVED")
TERMINAL_STOP_STATUSES = ("DELIVERED", "PARTIAL", "SKIPPED", "FAILED", "CANCELLED")


# --------------------------------------------------------------------- time

def now():
    return db.clock


def today():
    return db.clock.date()


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_date(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise ValueError("bad date")
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_datetime(s):
    if not isinstance(s, str):
        raise ValueError("bad datetime")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def day_start(d):
    return datetime.combine(d, dtime.min, tzinfo=UTC)


# ------------------------------------------------------------------ records

def new_id():
    return str(uuid.uuid4())


def base_record():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "seq": db.next_seq(),
    }


def bump(rec):
    """Common-field rule: updated_at refreshed and version incremented on
    every modification, including cascading side effects."""
    rec["updated_at"] = now()
    rec["version"] += 1


# -------------------------------------------------------------- pricing cfg

def config_at(d):
    """PricingConfig in effect on date d: half-open tiling
    [effective_from, next.effective_from)."""
    best = None
    for c in db.pricing_configs.values():
        if c["_ef"] <= d:
            if best is None or (c["_ef"], c["seq"]) > (best["_ef"], best["seq"]):
                best = c
    return best


def rate_for_tier(cfg, tier):
    if cfg is None:
        return 0
    return {
        "STANDARD": cfg["standard_per_bottle_cents"],
        "SILVER": cfg["silver_per_bottle_cents"],
        "GOLD": cfg["gold_per_bottle_cents"],
    }[tier]


# ------------------------------------------------------------ derived fields

def bottles_on_site(customer_id):
    return sum(e["quantity"] for e in db.ledger.values()
               if e["customer_ref"] == customer_id)


def outstanding_balance(customer_id):
    return sum(inv["balance_due_cents"] for inv in db.invoices.values()
               if inv["customer_id"] == customer_id
               and inv["invoice_status"] in INVOICE_OUTSTANDING_STATUSES)


def deposit_liability(customer_id):
    cfg = config_at(today())
    rate = cfg["bottle_deposit_cents"] if cfg else 0
    return bottles_on_site(customer_id) * rate


def committed_bottles(route_id):
    return sum(s["planned_bottles"] for s in db.stops.values()
               if s["route_id"] == route_id
               and s["stop_status"] in COMMITTED_STOP_STATUSES)


def add_ledger_entry(customer_ref, stop_id, entry_kind, quantity):
    rec = {
        "id": new_id(),
        "created_at": now(),
        "seq": db.next_seq(),
        "customer_ref": customer_ref,
        "stop_id": stop_id,
        "entry_kind": entry_kind,
        "quantity": quantity,
        "occurred_at": now(),
    }
    db.ledger[rec["id"]] = rec
    return rec


# ------------------------------------------------------- rent proration

def rental_status_at(rental, t):
    st = "PENDING_INSTALL"
    for ts, s in rental["status_history"]:
        if ts <= t:
            st = s
        else:
            break
    return st


def accruing_days(rental, start_date, end_date):
    """Count days d in [start_date, end_date) on which rent accrues:
    the rental stands INSTALLED or RETURN_REQUESTED at start of day;
    SUSPENDED days accrue zero; the install day and the return day each
    count as a full accrual day (inclusive return day variant)."""
    if end_date <= start_date:
        return 0
    days = 0
    installed_date = rental["installed_at"].date() if rental.get("installed_at") else None
    returned_date = rental["returned_at"].date() if rental.get("returned_at") else None
    d = start_date
    while d < end_date:
        st = rental_status_at(rental, day_start(d))
        if st in ACCRUING_STATUSES:
            days += 1
        elif st == "PENDING_INSTALL" and installed_date == d:
            days += 1
        elif st in ("RETURNED", "CLOSED") and returned_date == d:
            days += 1
        d += timedelta(days=1)
    return days


def daily_rate_cents(rental):
    return int((Decimal(rental["monthly_rent_cents"]) * 12 / Decimal(365))
               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def prorated_rent(rental, period_start, period_end):
    return daily_rate_cents(rental) * accruing_days(rental, period_start, period_end)


def refresh_accrued_rent(rental):
    """Cache the running accrual between installed_at and the current clock."""
    if not rental.get("installed_at"):
        rental["accrued_rent_cents"] = 0
        return
    end = rental["returned_at"].date() if rental.get("returned_at") else today()
    days = accruing_days(rental, rental["installed_at"].date(),
                         end + timedelta(days=1))
    rental["accrued_rent_cents"] = daily_rate_cents(rental) * days


# ------------------------------------------------------ deposit refund calc

def custody_balance_at(customer_id, t):
    return sum(e["quantity"] for e in db.ledger.values()
               if e["customer_ref"] == customer_id and e["occurred_at"] < t)


def deposit_refund_cents(customer_id, period_start, period_end):
    """Net-movement deposit refund: max(0, opening - closing) * deposit."""
    cfg = config_at(period_end)
    rate = cfg["bottle_deposit_cents"] if cfg else 0
    opening = custody_balance_at(customer_id, day_start(period_start))
    closing = custody_balance_at(customer_id, day_start(period_end))
    return max(0, opening - closing) * rate


# ------------------------------------------------------- skip credit calc

def skip_credit_cents(customer, planned_bottles, notified_before_cutoff, cfg):
    projected = planned_bottles * rate_for_tier(cfg, customer["pricing_tier"])
    if notified_before_cutoff:
        return projected
    return int((Decimal(projected) * Decimal("0.5"))
               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------- time-driven auto transitions

def run_time_transitions():
    """Fired when the logical clock advances: OPEN->OVERDUE invoices with a
    passed due_date and positive balance (late fee charged once), and
    PENDING->EXPIRED skip credits whose expires_at has been reached."""
    t = now()
    d = t.date()
    cfg = config_at(d)
    late_fee = cfg["late_fee_flat_cents"] if cfg else 0
    for inv in db.invoices.values():
        if (inv["invoice_status"] == "OPEN" and inv["balance_due_cents"] > 0
                and parse_date(inv["due_date"]) < d):
            inv["invoice_status"] = "OVERDUE"
            inv["total_due_cents"] += late_fee
            inv["balance_due_cents"] += late_fee
            bump(inv)
            cust = db.customers.get(inv["customer_id"])
            if cust is not None and cust.get("overdue_since") is None:
                cust["overdue_since"] = t
    for sc in db.skip_credits.values():
        if sc["credit_status"] == "PENDING" and sc["expires_at"] <= t:
            sc["credit_status"] = "EXPIRED"
            bump(sc)


def maybe_clear_overdue_since(customer):
    """After an invoice is paid: clear overdue_since when the customer holds
    no other OPEN or OVERDUE invoices."""
    for inv in db.invoices.values():
        if (inv["customer_id"] == customer["id"]
                and inv["invoice_status"] in ("OPEN", "OVERDUE")):
            return
    customer["overdue_since"] = None


# ------------------------------------------------------------- serializers

def _base(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_pricing_config(c):
    out = _base(c)
    out.update({
        "effective_from": c["effective_from"],
        "bottle_deposit_cents": c["bottle_deposit_cents"],
        "bottle_shortage_fee_cents": c["bottle_shortage_fee_cents"],
        "standard_per_bottle_cents": c["standard_per_bottle_cents"],
        "silver_per_bottle_cents": c["silver_per_bottle_cents"],
        "gold_per_bottle_cents": c["gold_per_bottle_cents"],
        "silver_volume_threshold": c["silver_volume_threshold"],
        "gold_volume_threshold": c["gold_volume_threshold"],
        "late_fee_flat_cents": c["late_fee_flat_cents"],
    })
    return out


def ser_zone(z):
    out = _base(z)
    out.update({"code": z["code"], "name": z["name"], "active": z["active"]})
    return out


def ser_customer(c):
    out = _base(c)
    out.update({
        "account_type": c["account_type"],
        "business_name": c["business_name"],
        "billing_email": c["billing_email"],
        "service_address": c["service_address"],
        "delivery_zone_id": c["delivery_zone_id"],
        "service_mode": c["service_mode"],
        "par_level_bottles": c["par_level_bottles"],
        "pricing_tier": c["pricing_tier"],
        "account_status": c["account_status"],
        "outstanding_balance_cents": outstanding_balance(c["id"]),
        "bottles_on_site": bottles_on_site(c["id"]),
        "deposit_liability_cents": deposit_liability(c["id"]),
        "overdue_since": fmt_dt(c["overdue_since"]),
    })
    return out


def ser_route(r):
    out = _base(r)
    out.update({
        "zone_id": r["zone_id"],
        "service_date": r["service_date"],
        "driver_name": r["driver_name"],
        "truck_capacity_bottles": r["truck_capacity_bottles"],
        "committed_bottles": committed_bottles(r["id"]),
        "route_status": r["route_status"],
    })
    return out


def ser_stop(s):
    out = _base(s)
    out.update({
        "route_id": s["route_id"],
        "customer_id": s["customer_id"],
        "sequence_index": s["sequence_index"],
        "planned_bottles": s["planned_bottles"],
        "planned_empties_pickup": s["planned_empties_pickup"],
        "stop_status": s["stop_status"],
        "actual_bottles_delivered": s["actual_bottles_delivered"],
        "actual_empties_collected": s["actual_empties_collected"],
        "shortage_count": s["shortage_count"],
        "skip_reason": s["skip_reason"],
    })
    return out


def ser_ledger(e):
    # Custody ledger entries carry id and created_at only -- no updated_at,
    # no version (PRD §2.5).
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "customer_ref": e["customer_ref"],
        "stop_id": e["stop_id"],
        "entry_kind": e["entry_kind"],
        "quantity": e["quantity"],
        "occurred_at": fmt_dt(e["occurred_at"]),
    }


def ser_rental(r):
    out = _base(r)
    out.update({
        "customer_id": r["customer_id"],
        "cooler_model": r["cooler_model"],
        "monthly_rent_cents": r["monthly_rent_cents"],
        "deposit_cents": r["deposit_cents"],
        "rental_status": r["rental_status"],
        "installed_at": fmt_dt(r["installed_at"]),
        "returned_at": fmt_dt(r["returned_at"]),
        "accrued_rent_cents": r["accrued_rent_cents"],
    })
    return out


def ser_addon(a):
    out = _base(a)
    out.update({
        "customer_id": a["customer_id"],
        "addon_kind": a["addon_kind"],
        "quantity": a["quantity"],
        "unit_price_cents": a["unit_price_cents"],
        "cadence": a["cadence"],
        "addon_status": a["addon_status"],
    })
    return out


def ser_invoice(inv):
    out = _base(inv)
    out.update({
        "customer_id": inv["customer_id"],
        "billing_period_start": inv["billing_period_start"],
        "billing_period_end": inv["billing_period_end"],
        "subtotal_water_cents": inv["subtotal_water_cents"],
        "subtotal_addon_cents": inv["subtotal_addon_cents"],
        "subtotal_rent_cents": inv["subtotal_rent_cents"],
        "shortage_charge_cents": inv["shortage_charge_cents"],
        "deposit_credit_cents": inv["deposit_credit_cents"],
        "total_due_cents": inv["total_due_cents"],
        "balance_due_cents": inv["balance_due_cents"],
        "invoice_status": inv["invoice_status"],
        "due_date": inv["due_date"],
        "issued_at": fmt_dt(inv["issued_at"]),
    })
    return out


def ser_payment(p):
    out = _base(p)
    out.update({
        "invoice_id": p["invoice_id"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "payment_status": p["payment_status"],
        "applied_at": fmt_dt(p["applied_at"]),
    })
    return out


def ser_work_order(w):
    out = _base(w)
    out.update({
        "customer_id": w["customer_id"],
        "order_kind": w["order_kind"],
        "requested_date": w["requested_date"],
        "quantity_bottles": w["quantity_bottles"],
        "order_status": w["order_status"],
        "linked_stop_id": w["linked_stop_id"],
        "linked_rental_id": w["linked_rental_id"],
    })
    return out


def ser_skip_credit(sc):
    out = _base(sc)
    out.update({
        "customer_id": sc["customer_id"],
        "stop_id": sc["stop_id"],
        "credit_cents": sc["credit_cents"],
        "credit_status": sc["credit_status"],
        "expires_at": fmt_dt(sc["expires_at"]),
        "notified_before_cutoff": sc["notified_before_cutoff"],
    })
    return out
