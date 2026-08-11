from datetime import timedelta, date
from decimal import Decimal

from db import store, now, next_seq, new_id, touch, Rec
from util import fmt_dt3, round_half_up_cents, dec

# ---- calculation constants (scaffold §1.3) ----
ANNUAL_DISCOUNT = Decimal("0.10")
MONTHLY_DISCOUNT = Decimal("0.00")
PROVISIONAL_REFERRAL_CENTS = 2000
REFERRAL_SHARE = Decimal("0.20")
REFERRAL_CAP_CENTS = 5000
EARLY_SEASON_DISCOUNT = Decimal("0.10")
MIN_CHARGE_CENTS = 1900
MAX_CHARGE_CENTS = 25000
TIER_T2_MIN_SQM = 500
TIER_T3_MIN_SQM = 2000
MAX_SKIPS_PER_WINDOW = 3
SKIP_WINDOW_DAYS = 365
SATISFACTION_CREDIT_CAP_CENTS = 10000
RAIN_BLOCK = Decimal("0.40")
WIND_BLOCK_KPH = 24
TEMP_LOW_BLOCK_C = 5
TEMP_HIGH_BLOCK_C = 32
QUOTE_EXPIRY_DAYS = 7
AUTO_SHIP_ADVANCE_DAYS = 90
AUTO_SHIP_WINDOW_DAYS = 7
CLAIM_WINDOW_DAYS = 30

CATEGORIES = {"FERTILIZER", "WEED", "PEST", "SEED", "SOIL_AMENDMENT"}


# ---------------------------------------------------------------- catalog ---

def find_product_by_sku(sku):
    for p in store.products.values():
        if p.sku == sku:
            return p
    return None


def tier_of(lawn_size_sqm):
    if lawn_size_sqm < TIER_T2_MIN_SQM:
        return "t1"
    if lawn_size_sqm < TIER_T3_MIN_SQM:
        return "t2"
    return "t3"


def tier_rate(product, tier):
    return {
        "t1": product.tier_t1_cents,
        "t2": product.tier_t2_cents,
        "t3": product.tier_t3_cents,
    }[tier]


def is_early_season(dt):
    """month-day in [03-01, 06-01) -> months March, April, May."""
    return 3 <= dt.month <= 5


# ------------------------------------------------------------- traversal ---

def lawn_of_subscription(sub):
    plan = store.plans.get(sub.plan_id)
    return store.lawns.get(plan.lawn_id) if plan else None


def lawn_of_soil_test(kit):
    return store.lawns.get(kit.lawn_id)


def owner_of_subscription(sub):
    return sub.customer_id


# ---------------------------------------------------------------- ledger ---

def recompute_balance(customer_id):
    cust = store.customers.get(customer_id)
    if cust is None:
        return
    cust.credit_balance_cents = sum(
        e.amount_cents for e in store.ledger.values() if e.customer_id == customer_id
    )


def post_ledger(customer_id, entry_type, amount_cents, reference_id=None, note=None):
    ts = now()
    rec = Rec(
        id=new_id(),
        created_at=ts,
        seq=next_seq(),
        customer_id=customer_id,
        entry_type=entry_type,
        amount_cents=amount_cents,
        reference_id=reference_id,
        note=note,
    )
    rec.raw["created_at"] = fmt_dt3(ts)
    store.ledger[rec.id] = rec
    recompute_balance(customer_id)
    return rec


# ----------------------------------------------------------------- plans ---

def compute_plan_provisional(plan):
    total = 0
    for line in plan.plan_lines:
        prod = find_product_by_sku(line["product_sku"])
        if prod is not None:
            total += line["qty_units"] * prod.list_price_cents
    return total


def lock_plan_discount(plan, billing_cycle):
    """Subscription creation / billing_cycle change: write the locked discount
    and committed value onto the plan (a plan mutation -> version bump)."""
    plan.discount_pct_locked = 0.10 if billing_cycle == "ANNUAL" else 0.00
    disc = ANNUAL_DISCOUNT if billing_cycle == "ANNUAL" else MONTHLY_DISCOUNT
    plan.committed_value_cents = round_half_up_cents(
        Decimal(plan.provisional_value_cents) * (Decimal(1) - disc)
    )
    touch(plan)


# ------------------------------------------------------------- shipments ---

def attached_confirmed_addons(box_id):
    return [
        a for a in store.addons.values()
        if a.attached_shipment_id == box_id and a.status == "CONFIRMED"
    ]


def compute_box_charge(box, discount_dt):
    """shipment_charge_calc. Provisional passes ship_date; final passes
    delivered_at and re-reads the lawn tier."""
    sub = store.subscriptions[box.subscription_id]
    lawn = lawn_of_subscription(sub)
    tier = tier_of(lawn.lawn_size_sqm)
    product_part = 0
    for line in box.lines:
        prod = find_product_by_sku(line["product_sku"])
        product_part += line["qty_units"] * tier_rate(prod, tier)
    addon_part = 0
    for ao in attached_confirmed_addons(box.id):
        prod = find_product_by_sku(ao.add_on_sku)
        addon_part += ao.qty_units * prod.add_on_flat_price_cents
    pre_discount = product_part + addon_part
    disc = EARLY_SEASON_DISCOUNT if is_early_season(discount_dt) else Decimal("0.00")
    discounted = round_half_up_cents(Decimal(pre_discount) * (Decimal(1) - disc))
    return min(MAX_CHARGE_CENTS, max(MIN_CHARGE_CENTS, discounted))


def recompute_box_provisional(box, bump=True):
    box.provisional_charge_cents = compute_box_charge(box, box.ship_date)
    if bump:
        touch(box)


def create_box(subscription_id, box_kind, ship_date, dw_start, dw_end, lines,
               source_claim_id=None, raw=None):
    """Shared box creation: ops-created, auto-ship sweep, and claim RESHIP
    replacement boxes. Attaches any unattached CONFIRMED add-on orders of the
    subscription and computes the provisional charge including them."""
    ts = now()
    box = Rec(
        id=new_id(),
        created_at=ts,
        updated_at=ts,
        version=1,
        seq=next_seq(),
        subscription_id=subscription_id,
        box_kind=box_kind,
        fulfillment_status="SCHEDULED",
        billing_status="PENDING",
        ship_date=ship_date,
        delivery_window_start=dw_start,
        delivery_window_end=dw_end,
        lines=lines,
        provisional_charge_cents=None,
        final_charge_cents=None,
        delivered_at=None,
        source_claim_id=source_claim_id,
    )
    box.raw["created_at"] = fmt_dt3(ts)
    box.raw["updated_at"] = fmt_dt3(ts)
    if raw:
        box.raw.update(raw)
    store.shipments[box.id] = box
    # deferred attach: CONFIRMED add-ons with no box yet ride the next created box
    for ao in sort_by_created(store.addons.values()):
        if (ao.subscription_id == subscription_id and ao.status == "CONFIRMED"
                and ao.attached_shipment_id is None):
            ao.attached_shipment_id = box.id
            touch(ao)
    box.provisional_charge_cents = compute_box_charge(box, ship_date)
    return box


def earliest_scheduled_box(subscription_id):
    """Attach/skip selector: status SCHEDULED, ship_date ASC, created_at ASC."""
    candidates = [
        b for b in store.shipments.values()
        if b.subscription_id == subscription_id and b.fulfillment_status == "SCHEDULED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda b: (b.ship_date, b.created_at, b.seq))
    return candidates[0]


def sort_by_created(recs):
    return sorted(recs, key=lambda r: (r.created_at, r.seq))


def void_issued_invoice_for_box(box):
    """Flip the box's ISSUED invoice (if any) to VOID and restore its applied
    credit via a RESTORE_VOID_INVOICE ledger entry."""
    for inv in store.invoices.values():
        if inv.shipment_id == box.id and inv.status == "ISSUED":
            inv.status = "VOID"
            touch(inv)
            if inv.credit_applied_cents > 0:
                post_ledger(inv_customer(inv), "RESTORE_VOID_INVOICE",
                            inv.credit_applied_cents, reference_id=inv.id)
    if box.billing_status == "INVOICED":
        box.billing_status = "VOID"


def inv_customer(inv):
    sub = store.subscriptions[inv.subscription_id]
    return sub.customer_id


# ---------------------------------------------------------------- invoices --

def create_invoice(box):
    """invoice_total_calc at SHIPPED: per-line rounding first, then sum."""
    sub = store.subscriptions[box.subscription_id]
    lawn = lawn_of_subscription(sub)
    tier = tier_of(lawn.lawn_size_sqm)
    customer = store.customers[sub.customer_id]
    early = is_early_season(box.ship_date)
    line_discount = EARLY_SEASON_DISCOUNT if early else Decimal("0.00")

    line_items = []
    for line in box.lines:
        prod = find_product_by_sku(line["product_sku"])
        unit = tier_rate(prod, tier)
        total = round_half_up_cents(
            Decimal(line["qty_units"]) * Decimal(unit) * (Decimal(1) - line_discount)
        )
        line_items.append({
            "product_sku": line["product_sku"],
            "qty_units": line["qty_units"],
            "unit_price_cents": unit,
            "line_discount_pct": float(line_discount),
            "line_total_cents": total,
        })
    for ao in attached_confirmed_addons(box.id):
        prod = find_product_by_sku(ao.add_on_sku)
        unit = prod.add_on_flat_price_cents
        total = round_half_up_cents(
            Decimal(ao.qty_units) * Decimal(unit) * (Decimal(1) - line_discount)
        )
        line_items.append({
            "product_sku": ao.add_on_sku,
            "qty_units": ao.qty_units,
            "unit_price_cents": unit,
            "line_discount_pct": float(line_discount),
            "line_total_cents": total,
        })

    subtotal = sum(li["line_total_cents"] for li in line_items)
    credit_applied = min(customer.credit_balance_cents, subtotal)
    total = subtotal - credit_applied

    ts = now()
    inv = Rec(
        id=new_id(),
        created_at=ts,
        updated_at=ts,
        version=1,
        seq=next_seq(),
        subscription_id=box.subscription_id,
        shipment_id=box.id,
        line_items=line_items,
        subtotal_cents=subtotal,
        credit_applied_cents=credit_applied,
        total_cents=total,
        status="ISSUED",
        issued_at=ts,
    )
    inv.raw["created_at"] = fmt_dt3(ts)
    inv.raw["updated_at"] = fmt_dt3(ts)
    inv.raw["issued_at"] = fmt_dt3(ts)
    store.invoices[inv.id] = inv
    if credit_applied > 0:
        post_ledger(customer.id, "REDEEM_INVOICE", -credit_applied, reference_id=inv.id)
    return inv


def invoice_for_box(box_id):
    for inv in sort_by_created(store.invoices.values()):
        if inv.shipment_id == box_id:
            return inv
    return None


# ----------------------------------------------------------- applications --

def product_window_for_year(product, year):
    return "%04d-%s" % (year, product.window_start_md), "%04d-%s" % (year, product.window_end_md)


def date_in_window(product, date_str):
    """Half-open [window_start_date, window_end_date) for the date's year."""
    d = date.fromisoformat(date_str)
    start, end = product_window_for_year(product, d.year)
    return start <= date_str < end, start, end


def weather_blocked(region, date_str):
    """weather_gate_calc. Absent advisory -> not blocked."""
    adv = None
    for a in store.weather_advisories.values():
        if a.region == region and a.date == date_str:
            adv = a
            break
    if adv is None:
        return False
    if dec(adv.rain_probability) >= RAIN_BLOCK:
        return True
    if adv.wind_kph > WIND_BLOCK_KPH:
        return True
    if adv.temp_high_c < TEMP_LOW_BLOCK_C or adv.temp_high_c > TEMP_HIGH_BLOCK_C:
        return True
    return False


def buffer_conflict(lawn_id, new_product, new_date_str, exclude_task_id=None):
    """application_window_calc buffer rule. Conflict counts in either direction
    of conflicting_categories; |delta| >= min_gap_days of the NEW product passes."""
    new_d = date.fromisoformat(new_date_str)
    for task in store.applications.values():
        if task.lawn_id != lawn_id or task.id == exclude_task_id:
            continue
        if task.status not in ("SCHEDULED", "FROZEN", "APPLIED"):
            continue
        if task.scheduled_date is None:
            continue
        existing = find_product_by_sku(task.product_sku)
        if existing is None:
            continue
        conflict = (
            existing.category in (new_product.conflicting_categories or [])
            or new_product.category in (existing.conflicting_categories or [])
        )
        if not conflict:
            continue
        delta = abs((new_d - date.fromisoformat(task.scheduled_date)).days)
        if delta < (new_product.min_gap_days if new_product.min_gap_days is not None else 14):
            return True
    return False


# ------------------------------------------------------ subscription flows --

def pause_cascade(sub):
    for box in store.shipments.values():
        if box.subscription_id == sub.id and box.fulfillment_status == "SCHEDULED":
            box.fulfillment_status = "HELD"
            touch(box)
    for task in store.applications.values():
        if task.subscription_id == sub.id and task.status == "SCHEDULED":
            task.status = "FROZEN"
            touch(task)


def resume_cascade(sub):
    for box in store.shipments.values():
        if box.subscription_id == sub.id and box.fulfillment_status == "HELD":
            box.fulfillment_status = "SCHEDULED"
            touch(box)
    for task in store.applications.values():
        if task.subscription_id == sub.id and task.status == "FROZEN":
            task.status = "SCHEDULED"
            touch(task)


def cancel_cascade(sub):
    # boxes: everything not DELIVERED/SKIPPED/CANCELLED -> CANCELLED, with the
    # ISSUED-invoice void + credit restore compensation
    for box in sort_by_created(store.shipments.values()):
        if box.subscription_id != sub.id:
            continue
        if box.fulfillment_status in ("DELIVERED", "SKIPPED", "CANCELLED"):
            continue
        box.fulfillment_status = "CANCELLED"
        void_issued_invoice_for_box(box)
        touch(box)
    # tasks: not APPLIED/CANCELLED -> CANCELLED
    for task in sort_by_created(store.applications.values()):
        if task.subscription_id != sub.id:
            continue
        if task.status in ("APPLIED", "CANCELLED"):
            continue
        task.status = "CANCELLED"
        touch(task)
    # add-ons: QUOTED/CONFIRMED -> CANCELLED with detach compensation
    for ao in sort_by_created(store.addons.values()):
        if ao.subscription_id != sub.id:
            continue
        if ao.status not in ("QUOTED", "CONFIRMED"):
            continue
        ao.status = "CANCELLED"
        touch(ao)


def deliver_cascade(box):
    """Box reaches DELIVERED: stamp delivered_at, compute the final charge with
    the delivered_at early-season test, fulfill attached add-ons, and release
    AWAITING_DELIVERY tasks."""
    ts = now()
    box.delivered_at = ts
    box.raw["delivered_at"] = fmt_dt3(ts)
    box.final_charge_cents = compute_box_charge(box, ts)
    for ao in attached_confirmed_addons(box.id):
        ao.status = "FULFILLED"
        touch(ao)
    delivery_date = ts.strftime("%Y-%m-%d")
    for task in sort_by_created(store.applications.values()):
        if task.shipment_id != box.id or task.status != "AWAITING_DELIVERY":
            continue
        task.status = "SCHEDULED"
        task.scheduled_date = delivery_date
        prod = find_product_by_sku(task.product_sku)
        if prod is not None:
            start, end = product_window_for_year(prod, ts.year)
            task.window_start_date = start
            task.window_end_date = end
        touch(task)


# ------------------------------------------------------------- the sweep ----

def run_clock_sweeps():
    """Auto-ship sweep then quote-expiry sweep (PRD 2.5)."""
    boxes_generated = 0
    for sub in sort_by_created(store.subscriptions.values()):
        if sub.status != "ACTIVE" or not sub.auto_ship:
            continue
        if sub.next_ship_date is None or sub.next_ship_date > now():
            continue
        plan = store.plans.get(sub.plan_id)
        if plan is None:
            continue
        ship_date = sub.next_ship_date
        lines = [
            {"product_sku": l["product_sku"], "qty_units": l["qty_units"]}
            for l in plan.plan_lines
        ]
        create_box(
            sub.id,
            "SEASONAL",
            ship_date,
            ship_date,
            ship_date + timedelta(days=AUTO_SHIP_WINDOW_DAYS),
            lines,
        )
        boxes_generated += 1
        sub.next_ship_date = ship_date + timedelta(days=AUTO_SHIP_ADVANCE_DAYS)
        sub.raw.pop("next_ship_date", None)
        touch(sub)

    add_ons_expired = 0
    for ao in sort_by_created(store.addons.values()):
        if ao.status == "QUOTED" and ao.quote_expires_at is not None and now() >= ao.quote_expires_at:
            ao.status = "EXPIRED"
            touch(ao)
            add_ons_expired += 1
    return boxes_generated, add_ons_expired


# -------------------------------------------------------------- referrals --

def maybe_qualify_referral(invoice):
    """On invoice PAID: if the subscriber is the referee of a PENDING referral
    and has no earlier PAID invoice, qualify it."""
    sub = store.subscriptions[invoice.subscription_id]
    referee_id = sub.customer_id
    referee_sub_ids = {s.id for s in store.subscriptions.values() if s.customer_id == referee_id}
    earlier_paid = any(
        inv.id != invoice.id and inv.subscription_id in referee_sub_ids and inv.status == "PAID"
        for inv in store.invoices.values()
    )
    if earlier_paid:
        return
    for ref in sort_by_created(store.referrals.values()):
        if ref.referee_customer_id != referee_id or ref.status != "PENDING":
            continue
        qualified = min(
            REFERRAL_CAP_CENTS,
            round_half_up_cents(REFERRAL_SHARE * Decimal(invoice.total_cents)),
        )
        ref.qualified_credit_cents = qualified
        ref.referee_first_invoice_id = invoice.id
        ref.status = "QUALIFIED"
        touch(ref)
        post_ledger(ref.referrer_customer_id, "EARN_REFERRAL", qualified, reference_id=ref.id)
