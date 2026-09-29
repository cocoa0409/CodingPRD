"""Domain logic: ledger recounts, calculations, selectors and cascades."""
from decimal import Decimal

from core import (
    AT_RISK_SLA_FRACTION, COLOR_CONSISTENCY_DRIFT_MAX, MAX_REWORK,
    OVERTIME_MULTIPLIER, RUSH_SLA_FACTOR, SCOPE_RANK, SECONDS_PER_DAY,
    TIER_WEIGHT, VENDOR_HOLD_STRIKES, by_created, ceil_int, cents_half_up, db,
    dec, fail, floor_int, hours_between, now, round_half_up, touch,
    whole_minutes,
)


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def find(table, row_id, error_id):
    if not isinstance(row_id, str):
        fail(error_id)
    row = table.get(row_id)
    if row is None:
        fail(error_id)
    return row


def vendor_of(vendor_id):
    return db.vendors.get(vendor_id)


# --------------------------------------------------------------------------
# Ledger recounts (PRD 2.9 -- always agree with a full recount)
# --------------------------------------------------------------------------
OUTSTANDING_CUSTODY = ("RECEIVED", "IN_STUDIO", "ON_SET", "RETURN_PENDING")


def vendor_outstanding(vendor_id):
    return sum(1 for s in db.samples.values()
               if s["vendor_id"] == vendor_id
               and s["custody_state"] in OUTSTANDING_CUSTODY)


def style_items(style_id):
    return [i for i in db.items.values() if i["style_id"] == style_id]


def style_required_item_count(style_id):
    return sum(1 for i in style_items(style_id)
               if i["required"] and i["item_state"] != "WAIVED")


def item_assets(item_id):
    return [a for a in db.assets.values() if a["shot_list_item_id"] == item_id]


def item_live_asset_count(item_id):
    return sum(1 for a in item_assets(item_id) if a["asset_state"] != "REJECTED")


def style_delivered_asset_count(style_id):
    ids = {i["id"] for i in style_items(style_id)}
    return sum(1 for a in db.assets.values()
               if a["shot_list_item_id"] in ids and a["asset_state"] == "DELIVERED")


def provider_assigned_asset_count(provider_id):
    return sum(1 for t in db.tasks.values()
               if t["provider_id"] == provider_id
               and t["task_state"] in ("QUEUED", "IN_PROGRESS", "SUBMITTED", "REWORK"))


def station_committed_minutes_today(station_id):
    today = now().date()
    return sum(s["planned_minutes"] for s in db.sessions.values()
               if s["station_id"] == station_id
               and s["session_state"] in ("BOOKED", "LOCKED", "SHOOTING", "WRAPPED")
               and s["scheduled_start"].date() == today)


def talent_booked_minutes_today(talent_id):
    today = now().date()
    return sum(b["booked_minutes"] for b in db.bookings.values()
               if b["talent_id"] == talent_id
               and b["booking_state"] in ("HELD", "CONFIRMED")
               and b["call_time"].date() == today)


def session_bookings(session_id):
    return by_created([b for b in db.bookings.values() if b["session_id"] == session_id])


def session_committed_talent_cost(session_id):
    return sum(b["charge_cents"] for b in session_bookings(session_id)
               if b["booking_state"] in ("CONFIRMED", "RELEASED"))


def session_items(session_id):
    return by_created([i for i in db.items.values() if i["session_id"] == session_id])


# --------------------------------------------------------------------------
# ReleaseDocument lazy expiry (PRD 2.4)
# --------------------------------------------------------------------------
def refresh_release(rel):
    if rel["doc_state"] in ("PENDING", "SIGNED") and now() >= rel["valid_until"]:
        rel["doc_state"] = "EXPIRED"
        touch(rel)
    return rel


def refresh_all_releases():
    for rel in db.releases.values():
        refresh_release(rel)


# --------------------------------------------------------------------------
# calculations.talent_booking_charge
# --------------------------------------------------------------------------
def compute_booking_charge(talent, call_time, wrap_time, exclude_booking_id=None):
    booked = whole_minutes(call_time, wrap_time)
    billable = max(booked, talent["minimum_call_hours"] * 60)

    call_date = call_time.date()
    prior = 0
    for b in db.bookings.values():
        if b["talent_id"] != talent["id"]:
            continue
        if exclude_booking_id is not None and b["id"] == exclude_booking_id:
            continue
        if b["booking_state"] not in ("HELD", "CONFIRMED"):
            continue
        if b["call_time"].date() != call_date:
            continue
        prior += b["booked_minutes"]

    remaining_regular = max(0, talent["max_daily_minutes"] - prior)
    regular_minutes = min(billable, remaining_regular)
    overtime_minutes = billable - regular_minutes

    rate = dec(talent["hourly_rate_cents"])
    base_cents = cents_half_up(rate * dec(regular_minutes) / Decimal(60))
    ot_cents = cents_half_up(rate * OVERTIME_MULTIPLIER * dec(overtime_minutes) / Decimal(60))
    uncapped = base_cents + ot_cents

    if overtime_minutes == 0:
        charge = min(uncapped, talent["day_rate_cents"])
    else:
        charge = uncapped

    return {
        "booked_minutes": booked,
        "regular_minutes": regular_minutes,
        "overtime_minutes": overtime_minutes,
        "charge_cents": charge,
    }


# --------------------------------------------------------------------------
# calculations.session_cost_allocation  (waterfall, floor + remainder)
# --------------------------------------------------------------------------
def allocate(total_cents, count):
    """Even share floored, leftover cents one each to the earliest items."""
    per_item = floor_int(dec(total_cents) / dec(count))
    remainder = total_cents - per_item * count
    return [per_item + (1 if i < remainder else 0) for i in range(count)]


def post_session_cost_allocation(session):
    provider = db.providers.get(session["provider_id"])
    rate = dec(provider["station_hour_rate_cents"]) if provider else Decimal(0)
    station_cost = cents_half_up(rate * dec(session["actual_minutes"] or 0) / Decimal(60))
    talent_cost = sum(b["charge_cents"] for b in session_bookings(session["id"])
                      if b["booking_state"] in ("CONFIRMED", "RELEASED"))
    session_total = station_cost + talent_cost

    items = [i for i in session_items(session["id"]) if i["item_state"] == "CAPTURED"]
    if not items:
        return
    shares = allocate(session_total, len(items))
    credited_styles = {}
    for item, share in zip(items, shares):
        item["allocated_cost_cents"] = share
        touch(item)
        credited_styles[item["style_id"]] = credited_styles.get(item["style_id"], 0) + share
    for style_id, amount in credited_styles.items():
        style = db.styles.get(style_id)
        if style is None:
            continue
        style["allocated_cost_cents"] = style.get("allocated_cost_cents", 0) + amount
        touch(style)


# --------------------------------------------------------------------------
# calculations.cost_per_style
# --------------------------------------------------------------------------
def cost_summary(style):
    style_id = style["id"]
    my_items = style_items(style_id)
    my_item_ids = {i["id"] for i in my_items}

    session_ids = {i["session_id"] for i in my_items if i["session_id"]}
    provisional = 0
    for session_id in session_ids:
        session = db.sessions.get(session_id)
        if session is None or session["session_state"] == "CANCELLED":
            continue
        provider = db.providers.get(session["provider_id"])
        rate = dec(provider["station_hour_rate_cents"]) if provider else Decimal(0)
        proj_total = cents_half_up(rate * dec(session["planned_minutes"]) / Decimal(60))
        proj_total += sum(b["charge_cents"] for b in session_bookings(session_id)
                          if b["booking_state"] in ("HELD", "CONFIRMED", "RELEASED"))
        denom_items = [i for i in session_items(session_id)
                       if i["item_state"] in ("ASSIGNED", "CAPTURED")]
        if not denom_items:
            continue
        shares = allocate(proj_total, len(denom_items))
        for item, share in zip(denom_items, shares):
            if item["id"] in my_item_ids:
                provisional += share

    final = style.get("allocated_cost_cents", 0)

    denom_prov = sum(1 for i in my_items if i["item_state"] in ("ASSIGNED", "CAPTURED"))
    denom_final = sum(1 for i in my_items if i["item_state"] == "CAPTURED")
    prov_per_asset = cents_half_up(dec(provisional) / dec(max(1, denom_prov)))
    final_per_asset = cents_half_up(dec(final) / dec(max(1, denom_final)))

    required_count = style_required_item_count(style_id)
    eligible = [p for p in db.providers.values()
                if p["provider_kind"] == "OUTSOURCED"
                and p["capacity_assets_per_day"] >= required_count]
    eligible = sorted(
        eligible,
        key=lambda p: (p["style_quote_cents"], -p["quality_score"],
                       p["created_at"], p["_seq"]),
    )
    if eligible:
        best = eligible[0]
        quote = best["style_quote_cents"]
        provider_id = best["id"]
        variance = final - quote
        recommended = "IN_HOUSE" if final <= quote else "OUTSOURCED"
    else:
        quote = None
        provider_id = None
        variance = None
        recommended = "IN_HOUSE"

    return {
        "style_id": style_id,
        "provisional_cost_cents": provisional,
        "final_cost_cents": final,
        "provisional_cost_per_asset_cents": prov_per_asset,
        "final_cost_per_asset_cents": final_per_asset,
        "outsourced_quote_cents": quote,
        "outsourced_provider_id": provider_id,
        "variance_cents": variance,
        "recommended_source": recommended,
    }


# --------------------------------------------------------------------------
# calculations.retouch_turnaround_hours / retouch_priority_score
# --------------------------------------------------------------------------
def pinned_sla_hours(provider, style):
    base = provider["sla_hours"]
    if style is not None and style.get("priority_tier") == "A":
        return ceil_int(dec(base) * RUSH_SLA_FACTOR)
    return base


def apply_turnaround(task, asset):
    gross = round_half_up(hours_between(asset["created_at"], task["approved_at"]), 2)
    net = round_half_up(gross - dec(task["rework_hours_total"]), 2)
    task["turnaround_hours_gross"] = gross
    task["turnaround_hours_net"] = net
    sla = dec(task["sla_hours"])
    if gross > sla:
        task["sla_state"] = "BREACHED"
    elif gross > AT_RISK_SLA_FRACTION * sla:
        task["sla_state"] = "AT_RISK"
    else:
        task["sla_state"] = "IN_SLA"


def task_style(task):
    asset = db.assets.get(task["asset_id"])
    if asset is None:
        return None
    item = db.items.get(asset["shot_list_item_id"])
    if item is None:
        return None
    return db.styles.get(item["style_id"])


def task_item(task):
    asset = db.assets.get(task["asset_id"])
    if asset is None:
        return None
    return db.items.get(asset["shot_list_item_id"])


def priority_score(task):
    style = task_style(task)
    tier = style.get("priority_tier") if style else "C"
    tier_weight = TIER_WEIGHT.get(tier, Decimal(30))
    age_hours = hours_between(task["created_at"], now())
    urgency = min(Decimal("50.00"), round_half_up(age_hours * Decimal(2), 2))
    rework_penalty = Decimal(15) * Decimal(min(task["rework_count"], MAX_REWORK))
    item = task_item(task)
    scope_bonus = Decimal(20) if (item and item["asset_kind"] == "ON_MODEL") else Decimal(0)
    return round_half_up(tier_weight + urgency - rework_penalty + scope_bonus, 2)


def claim_candidates():
    pool = []
    for task in db.tasks.values():
        if task["task_state"] != "QUEUED":
            continue
        provider = db.providers.get(task["provider_id"])
        if provider is None:
            continue
        if provider_assigned_asset_count(provider["id"]) > provider["capacity_assets_per_day"]:
            continue
        pool.append(task)
    return sorted(
        pool,
        key=lambda t: (-priority_score(t), t["due_at"], t["created_at"], t["_seq"]),
    )


# --------------------------------------------------------------------------
# calculations.color_composite_delta_e
# --------------------------------------------------------------------------
def color_composite(station, patch_deltas):
    values = [dec(v) for v in patch_deltas]
    mean_d = sum(values, Decimal(0)) / dec(len(values))
    max_d = max(values)
    if station["station_type"] == "MODEL":
        composite = round_half_up(Decimal("0.30") * mean_d + Decimal("0.70") * max_d, 2)
    else:
        composite = round_half_up(Decimal("0.50") * mean_d + Decimal("0.50") * max_d, 2)
    return composite


def color_baseline(session):
    candidates = [s for s in db.sessions.values()
                  if s["station_id"] == session["station_id"]
                  and s["id"] != session["id"]
                  and s["color_check_state"] == "PASS"
                  and s["scheduled_start"] < session["scheduled_start"]]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["created_at"], s["_seq"]))
    candidates.sort(key=lambda s: s["scheduled_start"], reverse=True)
    return candidates[0]


# --------------------------------------------------------------------------
# calculations.sample_return_lateness
# --------------------------------------------------------------------------
def return_days_late(due_return_at, returned_at):
    if due_return_at is None:
        return 0
    overdue = int((returned_at - due_return_at).total_seconds())
    if overdue <= 0:
        return 0
    return ceil_int(dec(overdue) / dec(SECONDS_PER_DAY))


def vendor_strike(vendor):
    vendor["late_return_count"] = vendor.get("late_return_count", 0) + 1
    if vendor["late_return_count"] >= VENDOR_HOLD_STRIKES:
        vendor["coordination_hold"] = True
