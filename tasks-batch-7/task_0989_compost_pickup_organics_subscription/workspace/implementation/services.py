"""Business logic: serializers, ledger, state transitions, calculations."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import db
from db import new_entity, store, touch
from errors import (ApiError, ERR_INSUFFICIENT_STOCK, ERR_INVALID_WEIGHT,
                    ERR_NO_BIN_AVAILABLE, ERR_PICKUP_LOCKED_BY_WEIGH_TICKET,
                    ERR_WEIGH_TICKET_PENDING, conflict, unprocessable)
from utils import (D, money, num_out, quarter_label, r2, season_label,
                   season_of, SEASON_MULTIPLIERS)

# ---------------------------------------------------------------------------
# Constants (scaffold calculations)
# ---------------------------------------------------------------------------
SKIP_CUTOFF_HOURS = 48
STRIKE_SUSPENSION_THRESHOLD = 3
SURCHARGE_BASE = {"LOW": 500, "MEDIUM": 1000, "HIGH": 1500}
SURCHARGE_TYPE_MULT = {"RESIDENTIAL": Decimal("1.0"), "COMMERCIAL": Decimal("2.0")}
ESCALATOR_STEP = Decimal("0.5")
INVOICE_DUE_DAYS = 14
COMPOST_YIELD = Decimal("0.3")
BAG_KG = 10
BAG_PRICE_CENTS = 500
CO2E_PER_KG = Decimal("0.5")

SUBSCRIBER_TYPES = {"RESIDENTIAL", "COMMERCIAL"}
BIN_TYPES = {"BIN_35L", "BIN_70L", "BIN_240L", "BIN_960L"}
WEEKDAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
CATEGORIES = {"PLASTIC", "GLASS", "METAL", "LIQUIDS", "OTHER"}


# ---------------------------------------------------------------------------
# Serializers (strip internal "_" keys; Decimal -> float for kg numbers)
# ---------------------------------------------------------------------------
def ser_plan(p):
    return {
        "id": p["id"], "code": p["code"], "name": p["name"],
        "subscriber_type": p["subscriber_type"], "bin_type": p["bin_type"],
        "included_bins": p["included_bins"],
        "weekly_price_cents": p["weekly_price_cents"],
        "metered_base_cents": p["metered_base_cents"],
        "per_kg_rate_cents": p["per_kg_rate_cents"],
        "included_kg_per_week": num_out(p["included_kg_per_week"]),
        "credit_rate_cents_per_kg": p["credit_rate_cents_per_kg"],
        "skip_allowance_per_quarter": p["skip_allowance_per_quarter"],
        "created_at": p["created_at"],
    }


def ser_subscriber(s):
    return {
        "id": s["id"], "email": s["email"], "full_name": s["full_name"],
        "subscriber_type": s["subscriber_type"], "address": s["address"],
        "account_standing": account_standing(s["id"]),
        "credit_balance_cents": s["credit_balance_cents"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_subscription(s):
    return {
        "id": s["id"], "subscriber_id": s["subscriber_id"],
        "plan_id": s["plan_id"], "route_id": s["route_id"],
        "start_date": s["start_date"], "service_status": s["service_status"],
        "strike_count": s["strike_count"],
        "skips_used_this_quarter": s["skips_used_this_quarter"],
        "current_quarter": s["current_quarter"],
        "pause_windows": [dict(w) for w in s["pause_windows"]],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_route(r):
    return {
        "id": r["id"], "code": r["code"], "weekday": r["weekday"],
        "max_stops": r["max_stops"],
        "active_subscriptions_count": active_subscriptions_count(r["id"]),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_bin(b):
    return {
        "id": b["id"], "bin_type": b["bin_type"],
        "nominal_capacity_kg": num_out(b["nominal_capacity_kg"]),
        "status": b["status"], "condition": b["condition"],
        "current_subscription_id": b["current_subscription_id"],
        "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_pickup(p):
    return {
        "id": p["id"], "subscription_id": p["subscription_id"],
        "route_id": p["route_id"], "service_date": p["service_date"],
        "status": p["status"],
        "fullness_pct": num_out(p["fullness_pct"]),
        "estimated_kg": num_out(p["estimated_kg"]),
        "final_kg": num_out(p["final_kg"]),
        "collected_bin_id": p["collected_bin_id"],
        "replacement_bin_id": p["replacement_bin_id"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_tag(t):
    return {
        "id": t["id"], "pickup_id": t["pickup_id"],
        "subscription_id": t["subscription_id"], "severity": t["severity"],
        "category": t["category"], "note": t["note"],
        "tagged_by_driver_id": t["tagged_by_driver_id"],
        "status": t["status"], "surcharge_cents": t["surcharge_cents"],
        "resolved_by": t["resolved_by"], "resolved_at": t["resolved_at"],
        "created_at": t["created_at"], "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_weigh_ticket(w):
    return {
        "id": w["id"], "route_id": w["route_id"],
        "service_date": w["service_date"],
        "gross_kg": num_out(w["gross_kg"]), "tare_kg": num_out(w["tare_kg"]),
        "net_kg": num_out(w["net_kg"]), "status": w["status"],
        "created_at": w["created_at"], "updated_at": w["updated_at"],
        "version": w["version"],
    }


def ser_entry(e):
    return {
        "id": e["id"], "subscriber_id": e["subscriber_id"],
        "pickup_id": e["pickup_id"], "redemption_id": e["redemption_id"],
        "invoice_id": e["invoice_id"], "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"], "reason": e["reason"],
        "season": e["season"], "created_at": e["created_at"],
    }


def ser_redemption(r):
    return {
        "id": r["id"], "subscriber_id": r["subscriber_id"],
        "bags": r["bags"], "total_kg": num_out(r["total_kg"]),
        "total_cents": r["total_cents"], "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_invoice(i):
    return {
        "id": i["id"], "subscriber_id": i["subscriber_id"],
        "week_start_date": i["week_start_date"],
        "lines": [dict(l) for l in i["lines"]],
        "subtotal_cents": i["subtotal_cents"],
        "credit_applied_cents": i["credit_applied_cents"],
        "total_cents": i["total_cents"], "status": i["status"],
        "due_date": i["due_date"],
        "created_at": i["created_at"], "updated_at": i["updated_at"],
        "version": i["version"],
    }


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def by_seq(items):
    return sorted(items, key=lambda e: e["_seq"])


def active_subscriptions_count(route_id):
    return sum(1 for s in store["subscriptions"].values()
               if s["route_id"] == route_id and s["service_status"] == "ACTIVE")


def subscription_of(pickup):
    return store["subscriptions"][pickup["subscription_id"]]


def plan_of(subscription):
    return store["service_plans"][subscription["plan_id"]]


def subscriber_of(subscription):
    return store["subscribers"][subscription["subscriber_id"]]


def account_standing(subscriber_id):
    """Derived on read (calculations.account_standing): DELINQUENT if any
    ISSUED invoice has due_date earlier than the current logical date."""
    today = db.logical_now().date()
    for inv in store["invoices"].values():
        if (inv["subscriber_id"] == subscriber_id and inv["status"] == "ISSUED"
                and date.fromisoformat(inv["due_date"]) < today):
            return "DELINQUENT"
    return "GOOD_STANDING"


def weigh_ticket_exists(route_id, service_date):
    return any(w["route_id"] == route_id and w["service_date"] == service_date
               for w in store["weigh_tickets"].values())


def assigned_bins(subscription_id):
    return by_seq([b for b in store["bins"].values()
                   if b["current_subscription_id"] == subscription_id])


def select_depot_bins(bin_type, count):
    cands = by_seq([b for b in store["bins"].values()
                    if b["bin_type"] == bin_type and b["status"] == "IN_DEPOT"
                    and b["condition"] == "CLEAN"])
    return cands[:count] if len(cands) >= count else None


# ---------------------------------------------------------------------------
# Credit ledger (PRD 2.6)
# ---------------------------------------------------------------------------
def post_entry(subscriber_id, entry_type, amount_cents, season,
               pickup_id=None, redemption_id=None, invoice_id=None,
               reason=None):
    e = new_entity(common=False)
    e.update({
        "subscriber_id": subscriber_id, "pickup_id": pickup_id,
        "redemption_id": redemption_id, "invoice_id": invoice_id,
        "entry_type": entry_type, "amount_cents": int(amount_cents),
        "reason": reason, "season": season,
    })
    store["credit_entries"][e["id"]] = e
    sub = store["subscribers"][subscriber_id]
    sub["credit_balance_cents"] += int(amount_cents)
    touch(sub)
    return e


# ---------------------------------------------------------------------------
# Bin transitions (parallel dimensions: status x condition)
# ---------------------------------------------------------------------------
def send_bin_to_customer(b, subscription_id):
    b["status"] = "AT_CUSTOMER"
    b["current_subscription_id"] = subscription_id
    touch(b)


def return_bin_to_depot(b):
    b["status"] = "IN_DEPOT"
    b["condition"] = "NEEDS_WASH"
    b["current_subscription_id"] = None
    touch(b)


def cancel_scheduled_pickups(subscription_id, window=None):
    """SCHEDULED pickups of the subscription -> CANCELLED_SYSTEM. When
    `window` is given as (start_date, end_date), only pickups whose
    service_date falls in the half-open window are cancelled."""
    for p in by_seq(store["pickups"].values()):
        if p["subscription_id"] != subscription_id or p["status"] != "SCHEDULED":
            continue
        if window is not None:
            sd = date.fromisoformat(p["service_date"])
            if not (window[0] <= sd < window[1]):
                continue
        p["status"] = "CANCELLED_SYSTEM"
        touch(p)


# ---------------------------------------------------------------------------
# Pickup completion (swap + estimated credit, atomic)
# ---------------------------------------------------------------------------
def complete_pickup(p, fullness_pct):
    sub = subscription_of(p)
    plan = plan_of(sub)
    replacement = select_depot_bins(plan["bin_type"], 1)
    if replacement is None:
        unprocessable(ERR_NO_BIN_AVAILABLE,
                      "No clean depot bin of the plan's bin_type for swap")
    replacement = replacement[0]
    current = assigned_bins(sub["id"])
    if not current:
        unprocessable(ERR_NO_BIN_AVAILABLE,
                      "Subscription has no bin assigned to collect")
    collected = current[0]

    est_kg = r2(D(collected["nominal_capacity_kg"]) * D(fullness_pct))
    season = season_label(date.fromisoformat(p["service_date"]))
    credit = money(est_kg * D(plan["credit_rate_cents_per_kg"])
                   * SEASON_MULTIPLIERS[season_of(date.fromisoformat(p["service_date"]))])

    p["status"] = "COMPLETED"
    p["fullness_pct"] = D(fullness_pct)
    p["estimated_kg"] = est_kg
    p["collected_bin_id"] = collected["id"]
    p["replacement_bin_id"] = replacement["id"]
    p["_earned_cents"] = credit
    touch(p)
    return_bin_to_depot(collected)
    send_bin_to_customer(replacement, sub["id"])
    post_entry(sub["subscriber_id"], "EARNED_ESTIMATED", credit, season,
               pickup_id=p["id"])
    return p


def void_pickup(p):
    sub = subscription_of(p)
    if weigh_ticket_exists(p["route_id"], p["service_date"]):
        conflict(ERR_PICKUP_LOCKED_BY_WEIGH_TICKET,
                 "A weigh ticket is already posted for this route and date")
    earned = p.get("_earned_cents", 0)
    if p.get("_forfeited"):
        # Credit already reversed by a facility tag; voiding must not
        # double-reverse (complete+void nets balance to zero drift).
        p["_forfeited"] = 0
    elif earned:
        season = season_label(db.logical_now().date())
        post_entry(sub["subscriber_id"], "REVERSAL", -earned, season,
                   pickup_id=p["id"])
    p["status"] = "VOIDED"
    touch(p)
    return p


def forfeit_pickup_credit(p):
    """Facility-discovery tag on a COMPLETED pickup: reverse the earned
    estimated credit; pickup keeps COMPLETED status."""
    earned = p.get("_earned_cents", 0)
    if earned:
        sub = subscription_of(p)
        season = season_label(db.logical_now().date())
        post_entry(sub["subscriber_id"], "REVERSAL", -earned, season,
                   pickup_id=p["id"])
        p["_forfeited"] = earned


# ---------------------------------------------------------------------------
# Contamination surcharge + strike cascade
# ---------------------------------------------------------------------------
def confirm_tag(t, resolver_id):
    p = store["pickups"][t["pickup_id"]]
    sub = subscription_of(p)
    subscriber = subscriber_of(sub)
    strikes_before = sub["strike_count"]
    surcharge = money(
        Decimal(SURCHARGE_BASE[t["severity"]])
        * SURCHARGE_TYPE_MULT[subscriber["subscriber_type"]]
        * (Decimal("1") + ESCALATOR_STEP * min(strikes_before, 3)))
    now = db.logical_now()
    t["surcharge_cents"] = surcharge
    t["status"] = "CONFIRMED"
    t["resolved_at"] = db.fmt_ts(now)
    t["resolved_by"] = resolver_id
    touch(t)
    sub["strike_count"] = strikes_before + 1
    touch(sub)
    if sub["strike_count"] >= STRIKE_SUSPENSION_THRESHOLD \
            and sub["service_status"] == "ACTIVE":
        sub["service_status"] = "SUSPENDED"
        touch(sub)
        cancel_scheduled_pickups(sub["id"])
    return t


def waive_tag(t, resolver_id):
    p = store["pickups"][t["pickup_id"]]
    now = db.logical_now()
    t["status"] = "WAIVED"
    t["resolved_at"] = db.fmt_ts(now)
    t["resolved_by"] = resolver_id
    touch(t)
    if p["status"] == "REJECTED_CONTAMINATION":
        p["status"] = "SCHEDULED"  # make-up attempt; late completion allowed
        touch(p)
    forfeited = p.get("_forfeited", 0)
    if forfeited:
        sub = subscription_of(p)
        post_entry(sub["subscriber_id"], "MANUAL_ADJUSTMENT", forfeited,
                   season_label(db.logical_now().date()), pickup_id=p["id"],
                   reason="TAG_WAIVED_CREDIT_RESTORE")
        p["_forfeited"] = 0
    return t


# ---------------------------------------------------------------------------
# Weigh ticket allocation (calculations.weighed_allocation)
# ---------------------------------------------------------------------------
def post_weigh_ticket(route, service_date_str, gross_kg, tare_kg):
    for w in store["weigh_tickets"].values():
        if w["route_id"] == route["id"] and w["service_date"] == service_date_str:
            raise ApiError("ERR_DUPLICATE_WEIGH_TICKET", 409,
                           "Weigh ticket already posted for this route and date")
    net = r2(D(gross_kg) - D(tare_kg))
    if net <= 0:
        unprocessable(ERR_INVALID_WEIGHT, "net_kg must be greater than zero")
    sd = date.fromisoformat(service_date_str)
    included = [p for p in by_seq(store["pickups"].values())
                if p["route_id"] == route["id"]
                and p["service_date"] == service_date_str
                and p["status"] == "COMPLETED"
                and p["estimated_kg"] is not None and p["estimated_kg"] > 0]
    if not included:
        unprocessable(ERR_INVALID_WEIGHT,
                      "No COMPLETED pickup with estimated_kg > 0 to allocate")
    S = sum((p["estimated_kg"] for p in included), Decimal("0"))
    finals = {p["id"]: r2(net * p["estimated_kg"] / S) for p in included}
    remainder = r2(net - sum(finals.values(), Decimal("0")))
    if remainder != 0:
        # Largest estimated_kg; tie-break earliest pickup created_at.
        target = max(included,
                     key=lambda p: (p["estimated_kg"], -p["_seq"]))
        finals[target["id"]] = r2(finals[target["id"]] + remainder)
    for p in included:
        p["final_kg"] = finals[p["id"]]
        touch(p)
    for p in included:
        sub = subscription_of(p)
        plan = plan_of(sub)
        final_credit = money(finals[p["id"]]
                             * D(plan["credit_rate_cents_per_kg"])
                             * SEASON_MULTIPLIERS[season_of(sd)])
        delta = final_credit - p.get("_earned_cents", 0)
        if delta != 0:
            post_entry(sub["subscriber_id"], "EARNED_FINAL_ADJUSTMENT",
                       delta, season_label(sd), pickup_id=p["id"])
    w = new_entity(common=True)
    w.update({
        "route_id": route["id"], "service_date": service_date_str,
        "gross_kg": D(gross_kg), "tare_kg": D(tare_kg), "net_kg": net,
        "status": "POSTED",
    })
    store["weigh_tickets"][w["id"]] = w
    return w


# ---------------------------------------------------------------------------
# Compost stock (calculations.compost_stock)
# ---------------------------------------------------------------------------
def compute_stock():
    produced = r2(COMPOST_YIELD * sum(
        (p["final_kg"] for p in store["pickups"].values()
         if p["final_kg"] is not None), Decimal("0")))
    redeemed = sum((r["total_kg"] for r in store["redemptions"].values()
                    if r["status"] == "FULFILLED"), Decimal("0"))
    reserved = sum((r["total_kg"] for r in store["redemptions"].values()
                    if r["status"] == "REQUESTED"), Decimal("0"))
    available = produced - redeemed - reserved
    return {
        "produced_kg": num_out(produced),
        "redeemed_kg": num_out(redeemed),
        "reserved_kg": num_out(reserved),
        "available_kg": num_out(available),
    }


def check_stock(total_kg):
    stock = compute_stock()
    if D(total_kg) > D(stock["available_kg"]):
        unprocessable(ERR_INSUFFICIENT_STOCK,
                      "Requested total_kg exceeds available compost stock")


# ---------------------------------------------------------------------------
# Impact report (calculations.impact_report)
# ---------------------------------------------------------------------------
def impact_report(subscriber_id):
    total = Decimal("0")
    count = 0
    for s in store["subscriptions"].values():
        if s["subscriber_id"] != subscriber_id:
            continue
        for p in store["pickups"].values():
            if p["subscription_id"] == s["id"] and p["status"] == "COMPLETED":
                kg = p["final_kg"] if p["final_kg"] is not None else p["estimated_kg"]
                total += D(kg)
                count += 1
    total_kg_diverted = r2(total)
    total_co2e_kg = r2(total_kg_diverted * CO2E_PER_KG)
    confirmed = 0
    for t in store["tags"].values():
        if t["status"] != "CONFIRMED":
            continue
        sub = store["subscriptions"].get(t["subscription_id"])
        if sub and sub["subscriber_id"] == subscriber_id:
            confirmed += 1
    return {
        "total_kg_diverted": num_out(total_kg_diverted),
        "total_co2e_kg": num_out(total_co2e_kg),
        "pickups_completed": count,
        "contamination_tags_confirmed": confirmed,
    }


# ---------------------------------------------------------------------------
# Weekly billing run (calculations.weekly_invoice_amount +
# credit_application_order)
# ---------------------------------------------------------------------------
def run_billing(week_start):
    week_end = week_start + timedelta(days=7)

    def in_week(d):
        return week_start <= d < week_end

    # Gate: every COMPLETED commercial pickup in the week needs a weigh
    # ticket for its (route_id, service_date); abort the whole run.
    for p in store["pickups"].values():
        if p["status"] != "COMPLETED":
            continue
        if not in_week(date.fromisoformat(p["service_date"])):
            continue
        sub = subscription_of(p)
        plan = plan_of(sub)
        if plan["subscriber_type"] == "COMMERCIAL" and not weigh_ticket_exists(
                p["route_id"], p["service_date"]):
            unprocessable(ERR_WEIGH_TICKET_PENDING,
                          "A COMPLETED commercial pickup lacks a weigh ticket")

    week_start_str = week_start.isoformat()
    issued_ids = []
    skipped_ids = []
    for subscriber in by_seq(store["subscribers"].values()):
        sid = subscriber["id"]
        existing = any(i["subscriber_id"] == sid
                       and i["week_start_date"] == week_start_str
                       for i in store["invoices"].values())

        lines = []
        for sub in by_seq([s for s in store["subscriptions"].values()
                           if s["subscriber_id"] == sid]):
            plan = plan_of(sub)
            for p in by_seq([pp for pp in store["pickups"].values()
                             if pp["subscription_id"] == sub["id"]]):
                if not in_week(date.fromisoformat(p["service_date"])):
                    continue
                if plan["subscriber_type"] == "RESIDENTIAL":
                    if p["status"] in ("COMPLETED", "REJECTED_CONTAMINATION"):
                        lines.append({
                            "line_type": "WEEKLY_FLAT",
                            "reference_id": p["id"],
                            "amount_cents": plan["weekly_price_cents"],
                        })
                else:
                    if p["status"] == "COMPLETED":
                        lines.append({
                            "line_type": "METERED_BASE",
                            "reference_id": p["id"],
                            "amount_cents": plan["metered_base_cents"],
                        })
                        fk = p["final_kg"]
                        if fk is not None and fk > D(plan["included_kg_per_week"]):
                            over = money(D(plan["per_kg_rate_cents"])
                                         * (fk - D(plan["included_kg_per_week"])))
                            lines.append({
                                "line_type": "OVERAGE_KG",
                                "reference_id": p["id"],
                                "amount_cents": over,
                            })
                    elif p["status"] == "REJECTED_CONTAMINATION":
                        lines.append({
                            "line_type": "METERED_BASE",
                            "reference_id": p["id"],
                            "amount_cents": plan["metered_base_cents"],
                        })
        for t in by_seq(store["tags"].values()):
            if t["status"] != "CONFIRMED":
                continue
            sub = store["subscriptions"].get(t["subscription_id"])
            if not sub or sub["subscriber_id"] != sid:
                continue
            resolved = datetime.fromisoformat(
                t["resolved_at"].replace("Z", "+00:00"))
            rst = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
            rend = datetime.combine(week_end, time.min, tzinfo=timezone.utc)
            if rst <= resolved < rend:
                lines.append({
                    "line_type": "CONTAMINATION_SURCHARGE",
                    "reference_id": t["id"],
                    "amount_cents": t["surcharge_cents"],
                })

        if existing:
            if lines or True:
                skipped_ids.append(sid)
            continue
        if not lines:
            continue
        subtotal = sum(l["amount_cents"] for l in lines)
        if subtotal == 0:
            continue
        credit_applied = min(subscriber["credit_balance_cents"], subtotal // 2)
        total = subtotal - credit_applied
        inv = new_entity(common=True)
        inv.update({
            "subscriber_id": sid, "week_start_date": week_start_str,
            "lines": lines, "subtotal_cents": subtotal,
            "credit_applied_cents": credit_applied, "total_cents": total,
            "status": "ISSUED",
            "due_date": (week_start + timedelta(days=INVOICE_DUE_DAYS)).isoformat(),
        })
        store["invoices"][inv["id"]] = inv
        if credit_applied > 0:
            post_entry(sid, "INVOICE_APPLICATION_DEBIT", -credit_applied,
                       season_label(db.logical_now().date()),
                       invoice_id=inv["id"])
        issued_ids.append(inv["id"])

    return {
        "issued_count": len(issued_ids),
        "invoice_ids": issued_ids,
        "skipped_subscriber_ids": skipped_ids,
    }
