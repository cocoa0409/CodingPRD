"""Core business services: posture, conservation, forecast, ledgers, cascades.

Implements PRD section 3 workflows and scaffold calculations exactly.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, maintenance_windows, inspection_rounds
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_SAFETY_VIOLATION,
    ERR_BATCH_EXPIRED,
    ERR_CAPACITY_FULL,
    ERR_REFERENCE_INVALID,
)
from helpers import touch
from util import CLOCK, parse_date, round_half_up_2dp, round_half_up_4dp, ceil_int, hours_between

# Program-wide constants (scaffold calculations.constants / PRD section 3)
LOOKBACK_DAYS = 28
GROWTH_FACTOR = Decimal("1.05")
DEFAULT_SEED_SERVINGS = 60
RESCUE_CAP_RATIO = Decimal("0.5")
HANDLING_FEE_CENTS = Decimal("35")
WASTE_ALERT_THRESHOLD = Decimal("0.15")
PENALTY_HOURS = 2.0
MAX_STRIKES = 3
INSPECTION_INTERVAL_DAYS = 90  # program-wide inspection cadence (PRD 3.1 names the constant)
CANCEL_LOCKOUT_HOURS = 24      # program lockout margin (PRD 3.4 names the constant)


# ---------------------------------------------------------------------------
# Equipment posture (PRD 3.1)
# ---------------------------------------------------------------------------

def recompute_posture(site_id):
    site = db["sites"].get(site_id)
    if site is None:
        return
    down = 0
    for a in db["equipment_assets"].values():
        if a["site_id"] == site_id and a["criticality"] == "CRITICAL" and a["status"] != "DECOMMISSIONED":
            if a["status"] in ("DOWN_FOR_REPAIR", "IN_MAINTENANCE"):
                down += 1
    if down == 0:
        new_posture = "OPERATIONAL"
    elif down == 1:
        new_posture = "RESTRICTED"
    else:
        new_posture = "HALTED"
    if site.get("equipment_posture") != new_posture:
        site["equipment_posture"] = new_posture
        touch(site)


# ---------------------------------------------------------------------------
# Batch conservation (PRD 3.3 / calc inventory_conservation)
# ---------------------------------------------------------------------------

def batch_wasted(batch_id):
    """Servings wasted with disposition DISCARD/COMPOST (kitchen waste)."""
    return sum(
        w["servings_wasted"]
        for w in db["waste_logs"].values()
        if w["food_batch_id"] == batch_id and w["disposition"] in ("DISCARD", "COMPOST")
    )


def batch_redirected(batch_id):
    return sum(
        w["servings_wasted"]
        for w in db["waste_logs"].values()
        if w["food_batch_id"] == batch_id and w["disposition"] == "RESCUE_REDIRECT"
    )


def batch_allocated(batch_id):
    return sum(
        a["servings"]
        for a in db["batch_allocations"].values()
        if a["food_batch_id"] == batch_id and not a.get("released")
    )


def recalc_batch_remaining(batch):
    """remaining = quantity - allocated - wasted(DISCARD/COMPOST) - redirected."""
    bid = batch["id"]
    remaining = (
        batch["quantity_servings"]
        - batch_allocated(bid)
        - batch_wasted(bid)
        - batch_redirected(bid)
    )
    batch["remaining_servings"] = max(0, remaining)
    touch(batch)
    check_batch_depleted(batch)


def check_batch_depleted(batch):
    """ACCEPTED -> DEPLETED when remaining hits 0 (system auto-transition)."""
    if batch["status"] == "ACCEPTED" and batch["remaining_servings"] == 0:
        batch["status"] = "DEPLETED"
        touch(batch)


# ---------------------------------------------------------------------------
# MenuDay ledger helpers (PRD 2.9)
# ---------------------------------------------------------------------------

def recompute_overproduction(md):
    sc = md["served_count"]
    if sc > 0:
        md["overproduction_ratio"] = round_half_up_4dp(
            Decimal(md["committed_servings"] - sc) / Decimal(sc)
        )
    else:
        md["overproduction_ratio"] = None


def bump_menu_day(md):
    recompute_overproduction(md)
    touch(md)


# ---------------------------------------------------------------------------
# Production forecast (PRD 3.2 / calc production_forecast)
# ---------------------------------------------------------------------------

def run_production_forecast(md):
    site_id = md["site_id"]
    service_date = parse_date(md["service_date"])
    window_start = service_date - timedelta(days=LOOKBACK_DAYS)
    window_end = service_date - timedelta(days=1)  # inclusive of service_date - 1

    history = []
    for other in db["menu_days"].values():
        if other["site_id"] != site_id or other["status"] != "RECONCILED":
            continue
        d = parse_date(other["service_date"])
        if window_start <= d <= window_end:
            history.append((d, other["served_count"]))

    if not history:
        md["forecast_servings"] = DEFAULT_SEED_SERVINGS
        return

    overall_mean = Decimal(sum(c for _, c in history)) / Decimal(len(history))

    if md.get("forecast_variant", "TRAILING_AVERAGE") == "DOW_WEIGHTED":
        same_dow = sorted(
            ((d, c) for (d, c) in history if d.weekday() == service_date.weekday()),
            key=lambda t: t[0], reverse=True,
        )[:4]
        if same_dow:
            dow_mean = Decimal(sum(c for _, c in same_dow)) / Decimal(len(same_dow))
        else:
            dow_mean = overall_mean
        blend = Decimal("0.6") * dow_mean + Decimal("0.4") * overall_mean
        md["forecast_servings"] = ceil_int(ceil_int(blend) * GROWTH_FACTOR)
    else:
        md["forecast_servings"] = ceil_int(overall_mean * GROWTH_FACTOR)


# ---------------------------------------------------------------------------
# Waste ratio (PRD 3.8 / calc waste_ratio)
# ---------------------------------------------------------------------------

def compute_waste_ratio(menu_day_id):
    wasted = sum(
        w["servings_wasted"]
        for w in db["waste_logs"].values()
        if w["menu_day_id"] == menu_day_id and w["disposition"] in ("DISCARD", "COMPOST")
    )
    md = db["menu_days"][menu_day_id]
    produced = md["committed_servings"]
    if produced == 0:
        return None
    return round_half_up_4dp(Decimal(wasted) / Decimal(produced))


# ---------------------------------------------------------------------------
# Cost per served meal (PRD 3.8 / calc cost_per_served_meal)
# ---------------------------------------------------------------------------

def compute_cost_summary(md):
    """One cost line per CONFIRMED (incl. later-UNAVAILABLE/SOLD_OUT) MenuItem,
    fed by its allocated batches. Per-line round-half-up 2dp, then summed."""
    total = Decimal("0")
    item_ids = [
        i for i in db["menu_items"].values()
        if i["menu_day_id"] == md["id"] and i.get("was_confirmed")
    ]
    for item in item_ids:
        # Aggregate allocated servings per batch for this item; cost line per
        # (item, source-type-of-feeding-batch) uses item.planned_servings.
        batch_ids = {
            a["food_batch_id"]
            for a in db["batch_allocations"].values()
            if a["menu_item_id"] == item["id"]
        }
        # Determine line cost by source type of allocated batches. If multiple
        # source types feed one item, produce one line per batch and sum.
        if not batch_ids:
            continue
        for bid in batch_ids:
            batch = db["food_batches"].get(bid)
            if batch is None:
                continue
            st = batch["source_type"]
            if st == "PURCHASE":
                raw = Decimal(str(batch.get("unit_cost_cents_per_serving") or 0)) * Decimal(item["planned_servings"])
                line = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            elif st == "RESCUE":
                raw = HANDLING_FEE_CENTS * Decimal(item["planned_servings"])
                line = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:  # DONATION
                line = Decimal("0.00")
            total += line
    served = md["served_count"]
    divisor = Decimal(max(1, served))
    per_served = (total / divisor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "total_cost_cents": float(total.quantize(Decimal("0.01"))),
        "cost_per_served_cents": float(per_served),
    }


# ---------------------------------------------------------------------------
# MenuItem transitions and the substitute-or-release cascade (PRD 3.7)
# ---------------------------------------------------------------------------

def item_allergens(item):
    """MenuItem allergen_tags including anything propagated from allocated batches."""
    tags = set(item.get("allergen_tags") or [])
    for a in db["batch_allocations"].values():
        if a["menu_item_id"] == item["id"] and not a.get("released"):
            batch = db["food_batches"].get(a["food_batch_id"])
            if batch:
                tags.update(batch.get("allergen_tags") or [])
    return tags


def item_sold_out_reeval(item):
    """Auto CONFIRMED -> SOLD_OUT when RESERVED+SERVED+DELIVERED count reaches planned."""
    if item["status"] != "CONFIRMED":
        return
    n = sum(
        1 for o in db["meal_orders"].values()
        if o["menu_item_id"] == item["id"]
        and o["fulfillment_status"] in ("RESERVED", "SERVED", "DELIVERED")
    )
    if n >= item["planned_servings"]:
        item["status"] = "SOLD_OUT"
        touch(item)


def _allergen_compatible(item, guest):
    return not (item_allergens(item) & set(guest.get("allergens") or []))


def substitute_or_release_orders(item):
    """For a CONFIRMED -> UNAVAILABLE cascade: orders still RESERVED and not READY
    are substituted (if allowed) to a CONFIRMED allergen-compatible item on the
    same MenuDay, else released."""
    for order in list(db["meal_orders"].values()):
        if order["menu_item_id"] != item["id"]:
            continue
        if order["fulfillment_status"] != "RESERVED":
            continue
        if order["prep_status"] == "READY":
            continue  # orders already READY are left alone to be served
        guest = db["guests"].get(order["guest_id"])
        target = None
        if order.get("substitution_allowed", True) and guest is not None:
            candidates = sorted(
                (
                    i for i in db["menu_items"].values()
                    if i["menu_day_id"] == item["menu_day_id"]
                    and i["id"] != item["id"]
                    and i["status"] == "CONFIRMED"
                    and _allergen_compatible(i, guest)
                ),
                key=lambda i: (i.get("created_at", ""), i.get("id", "")),
            )
            if candidates:
                target = candidates[0]
        if target is not None:
            order["menu_item_id"] = target["id"]
            touch(order)
            item_sold_out_reeval(target)
        else:
            release_order(order, actor="system")


def mark_item_unavailable(item, by_cascade=False):
    """PLANNED|CONFIRMED -> UNAVAILABLE with ledger + order cascade."""
    md = db["menu_days"].get(item["menu_day_id"])
    if item["status"] == "CONFIRMED":
        if md is not None and md["status"] in ("DRAFT", "FORECAST_LOCKED", "IN_PRODUCTION", "SERVING"):
            md["committed_servings"] -= item["planned_servings"]
            bump_menu_day(md)
        item["status"] = "UNAVAILABLE"
        touch(item)
        substitute_or_release_orders(item)
    elif item["status"] == "PLANNED":
        item["status"] = "UNAVAILABLE"
        touch(item)
    else:
        raise_error(ERR_INVALID_STATE, f"item cannot be marked unavailable from {item['status']}")


# ---------------------------------------------------------------------------
# MealOrder helpers (PRD 3.7)
# ---------------------------------------------------------------------------

def release_order(order, actor="system"):
    if order["fulfillment_status"] != "RESERVED":
        raise_error(ERR_INVALID_STATE, f"order cannot be released from {order['fulfillment_status']}")
    order["fulfillment_status"] = "RELEASED"
    touch(order)
    svc = db["meal_services"].get(order["meal_service_id"])
    if svc is not None and svc["reserved_count"] > 0:
        svc["reserved_count"] -= 1
        touch(svc)
    item = db["menu_items"].get(order["menu_item_id"])
    if item is not None:
        item_sold_out_reeval(item)


def expire_order(order):
    if order["fulfillment_status"] != "RESERVED":
        return
    order["fulfillment_status"] = "EXPIRED"
    touch(order)
    svc = db["meal_services"].get(order["meal_service_id"])
    if svc is not None and svc["reserved_count"] > 0:
        svc["reserved_count"] -= 1
        touch(svc)


def fulfill_order(order, new_status):
    """RESERVED -> SERVED | DELIVERED ledger cascade (depth-3)."""
    order["fulfillment_status"] = new_status
    touch(order)
    svc = db["meal_services"].get(order["meal_service_id"])
    if svc is not None and svc["reserved_count"] > 0:
        svc["reserved_count"] -= 1
        touch(svc)
    md = None
    if svc is not None:
        md = db["menu_days"].get(svc["menu_day_id"])
    if md is not None:
        md["served_count"] += order["quantity"]
        bump_menu_day(md)
    guest = db["guests"].get(order["guest_id"])
    if guest is not None:
        guest["visits_count"] += 1
        touch(guest)
    item = db["menu_items"].get(order["menu_item_id"])
    if item is not None:
        item_sold_out_reeval(item)


# ---------------------------------------------------------------------------
# FoodBatch transitions (PRD 3.3)
# ---------------------------------------------------------------------------

def batch_not_expired(batch):
    return CLOCK.now() < batch["_use_by"]


def release_batch_allocations(batch):
    for a in db["batch_allocations"].values():
        if a["food_batch_id"] == batch["id"] and not a.get("released"):
            a["released"] = True


def quarantine_cascade(batch):
    """Depth-3 cascade on inspection FAILED: allocations -> CONFIRMED items
    -> UNAVAILABLE (which cascades to orders and the committed ledger)."""
    item_ids = {
        a["menu_item_id"]
        for a in db["batch_allocations"].values()
        if a["food_batch_id"] == batch["id"] and not a.get("released")
    }
    for iid in item_ids:
        item = db["menu_items"].get(iid)
        if item is not None and item["status"] == "CONFIRMED":
            mark_item_unavailable(item, by_cascade=True)


def safety_discard_exists(batch_id):
    return any(
        w["food_batch_id"] == batch_id and w["reason"] == "SAFETY_DISCARD"
        for w in db["waste_logs"].values()
    )


# ---------------------------------------------------------------------------
# Volunteer / shift helpers (PRD 3.4)
# ---------------------------------------------------------------------------

ROLE_CERT_REQUIREMENT = {
    "PREP": None,
    "COOK": "BASIC",
    "SERVER": None,
    "DRIVER": None,
    "SUPERVISOR_ON_DUTY": "SUPERVISOR",
}
CERT_RANK = {"NONE": 0, "BASIC": 1, "SUPERVISOR": 2}


def certification_valid(volunteer, role_on_shift):
    required = ROLE_CERT_REQUIREMENT.get(role_on_shift)
    if required is None:
        return True
    if CERT_RANK.get(volunteer.get("certification_level", "NONE"), 0) < CERT_RANK[required]:
        return False
    exp = volunteer.get("_certification_expires_at")
    if exp is None:
        return False
    return exp > CLOCK.now()


def shifts_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap."""
    return a_start < b_end and b_start < a_end


def volunteer_has_overlap(volunteer_id, starts_at, ends_at, exclude_shift_id=None):
    for s in db["volunteer_shifts"].values():
        if s["volunteer_id"] != volunteer_id or s["id"] == exclude_shift_id:
            continue
        if s["status"] in ("CANCELLED", "NO_SHOW", "COMPLETED"):
            continue
        if shifts_overlap(starts_at, ends_at, s["_starts_at"], s["_ends_at"]):
            return True
    return False


def apply_strike(volunteer):
    volunteer["strike_count"] += 1
    if volunteer["strike_count"] >= MAX_STRIKES and volunteer["status"] == "ACTIVE":
        suspend_volunteer(volunteer)
    else:
        touch(volunteer)


def suspend_volunteer(volunteer):
    volunteer["status"] = "SUSPENDED"
    touch(volunteer)
    now = CLOCK.now()
    for s in db["volunteer_shifts"].values():
        if s["volunteer_id"] == volunteer["id"] and s["status"] == "SCHEDULED" and s["_starts_at"] >= now:
            s["status"] = "CANCELLED"
            touch(s)


def credit_hours(volunteer, shift):
    hours = hours_between(shift["_starts_at"], shift["_ends_at"])
    volunteer["hours_balance"] = round_half_up_2dp(
        Decimal(str(volunteer.get("hours_balance", 0))) + Decimal(str(hours))
    )
    touch(volunteer)


def apply_penalty(volunteer):
    volunteer["hours_balance"] = round_half_up_2dp(
        max(Decimal("0"), Decimal(str(volunteer.get("hours_balance", 0))) - Decimal(str(PENALTY_HOURS)))
    )
    touch(volunteer)


# ---------------------------------------------------------------------------
# Service window rules (PRD 3.6)
# ---------------------------------------------------------------------------

def service_window_conflict(site_id, service_model, w_start, w_end, exclude_id=None):
    """Same site+model half-open overlap; DINE_IN keeps a 30-min buffer against TO_GO."""
    buffer = timedelta(minutes=30)
    for s in db["meal_services"].values():
        if s["site_id"] != site_id or s["id"] == exclude_id:
            continue
        if s["status"] in ("CLOSED", "ABORTED"):
            continue
        if s["service_model"] == service_model:
            if shifts_overlap(w_start, w_end, s["_window_start"], s["_window_end"]):
                return True
        # DINE_IN vs TO_GO buffer: no TO_GO window may start within 30 minutes
        # before or after the DINE_IN window.
        pair = {service_model, s["service_model"]}
        if pair == {"DINE_IN", "TO_GO"}:
            dine = (w_start, w_end) if service_model == "DINE_IN" else (s["_window_start"], s["_window_end"])
            togo_start = s["_window_start"] if service_model == "DINE_IN" else w_start
            if dine[0] - buffer <= togo_start <= dine[1] + buffer:
                return True
    return False
