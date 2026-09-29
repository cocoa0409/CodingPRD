"""The thirteen calculations and the derivation cascade (PRD 2.6, 2.7, 3.x).

Money is integer cents, rates are integer basis points, quantities are whole
units.  Every fractional intermediate is a ``Decimal``; ``float`` never touches
a monetary value.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from db import clock_today, db, next_seq, row_stamp_iso, timedelta

# ---------------------------------------------------------------------------
# global constants (PRD 2.6, 3.x)
# ---------------------------------------------------------------------------
MAX_REWORK_ROUNDS = 2
MAX_RECOUNT_ROUNDS = 1
MIN_COVERAGE_PCT = Decimal("90.00")
MIN_ACCELERATED_CADENCE_DAYS = 7
SUPERVISOR_SINGLE_APPROVAL_CAP_CENTS = 500000
PHYSICAL_BLACKOUT_BUFFER_DAYS = 3
NEGATIVE_AUTO_CORRECT_MAX_UNITS = 5
PHANTOM_STALE_DAYS = 45
PHANTOM_MAX_AUTO_UNITS = 3
TAG_PASS_REWARD_BPS = 200
TAG_FAIL_PENALTY_BPS = 1500
VENDOR_SHORTAGE_PENALTY_BPS = 1500
MIN_READ_RATE_BPS = 9800
BAND_5_PCT_MIN_SCORE_BPS = 9000
BAND_10_PCT_MIN_SCORE_BPS = 7500
STORE_CAP_CENTS = 100000
CATEGORY_FLOOR_CENTS = 5000
MIN_EFFECTIVE_CENTS = 1000
THEFT_STRICTNESS_BPS = 5000
VENDOR_SHORTAGE_STRICTNESS_BPS = 7500
DEFAULT_STRICTNESS_BPS = 10000
PRIOR_POSTED_PENALTY_BPS = 1000
MAX_PRIOR_POSTED_PENALTY_BPS = 5000
PROCESS_ERROR_CAP_BPS = 3000
DAMAGE_CAP_BPS = 2000
THEFT_CAP_BPS = 4000
TIER_1_MAX_CENTS = 50000
TIER_2_MAX_CENTS = 200000
TIER_1_RATE_BPS = 8000
TIER_2_RATE_BPS = 9000
TIER_3_RATE_BPS = 10000
TIER_1_CREDIT_BPS = 1500
TIER_2_CREDIT_BPS = 1000
TIER_3_CREDIT_BPS = 500
SUSPENDED_BLOCKED_RATIO_BPS = 2000
SUSPENDED_ACCURACY_INDEX_BPS = 9000
PROBATION_RESTRICTED_RATIO_BPS = 3000
PROBATION_ACCURACY_INDEX_BPS = 9500

INVESTIGATION_NON_TERMINAL = ("OPEN", "IN_REVIEW", "CAUSE_PROPOSED", "CAUSE_APPROVED")
CAUSE_BUCKET = {
    "THEFT": "theft_cents",
    "DAMAGE": "damage_cents",
    "PROCESS_ERROR": "process_error_cents",
    "VENDOR_SHORTAGE": "vendor_shortage_cents",
}

ZERO = Decimal(0)
HUNDRED = Decimal(100)
BPS = Decimal(10000)
CENT2 = Decimal("0.01")


# ---------------------------------------------------------------------------
# rounding disciplines (PRD 2.6)
# ---------------------------------------------------------------------------

def rhu(value, places=0):
    """Round half up.  Returns int when places == 0, else a 2dp Decimal."""
    quant = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    result = Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else result


def rfloor(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def rceil(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_CEILING))


def clamp_pct(value):
    if value < ZERO:
        return ZERO.quantize(CENT2)
    if value > HUNDRED:
        return HUNDRED.quantize(CENT2)
    return value


# ---------------------------------------------------------------------------
# row bookkeeping
# ---------------------------------------------------------------------------

def touch(rec):
    """Refresh updated_at and increment version, as PRD 2.7 requires."""
    rec["updated_at"] = row_stamp_iso()
    rec["version"] = rec.get("version", 1) + 1


def snapshot(rec, keys):
    return tuple(rec.get(k) for k in keys)


def rows(collection):
    """All rows of a collection in ascending creation order."""
    return sorted(getattr(db, collection).values(), key=lambda r: r["_seq"])


def newest_first(values):
    return sorted(values, key=lambda r: r["_seq"], reverse=True)


def base_row(extra=None):
    stamp = row_stamp_iso()
    row = {
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    if extra:
        row.update(extra)
    return row


# ---------------------------------------------------------------------------
# 1. count_variance_valuation (PRD 3.4)
# ---------------------------------------------------------------------------

def count_variance_valuation(variance_units, item, category):
    """Landed-cost uplifted absolute variance value, rounded half up once."""
    uplift = (BPS + Decimal(category["landed_cost_uplift_bps"])) / BPS
    raw = Decimal(abs(variance_units)) * Decimal(item["unit_cost_cents"]) * uplift
    return rhu(raw, 0)


def within_tolerance(variance_units, variance_value_cents, category):
    """Units boundary inclusive, value boundary exclusive (PRD 3.4)."""
    return (abs(variance_units) <= category["variance_tolerance_units"]
            and variance_value_cents < category["variance_tolerance_value_cents"])


# ---------------------------------------------------------------------------
# 2. stock_accuracy_pct (PRD 3.2)
# ---------------------------------------------------------------------------

def stock_accuracy_pct(position):
    if position.get("last_counted_at") is None:
        return HUNDRED.quantize(CENT2), HUNDRED.quantize(CENT2)
    base_units = Decimal(max(position["last_count_system_units"], 1))
    unit_pct = clamp_pct(rhu(
        HUNDRED * (Decimal(1) - Decimal(abs(position["last_variance_units"])) / base_units), 2))
    base_value = Decimal(max(position["last_count_book_value_cents"], 1))
    value_pct = clamp_pct(rhu(
        HUNDRED * (Decimal(1) - Decimal(position["last_variance_value_cents"]) / base_value), 2))
    return unit_pct, value_pct


# ---------------------------------------------------------------------------
# 3. count_coverage_pct (PRD 3.4)
# ---------------------------------------------------------------------------

def line_weight(read_mode_used, task_reader_mode):
    if read_mode_used == task_reader_mode:
        return Decimal("1.00")
    if read_mode_used == "HANDHELD" and task_reader_mode == "OVERHEAD":
        return Decimal("0.50")
    return Decimal("0.00")


def count_coverage_pct(task):
    in_scope = task.get("in_scope_position_count") or 0
    if in_scope == 0:
        return Decimal("0.00")
    effective = ZERO
    for line in rows("count_lines"):
        if line["count_task_id"] != task["id"]:
            continue
        effective += line_weight(line["read_mode_used"], task["reader_mode"])
    return clamp_pct(rhu(HUNDRED * effective / Decimal(in_scope), 2))


# ---------------------------------------------------------------------------
# 4. position_promising_state (PRD 3.2)
# ---------------------------------------------------------------------------

def position_open_investigations(position_id):
    return [inv for inv in rows("investigations")
            if inv.get("_stock_position_id") == position_id
            and inv["status"] in INVESTIGATION_NON_TERMINAL]


def position_promising_state(position, category):
    if position.get("tag_integrity_hold"):
        return "BLOCKED", "tag_integrity_hold is set on this position"
    if position["on_hand_units"] < 0:
        return "BLOCKED", "on_hand_units is negative"
    if position.get("phantom_units", 0) > 0:
        return "BLOCKED", "phantom_units is greater than zero"
    if position["value_accuracy_pct"] < category["min_accuracy_pct"]:
        return ("RESTRICTED",
                "value_accuracy_pct is below the category min_accuracy_pct")
    if position_open_investigations(position["id"]):
        return "RESTRICTED", "an unresolved variance investigation covers this position"
    return "PROMISABLE", ""


# ---------------------------------------------------------------------------
# 5. store_fulfillment_posture (PRD 3.10)
# ---------------------------------------------------------------------------

STORE_POSTURE_KEYS = ("total_position_count", "blocked_position_count",
                      "restricted_position_count", "accuracy_index_bps",
                      "fulfillment_status")


def store_posture_figures(store_id):
    positions = [p for p in rows("stock_positions") if p["store_id"] == store_id]
    total = len(positions)
    if total == 0:
        return {
            "total_position_count": 0,
            "blocked_position_count": 0,
            "restricted_position_count": 0,
            "accuracy_index_bps": 10000,
            "blocked_ratio_bps": 0,
            "restricted_ratio_bps": 0,
            "fulfillment_status": "ELIGIBLE",
            "demotion_reason": "",
        }
    blocked = sum(1 for p in positions if p["promising_state"] == "BLOCKED")
    restricted = sum(1 for p in positions if p["promising_state"] == "RESTRICTED")
    accuracy_sum = ZERO
    for p in positions:
        accuracy_sum += Decimal(p["unit_accuracy_pct"])
    accuracy_index_bps = rfloor(accuracy_sum * HUNDRED / Decimal(total))
    blocked_ratio_bps = rfloor(BPS * Decimal(blocked) / Decimal(total))
    restricted_ratio_bps = rfloor(BPS * Decimal(restricted) / Decimal(total))
    if blocked_ratio_bps >= SUSPENDED_BLOCKED_RATIO_BPS:
        status, reason = "SUSPENDED", "blocked_ratio_bps at or above 2000"
    elif accuracy_index_bps < SUSPENDED_ACCURACY_INDEX_BPS:
        status, reason = "SUSPENDED", "accuracy_index_bps below 9000"
    elif blocked > 0:
        status, reason = "PROBATION", "blocked_position_count is at least 1"
    elif restricted_ratio_bps >= PROBATION_RESTRICTED_RATIO_BPS:
        status, reason = "PROBATION", "restricted_ratio_bps at or above 3000"
    elif accuracy_index_bps < PROBATION_ACCURACY_INDEX_BPS:
        status, reason = "PROBATION", "accuracy_index_bps below 9500"
    else:
        status, reason = "ELIGIBLE", ""
    return {
        "total_position_count": total,
        "blocked_position_count": blocked,
        "restricted_position_count": restricted,
        "accuracy_index_bps": accuracy_index_bps,
        "blocked_ratio_bps": blocked_ratio_bps,
        "restricted_ratio_bps": restricted_ratio_bps,
        "fulfillment_status": status,
        "demotion_reason": reason,
    }


# ---------------------------------------------------------------------------
# derivation cascade (PRD 2.7)
# ---------------------------------------------------------------------------
POSITION_DERIVED_KEYS = ("on_hand_units", "book_value_cents", "unit_accuracy_pct",
                         "value_accuracy_pct", "phantom_units", "tag_integrity_hold",
                         "promising_state", "promising_reason", "negative_correction_count",
                         "last_counted_at", "last_count_system_units",
                         "last_count_book_value_cents", "last_variance_units",
                         "last_variance_value_cents")


def posted_delta_sum(position_id):
    total = 0
    for adj in rows("adjustments"):
        if adj["stock_position_id"] == position_id and adj["posting_state"] == "POSTED":
            total += adj["delta_units"]
    return total


def derive_position(position, force=False):
    """Re-derive the position's own facts, then its promising gate."""
    item = db.items[position["item_id"]]
    category = db.categories[item["category_id"]]
    before = snapshot(position, POSITION_DERIVED_KEYS)
    on_hand = position["baseline_on_hand_units"] + posted_delta_sum(position["id"])
    position["on_hand_units"] = on_hand
    position["book_value_cents"] = on_hand * item["unit_cost_cents"]
    unit_pct, value_pct = stock_accuracy_pct(position)
    position["unit_accuracy_pct"] = unit_pct
    position["value_accuracy_pct"] = value_pct
    state, reason = position_promising_state(position, category)
    position["promising_state"] = state
    position["promising_reason"] = reason
    if force or snapshot(position, POSITION_DERIVED_KEYS) != before:
        touch(position)
    return position["store_id"]


def accelerate_schedules(store_id):
    """One-way cycle-count acceleration; never rolled back (PRD 3.10)."""
    today = clock_today().isoformat()
    for sched in rows("count_schedules"):
        if sched["store_id"] != store_id or sched["status"] != "ACTIVE":
            continue
        sched["cadence_days"] = max(MIN_ACCELERATED_CADENCE_DAYS,
                                    rfloor(Decimal(sched["cadence_days"]) / Decimal(2)))
        sched["next_due_date"] = today
        touch(sched)


def derive_store(store_id, force=False):
    store = db.stores.get(store_id)
    if store is None:
        return
    figures = store_posture_figures(store_id)
    before = snapshot(store, STORE_POSTURE_KEYS)
    previous_status = store.get("fulfillment_status")
    for key in STORE_POSTURE_KEYS:
        store[key] = figures[key]
    store["_blocked_ratio_bps"] = figures["blocked_ratio_bps"]
    store["_restricted_ratio_bps"] = figures["restricted_ratio_bps"]
    store["_demotion_reason"] = figures["demotion_reason"]
    if force or snapshot(store, STORE_POSTURE_KEYS) != before:
        touch(store)
    if previous_status != "SUSPENDED" and store["fulfillment_status"] == "SUSPENDED":
        accelerate_schedules(store_id)


def settle(position_ids, force_positions=False):
    """Settle every touched position, then re-derive the owning stores."""
    store_ids = []
    for pid in position_ids:
        position = db.stock_positions.get(pid)
        if position is None:
            continue
        store_id = derive_position(position, force=force_positions)
        if store_id not in store_ids:
            store_ids.append(store_id)
    for store_id in store_ids:
        derive_store(store_id)


# ---------------------------------------------------------------------------
# 6. shrink_attribution (PRD 3.8)
# ---------------------------------------------------------------------------
PERIOD_MONEY_KEYS = ("theft_cents", "damage_cents", "process_error_cents",
                     "vendor_shortage_cents", "unresolved_cents",
                     "total_attributable_variance_cents",
                     "provisional_total_shrink_cents", "final_total_shrink_cents",
                     "shrink_rate_bps")


def empty_waterfall():
    return {"theft_cents": 0, "damage_cents": 0, "process_error_cents": 0,
            "vendor_shortage_cents": 0, "unresolved_cents": 0}


def period_investigations(period_id):
    return [inv for inv in rows("investigations") if inv.get("shrink_period_id") == period_id]


def shrink_rate_bps(total_cents, sales_at_cost_cents):
    if not sales_at_cost_cents:
        return 0
    return rhu(BPS * Decimal(total_cents) / Decimal(sales_at_cost_cents), 0)


def recompute_period(period):
    waterfall = period.get("_waterfall") or empty_waterfall()
    buckets = {
        "theft_cents": waterfall["theft_cents"],
        "damage_cents": waterfall["damage_cents"],
        "process_error_cents": waterfall["process_error_cents"],
        "vendor_shortage_cents": waterfall["vendor_shortage_cents"],
    }
    unresolved = waterfall["unresolved_cents"]
    for inv in period_investigations(period["id"]):
        amount = inv["variance_value_cents"]
        if inv["status"] == "CLOSED":
            bucket = CAUSE_BUCKET.get(inv.get("approved_root_cause"))
            if bucket:
                buckets[bucket] += amount
        elif inv["status"] in INVESTIGATION_NON_TERMINAL:
            unresolved += amount
        # WAIVED contributes nothing.
    before = snapshot(period, PERIOD_MONEY_KEYS)
    for key, value in buckets.items():
        period[key] = value
    period["unresolved_cents"] = 0 if period["status"] == "FINAL_CLOSED" else unresolved
    bucket_total = sum(buckets.values())
    period["final_total_shrink_cents"] = bucket_total
    period["provisional_total_shrink_cents"] = bucket_total + period["unresolved_cents"]
    period["total_attributable_variance_cents"] = bucket_total + period["unresolved_cents"]
    active_total = (period["final_total_shrink_cents"] if period["status"] == "FINAL_CLOSED"
                    else period["provisional_total_shrink_cents"])
    period["shrink_rate_bps"] = shrink_rate_bps(active_total, period["sales_at_cost_cents"])
    if snapshot(period, PERIOD_MONEY_KEYS) != before:
        touch(period)


def covering_period(store_id, day, statuses):
    """The shrink period whose inclusive range contains ``day``."""
    for period in rows("shrink_periods"):
        if period["store_id"] != store_id or period["status"] not in statuses:
            continue
        if period["period_start"] <= day.isoformat() <= period["period_end"]:
            return period
    return None


# ---------------------------------------------------------------------------
# 7. adjustment_authority_threshold (PRD 3.7)
# ---------------------------------------------------------------------------

def strictness_bps(investigation):
    """10000 unless a CLOSED linked investigation names a stricter cause."""
    if investigation is None or investigation.get("status") != "CLOSED":
        return DEFAULT_STRICTNESS_BPS
    cause = investigation.get("approved_root_cause")
    if cause == "THEFT":
        return THEFT_STRICTNESS_BPS
    if cause == "VENDOR_SHORTAGE":
        return VENDOR_SHORTAGE_STRICTNESS_BPS
    return DEFAULT_STRICTNESS_BPS


def prior_posted_penalty_bps(stock_position_id):
    posted = sum(1 for adj in rows("adjustments")
                 if adj["stock_position_id"] == stock_position_id
                 and adj["posting_state"] == "POSTED")
    return min(MAX_PRIOR_POSTED_PENALTY_BPS, PRIOR_POSTED_PENALTY_BPS * posted)


def adjustment_authority_threshold(category, stock_position_id, investigation):
    strict = strictness_bps(investigation)
    penalty = prior_posted_penalty_bps(stock_position_id)
    candidate = min(category["variance_tolerance_value_cents"], STORE_CAP_CENTS)
    base = max(CATEGORY_FLOOR_CENTS, candidate)
    scaled = (Decimal(base) * Decimal(strict) / BPS) * (Decimal(BPS - penalty) / BPS)
    return max(MIN_EFFECTIVE_CENTS, rfloor(scaled))


# ---------------------------------------------------------------------------
# 8. tag_verification_outcome (PRD 3.3)
# ---------------------------------------------------------------------------

def required_sample_units(quantity_encoded, sample_pct):
    """The only ceiling-rounded figure in the system."""
    return rceil(Decimal(quantity_encoded) * Decimal(sample_pct) / HUNDRED)


def read_rate_bps(readable_units, sampled_units):
    if sampled_units <= 0:
        return 0
    return rfloor(BPS * Decimal(readable_units) / Decimal(sampled_units))


def tag_verification_outcome(rate_bps, duplicate_epc_count, unencoded_units):
    passed = (rate_bps >= MIN_READ_RATE_BPS
              and duplicate_epc_count == 0
              and unencoded_units == 0)
    return "PASS" if passed else "FAIL"


def vendor_sample_band(score_bps):
    if score_bps >= BAND_5_PCT_MIN_SCORE_BPS:
        return 5
    if score_bps >= BAND_10_PCT_MIN_SCORE_BPS:
        return 10
    return 20


def apply_vendor_score(vendor, delta_bps):
    score = vendor["tag_compliance_score_bps"] + delta_bps
    score = max(0, min(10000, score))
    vendor["tag_compliance_score_bps"] = score
    vendor["required_verification_sample_pct"] = vendor_sample_band(score)


def refreeze_vendor_batches(vendor_id):
    """Re-freeze required_sample_units on DRAFT and ENCODED batches (PRD 3.6)."""
    vendor = db.vendors[vendor_id]
    for batch in rows("tag_batches"):
        if batch["vendor_id"] != vendor_id:
            continue
        if batch["status"] not in ("DRAFT", "ENCODED"):
            continue
        fresh = required_sample_units(batch["quantity_encoded"],
                                      vendor["required_verification_sample_pct"])
        if batch["required_sample_units"] != fresh:
            batch["required_sample_units"] = fresh
            touch(batch)


# ---------------------------------------------------------------------------
# 9. vendor_shortage_chargeback (PRD 3.8)
# ---------------------------------------------------------------------------

def chargeback_tier(gross_shortage_cents):
    if gross_shortage_cents <= TIER_1_MAX_CENTS:
        return "TIER_1", TIER_1_RATE_BPS, TIER_1_CREDIT_BPS
    if gross_shortage_cents <= TIER_2_MAX_CENTS:
        return "TIER_2", TIER_2_RATE_BPS, TIER_2_CREDIT_BPS
    return "TIER_3", TIER_3_RATE_BPS, TIER_3_CREDIT_BPS


def vendor_shortage_chargeback(shortage_cents):
    """Tier on the gross shortage; the credit rate keys off the SAME tier."""
    tier, rate_bps, credit_bps = chargeback_tier(shortage_cents)
    gross = rhu(Decimal(shortage_cents) * Decimal(rate_bps) / BPS, 0)
    credit = rhu(Decimal(gross) * Decimal(credit_bps) / BPS, 0)
    return tier, gross, credit, gross - credit


# ---------------------------------------------------------------------------
# 10. physical_inventory_blackout_interval (PRD 3.9)
# ---------------------------------------------------------------------------
BLACKOUT_STATUSES = ("PLANNED", "COUNTING", "FIRST_PASS_COMPLETE", "RECONCILING", "CERTIFIED")


def blackout_interval(start_date, end_date):
    buffer_days = timedelta(days=PHYSICAL_BLACKOUT_BUFFER_DAYS)
    return start_date - buffer_days, end_date + buffer_days


def blackout_conflict(store_id, start_date, end_date, exclude_id=None):
    for existing in rows("physical_inventories"):
        if existing["store_id"] != store_id or existing["id"] == exclude_id:
            continue
        if existing["status"] not in BLACKOUT_STATUSES:
            continue
        low, high = blackout_interval(_as_date(existing["scheduled_start_date"]),
                                      _as_date(existing["scheduled_end_date"]))
        if start_date <= high and end_date >= low:
            return existing
    return None


def _as_date(text):
    from datetime import date as _date
    return _date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


# ---------------------------------------------------------------------------
# 11. count_task_window_overlap (PRD 3.4)
# ---------------------------------------------------------------------------
OCCUPYING_TASK_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COUNTED")


def overlapping_tasks(store_id, category_id, window_start, window_end, reader_mode=None):
    """Half-open interval geometry: req.start < ex.end AND ex.start < req.end."""
    hits = []
    for task in rows("count_tasks"):
        if task["store_id"] != store_id:
            continue
        if category_id is not None and task["category_id"] != category_id:
            continue
        if task["status"] not in OCCUPYING_TASK_STATUSES:
            continue
        if reader_mode is not None and task["reader_mode"] != reader_mode:
            continue
        if window_start < task["_window_end"] and task["_window_start"] < window_end:
            hits.append(task)
    return hits


# ---------------------------------------------------------------------------
# 12. physical_reconciliation waterfall (PRD 3.9)
# ---------------------------------------------------------------------------

def reconciliation_waterfall(abs_net_variance_cents, explained_cents):
    """Fixed bucket order with floored caps; the remainder is unresolved."""
    remaining = max(0, abs_net_variance_cents - explained_cents)
    allocation = empty_waterfall()
    for key, cap_bps in (("process_error_cents", PROCESS_ERROR_CAP_BPS),
                         ("damage_cents", DAMAGE_CAP_BPS),
                         ("theft_cents", THEFT_CAP_BPS)):
        cap = rfloor(Decimal(abs_net_variance_cents) * Decimal(cap_bps) / BPS)
        take = min(remaining, cap)
        allocation[key] = take
        remaining -= take
    allocation["unresolved_cents"] = remaining
    return allocation


def net_variance_bps(net_variance_cents, book_value_cents):
    if book_value_cents == 0:
        return 0
    return rfloor(BPS * Decimal(abs(net_variance_cents)) / Decimal(book_value_cents))


# ---------------------------------------------------------------------------
# 13. adjustment minting / posting (PRD 3.7)
# ---------------------------------------------------------------------------
REASON_CODES = ("COUNT_VARIANCE", "NEGATIVE_CORRECTION", "PHANTOM_CLEAR",
                "PHYSICAL_RECONCILIATION")
APPROVAL_STATES = ("NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED")
POSTING_STATES = ("UNPOSTED", "POSTED", "REVERSED")


def mint_adjustment(position, delta_units, reason_code, investigation,
                    requested_by_user_id, exempt=False, force_approval_state=None):
    from db import new_id
    item = db.items[position["item_id"]]
    category = db.categories[item["category_id"]]
    value_impact_cents = abs(delta_units) * item["unit_cost_cents"]
    if exempt or reason_code == "PHYSICAL_RECONCILIATION":
        threshold = 0
        approval_state = "NOT_REQUIRED"
    else:
        threshold = adjustment_authority_threshold(category, position["id"], investigation)
        approval_state = "PENDING" if value_impact_cents >= threshold else "NOT_REQUIRED"
    if force_approval_state is not None:
        approval_state = force_approval_state
    adjustment = base_row({
        "id": new_id(),
        "stock_position_id": position["id"],
        "investigation_id": investigation["id"] if investigation else None,
        "delta_units": delta_units,
        "reason_code": reason_code,
        "value_impact_cents": value_impact_cents,
        "authority_threshold_cents": threshold,
        "approval_state": approval_state,
        "posting_state": "UNPOSTED",
        "requested_by_user_id": requested_by_user_id,
        "approved_by_user_id": None,
        "posted_at": None,
        "reversed_at": None,
        "_phantom_restore": 0,
    })
    db.adjustments[adjustment["id"]] = adjustment
    return adjustment


def post_adjustment(adjustment, position, settle_store=True):
    """The five-hop posting cascade of PRD 3.7."""
    from db import clock_now_iso
    adjustment["posting_state"] = "POSTED"
    adjustment["posted_at"] = clock_now_iso()
    touch(adjustment)
    if adjustment["reason_code"] == "PHANTOM_CLEAR":
        adjustment["_phantom_restore"] = position.get("phantom_units", 0)
        position["phantom_units"] = 0
    derive_position(position, force=True)
    if settle_store:
        derive_store(position["store_id"])


def reverse_adjustment(adjustment, position):
    from db import clock_now_iso
    adjustment["posting_state"] = "REVERSED"
    adjustment["reversed_at"] = clock_now_iso()
    touch(adjustment)
    if adjustment["reason_code"] == "PHANTOM_CLEAR":
        position["phantom_units"] = adjustment.get("_phantom_restore", 0)
    derive_position(position, force=True)
    derive_store(position["store_id"])


def position_for(store_id, item_id):
    for position in rows("stock_positions"):
        if position["store_id"] == store_id and position["item_id"] == item_id:
            return position
    return None
