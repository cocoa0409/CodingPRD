"""Business logic: lookups, serializers, calculations C1-C8, cascades, sweeps."""
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from db import DB, logical_now_dt, now_iso
from errors import ApiError
from util import parse_dt, parse_ymd, rhu_decimal, rhu_fraction, rhu_int

# ---------------------------------------------------------------------------
# Enum domains
# ---------------------------------------------------------------------------
SERVICE_MODELS = ("BOARD", "RETAIL", "HYBRID")
STATIONS = ("GRILL", "DELI", "PIZZA", "SALAD", "GLOBAL", "BAKERY")
ALLERGENS = ("MILK", "EGG", "PEANUT", "TREE_NUT", "SOY", "WHEAT", "FISH", "SHELLFISH", "SESAME")
DIETARY_FLAGS = ("VEGAN", "VEGETARIAN", "HALAL", "KOSHER", "GLUTEN_FREE")
DIETARY_REQUIREMENTS = DIETARY_FLAGS + ("OTHER",)
MEAL_PERIODS = ("BREAKFAST", "LUNCH", "DINNER", "LATE_NIGHT")
ENTRY_TYPES = ("BOARD_SWIPE", "RETAIL_SALE")
FORECAST_VARIANTS = ("BASE", "TREND")
SHIFT_ROLES = ("COOK", "SERVER", "CASHIER", "DISHWASHER")
WASTE_CATEGORIES = ("PRE_CONSUMER", "POST_CONSUMER", "SPOILAGE")
WASTE_DISPOSITIONS = ("LANDFILL", "COMPOST", "DONATION")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
TIME_SLOTS = ("BREAKFAST", "LUNCH", "DINNER")
SLOT_START_HOUR = {"BREAKFAST": 7, "LUNCH": 11, "DINNER": 17}

# C1 constants
HISTORY_WINDOW_OCCURRENCES = 4
PREP_BUFFER_PCT = Decimal("0.05")
DEFAULT_OCCUPANCY_PCT = Decimal("0.60")

# C2 constants
DIETARY_PREMIUM_CENTS = 300
SERVICE_FEE_BASE_CENTS = 7500
PER_COVER_STAFFING_CENTS = 25
MINIMUM_ORDER_CENTS = 50000

# C4 constants
WEEKLY_OT_THRESHOLD_MINUTES = 2400
OT_MULTIPLIER = Decimal("1.5")

# C5 constants
DEMERIT = {"CRITICAL": 25, "MAJOR": 10, "MINOR": 3}
PASS_THRESHOLD = 70
CONDITIONAL_THRESHOLD = 40

# C6 constants
ALERT_THRESHOLD_KG = Decimal("0.15")

# Corrective-action due-date offsets (days) by severity
CA_DUE_DAYS = {"CRITICAL": 7, "MAJOR": 14, "MINOR": 30}


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------

def stamp(rec):
    t = now_iso()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def ser(rec):
    """Serialize a record: drop internal keys (prefixed '_')."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_created(records):
    return sorted(records, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Lookups (existence, hierarchical left-to-right)
# ---------------------------------------------------------------------------

def _lookup(store, rid, label):
    rec = DB[store].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found")
    return rec


def get_hall(rid):
    return _lookup("dining_halls", rid, "DiningHall")


def get_contract(rid):
    return _lookup("vendor_contracts", rid, "VendorContract")


def get_cycle(rid):
    return _lookup("menu_cycles", rid, "MenuCycle")


def get_recipe(rid):
    return _lookup("recipes", rid, "Recipe")


def get_period(rid):
    return _lookup("meal_periods", rid, "MealPeriodService")


def get_swipe(rid):
    return _lookup("swipe_events", rid, "SwipeEvent")


def get_forecast(rid):
    return _lookup("forecasts", rid, "ProductionForecast")


def get_accommodation(rid):
    return _lookup("accommodation_requests", rid, "AccommodationRequest")


def get_shift(rid):
    return _lookup("labor_shifts", rid, "LaborShift")


def get_waste_log(rid):
    return _lookup("waste_logs", rid, "WasteLog")


def get_report(rid):
    return _lookup("inspection_reports", rid, "InspectionReport")


def get_action(rid):
    return _lookup("corrective_actions", rid, "CorrectiveAction")


def get_department(rid):
    return _lookup("departments", rid, "Department")


def get_catering_order(rid):
    return _lookup("catering_orders", rid, "CateringOrder")


def get_statement(rid):
    return _lookup("commission_statements", rid, "CommissionStatement")


# ---------------------------------------------------------------------------
# Cross-entity helpers
# ---------------------------------------------------------------------------

def hall_of_period(period):
    return DB["dining_halls"][period["dining_hall_id"]]


def has_open_critical_action(hall_id):
    """Any CRITICAL CorrectiveAction OPEN/OVERDUE on any report at the hall."""
    for report in DB["inspection_reports"].values():
        if report["dining_hall_id"] != hall_id:
            continue
        for action in DB["corrective_actions"].values():
            if (
                action["inspection_report_id"] == report["id"]
                and action["severity"] == "CRITICAL"
                and action["status"] in ("OPEN", "OVERDUE")
            ):
                return True
    return False


def suspend_hall(hall):
    """ACTIVE -> SUSPENDED with the section-2.10 cascade. No-op if not ACTIVE."""
    if hall["status"] != "ACTIVE":
        return
    hall["status"] = "SUSPENDED"
    touch(hall)
    for period in DB["meal_periods"].values():
        if period["dining_hall_id"] == hall["id"] and period["status"] == "SCHEDULED":
            period["status"] = "CANCELLED"
            touch(period)


def event_start_dt(order):
    """Event start instant: event_date + slot start hour (UTC)."""
    d = parse_ymd(order["event_date"])
    return parse_dt(
        f"{d.isoformat()}T{SLOT_START_HOUR[order['time_slot']]:02d}:00:00Z"
    )


# ---------------------------------------------------------------------------
# C1 — production forecast portions
# ---------------------------------------------------------------------------

def _covers_of(period_id):
    return sum(
        1 for e in DB["swipe_events"].values() if e["meal_period_id"] == period_id
    )


def historical_occurrences(period):
    """Up to 4 most-recent same-hall, same-slot periods exactly 7k days earlier,
    in {IN_SERVICE, RECONCILED, CLOSED}; service_date DESC, created_at ASC ties."""
    target = parse_ymd(period["service_date"])
    cands = []
    for p in DB["meal_periods"].values():
        if p["id"] == period["id"]:
            continue
        if p["dining_hall_id"] != period["dining_hall_id"]:
            continue
        if p["meal_period"] != period["meal_period"]:
            continue
        if p["status"] not in ("IN_SERVICE", "RECONCILED", "CLOSED"):
            continue
        delta = (target - parse_ymd(p["service_date"])).days
        if delta > 0 and delta % 7 == 0:
            cands.append(p)
    cands.sort(key=lambda p: (-parse_ymd(p["service_date"]).toordinal(), p["_seq"]))
    return cands[:HISTORY_WINDOW_OCCURRENCES]


def c1_base_covers(period, variant):
    """C1 period-level base covers for the given variant."""
    occ = historical_occurrences(period)
    if len(occ) >= 2:
        covers = [_covers_of(p["id"]) for p in occ]
        mean = rhu_fraction(Fraction(sum(covers), len(covers)))
        if variant == "BASE":
            return mean
        # TREND: slope between oldest and newest occurrence, added to the mean.
        newest, oldest = covers[0], covers[-1]
        slope = Fraction(newest - oldest, len(occ) - 1)
        return rhu_fraction(Fraction(mean) + slope)
    if variant == "TREND":
        raise ApiError(
            "ERR_INSUFFICIENT_HISTORY",
            422,
            "TREND forecast requires at least 2 historical occurrences",
        )
    hall = hall_of_period(period)
    return rhu_int(Decimal(hall["dining_capacity"]) * DEFAULT_OCCUPANCY_PCT)


def c1_forecast_portions(period, recipe, variant):
    """C1 full output: (base_covers, forecasted_portions) for a recipe."""
    base_covers = c1_base_covers(period, variant)
    portions = rhu_int(
        Decimal(base_covers)
        * Decimal(str(recipe["popularity_share"]))
        * (Decimal(1) + PREP_BUFFER_PCT)
    )
    return base_covers, portions


# ---------------------------------------------------------------------------
# C2 — catering quote
# ---------------------------------------------------------------------------

def c2_quote(menu_lines, guaranteed_covers, dietary_plates):
    food_cost = sum(line["portions"] * line["_unit_cost_cents"] for line in menu_lines)
    if guaranteed_covers < 50:
        markup = Decimal("1.40")
    elif guaranteed_covers < 200:
        markup = Decimal("1.25")
    else:
        markup = Decimal("1.15")
    marked_up = rhu_int(Decimal(food_cost) * markup)
    dietary_premium = dietary_plates * DIETARY_PREMIUM_CENTS
    service_fee = SERVICE_FEE_BASE_CENTS + PER_COVER_STAFFING_CENTS * guaranteed_covers
    return max(MINIMUM_ORDER_CENTS, marked_up + dietary_premium + service_fee)


# ---------------------------------------------------------------------------
# C3 — commission settlement
# ---------------------------------------------------------------------------

def _periods_in_month(hall_id, period_month, statuses):
    return [
        p
        for p in DB["meal_periods"].values()
        if p["dining_hall_id"] == hall_id
        and p["service_date"].startswith(period_month)
        and p["status"] in statuses
    ]


def c3_settlement(contract, period_month, variant):
    """C3 aggregation. variant is 'PROVISIONAL' or 'FINAL'."""
    hall_id = contract["dining_hall_id"]
    if variant == "FINAL":
        periods = _periods_in_month(hall_id, period_month, ("CLOSED",))
    else:
        periods = _periods_in_month(hall_id, period_month, ("RECONCILED", "CLOSED"))
    period_ids = {p["id"] for p in periods}

    board_revenue_cents = sum(
        p["actual_board_swipes"] * contract["board_rate_per_cover_cents"]
        for p in periods
    )

    retail_commission_cents = 0
    for e in DB["swipe_events"].values():
        if e["meal_period_id"] in period_ids and e["entry_type"] == "RETAIL_SALE":
            retail_commission_cents += rhu_int(
                Decimal(e["amount_cents"] * contract["retail_commission_bps"])
                / Decimal(10000)
            )

    if variant == "FINAL":
        order_statuses = ("PAID",)
    else:
        order_statuses = ("SCHEDULED", "FULFILLED", "INVOICED", "PAID")
    catering_commission_cents = 0
    for o in DB["catering_orders"].values():
        if o["dining_hall_id"] != hall_id:
            continue
        if not o["event_date"].startswith(period_month):
            continue
        if o["fulfillment_status"] not in order_statuses:
            continue
        base = o["final_total_cents"] if variant == "FINAL" else o["quoted_total_cents"]
        catering_commission_cents += rhu_int(
            Decimal(base * contract["catering_commission_bps"]) / Decimal(10000)
        )

    if variant == "FINAL":
        guarantee_top_up_cents = max(
            0,
            contract["minimum_monthly_guarantee_cents"]
            - (retail_commission_cents + catering_commission_cents),
        )
    else:
        guarantee_top_up_cents = 0

    total_due = retail_commission_cents + catering_commission_cents + guarantee_top_up_cents
    return {
        "board_revenue_cents": board_revenue_cents,
        "retail_commission_cents": retail_commission_cents,
        "catering_commission_cents": catering_commission_cents,
        "guarantee_top_up_cents": guarantee_top_up_cents,
        "total_due_to_university_cents": total_due,
    }


# ---------------------------------------------------------------------------
# C4 — weekly overtime allocation (re-scores only the just-completed shift)
# ---------------------------------------------------------------------------

def c4_allocate(shift):
    """Compute regular/overtime split and pay for the just-completed shift."""
    target_date = parse_ymd(shift["shift_date"])
    target_week = target_date.isocalendar()[:2]
    candidates = [
        s
        for s in DB["labor_shifts"].values()
        if s["staff_ref"] == shift["staff_ref"]
        and s["status"] == "COMPLETED"
        and parse_ymd(s["shift_date"]).isocalendar()[:2] == target_week
    ]
    candidates.sort(key=lambda s: (s["shift_date"], s["start_minute"], s["_seq"]))
    running = 0
    regular = overtime = 0
    for s in candidates:
        worked = s["worked_minutes"]
        reg = max(0, min(worked, WEEKLY_OT_THRESHOLD_MINUTES - running))
        ot = worked - reg
        if s["id"] == shift["id"]:
            regular, overtime = reg, ot
        running += worked
    shift["regular_minutes"] = regular
    shift["overtime_minutes"] = overtime
    shift["regular_pay_cents"] = rhu_int(
        Decimal(regular * shift["hourly_rate_cents"]) / Decimal(60)
    )
    shift["overtime_pay_cents"] = rhu_int(
        Decimal(overtime) * Decimal(shift["hourly_rate_cents"]) * OT_MULTIPLIER
        / Decimal(60)
    )


# ---------------------------------------------------------------------------
# C5 — inspection scoring
# ---------------------------------------------------------------------------

def c5_score(violations):
    demerits = sum(DEMERIT[v["severity"]] for v in violations)
    score = max(0, 100 - demerits)
    if any(v["severity"] == "CRITICAL" for v in violations):
        outcome = "FAIL"
    elif score >= PASS_THRESHOLD:
        outcome = "PASS"
    elif score >= CONDITIONAL_THRESHOLD:
        outcome = "CONDITIONAL"
    else:
        outcome = "FAIL"
    return score, outcome


# ---------------------------------------------------------------------------
# C6 — sustainability metrics (recompute a period from its POSTED waste logs)
# ---------------------------------------------------------------------------

def _kg2(value):
    """Decimal kilograms -> float at 2dp half-up."""
    return float(rhu_decimal(value, "0.01"))


def c6_recompute(period):
    posted = [
        w
        for w in DB["waste_logs"].values()
        if w["meal_period_id"] == period["id"] and w["status"] == "POSTED"
    ]
    total = sum((Decimal(str(w["weight_kg"])) for w in posted), Decimal("0"))
    landfill = sum(
        (Decimal(str(w["weight_kg"])) for w in posted if w["disposition"] == "LANDFILL"),
        Decimal("0"),
    )
    diverted = sum(
        (
            Decimal(str(w["weight_kg"]))
            for w in posted
            if w["disposition"] in ("COMPOST", "DONATION")
        ),
        Decimal("0"),
    )
    period["posted_waste_kg"] = _kg2(total)
    period["landfill_waste_kg"] = _kg2(landfill)
    if total == 0:
        period["diversion_rate"] = None
    else:
        period["diversion_rate"] = float(rhu_decimal(diverted / total, "0.0001"))
    covers = period["actual_covers"]
    period["sustainability_alert"] = bool(
        covers > 0 and landfill > ALERT_THRESHOLD_KG * covers
    )


# ---------------------------------------------------------------------------
# C7 — department budget ledger (recomputed from the department's orders)
# ---------------------------------------------------------------------------

def c7_recompute(department):
    orders = [
        o for o in DB["catering_orders"].values() if o["department_id"] == department["id"]
    ]
    reserved = sum(o["quoted_total_cents"] for o in orders if o["approval_status"] == "SUBMITTED")
    committed = sum(
        o["quoted_total_cents"]
        for o in orders
        if o["approval_status"] == "APPROVED"
        and o["fulfillment_status"] in ("NONE", "SCHEDULED", "FULFILLED", "INVOICED")
    )
    spent = sum(
        o["final_total_cents"] for o in orders if o["fulfillment_status"] == "PAID"
    ) + sum(
        o["cancellation_fee_cents"]
        for o in orders
        if o["approval_status"] == "CANCELLED" and o["cancellation_fee_cents"] > 0
    )
    department["reserved_cents"] = reserved
    department["committed_cents"] = committed
    department["spent_cents"] = spent
    department["available_cents"] = (
        department["semester_budget_cents"] - reserved - committed - spent
    )


# ---------------------------------------------------------------------------
# C8 — meal period reconciliation
# ---------------------------------------------------------------------------

def c8_reconcile(period):
    events = [e for e in DB["swipe_events"].values() if e["meal_period_id"] == period["id"]]
    board = [e for e in events if e["entry_type"] == "BOARD_SWIPE"]
    retail = [e for e in events if e["entry_type"] == "RETAIL_SALE"]
    period["actual_board_swipes"] = len(board)
    period["actual_retail_sales_cents"] = sum(e["amount_cents"] for e in retail)
    period["actual_covers"] = len(board) + len(retail)
    forecasted = period["forecasted_covers"]
    if forecasted == 0:
        period["forecast_variance_pct"] = None
    else:
        pct = (
            Decimal(period["actual_covers"] - forecasted) / Decimal(forecasted)
        ) * Decimal(100)
        period["forecast_variance_pct"] = float(rhu_decimal(pct, "0.01"))


# ---------------------------------------------------------------------------
# Clock sweeps (PRD section 2.4)
# ---------------------------------------------------------------------------

def run_sweeps(now_dt):
    """Expire ACTIVE contracts whose end date is reached; overdue OPEN actions."""
    now_date = now_dt.date()
    expired_contract_ids = []
    for contract in DB["vendor_contracts"].values():
        if contract["status"] != "ACTIVE":
            continue
        if parse_ymd(contract["effective_end_date"]) <= now_date:
            contract["status"] = "EXPIRED"
            touch(contract)
            expired_contract_ids.append(contract["id"])
    overdue_ids = []
    for action in DB["corrective_actions"].values():
        if action["status"] != "OPEN":
            continue
        if parse_ymd(action["due_date"]) < now_date:
            action["status"] = "OVERDUE"
            touch(action)
            overdue_ids.append(action["id"])
    return expired_contract_ids, overdue_ids


def ca_due_date(inspection_date, severity):
    return (parse_ymd(inspection_date) + timedelta(days=CA_DUE_DAYS[severity])).isoformat()
