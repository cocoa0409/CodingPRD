"""Domain calculations, cascades and sweeps.

Every rule here traces to a paragraph of PRD.md section 2 or 3.
"""

import datetime
from decimal import Decimal

from core import (
    BAKERY_PREP_MINUTES,
    CATERING_FEE_BP,
    CATERING_MIN_FEE_CENTS,
    ELITE_THRESHOLD,
    FUEL_COMBO_BONUS_POINTS,
    FUEL_LOOKBACK_DAYS,
    GRAB_TXNS_PER_LABOR_HOUR,
    MIN_DAYPART_MINUTES,
    MODIFIER_PREP_SECONDS,
    MTO_TXNS_PER_LABOR_HOUR,
    PEAK_MULTIPLIER_BP,
    PEAK_TXN_THRESHOLD,
    PLUS_THRESHOLD,
    PREMIUM_SURCHARGE_CENTS,
    READY_COMPLIANCE_PCT,
    NOT_READY_COMPLIANCE_PCT,
    SANITATION_BUFFER_MINUTES,
    STATION_SEQUENCE,
    TEMP_LOG_WINDOW_MINUTES,
    TIER_MULTIPLIER_BP,
    base_record,
    ceil_div,
    db,
    gallons_q,
    plus_minutes,
    plus_seconds,
    round_half_up,
    sort_created,
    touch,
)
from errors import ApiError


# ---------------------------------------------------------------------------
# path / foreign-key resolution (PRD 2.7 steps 4 and 5)
# ---------------------------------------------------------------------------
def find_store(store_id):
    rec = db.stores.get(store_id)
    if rec is None:
        raise ApiError("ERR_STORE_NOT_FOUND")
    return rec


def find_holding_unit(unit_id):
    rec = db.holding_units.get(unit_id)
    if rec is None:
        raise ApiError("ERR_HOLDING_UNIT_NOT_FOUND")
    return rec


def find_menu_item(item_id):
    rec = db.menu_items.get(item_id)
    if rec is None:
        raise ApiError("ERR_MENU_ITEM_NOT_FOUND")
    return rec


def find_modifier_option(option_id):
    rec = db.modifier_options.get(option_id)
    if rec is None:
        raise ApiError("ERR_MODIFIER_OPTION_NOT_FOUND")
    return rec


def find_promotion_rule(rule_id):
    rec = db.promotion_rules.get(rule_id)
    if rec is None:
        raise ApiError("ERR_PROMOTION_RULE_NOT_FOUND")
    return rec


def find_loyalty_account(account_id):
    rec = db.loyalty_accounts.get(account_id)
    if rec is None:
        raise ApiError("ERR_LOYALTY_ACCOUNT_NOT_FOUND")
    return rec


def find_staffing_plan(plan_id):
    rec = db.staffing_plans.get(plan_id)
    if rec is None:
        raise ApiError("ERR_STAFFING_PLAN_NOT_FOUND")
    return rec


def find_production_batch(batch_id):
    rec = db.production_batches.get(batch_id)
    if rec is None:
        raise ApiError("ERR_PRODUCTION_BATCH_NOT_FOUND")
    return rec


def find_temperature_log(log_id):
    rec = db.temperature_logs.get(log_id)
    if rec is None:
        raise ApiError("ERR_TEMPERATURE_LOG_NOT_FOUND")
    return rec


def find_corrective_action(action_id):
    rec = db.corrective_actions.get(action_id)
    if rec is None:
        raise ApiError("ERR_CORRECTIVE_ACTION_NOT_FOUND")
    return rec


def find_order(order_id):
    rec = db.orders.get(order_id)
    if rec is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")
    return rec


def find_order_line_of(order, line_id):
    """A line that exists but belongs to another order is unresolved (PRD 2.7.4)."""
    rec = db.order_lines.get(line_id)
    if rec is None or rec["order_id"] != order["id"]:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND")
    return rec


def find_order_line(line_id):
    rec = db.order_lines.get(line_id)
    if rec is None:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND")
    return rec


def find_kitchen_ticket(ticket_id):
    rec = db.kitchen_tickets.get(ticket_id)
    if rec is None:
        raise ApiError("ERR_KITCHEN_TICKET_NOT_FOUND")
    return rec


def order_lines_of(order_id):
    return sort_created([l for l in db.order_lines.values() if l["order_id"] == order_id])


def tickets_of_order(order_id):
    return sort_created([t for t in db.kitchen_tickets.values() if t["order_id"] == order_id])


# ---------------------------------------------------------------------------
# line_gross_pricing (PRD 3.7)
# ---------------------------------------------------------------------------
def price_line(item, qty, modifier_entries):
    """modifier_entries: list of {modifier_option_id, qty, _option}."""
    unit_price = item["base_price_cents"]
    premium_units = 0
    for entry in modifier_entries:
        option = entry["_option"]
        unit_price += option["price_delta_cents"] * entry["qty"]
        if option["is_premium"]:
            premium_units += entry["qty"]
    surcharge = PREMIUM_SURCHARGE_CENTS * max(
        0, premium_units - item["included_premium_count"]
    )
    line_gross = (unit_price + surcharge) * qty
    return unit_price, surcharge, line_gross


def recompute_order_subtotal(order):
    order["subtotal_gross_cents"] = sum(
        l["line_gross_cents"] for l in order_lines_of(order["id"])
    )


# ---------------------------------------------------------------------------
# loyalty_tier_derivation (PRD 3.2)
# ---------------------------------------------------------------------------
def derive_tier(lifetime_points_earned):
    if lifetime_points_earned >= ELITE_THRESHOLD:
        return "ELITE"
    if lifetime_points_earned >= PLUS_THRESHOLD:
        return "PLUS"
    return "BASIC"


def points_from_basis(basis_cents, tier):
    """Truncate toward zero: basis * multiplier_bp // 1_000_000."""
    multiplier = TIER_MULTIPLIER_BP[tier]
    product = basis_cents * multiplier
    if product < 0:
        return -((-product) // 1000000)
    return product // 1000000


# ---------------------------------------------------------------------------
# fuel_gallons_30d (PRD 3.2)
# ---------------------------------------------------------------------------
def fuel_gallons_30d(account_id):
    window_start = db.clock - datetime.timedelta(days=FUEL_LOOKBACK_DAYS)
    total = Decimal("0.000")
    for txn in db.fuel_transactions.values():
        if txn["loyalty_account_id"] != account_id:
            continue
        occurred = txn["occurred_at"]
        if window_start <= occurred <= db.clock:
            total += txn["gallons"]
    return gallons_q(total)


# ---------------------------------------------------------------------------
# waste_valuation (PRD 3.5) and waste-log append
# ---------------------------------------------------------------------------
def waste_valuation(item, qty):
    return qty * item["unit_food_cost_cents"], qty * item["base_price_cents"]


def append_waste_log(batch, item, qty, reason, logged_by_user_id, store):
    food_cost, retail = waste_valuation(item, qty)
    rec = base_record(versioned=False)
    rec.update({
        "production_batch_id": batch["id"],
        "qty": qty,
        "reason": reason,
        "food_cost_cents": food_cost,
        "retail_value_cents": retail,
        "logged_by_user_id": logged_by_user_id,
        "daypart_epoch": store["daypart_epoch"],
    })
    db.waste_logs[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# sweeps (PRD 3.5 daypart transition, PRD 3.6 impairment)
# ---------------------------------------------------------------------------
def _sweep_order(batches):
    """Deterministic sweep order: bake_start_at ASC, then created_at ASC."""
    return sorted(batches, key=lambda b: (b["bake_start_at"], b["created_at"], b["_seq"]))


def impairment_sweep(unit, store):
    """Write off the unreserved stock of a unit whose posture just escalated."""
    batches = [
        b for b in db.production_batches.values()
        if b["holding_unit_id"] == unit["id"] and b["status"] == "HOLDING"
    ]
    for batch in _sweep_order(batches):
        item = db.menu_items[batch["menu_item_id"]]
        qty = batch["remaining_qty"]
        if batch["reserved_qty"] > 0:
            # keeps HOLDING and keeps its slot; only the unreserved units go
            if qty <= 0:
                continue
            batch["discarded_qty"] += qty
            batch["remaining_qty"] = 0
            log = append_waste_log(batch, item, qty, "UNIT_IMPAIRED", "system", store)
            store["waste_cost_cents_mtd"] += log["food_cost_cents"]
            touch(store)
            touch(batch)
            continue
        batch["discarded_qty"] += qty
        batch["remaining_qty"] = 0
        batch["status"] = "DISCARDED"
        log = append_waste_log(batch, item, qty, "UNIT_IMPAIRED", "system", store)
        store["waste_cost_cents_mtd"] += log["food_cost_cents"]
        store["hot_case_slots_used"] -= 1
        touch(store)
        touch(batch)


def daypart_transition_sweep(store):
    """Write off holding batches that expired or fell off the new daypart menu."""
    batches = [
        b for b in db.production_batches.values()
        if b["store_id"] == store["id"] and b["status"] == "HOLDING" and b["reserved_qty"] == 0
    ]
    new_daypart = store["current_daypart"]
    for batch in _sweep_order(batches):
        item = db.menu_items[batch["menu_item_id"]]
        expired = batch["hold_expires_at"] is not None and batch["hold_expires_at"] <= db.clock
        off_menu = new_daypart not in item["valid_dayparts"]
        if not (expired or off_menu):
            continue
        qty = batch["remaining_qty"]
        batch["discarded_qty"] += qty
        batch["remaining_qty"] = 0
        batch["status"] = "DISCARDED"
        log = append_waste_log(batch, item, qty, "DAYPART_TRANSITION", "system", store)
        store["waste_cost_cents_mtd"] += log["food_cost_cents"]
        store["hot_case_slots_used"] -= 1
        touch(store)
        touch(batch)


# ---------------------------------------------------------------------------
# slot_occupancy_conflict (PRD 3.4)
# ---------------------------------------------------------------------------
def occupancy_end_for(bake_start_at, item):
    end = plus_minutes(bake_start_at, item["bake_minutes"])
    end = plus_minutes(end, item["hold_minutes"])
    return plus_minutes(end, SANITATION_BUFFER_MINUTES)


def slot_conflict_exists(unit_id, slot_index, bake_start_at, occupancy_end_at):
    for other in db.production_batches.values():
        if other["holding_unit_id"] != unit_id or other["slot_index"] != slot_index:
            continue
        if other["status"] not in ("PLANNED", "BAKING", "HOLDING"):
            continue
        if bake_start_at < other["occupancy_end_at"] and other["bake_start_at"] < occupancy_end_at:
            return True
    return False


# ---------------------------------------------------------------------------
# staffing_labor_minutes (PRD 3.3)
# ---------------------------------------------------------------------------
def staffing_labor_minutes(forecast_txn_count, mto_share_bp, daypart):
    peak_bp = (
        PEAK_MULTIPLIER_BP if forecast_txn_count >= PEAK_TXN_THRESHOLD else 10000
    )
    mto_count = ceil_div(forecast_txn_count * mto_share_bp, 10000)
    grab_count = forecast_txn_count - mto_count
    raw_minutes = ceil_div(mto_count, MTO_TXNS_PER_LABOR_HOUR) * 60
    raw_minutes += ceil_div(grab_count, GRAB_TXNS_PER_LABOR_HOUR) * 60
    if daypart == "BREAKFAST":
        raw_minutes += BAKERY_PREP_MINUTES
    scaled = round_half_up(Decimal(raw_minutes * peak_bp) / Decimal(10000))
    return max(scaled, MIN_DAYPART_MINUTES), peak_bp


# ---------------------------------------------------------------------------
# batch_selection_fefo (PRD 3.8)
# ---------------------------------------------------------------------------
def fefo_candidates(order, line, item):
    out = []
    for batch in db.production_batches.values():
        if batch["store_id"] != order["store_id"]:
            continue
        if batch["menu_item_id"] != line["menu_item_id"]:
            continue
        if batch["status"] != "HOLDING":
            continue
        if batch["remaining_qty"] < line["qty"]:
            continue
        out.append(batch)
    return sorted(out, key=lambda b: (b["hold_expires_at"] or db.clock, b["created_at"], b["_seq"]))


def fefo_select(order, line, item):
    """Return (batch, error_id_or_None).  A live hold is strictly after the clock."""
    fresh = []
    expired = []
    for batch in fefo_candidates(order, line, item):
        if batch["hold_expires_at"] is not None and batch["hold_expires_at"] > db.clock:
            fresh.append(batch)
        else:
            expired.append(batch)
    if fresh:
        return fresh[0], None
    if expired:
        # stock exists but its hold has already run out (PRD 3.8, last gate)
        return None, "ERR_BATCH_HOLD_EXPIRED"
    return None, "ERR_INSUFFICIENT_BATCH_QTY"


# ---------------------------------------------------------------------------
# pickup_window_capacity (PRD 3.8)
# ---------------------------------------------------------------------------
OCCUPYING_PRODUCTION_STATES = ("PLACED", "IN_PRODUCTION", "ASSEMBLED", "READY")


def overlapping_window_count(order):
    count = 0
    for other in db.orders.values():
        if other["id"] == order["id"] or other["store_id"] != order["store_id"]:
            continue
        if other["channel"] not in ("MOBILE_PREORDER", "CATERING"):
            continue
        if other["production_status"] not in OCCUPYING_PRODUCTION_STATES:
            continue
        if other["pickup_window_start"] is None or other["pickup_window_end"] is None:
            continue
        if (order["pickup_window_start"] < other["pickup_window_end"]
                and other["pickup_window_start"] < order["pickup_window_end"]):
            count += 1
    return count


# ---------------------------------------------------------------------------
# promotion_selection / promotion_discount (PRD 3.8)
# ---------------------------------------------------------------------------
def eligible_lines_for(rule, lines):
    if rule["target_station"] == "ALL":
        return list(lines)
    return [l for l in lines if l["station"] == rule["target_station"]]


def raw_discount_for(rule, order, lines):
    """Per-line rounded figures and the capped order-level discount."""
    if rule["discount_kind"] == "PCT_PER_LINE":
        eligible = eligible_lines_for(rule, lines)
        per_line = []
        for line in eligible:
            amount = round_half_up(
                Decimal(line["line_gross_cents"] * rule["discount_bp"]) / Decimal(10000)
            )
            per_line.append((line, amount))
        raw = sum(a for _, a in per_line)
    else:
        per_line = []
        raw = min(rule["discount_cents"], order["subtotal_gross_cents"])
    capped = min(raw, rule["max_discount_cents"])
    return per_line, capped


def promotion_candidates(order, store, lines):
    candidates = []
    gallons = None
    for rule in db.promotion_rules.values():
        if rule["status"] != "ACTIVE":
            continue
        if store["current_daypart"] not in rule["valid_dayparts"]:
            continue
        if rule["min_food_subtotal_cents"] > order["subtotal_gross_cents"]:
            continue
        if rule["kind"] == "FUEL_FOOD_COMBO":
            if not store["is_fuel_site"]:
                continue
            if order["loyalty_account_id"] is None:
                continue
            if gallons is None:
                gallons = fuel_gallons_30d(order["loyalty_account_id"])
            if gallons < rule["requires_fuel_gallons"]:
                continue
        candidates.append(rule)
    return candidates


def select_promotion(order, store, lines):
    """Return (rule, per_line_amounts, discount_cents) or (None, [], 0)."""
    best = None
    for rule in promotion_candidates(order, store, lines):
        per_line, discount = raw_discount_for(rule, order, lines)
        key = (-discount, rule["stacking_rank"], rule["created_at"], rule["_seq"])
        if best is None or key < best[0]:
            best = (key, rule, per_line, discount)
    if best is None:
        return None, [], 0
    _, rule, per_line, discount = best
    return rule, per_line, discount


def apply_promotion(order, rule, per_line, discount):
    """Write line_discount_cents / line_net_cents; the per-line sum must match."""
    lines = order_lines_of(order["id"])
    amounts = {}
    if rule is not None and rule["discount_kind"] == "PCT_PER_LINE":
        amounts = {line["id"]: amount for line, amount in per_line}
        overflow = sum(amounts.values()) - discount
        if overflow > 0:
            # remove cents from the LAST eligible line first, descending created_at
            for line, _ in sorted(
                per_line, key=lambda p: (p[0]["created_at"], p[0]["_seq"]), reverse=True
            ):
                if overflow <= 0:
                    break
                take = min(overflow, amounts[line["id"]])
                amounts[line["id"]] -= take
                overflow -= take
    for line in lines:
        line["line_discount_cents"] = amounts.get(line["id"], 0)
        line["line_net_cents"] = line["line_gross_cents"] - line["line_discount_cents"]
    order["promo_discount_cents"] = discount
    order["applied_promotion_id"] = rule["id"] if rule is not None else None


# ---------------------------------------------------------------------------
# order_total_assembly (PRD 3.8)
# ---------------------------------------------------------------------------
def assemble_totals(order):
    discounted_food = order["subtotal_gross_cents"] - order["promo_discount_cents"]
    if order["channel"] == "CATERING":
        pct_fee = round_half_up(
            Decimal(discounted_food * CATERING_FEE_BP) / Decimal(10000)
        )
        order["service_fee_cents"] = max(CATERING_MIN_FEE_CENTS, pct_fee)
    else:
        order["service_fee_cents"] = 0
    order["total_cents"] = discounted_food + order["service_fee_cents"]


# ---------------------------------------------------------------------------
# loyalty_points_accrual (PRD 3.8 provisional, PRD 3.9 final)
# ---------------------------------------------------------------------------
def accrue_provisional(order, account):
    points = points_from_basis(order["total_cents"], account["tier"])
    order["points_provisional"] = points
    account["points_balance"] += points
    account["lifetime_points_earned"] += points
    account["tier"] = derive_tier(account["lifetime_points_earned"])
    touch(account)
    return points


def settle_points(order, account):
    basis = order["subtotal_gross_cents"] - order["promo_discount_cents"]
    points = points_from_basis(basis, account["tier"])
    rule_id = order["applied_promotion_id"]
    if rule_id is not None:
        rule = db.promotion_rules.get(rule_id)
        if rule is not None and rule["kind"] == "FUEL_FOOD_COMBO":
            points += FUEL_COMBO_BONUS_POINTS
    order["points_final"] = points
    delta = points - order["points_provisional"]
    account["points_balance"] += delta
    account["lifetime_points_earned"] += delta
    account["tier"] = derive_tier(account["lifetime_points_earned"])
    touch(account)
    return points


# ---------------------------------------------------------------------------
# kitchen_ticket_prep_seconds / station_queue_sequencing (PRD 3.8)
# ---------------------------------------------------------------------------
def modifier_unit_count(line):
    return sum(entry["qty"] for entry in line["modifiers"])


def ticket_lines(ticket):
    """The MADE_TO_ORDER lines of the ticket's order routed to its station."""
    out = []
    for line in order_lines_of(ticket["order_id"]):
        item = db.menu_items[line["menu_item_id"]]
        if item["fulfillment_mode"] != "MADE_TO_ORDER":
            continue
        if line["station"] != ticket["station"]:
            continue
        out.append((line, item))
    return out


def station_prep_seconds(lines_with_items):
    total = 0
    for line, item in lines_with_items:
        total += item["prep_seconds"] * line["qty"]
        total += MODIFIER_PREP_SECONDS * modifier_unit_count(line) * line["qty"]
    return total


def station_queue(store_id, station):
    queue = [
        t for t in db.kitchen_tickets.values()
        if t["store_id"] == store_id and t["station"] == station
        and t["status"] in ("QUEUED", "IN_PROGRESS")
    ]
    return sorted(queue, key=lambda t: (t["created_at"], t["sequence_position"], t["_seq"]))


def cut_kitchen_tickets(order):
    """One ticket per distinct station among the order's MADE_TO_ORDER lines."""
    by_station = {}
    for line in order_lines_of(order["id"]):
        item = db.menu_items[line["menu_item_id"]]
        if item["fulfillment_mode"] != "MADE_TO_ORDER":
            continue
        by_station.setdefault(line["station"], []).append((line, item))
    created = []
    for station in STATION_SEQUENCE:
        if station not in by_station:
            continue
        prep_seconds = station_prep_seconds(by_station[station])
        queue = station_queue(order["store_id"], station)
        rec = base_record()
        rec.update({
            "order_id": order["id"],
            "store_id": order["store_id"],
            "station": station,
            "status": "QUEUED",
            "sequence_position": len(queue) + 1,
            "prep_seconds": prep_seconds,
            "lead_seconds": sum(t["prep_seconds"] for t in queue),
            "started_by_user_id": None,
            "completed_by_user_id": None,
            "rework_count": 0,
        })
        rec["promised_ready_at"] = plus_seconds(
            db.clock.replace(microsecond=0), rec["lead_seconds"] + rec["prep_seconds"]
        )
        db.kitchen_tickets[rec["id"]] = rec
        created.append(rec)
    return created


# ---------------------------------------------------------------------------
# the ready gate and the reservation-to-sale conversion (PRD 3.9)
# ---------------------------------------------------------------------------
def ready_gate_holds(order):
    if order["channel"] == "TOUCHSCREEN":
        return True
    start = order["pickup_window_start"]
    return start is not None and db.clock >= start


def enter_ready(order, store):
    order["production_status"] = "READY"
    order["ready_at"] = db.clock
    touch(order)
    for line in order_lines_of(order["id"]):
        batch_id = line["fulfillment_batch_id"]
        if batch_id is None:
            continue
        batch = db.production_batches.get(batch_id)
        if batch is None:
            continue
        qty = line["reserved_qty"]
        batch["reserved_qty"] -= qty
        batch["sold_qty"] += qty
        line["reserved_qty"] = 0
        touch(line)
        touch(batch)
        if batch["remaining_qty"] == 0 and batch["reserved_qty"] == 0:
            batch["status"] = "SOLD_OUT"
            store["hot_case_slots_used"] -= 1
            touch(store)


def enter_assembled(order, store):
    """Entering ASSEMBLED immediately evaluates the ready gate (PRD 2.9, 3.9)."""
    order["production_status"] = "ASSEMBLED"
    if ready_gate_holds(order):
        enter_ready(order, store)


# ---------------------------------------------------------------------------
# inspection_readiness (PRD 3.6)
# ---------------------------------------------------------------------------
def inspection_readiness(store):
    units = [u for u in db.holding_units.values() if u["store_id"] == store["id"]]
    unit_ids = set(u["id"] for u in units)
    threshold = plus_minutes(db.clock, -TEMP_LOG_WINDOW_MINUTES)
    compliant = 0
    for unit in units:
        for log in db.temperature_logs.values():
            if log["holding_unit_id"] == unit["id"] and log["recorded_at"] >= threshold:
                compliant += 1
                break
    if not units:
        compliance_pct = 100
    else:
        compliance_pct = round_half_up(
            Decimal(100 * compliant) / Decimal(len(units))
        )
    impaired = sum(1 for u in units if u["status"] == "IMPAIRED")
    locked_out = sum(1 for u in units if u["status"] == "LOCKED_OUT")
    open_actions = 0
    for action in db.corrective_actions.values():
        if action["status"] != "OPEN":
            continue
        log = db.temperature_logs.get(action["temperature_log_id"])
        if log is not None and log["holding_unit_id"] in unit_ids:
            open_actions += 1
    batch_ids = set(
        b["id"] for b in db.production_batches.values() if b["store_id"] == store["id"]
    )
    retail_exposure = sum(
        w["retail_value_cents"] for w in db.waste_logs.values()
        if w["production_batch_id"] in batch_ids
    )
    if locked_out >= 1 or compliance_pct < NOT_READY_COMPLIANCE_PCT:
        status = "NOT_READY"
    elif open_actions >= 1 or impaired >= 1 or compliance_pct < READY_COMPLIANCE_PCT:
        status = "AT_RISK"
    else:
        status = "READY"
    return {
        "temp_log_compliance_pct": compliance_pct,
        "units_impaired_count": impaired,
        "units_locked_out_count": locked_out,
        "open_corrective_actions_count": open_actions,
        "food_cost_waste_cents_mtd": store["waste_cost_cents_mtd"] + store["rework_waste_cents_mtd"],
        "retail_waste_exposure_cents": retail_exposure,
        "readiness_status": status,
    }
