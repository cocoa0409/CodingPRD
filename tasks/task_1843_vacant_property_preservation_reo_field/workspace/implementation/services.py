"""Business logic: calculations, cascades, and the daily operational sweep."""

from datetime import date, timedelta
from decimal import Decimal

from db import store, new_entity, bump, bump_if_changed, clock_date
from util import round_half_up_cents, parse_date_str

# =============================================================================
# Constants (calculation tables)
# =============================================================================

HEATING_MULT = {
    "NONE": Decimal("1.00"),
    "FORCED_AIR": Decimal("1.00"),
    "HOT_WATER": Decimal("1.50"),
    "STEAM": Decimal("1.75"),
}
BASE_WINTERIZATION_CENTS = 15000
PER_FIXTURE_CENTS = 1200
POOL_CENTS = 9000
SEASONAL_MULT = Decimal("1.20")
WINTER_MONTHS = {10, 11, 12, 1, 2, 3}

PHOTO_MINIMUMS = {
    "SECURING": {"BEFORE": 2, "DURING": 1, "AFTER": 2, "SERIAL_NUMBER": 1},
    "WINTERIZATION": {"BEFORE": 1, "DURING": 2, "AFTER": 1},
    "DEWINTERIZATION": {"BEFORE": 1, "AFTER": 1},
    "GRASS_CUT": {"BEFORE": 1, "AFTER": 1},
    "SNOW_REMOVAL": {"BEFORE": 1, "AFTER": 1},
    "DEBRIS_REMOVAL": {"BEFORE": 2, "AFTER": 2},
    "PERSONAL_PROPERTY": {"BEFORE": 1, "DOCUMENT": 2},
    "CODE_CURE": {"BEFORE": 1, "DURING": 1, "AFTER": 2},
    "BOARD_UP": {"BEFORE": 1, "AFTER": 2},
    "DAMAGE_REPAIR": {"BEFORE": 1, "DURING": 1, "AFTER": 1},
    "INSPECTION": {"STREET_SCENE": 1},
}

HOLD_DAYS = {"OH": 30, "MI": 28}
HOLD_DAYS_DEFAULT = 30

CLASS_DEDUCT = {"MINOR": 15, "MAJOR": 25, "HAZARDOUS": 40}
VIOLATION_OPEN_STATUSES = {"OPEN", "CURE_IN_PROGRESS", "CURE_SUBMITTED", "ESCALATED"}
DAMAGE_OPEN_STATUSES = {"REPORTED", "TRIAGED", "BID_REQUESTED", "REPAIR_IN_PROGRESS"}

PROMPT_PAY_RATE = Decimal("0.02")
PROPERTY_YTD_REVIEW_THRESHOLD_CENTS = 200000

REBATE_TIER1_GROSS = 500000
REBATE_TIER1_RATE = Decimal("0.010")
REBATE_TIER2_GROSS = 1000000
REBATE_TIER2_RATE = Decimal("0.015")

WO_OPEN_FOR_CONVEY = {"ISSUED", "ASSIGNED", "IN_PROGRESS", "SUBMITTED"}


# =============================================================================
# Investor allowable schedule
# =============================================================================

def select_allowable(investor_type, item_code):
    """Latest effective_from <= clock date; tie-break created_at DESC. None if empty."""
    today = clock_date()
    candidates = [
        a for a in store.allowables.values()
        if a["investor_type"] == investor_type
        and a["item_code"] == item_code
        and parse_date_str(a["effective_from"], "effective_from") <= today
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (parse_date_str(a["effective_from"], "effective_from"), a["created_at"], a["_seq"]), reverse=True)
    return candidates[0]


def recompute_is_current(investor_type, item_code, skip_bump_id=None):
    """Latest effective_from row per (investor_type, item_code) as of the logical clock.

    skip_bump_id: a newly created row gets is_current set at creation (no version bump).
    """
    today = clock_date()
    family = [
        a for a in store.allowables.values()
        if a["investor_type"] == investor_type and a["item_code"] == item_code
    ]
    effective = [a for a in family if parse_date_str(a["effective_from"], "effective_from") <= today]
    current_id = None
    if effective:
        effective.sort(key=lambda a: (parse_date_str(a["effective_from"], "effective_from"), a["created_at"], a["_seq"]), reverse=True)
        current_id = effective[0]["id"]
    for a in family:
        target = a["id"] == current_id
        if a["id"] == skip_bump_id:
            a["is_current"] = target
        else:
            bump_if_changed(a, {"is_current": target})


def snapshot_allowable_version(row):
    """Record the fiscal params of an allowable row at its current version."""
    hist = store.allowable_history.setdefault(row["id"], {})
    hist[row["version"]] = {
        "max_per_occurrence_cents": row["max_per_occurrence_cents"],
        "max_occurrences_per_calendar_year": row["max_occurrences_per_calendar_year"],
        "aggregate_cap_cents_per_property_year": row["aggregate_cap_cents_per_property_year"],
        "requires_bid_over_cents": row["requires_bid_over_cents"],
    }


def pinned_schedule(wo):
    """The InvestorAllowable snapshot pinned on a work order (or None components)."""
    cap = wo.get("allowable_cap_cents")
    max_occ = None
    agg = None
    aid = wo.get("investor_allowable_id")
    ver = wo.get("investor_allowable_version")
    if aid is not None and ver is not None:
        snap = store.allowable_history.get(aid, {}).get(ver)
        if snap is not None:
            max_occ = snap["max_occurrences_per_calendar_year"]
            agg = snap["aggregate_cap_cents_per_property_year"]
            if cap is None:
                cap = snap["max_per_occurrence_cents"]
    return cap, max_occ, agg


# =============================================================================
# winterization_quote
# =============================================================================

def winterization_quote(prop, order_type):
    base = BASE_WINTERIZATION_CENTS + prop["fixture_count"] * PER_FIXTURE_CENTS
    if prop.get("has_pool"):
        base += POOL_CENTS
    heating_mult = HEATING_MULT[prop["heating_system"]]
    seasonal_mult = SEASONAL_MULT if store.clock.month in WINTER_MONTHS else Decimal("1.00")
    if order_type == "DEWINTERIZATION":
        seasonal_mult = Decimal("1.00")
        base = base // 2
    return round_half_up_cents(Decimal(base) * heating_mult * seasonal_mult)


# =============================================================================
# photo_completeness
# =============================================================================

def unflagged_photo_counts(work_order_id):
    counts = {}
    for p in store.photos.values():
        if p.get("work_order_id") == work_order_id and not p["flagged"]:
            counts[p["category"]] = counts.get(p["category"], 0) + 1
    return counts


def evidence_complete(wo):
    required = PHOTO_MINIMUMS.get(wo["order_type"], {})
    counts = unflagged_photo_counts(wo["id"])
    return all(counts.get(cat, 0) >= n for cat, n in required.items())


def recompute_evidence_complete(wo):
    wo["evidence_complete"] = evidence_complete(wo)


def has_unresolved_flags(work_order_id):
    return any(
        p.get("work_order_id") == work_order_id and p["flagged"]
        for p in store.photos.values()
    )


# =============================================================================
# crew_day_capacity
# =============================================================================

def crew_day_load(crew_id, scheduled_date, exclude_wo_id=None):
    count = 0
    for wo in store.work_orders.values():
        if wo["id"] == exclude_wo_id:
            continue
        if (
            wo.get("assigned_crew_id") == crew_id
            and wo.get("scheduled_date") == scheduled_date
            and wo["status"] in ("ASSIGNED", "IN_PROGRESS")
        ):
            count += 1
    return count


# =============================================================================
# registration_overlap / coverage
# =============================================================================

def registration_covers(reg, municipality_code, on_date):
    return (
        reg["status"] == "ACTIVE"
        and reg["municipality_code"] == municipality_code
        and parse_date_str(reg["valid_from"], "valid_from") <= on_date
        and on_date < parse_date_str(reg["valid_to"], "valid_to")
    )


def has_active_registration(prop, on_date):
    return any(
        r["property_id"] == prop["id"] and registration_covers(r, prop["municipality_code"], on_date)
        for r in store.registrations.values()
    )


def registration_overlaps(reg):
    """Half-open overlap vs other ACTIVE registrations, same property + municipality."""
    vf = parse_date_str(reg["valid_from"], "valid_from")
    vt = parse_date_str(reg["valid_to"], "valid_to")
    for other in store.registrations.values():
        if other["id"] == reg["id"]:
            continue
        if other["property_id"] != reg["property_id"]:
            continue
        if other["municipality_code"] != reg["municipality_code"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        ovf = parse_date_str(other["valid_from"], "valid_from")
        ovt = parse_date_str(other["valid_to"], "valid_to")
        if vf < ovt and vt > ovf:
            return True
    return False


# =============================================================================
# fine_accrual
# =============================================================================

def compute_accrued_fine(v, on_date=None):
    if on_date is None:
        on_date = clock_date()
    deadline = parse_date_str(v["cure_deadline"], "cure_deadline")
    days_overdue = max(0, (on_date - deadline).days)
    return min(days_overdue * v["daily_fine_cents"], v["fine_cap_cents"])


def refresh_accrued_fine(v, on_date=None):
    """fine_accrual trigger: daily sweep and on read, for open statuses."""
    if v["status"] in VIOLATION_OPEN_STATUSES:
        v["accrued_fine_cents"] = compute_accrued_fine(v, on_date)


# =============================================================================
# property_condition_score
# =============================================================================

def _latest_completed_inspection(prop):
    latest = None
    for ins in store.inspections.values():
        if ins["property_id"] != prop["id"] or ins["status"] != "COMPLETED":
            continue
        key = (ins.get("recorded_at") or ins["created_at"], ins["_seq"])
        if latest is None or key > latest[0]:
            latest = (key, ins)
    return latest[1] if latest else None


def compute_condition_score(prop, on_date=None):
    if on_date is None:
        on_date = clock_date()
    score = 100

    vd = sum(
        CLASS_DEDUCT[v["violation_class"]]
        for v in store.violations.values()
        if v["property_id"] == prop["id"] and v["status"] in VIOLATION_OPEN_STATUSES
    )
    score -= min(45, vd)

    if not has_active_registration(prop, on_date):
        score -= 20

    open_reports = [
        d for d in store.damage_reports.values()
        if d["property_id"] == prop["id"] and d["status"] in DAMAGE_OPEN_STATUSES
    ]
    ext = sum(1 for d in open_reports if not d["is_interior"])
    score -= min(20, 10 * ext)

    latest = _latest_completed_inspection(prop)
    interior_inclusive = latest is not None and latest.get("interior_access") is True
    if interior_inclusive:
        interior = sum(1 for d in open_reports if d["is_interior"])
        score -= min(30, 15 * interior)

    if latest is not None:
        ref = latest.get("recorded_at") or latest["created_at"]
        ref_date = parse_date_str(ref[:10], "recorded_at")
    else:
        ref_date = parse_date_str(prop["created_at"][:10], "created_at")
    if (on_date - ref_date).days > 30:
        score -= 10

    return max(0, score)


def posture_for(score):
    if score >= 80:
        return "CLEAR"
    if score >= 50:
        return "AT_RISK"
    return "NON_COMPLIANT"


def recompute_property_score(prop, on_date=None):
    score = compute_condition_score(prop, on_date)
    bump_if_changed(prop, {
        "condition_score": score,
        "compliance_posture": posture_for(score),
    })


# =============================================================================
# hold_period
# =============================================================================

def hold_until_for(state_code, documented_date_str):
    days = HOLD_DAYS.get(state_code, HOLD_DAYS_DEFAULT)
    d = parse_date_str(documented_date_str, "documented_date")
    return (d + timedelta(days=days)).isoformat()


# =============================================================================
# recurring plan cancellation cascade
# =============================================================================

def cancel_work_order(wo):
    """Cancel an open work order; compensates plan.generated_this_season."""
    wo["status"] = "CANCELLED"
    bump(wo)
    if wo.get("source") == "RECURRING_AUTO" and wo.get("recurring_plan_id"):
        plan = store.plans.get(wo["recurring_plan_id"])
        if plan is not None:
            bump_if_changed(plan, {"generated_this_season": plan["generated_this_season"] - 1})


def suspend_plan_cascade(plan):
    """Cancel this plan's open RECURRING_AUTO orders with compensation."""
    for wo in list(store.work_orders.values()):
        if (
            wo.get("recurring_plan_id") == plan["id"]
            and wo.get("source") == "RECURRING_AUTO"
            and wo["status"] in ("ISSUED", "ASSIGNED")
        ):
            cancel_work_order(wo)


# =============================================================================
# allowable_reimbursement + prompt_pay_discount
# =============================================================================

def compute_allowable(invoice, inclusion_statuses):
    """Runs the allowable_reimbursement calculation for one invoice.

    Returns total allowed cents; mutates each line's allowed_cents / denial_reason.
    """
    wo = store.work_orders.get(invoice["work_order_id"])
    cap_per_occ, max_occurrences, aggregate_cap = (None, None, None)
    if wo is not None:
        cap_per_occ, max_occurrences, aggregate_cap = pinned_schedule(wo)

    year = None
    if invoice.get("submitted_at"):
        year = parse_date_str(invoice["submitted_at"][:10], "submitted_at").year

    lines = [l for l in store.expense_lines.values() if l["invoice_id"] == invoice["id"]]
    # Fixed evaluation order: created_at ASC, then unit_price_cents DESC.
    lines.sort(key=lambda l: (l["created_at"], -l["unit_price_cents"], l["_seq"]))

    # Prior invoices of the same property in the inclusion set, same calendar year.
    prior_lines_by_item = {}
    for other in store.invoices.values():
        if other["id"] == invoice["id"]:
            continue
        if other["property_id"] != invoice["property_id"]:
            continue
        if other["status"] not in inclusion_statuses:
            continue
        if not other.get("submitted_at"):
            continue
        if year is not None and parse_date_str(other["submitted_at"][:10], "submitted_at").year != year:
            continue
        for l in store.expense_lines.values():
            if l["invoice_id"] == other["id"]:
                prior_lines_by_item.setdefault(l["item_code"], []).append(l)

    remaining_budget = {}
    used_units = {}
    for item, plines in prior_lines_by_item.items():
        used_units[item] = sum(l["quantity"] for l in plines)
        used_cents = sum(l["allowed_cents"] or 0 for l in plines)
        if aggregate_cap is None:
            remaining_budget[item] = None  # unbounded
        else:
            remaining_budget[item] = max(0, aggregate_cap - used_cents)

    total = 0
    for l in lines:
        item = l["item_code"]
        u = used_units.get(item, 0)
        if max_occurrences is None:
            allowed_units = l["quantity"]
        else:
            allowed_units = min(l["quantity"], max(0, max_occurrences - u))
        unit_cap = l["unit_price_cents"] if cap_per_occ is None else min(l["unit_price_cents"], cap_per_occ)
        per_line_amount = allowed_units * unit_cap
        if item not in remaining_budget:
            remaining_budget[item] = None if aggregate_cap is None else max(0, aggregate_cap)
        budget = remaining_budget[item]
        if budget is None:
            allowed = per_line_amount
        else:
            allowed = min(per_line_amount, budget)
            remaining_budget[item] = budget - allowed

        # First applicable denial reason.
        if cap_per_occ is not None and l["unit_price_cents"] > cap_per_occ:
            reason = "PER_OCCURRENCE_CAP"
        elif allowed_units < l["quantity"]:
            reason = "OCCURRENCE_COUNT_EXCEEDED"
        elif allowed < per_line_amount:
            reason = "AGGREGATE_CAP_EXCEEDED"
        else:
            reason = None

        l["allowed_cents"] = allowed
        l["denial_reason"] = reason
        total += allowed

    return total


def compute_prompt_pay_discount(invoice):
    """Per-line 2% discount rounded half up, then summed (pinned rounding order)."""
    total_discount = 0
    for l in store.expense_lines.values():
        if l["invoice_id"] != invoice["id"]:
            continue
        disc = round_half_up_cents(Decimal(l["allowed_cents"] or 0) * PROMPT_PAY_RATE)
        l["line_discount_cents"] = disc
        total_discount += disc
    return total_discount


# =============================================================================
# ytd_rollup
# =============================================================================

def property_of_invoice(invoice):
    return store.properties.get(invoice["property_id"])


def ytd_add(prop, amount):
    bump_if_changed(prop, {"ytd_investor_approved_cents": prop["ytd_investor_approved_cents"] + amount})


def ytd_subtract(prop, amount):
    bump_if_changed(prop, {"ytd_investor_approved_cents": prop["ytd_investor_approved_cents"] - amount})


def evaluate_review_flag_on_approve(prop):
    if prop["ytd_investor_approved_cents"] >= PROPERTY_YTD_REVIEW_THRESHOLD_CENTS:
        bump_if_changed(prop, {"financial_review_required": True})


def reevaluate_review_flag(prop):
    if prop["ytd_investor_approved_cents"] < PROPERTY_YTD_REVIEW_THRESHOLD_CENTS:
        bump_if_changed(prop, {"financial_review_required": False})


# =============================================================================
# recurring_generation
# =============================================================================

def season_window(plan, year):
    start = date(year, int(plan["season_start_md"][:2]), int(plan["season_start_md"][3:5]))
    end = date(year, int(plan["season_end_md"][:2]), int(plan["season_end_md"][3:5]))
    return start, end


def generate_recurring_order(plan):
    """Generate one RECURRING_AUTO work order for the plan at the clock date."""
    prop = store.properties.get(plan["property_id"])
    today = clock_date()
    due = today + timedelta(days=plan["interval_days"])

    item_code = plan["service_type"]
    investor_allowable_id = None
    investor_allowable_version = None
    allowable_cap_cents = None
    requires_bid_over_cents = None
    row = select_allowable(prop["investor_type"], item_code) if prop else None
    if row is not None:
        investor_allowable_id = row["id"]
        investor_allowable_version = row["version"]
        allowable_cap_cents = row["max_per_occurrence_cents"]
        requires_bid_over_cents = row["requires_bid_over_cents"]

    wo = new_entity({
        "property_id": plan["property_id"],
        "servicer_id": prop["servicer_id"] if prop else None,
        "order_type": plan["service_type"],
        "item_code": item_code,
        "source": "RECURRING_AUTO",
        "status": "ISSUED",
        "due_date": due.isoformat(),
        "scheduled_date": None,
        "assigned_crew_id": None,
        "bid_id": None,
        "damage_report_id": None,
        "code_violation_id": None,
        "recurring_plan_id": plan["id"],
        "investor_allowable_id": investor_allowable_id,
        "investor_allowable_version": investor_allowable_version,
        "allowable_cap_cents": allowable_cap_cents,
        "requires_bid_over_cents": requires_bid_over_cents,
        "estimated_cost_cents": 0,
        "submitted_cost_cents": None,
        "approved_cost_cents": None,
        "rework_count": 0,
        "evidence_complete": False,
    })
    store.work_orders[wo["id"]] = wo
    bump_if_changed(plan, {
        "generated_this_season": plan["generated_this_season"] + 1,
        "last_generated_date": today.isoformat(),
    })
    return wo


# =============================================================================
# volume_rebate
# =============================================================================

def settle_volume_rebates():
    """Runs on daily sweep when the clock date is the 1st of a month."""
    today = clock_date()
    first_of_month = today.replace(day=1)
    prev_end = first_of_month - timedelta(days=1)
    prev_start = prev_end.replace(day=1)

    gross_by_servicer = {}
    for inv in store.invoices.values():
        approved_at = inv.get("approved_at")
        if not approved_at:
            continue
        d = parse_date_str(approved_at[:10], "approved_at")
        if not (prev_start <= d <= prev_end):
            continue
        prop = store.properties.get(inv["property_id"])
        if prop is None:
            continue
        sid = prop["servicer_id"]
        gross_by_servicer[sid] = gross_by_servicer.get(sid, 0) + (inv.get("approved_amount_cents") or 0)

    for svc in store.servicers.values():
        gross = gross_by_servicer.get(svc["id"], 0)
        if gross >= REBATE_TIER2_GROSS:
            rate = REBATE_TIER2_RATE
        elif gross >= REBATE_TIER1_GROSS:
            rate = REBATE_TIER1_RATE
        else:
            rate = Decimal("0")
        rebate = round_half_up_cents(Decimal(gross) * rate)
        bump_if_changed(svc, {
            "prior_month_gross_cents": gross,
            "volume_rebate_cents": rebate,
        })


# =============================================================================
# Daily operational sweep
# =============================================================================

def run_daily_sweep():
    today = clock_date()
    result = {
        "generated_work_order_ids": [],
        "expired_registration_ids": [],
        "escalated_violation_ids": [],
        "released_disposition_ids": [],
        "expired_work_order_ids": [],
        "missed_inspection_ids": [],
    }

    # 1. Recurring service generation for ACTIVE plans.
    for plan in sorted(store.plans.values(), key=lambda p: p["_seq"]):
        if plan["status"] != "ACTIVE":
            continue
        start, end = season_window(plan, today.year)
        if not (start <= today <= end):
            continue
        last = plan.get("last_generated_date")
        if last is not None:
            if (today - parse_date_str(last, "last_generated_date")).days < plan["interval_days"]:
                continue
        if plan["generated_this_season"] >= plan["max_per_season"]:
            continue
        prop = store.properties.get(plan["property_id"])
        if prop is None or prop["status"] != "ACTIVE" or prop["occupancy_status"] == "OCCUPIED":
            continue
        wo = generate_recurring_order(plan)
        result["generated_work_order_ids"].append(wo["id"])

    # 2. Registration expiry: ACTIVE -> EXPIRED once clock date reaches valid_to.
    for reg in sorted(store.registrations.values(), key=lambda r: r["_seq"]):
        if reg["status"] == "ACTIVE" and today >= parse_date_str(reg["valid_to"], "valid_to"):
            reg["status"] = "EXPIRED"
            bump(reg)
            result["expired_registration_ids"].append(reg["id"])
            prop = store.properties.get(reg["property_id"])
            if prop is not None:
                recompute_property_score(prop)

    # 3. Violation escalation past cure deadline.
    for v in sorted(store.violations.values(), key=lambda x: x["_seq"]):
        if v["status"] in ("OPEN", "CURE_IN_PROGRESS") and today > parse_date_str(v["cure_deadline"], "cure_deadline"):
            was_open = v["status"] == "OPEN"
            v["status"] = "ESCALATED"
            v["accrued_fine_cents"] = compute_accrued_fine(v)
            bump(v)
            result["escalated_violation_ids"].append(v["id"])
            if was_open:
                prop = store.properties.get(v["property_id"])
                if prop is not None:
                    recompute_property_score(prop)
        elif v["status"] in VIOLATION_OPEN_STATUSES:
            refresh_accrued_fine(v)

    # 4. Personal property hold release (inclusive boundary).
    for d in sorted(store.dispositions.values(), key=lambda x: x["_seq"]):
        if d["status"] == "IN_HOLD" and today >= parse_date_str(d["hold_until_date"], "hold_until_date"):
            d["status"] = "RELEASE_ELIGIBLE"
            bump(d)
            result["released_disposition_ids"].append(d["id"])

    # 5. Work order expiry: ISSUED/ASSIGNED past due_date.
    for wo in sorted(store.work_orders.values(), key=lambda x: x["_seq"]):
        if wo["status"] in ("ISSUED", "ASSIGNED") and today > parse_date_str(wo["due_date"], "due_date"):
            wo["status"] = "EXPIRED"
            bump(wo)
            result["expired_work_order_ids"].append(wo["id"])
            if wo.get("source") == "RECURRING_AUTO" and wo.get("recurring_plan_id"):
                plan = store.plans.get(wo["recurring_plan_id"])
                if plan is not None:
                    bump_if_changed(plan, {"generated_this_season": plan["generated_this_season"] - 1})

    # 6. Inspection miss: SCHEDULED past due_date.
    for ins in sorted(store.inspections.values(), key=lambda x: x["_seq"]):
        if ins["status"] == "SCHEDULED" and today > parse_date_str(ins["due_date"], "due_date"):
            ins["status"] = "MISSED"
            bump(ins)
            result["missed_inspection_ids"].append(ins["id"])

    # 7. Posture recompute for all properties.
    for prop in store.properties.values():
        recompute_property_score(prop)

    # 8. Year rollover of ytd counters on first sweep of a new calendar year.
    for prop in store.properties.values():
        if prop["ytd_calendar_year"] != today.year:
            bump_if_changed(prop, {
                "ytd_investor_approved_cents": 0,
                "ytd_calendar_year": today.year,
                "financial_review_required": False,
            })

    # 9. Monthly volume rebate settlement on the 1st.
    if today.day == 1:
        settle_volume_rebates()

    return result
