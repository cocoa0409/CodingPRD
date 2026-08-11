"""Business logic: calculations, state-machine side effects, cascades,
invoice waterfall, satisfaction scoring, and serializers."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from clock import now, iso, today_midnight
from db import STORE, new_id, next_seq

customers = STORE["customers"]
yards = STORE["yards"]
access_profiles = STORE["access_profiles"]
plans = STORE["plans"]
addons = STORE["addons"]
subscriptions = STORE["subscriptions"]
routes = STORE["routes"]
technicians = STORE["technicians"]
vacation_windows = STORE["vacation_windows"]
visits = STORE["visits"]
invoices = STORE["invoices"]
line_items = STORE["line_items"]
reports = STORE["reports"]

# --- calculation constants (SCAFFOLD section 1.3) ---
AVG_VISITS = {
    "WEEKLY": Decimal("4.33"),
    "BIWEEKLY": Decimal("2.17"),
    "TWICE_WEEKLY": Decimal("8.67"),
    "DAILY": Decimal("30"),
}
BUNDLE_SANITIZE_DEODORIZE_DISCOUNT_BP = 1500
DECAY_PER_DAY = Decimal("0.9")
RESOLVED_RESET_RATING = Decimal("5.0")

TERMINAL_VISIT_STATES = {"COMPLETED", "SKIPPED", "MISSED", "CANCELLED"}
COMMITTED_VISIT_STATES = {"SCHEDULED", "EN_ROUTE", "ON_SITE"}


def rhu(value):
    """Round-half-up a Decimal to whole cents."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_record():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def bump(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# monthly_subscription_fee (tiered pricing)
# ---------------------------------------------------------------------------
def monthly_fee(plan, yard):
    base = plan["base_monthly_fee_cents"]
    yard_idx = sum(1 for t in plan["yard_tier_thresholds"] if yard["yard_size_sqft"] >= t)
    yard_surcharge = plan["yard_tier_surcharges_cents"][yard_idx]
    pet_idx = sum(1 for t in plan["pet_tier_thresholds"] if yard["pet_count"] >= t)
    pet_surcharge = plan["pet_tier_surcharges_cents"][pet_idx]
    subtotal = base + yard_surcharge + pet_surcharge
    if yard["is_multifamily_common_area"]:
        return rhu(
            Decimal(subtotal) * Decimal(plan["multifamily_multiplier_bp"]) / Decimal(10000)
        )
    return subtotal


# ---------------------------------------------------------------------------
# per_visit_charge
# ---------------------------------------------------------------------------
def base_per_visit_cents(subscription):
    plan = plans.get(subscription["plan_id"])
    if plan is None:
        return 0
    snapshot = subscription.get("monthly_fee_cents_snapshot") or 0
    return rhu(Decimal(snapshot) / AVG_VISITS[plan["visit_frequency"]])


def _dedupe(ids):
    seen = set()
    out = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def addon_total_cents(addon_ids):
    """Resolve addon_ids against ACTIVE ServiceAddons; SANITIZE+DEODORIZE pair
    is discounted by 1500bp (round-half-up once on the pair sum)."""
    sanitize_price = 0
    deodorize_price = 0
    other_total = 0
    for aid in _dedupe(addon_ids or []):
        a = addons.get(aid)
        if a is None or a["addon_status"] != "ACTIVE":
            continue
        price = a["price_cents_per_visit"]
        if a["addon_code"] == "SANITIZE" and sanitize_price == 0:
            sanitize_price = price
        elif a["addon_code"] == "DEODORIZE" and deodorize_price == 0:
            deodorize_price = price
        else:
            other_total += price
    if sanitize_price > 0 and deodorize_price > 0:
        pair = rhu(
            Decimal(sanitize_price + deodorize_price)
            * Decimal(10000 - BUNDLE_SANITIZE_DEODORIZE_DISCOUNT_BP)
            / Decimal(10000)
        )
    else:
        pair = sanitize_price + deodorize_price
    return pair + other_total


def per_visit_charge_cents(subscription, addon_ids):
    return base_per_visit_cents(subscription) + addon_total_cents(addon_ids)


# ---------------------------------------------------------------------------
# route load accounting
# ---------------------------------------------------------------------------
def route_visits(route_id):
    return [v for v in visits.values() if v.get("service_route_id") == route_id]


def recompute_route(route, do_bump=True):
    committed = sum(
        1
        for v in route_visits(route["id"])
        if v["status"] in COMMITTED_VISIT_STATES
    )
    route["committed_visit_count"] = committed
    route["route_load_factor_bp"] = (committed * 10000) // route["max_visit_capacity"]
    if do_bump:
        bump(route)


def maybe_auto_close_route(route):
    """System transition: IN_PROGRESS -> CLOSED when every visit is terminal."""
    if route["route_status"] != "IN_PROGRESS":
        return
    rvs = route_visits(route["id"])
    if rvs and all(v["status"] in TERMINAL_VISIT_STATES for v in rvs):
        route["route_status"] = "CLOSED"
        # single bump covers the status change (counters were recomputed by caller)


# ---------------------------------------------------------------------------
# invoices: waterfall helpers and line posting
# ---------------------------------------------------------------------------
def month_period(d):
    start = d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def find_covering_open_invoice(customer_id, when):
    for inv in invoices.values():
        if (
            inv["customer_id"] == customer_id
            and inv["invoice_status"] == "OPEN"
            and inv["billing_period_start"] <= when < inv["billing_period_end"]
        ):
            return inv
    return None


def find_covering_any_invoice(customer_id, when):
    for inv in invoices.values():
        if (
            inv["customer_id"] == customer_id
            and inv["billing_period_start"] <= when < inv["billing_period_end"]
        ):
            return inv
    return None


def next_open_invoice_after(customer_id, period_start):
    cands = [
        inv
        for inv in invoices.values()
        if inv["customer_id"] == customer_id
        and inv["invoice_status"] == "OPEN"
        and inv["billing_period_start"] > period_start
    ]
    if not cands:
        return None
    return min(cands, key=lambda i: (i["billing_period_start"], i["_seq"]))


def create_invoice(customer_id, period_start, period_end):
    rec = new_record()
    rec.update(
        {
            "customer_id": customer_id,
            "billing_period_start": period_start,
            "billing_period_end": period_end,
            "invoice_status": "OPEN",
            "subtotal_cents": 0,
            "credits_applied_cents": 0,
            "total_due_cents": 0,
            "finalized_at": None,
        }
    )
    invoices[rec["id"]] = rec
    return rec


def invoice_lines(invoice_id):
    return [l for l in line_items.values() if l["invoice_id"] == invoice_id]


def post_line(invoice, line_type, description, quantity, unit_price_cents,
              visit_id=None, applied_addon_id=None, bump_invoice=True):
    rec = {
        "id": new_id(),
        "created_at": now(),
        "_seq": next_seq(),
        "invoice_id": invoice["id"],
        "visit_id": visit_id,
        "line_type": line_type,
        "description": description,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "line_total_cents": quantity * unit_price_cents,
        "applied_addon_id": applied_addon_id,
    }
    line_items[rec["id"]] = rec
    if bump_invoice:
        bump(invoice)
    return rec


def charge_target_invoice(customer_id, when):
    """For charges: covering OPEN invoice, else a new OPEN invoice for the
    calendar-month period containing `when`."""
    inv = find_covering_open_invoice(customer_id, when)
    if inv is not None:
        return inv
    ps, pe = month_period(when)
    return create_invoice(customer_id, ps, pe)


def post_vacation_credit(customer_id, when, credit_cents, description, visit_id):
    """vacation_skip_credit waterfall:
    1. OPEN invoice covering the skipped date -> post there
    2. else create a new OPEN invoice for that period -> post there
    3. else (covering invoice exists but not OPEN) -> next OPEN invoice
    Bound: an invoice that already carries line items never goes negative;
    remainder rolls forward to the next OPEN invoice."""
    target = find_covering_open_invoice(customer_id, when)
    if target is None:
        covering = find_covering_any_invoice(customer_id, when)
        if covering is None:
            ps, pe = month_period(when)
            target = create_invoice(customer_id, ps, pe)
        else:
            nxt = next_open_invoice_after(customer_id, covering["billing_period_start"])
            if nxt is None:
                ps = covering["billing_period_end"]
                pe = month_period(ps + timedelta(days=1))[1]
                nxt = create_invoice(customer_id, ps, pe)
            target = nxt

    remaining = credit_cents
    for _ in range(24):
        lines = invoice_lines(target["id"])
        subtotal = sum(l["line_total_cents"] for l in lines)
        has_charges = any(
            l["line_type"] not in ("VACATION_CREDIT", "SATISFACTION_CREDIT")
            for l in lines
        )
        if not has_charges:
            # Freshly created / credits-only invoice: the line posts in full
            allowance = remaining
        else:
            # No over-credit against real charges; remainder rolls forward
            allowance = max(0, min(remaining, subtotal))
        if allowance > 0:
            post_line(
                target,
                "VACATION_CREDIT",
                description,
                1,
                -allowance,
                visit_id=visit_id,
            )
            remaining -= allowance
        if remaining == 0:
            return
        nxt = next_open_invoice_after(customer_id, target["billing_period_start"])
        if nxt is None:
            ps = target["billing_period_end"]
            pe = month_period(ps + timedelta(days=1))[1]
            nxt = create_invoice(customer_id, ps, pe)
        target = nxt
    if remaining > 0:
        post_line(target, "VACATION_CREDIT", description, 1, -remaining,
                  visit_id=visit_id)


# ---------------------------------------------------------------------------
# satisfaction_rolling_score
# ---------------------------------------------------------------------------
def compute_satisfaction_avg(customer_id):
    reps = [r for r in reports.values() if r["customer_id"] == customer_id]
    if not reps:
        return None
    numerator = Decimal(0)
    denominator = Decimal(0)
    current = now()
    for r in reps:
        days = (current - r["created_at"]).days
        weight = DECAY_PER_DAY ** days
        rating = RESOLVED_RESET_RATING if r["report_status"] == "RESOLVED" else Decimal(r["rating"])
        numerator += rating * weight
        denominator += weight
    if denominator == 0:
        return None
    score = (numerator / denominator).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(score)


def recompute_satisfaction(customer, do_bump=False):
    customer["satisfaction_rolling_avg"] = compute_satisfaction_avg(customer["id"])
    if do_bump:
        bump(customer)


# ---------------------------------------------------------------------------
# visit lifecycle helpers
# ---------------------------------------------------------------------------
def visit_route(visit):
    rid = visit.get("service_route_id")
    return routes.get(rid) if rid else None


def yard_of_subscription(sub):
    return yards.get(sub["yard_id"])


def access_profile_of_yard(yard_id):
    for p in access_profiles.values():
        if p["yard_id"] == yard_id:
            return p
    return None


def finalize_visit_skip(visit, skip_source, subscription, post_credit, credit_line_type):
    visit["status"] = "SKIPPED"
    visit["skip_source"] = skip_source
    visit["final_visit_charge_cents"] = 0
    bump(visit)
    route = visit_route(visit)
    if route is not None:
        recompute_route(route)
        maybe_auto_close_route(route)
    if post_credit and subscription is not None:
        credit = base_per_visit_cents(subscription)
        post_vacation_credit(
            subscription["customer_id"],
            visit["scheduled_date"],
            credit,
            "Vacation skip credit",
            visit["id"],
        )


def cancel_visit_record(visit, skip_source=None):
    visit["status"] = "CANCELLED"
    if skip_source is not None:
        visit["skip_source"] = skip_source
    bump(visit)
    route = visit_route(visit)
    if route is not None:
        recompute_route(route)
        maybe_auto_close_route(route)


def complete_visit_record(visit):
    sub = subscriptions.get(visit["subscription_id"])
    visit["status"] = "COMPLETED"
    visit["completed_at"] = now()
    visit["final_visit_charge_cents"] = (
        per_visit_charge_cents(sub, visit["addon_ids"]) if sub else 0
    )
    customer = customers.get(sub["customer_id"]) if sub else None
    # invoice lines: VISIT_CHARGE (base) + one ADDON_CHARGE per active addon
    if customer is not None:
        inv = charge_target_invoice(customer["id"], visit["scheduled_date"])
        base = base_per_visit_cents(sub)
        post_line(inv, "VISIT_CHARGE", "Visit charge", 1, base,
                  visit_id=visit["id"], bump_invoice=False)
        for aid in _dedupe(visit["addon_ids"] or []):
            a = addons.get(aid)
            if a is not None and a["addon_status"] == "ACTIVE":
                post_line(inv, "ADDON_CHARGE", a["display_name"], 1,
                          a["price_cents_per_visit"], visit_id=visit["id"],
                          applied_addon_id=aid, bump_invoice=False)
        bump(inv)
        visit["invoiced_at"] = now()
    bump(visit)
    if customer is not None:
        customer["lifetime_visits_completed"] += 1
        customer["satisfaction_rolling_avg"] = compute_satisfaction_avg(customer["id"])
        bump(customer)
    route = visit_route(visit)
    if route is not None:
        recompute_route(route)
        maybe_auto_close_route(route)


# ---------------------------------------------------------------------------
# visit sequence generation (activate / resume)
# ---------------------------------------------------------------------------
def _freq_offset(frequency, k):
    if frequency == "WEEKLY":
        return 7 * k
    if frequency == "BIWEEKLY":
        return 14 * k
    if frequency == "TWICE_WEEKLY":
        return (7 * k) // 2
    if frequency == "DAILY":
        return k
    return 7 * k


def generate_visits(subscription):
    plan = plans.get(subscription["plan_id"])
    anchor = subscription.get("next_billing_anchor_date")
    if plan is None or anchor is None:
        return
    start = today_midnight()
    created = []
    k = 0
    while k < 400:
        day = start + timedelta(days=_freq_offset(plan["visit_frequency"], k))
        if day >= anchor:
            break
        created.append(create_visit_record(
            subscription,
            scheduled_date=day,
            window_start=day.replace(hour=8),
            window_end=day.replace(hour=17),
            service_route_id=None,
            addon_ids=[],
        ))
        k += 1
    return created


def create_visit_record(subscription, scheduled_date, window_start, window_end,
                        service_route_id, addon_ids):
    rec = new_record()
    rec.update(
        {
            "subscription_id": subscription["id"],
            "service_route_id": service_route_id,
            "scheduled_date": scheduled_date,
            "scheduled_window_start": window_start,
            "scheduled_window_end": window_end,
            "status": "SCHEDULED",
            "skip_source": None,
            "addon_ids": list(addon_ids or []),
            "tech_safety_ack_at": None,
            "provisional_visit_charge_cents": per_visit_charge_cents(subscription, addon_ids or []),
            "final_visit_charge_cents": None,
            "completed_at": None,
            "invoiced_at": None,
        }
    )
    visits[rec["id"]] = rec
    if service_route_id:
        route = routes.get(service_route_id)
        if route is not None:
            recompute_route(route)
    return rec


# ---------------------------------------------------------------------------
# pending plan changes (effective at the next billing anchor)
# ---------------------------------------------------------------------------
def first_of_next_month(ref):
    base = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if base.month == 12:
        return base.replace(year=base.year + 1, month=1)
    return base.replace(month=base.month + 1)


def apply_pending_plan_changes():
    for sub in subscriptions.values():
        eff = sub.get("plan_change_effective_date")
        if (
            sub.get("pending_plan_change_id")
            and eff is not None
            and eff <= now()
            and sub["status"] != "CANCELLED"
        ):
            new_plan = plans.get(sub["pending_plan_change_id"])
            if new_plan is not None:
                sub["plan_id"] = new_plan["id"]
            sub["pending_plan_change_id"] = None
            sub["plan_change_effective_date"] = None
            if sub["status"] == "ACTIVE":
                yard = yards.get(sub["yard_id"])
                plan = plans.get(sub["plan_id"])
                if yard is not None and plan is not None:
                    sub["monthly_fee_cents_snapshot"] = monthly_fee(plan, yard)
            bump(sub)


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------
def ser_customer(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "phone": c["phone"],
        "account_status": c["account_status"],
        "credit_balance_cents": c["credit_balance_cents"],
        "lifetime_visits_completed": c["lifetime_visits_completed"],
        "satisfaction_rolling_avg": c["satisfaction_rolling_avg"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_yard(y):
    return {
        "id": y["id"],
        "customer_id": y["customer_id"],
        "address_line1": y["address_line1"],
        "city": y["city"],
        "state_code": y["state_code"],
        "postal_code": y["postal_code"],
        "yard_size_sqft": y["yard_size_sqft"],
        "pet_count": y["pet_count"],
        "is_multifamily_common_area": y["is_multifamily_common_area"],
        "hoa_account_code": y["hoa_account_code"],
        "service_region_code": y["service_region_code"],
        "created_at": iso(y["created_at"]),
        "updated_at": iso(y["updated_at"]),
        "version": y["version"],
    }


def ser_access_profile(p):
    return {
        "id": p["id"],
        "yard_id": p["yard_id"],
        "gate_access_code": p["gate_access_code"],
        "gate_instructions": p["gate_instructions"],
        "pet_on_premises": p["pet_on_premises"],
        "pet_aggression_flag": p["pet_aggression_flag"],
        "access_status": p["access_status"],
        "suspension_reason": p["suspension_reason"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_plan(p):
    return {
        "id": p["id"],
        "plan_code": p["plan_code"],
        "display_name": p["display_name"],
        "visit_frequency": p["visit_frequency"],
        "applies_to_multifamily": p["applies_to_multifamily"],
        "base_monthly_fee_cents": p["base_monthly_fee_cents"],
        "yard_tier_thresholds": p["yard_tier_thresholds"],
        "yard_tier_surcharges_cents": p["yard_tier_surcharges_cents"],
        "pet_tier_thresholds": p["pet_tier_thresholds"],
        "pet_tier_surcharges_cents": p["pet_tier_surcharges_cents"],
        "multifamily_multiplier_bp": p["multifamily_multiplier_bp"],
        "plan_status": p["plan_status"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_addon(a):
    return {
        "id": a["id"],
        "addon_code": a["addon_code"],
        "display_name": a["display_name"],
        "price_cents_per_visit": a["price_cents_per_visit"],
        "addon_status": a["addon_status"],
        "created_at": iso(a["created_at"]),
        "updated_at": iso(a["updated_at"]),
        "version": a["version"],
    }


def ser_subscription(s):
    return {
        "id": s["id"],
        "customer_id": s["customer_id"],
        "yard_id": s["yard_id"],
        "plan_id": s["plan_id"],
        "status": s["status"],
        "started_on": iso(s["started_on"]),
        "next_billing_anchor_date": iso(s["next_billing_anchor_date"]),
        "monthly_fee_cents_snapshot": s["monthly_fee_cents_snapshot"],
        "pending_plan_change_id": s["pending_plan_change_id"],
        "plan_change_effective_date": iso(s["plan_change_effective_date"]),
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def ser_route(r):
    return {
        "id": r["id"],
        "route_code": r["route_code"],
        "service_date": iso(r["service_date"]),
        "service_region_code": r["service_region_code"],
        "assigned_technician_id": r["assigned_technician_id"],
        "max_visit_capacity": r["max_visit_capacity"],
        "committed_visit_count": r["committed_visit_count"],
        "route_load_factor_bp": r["route_load_factor_bp"],
        "route_status": r["route_status"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def ser_technician(t):
    return {
        "id": t["id"],
        "full_name": t["full_name"],
        "employee_code": t["employee_code"],
        "certified_for_aggressive_pets": t["certified_for_aggressive_pets"],
        "active": t["active"],
        "created_at": iso(t["created_at"]),
        "updated_at": iso(t["updated_at"]),
        "version": t["version"],
    }


def ser_vacation_window(w):
    return {
        "id": w["id"],
        "subscription_id": w["subscription_id"],
        "start_date": iso(w["start_date"]),
        "end_date": iso(w["end_date"]),
        "skip_reason": w["skip_reason"],
        "window_status": w["window_status"],
        "created_at": iso(w["created_at"]),
        "updated_at": iso(w["updated_at"]),
        "version": w["version"],
    }


def ser_visit(v):
    return {
        "id": v["id"],
        "subscription_id": v["subscription_id"],
        "service_route_id": v["service_route_id"],
        "scheduled_date": iso(v["scheduled_date"]),
        "scheduled_window_start": iso(v["scheduled_window_start"]),
        "scheduled_window_end": iso(v["scheduled_window_end"]),
        "status": v["status"],
        "skip_source": v["skip_source"],
        "addon_ids": v["addon_ids"],
        "tech_safety_ack_at": iso(v["tech_safety_ack_at"]),
        "provisional_visit_charge_cents": v["provisional_visit_charge_cents"],
        "final_visit_charge_cents": v["final_visit_charge_cents"],
        "completed_at": iso(v["completed_at"]),
        "invoiced_at": iso(v["invoiced_at"]),
        "created_at": iso(v["created_at"]),
        "updated_at": iso(v["updated_at"]),
        "version": v["version"],
    }


def ser_invoice(i):
    return {
        "id": i["id"],
        "customer_id": i["customer_id"],
        "billing_period_start": iso(i["billing_period_start"]),
        "billing_period_end": iso(i["billing_period_end"]),
        "invoice_status": i["invoice_status"],
        "subtotal_cents": i["subtotal_cents"],
        "credits_applied_cents": i["credits_applied_cents"],
        "total_due_cents": i["total_due_cents"],
        "finalized_at": iso(i["finalized_at"]),
        "created_at": iso(i["created_at"]),
        "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def ser_line_item(l):
    # InvoiceLineItem carries only id and created_at (no updated_at / version)
    return {
        "id": l["id"],
        "invoice_id": l["invoice_id"],
        "visit_id": l["visit_id"],
        "line_type": l["line_type"],
        "description": l["description"],
        "quantity": l["quantity"],
        "unit_price_cents": l["unit_price_cents"],
        "line_total_cents": l["line_total_cents"],
        "applied_addon_id": l["applied_addon_id"],
        "created_at": iso(l["created_at"]),
    }


def ser_report(r):
    return {
        "id": r["id"],
        "customer_id": r["customer_id"],
        "visit_id": r["visit_id"],
        "rating": r["rating"],
        "issue_category": r["issue_category"],
        "report_status": r["report_status"],
        "resolution_credit_cents": r["resolution_credit_cents"],
        "resolved_at": iso(r["resolved_at"]),
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }
