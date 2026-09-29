"""All 17 calculations from SCAFFOLD §1.3 / PRD §3."""
from datetime import timedelta
from fractions import Fraction

from core import db, ordered, round_half_up, whole_days_between

# --- staple_criterion_a_qualification -------------------------------------
STAPLE_CATEGORIES = ["BREAD_CEREAL", "DAIRY", "FRUIT_VEG", "MEAT_POULTRY_FISH"]
MIN_VARIETIES_PER_CATEGORY = 3
MIN_UNITS_PER_VARIETY = 3
AGGREGATE_UNITS_PER_CATEGORY = 9
MIN_QUALIFYING_CATEGORIES = 4
MIN_PERISHABLE_CATEGORIES = 2


def criterion_a(lines, variant):
    """Returns (qualifying_categories, perishable_categories, passes)."""
    lines = lines or []
    qualifying = 0
    perishable = 0
    for category in STAPLE_CATEGORIES:
        rows = [l for l in lines if l.get("category") == category]
        if not rows:
            continue
        if variant == "DESK_VARIETY_FIRST":
            varieties = {}
            for row in rows:
                varieties.setdefault(row.get("variety_key"), []).append(row)
            distinct = len(varieties)
            aggregate = sum(int(r.get("unit_count") or 0) for r in rows)
            qualifies = (distinct >= MIN_VARIETIES_PER_CATEGORY
                         and aggregate >= AGGREGATE_UNITS_PER_CATEGORY)
            contributing = rows
        else:  # ONSITE_DEPTH_FIRST
            deep = {}
            for row in rows:
                if int(row.get("unit_count") or 0) >= MIN_UNITS_PER_VARIETY:
                    deep.setdefault(row.get("variety_key"), []).append(row)
            qualifies = len(deep) >= MIN_VARIETIES_PER_CATEGORY
            contributing = [r for group in deep.values() for r in group]
        if qualifies:
            qualifying += 1
            if any(bool(r.get("is_perishable")) for r in contributing):
                perishable += 1
    passes = (qualifying == MIN_QUALIFYING_CATEGORIES
              and perishable >= MIN_PERISHABLE_CATEGORIES)
    return qualifying, perishable, passes


# --- criterion_b_staple_sales_share ---------------------------------------
CRITERION_B_MIN_BPS = 5000


def criterion_b(annual_staple_sales_cents, annual_gross_sales_cents):
    if not annual_gross_sales_cents:
        return 0, False
    bps = (annual_staple_sales_cents * 10000) // annual_gross_sales_cents
    return bps, bps > CRITERION_B_MIN_BPS


# --- depth_of_stock_assessment --------------------------------------------
MIN_SHELF_LINEAR_FEET = {
    "SUPERMARKET": 120,
    "GROCERY": 60,
    "CONVENIENCE": 24,
    "SPECIALTY": 16,
    "FARMERS_MARKET": 0,
    "MEAL_SERVICE": 0,
}
SHELF_DISCREPANCY_FLAG_BPS = 2500


def depth_of_stock(observed_ft, store):
    floor_ft = MIN_SHELF_LINEAR_FEET.get(store["store_type"], 0)
    reported = store["staple_shelf_linear_feet"]
    depth_pass = observed_ft >= floor_ft
    bps = (abs(observed_ft - reported) * 10000) // max(reported, 1)
    return depth_pass, bps, bps > SHELF_DISCREPANCY_FLAG_BPS


# --- pos_eligibility_split_tender -----------------------------------------
ELIGIBLE_ITEM_CLASSES = ["STAPLE_FOOD", "NONSTAPLE_FOOD", "SEED_PLANT"]
INELIGIBLE_ITEM_CLASSES = ["HOT_PREPARED", "ALCOHOL", "TOBACCO", "NONFOOD",
                           "ENERGY_DRINK_SUPPLEMENT", "LIVE_ANIMAL"]
ITEM_CLASSES = ELIGIBLE_ITEM_CLASSES + INELIGIBLE_ITEM_CLASSES


def pos_split_tender(line_items, snap_available, other_offered, tax_rate_bps):
    eligible = 0
    ineligible = 0
    flagged = []
    for line in line_items:
        extended = int(line["unit_price_cents"]) * int(line["qty"])
        if line["item_class"] in ELIGIBLE_ITEM_CLASSES:
            eligible += extended
        else:
            ineligible += extended
            flagged.append(line["sku"])
    result = {
        "eligible_subtotal_cents": eligible,
        "ineligible_subtotal_cents": ineligible,
        "flagged_line_skus": flagged,
    }
    if eligible == 0:
        result.update({
            "tax_cents": 0,
            "ebt_tender_cents": 0,
            "other_tender_cents": 0,
            "split_tender_applied": False,
            "status": "DECLINED",
            "decline_reason_code": "NO_ELIGIBLE_ITEMS",
            "error_id": "ERR_NO_ELIGIBLE_ITEMS",
        })
        return result
    tax = round_half_up(Fraction(ineligible * tax_rate_bps, 10000))
    ebt = min(eligible, snap_available)
    shortfall = eligible - ebt
    required = ineligible + tax + shortfall
    result["tax_cents"] = tax
    if other_offered < required:
        result.update({
            "ebt_tender_cents": 0,
            "other_tender_cents": 0,
            "split_tender_applied": False,
            "status": "DECLINED",
            "decline_reason_code": "INSUFFICIENT_SPLIT_TENDER",
            "error_id": "ERR_SPLIT_TENDER_SHORTFALL",
        })
        return result
    result.update({
        "ebt_tender_cents": ebt,
        "other_tender_cents": required,
        "split_tender_applied": required > 0,
        "status": "AUTHORIZED",
        "decline_reason_code": None,
        "error_id": None,
    })
    return result


# --- redemption_period_metrics --------------------------------------------
LARGE_TXN_THRESHOLD_CENTS = 10000
EVEN_DOLLAR_UNIT_CENTS = 1000
RECON_TOLERANCE_CENTS = 500


def included_pos_rows(period):
    rows = []
    for txn in db.pos_transactions.values():
        if txn["store_id"] != period["store_id"]:
            continue
        if txn["status"] != "AUTHORIZED":
            continue
        if period["period_start"] <= txn["created_at"] < period["period_end"]:
            rows.append(txn)
    return ordered(rows)


def period_metrics(period):
    rows = included_pos_rows(period)
    pos_total = sum(r["ebt_tender_cents"] for r in rows)
    pos_count = len(rows)
    pos_large = sum(r["ebt_tender_cents"] for r in rows
                    if r["ebt_tender_cents"] >= LARGE_TXN_THRESHOLD_CENTS)
    pos_even = sum(1 for r in rows
                   if r["ebt_tender_cents"] > 0
                   and r["ebt_tender_cents"] % EVEN_DOLLAR_UNIT_CENTS == 0)
    imported = period.get("imported_total_cents")
    out = {
        "pos_derived_total_cents": pos_total,
        "pos_derived_transaction_count": pos_count,
    }
    if imported is not None:
        out["redemption_total_cents"] = imported
        out["transaction_count"] = period.get("imported_transaction_count")
        out["large_transaction_cents"] = period.get("imported_large_transaction_cents")
        out["even_dollar_transaction_count"] = period.get(
            "imported_even_dollar_transaction_count")
        variance = imported - pos_total
        out["reconciliation_variance_cents"] = variance
        out["reconciliation_status"] = (
            "VARIANCE" if abs(variance) > RECON_TOLERANCE_CENTS else "MATCHED")
    else:
        out["redemption_total_cents"] = pos_total
        out["transaction_count"] = pos_count
        out["large_transaction_cents"] = pos_large
        out["even_dollar_transaction_count"] = pos_even
        out["reconciliation_variance_cents"] = None
        out["reconciliation_status"] = "NOT_IMPORTED"
    return out


# --- redemption_anomaly_score --------------------------------------------
LANE_BASE_CENTS = 400000
SHELF_FOOT_CENTS = 15000
MIN_EXPECTATION_CENTS = 100000
EXCESS_SPAN_BPS = 20000
LARGE_SHARE_CAP = Fraction(1, 2)
EVEN_SHARE_CAP = Fraction(2, 5)
WEIGHTS_DEFAULT = {"excess": 50, "large": 30, "even": 20}
WEIGHTS_SMALL_FORMAT = {"excess": 45, "large": 35, "even": 20}
WEIGHTS_FARMERS_MARKET = {"excess": 20, "large": 30, "even": 50}


def anomaly_score(period_values, store):
    footprint = (store["checkout_lane_count"] * LANE_BASE_CENTS
                 + store["staple_shelf_linear_feet"] * SHELF_FOOT_CENTS)
    from_sales = store["annual_gross_sales_cents"] // 12
    size_expectation = max(MIN_EXPECTATION_CENTS, min(footprint, from_sales))

    total = period_values.get("redemption_total_cents") or 0
    count = period_values.get("transaction_count") or 0
    large = period_values.get("large_transaction_cents") or 0
    even = period_values.get("even_dollar_transaction_count") or 0

    ratio_bps = (total * 10000) // size_expectation
    excess = min(Fraction(1), Fraction(max(0, ratio_bps - 10000), EXCESS_SPAN_BPS))
    large_share = Fraction(large, max(total, 1))
    large_component = min(Fraction(1), large_share / LARGE_SHARE_CAP)
    even_share = Fraction(even, max(count, 1))
    even_component = min(Fraction(1), even_share / EVEN_SHARE_CAP)

    if store["store_type"] in ("CONVENIENCE", "SPECIALTY"):
        weights = WEIGHTS_SMALL_FORMAT
    elif store["store_type"] == "FARMERS_MARKET":
        weights = WEIGHTS_FARMERS_MARKET
    else:
        weights = WEIGHTS_DEFAULT

    weighted = (weights["excess"] * excess + weights["large"] * large_component
                + weights["even"] * even_component)
    score = min(100, round_half_up(weighted))
    return size_expectation, score


# --- store_redemption_flag_level -----------------------------------------
FLAG_L1_MIN = 25
FLAG_L2_MIN = 50
FLAG_L3_MIN = 70


def flag_level_for(score):
    if score >= FLAG_L3_MIN:
        return "FLAG_L3"
    if score >= FLAG_L2_MIN:
        return "FLAG_L2"
    if score >= FLAG_L1_MIN:
        return "FLAG_L1"
    return "FLAG_L0"


def store_flag_level(store_id):
    closed = [p for p in db.redemption_periods.values()
              if p["store_id"] == store_id and p["status"] == "CLOSED"]
    if not closed:
        return "FLAG_L0"
    closed.sort(key=lambda p: (-p["period_index"], p["created_at"], p.get("_seq", 0)))
    return closed[0].get("flag_level") or "FLAG_L0"


# --- trafficking_confidence_score ----------------------------------------
EVIDENCE_BASE_POINTS = {
    "UNDERCOVER_BUY": 40,
    "INVENTORY_PURCHASE_MISMATCH": 25,
    "EBT_ONLY_TRANSACTION_PATTERN": 20,
    "INFORMANT_STATEMENT": 15,
    "HOUSEHOLD_INTERVIEW": 10,
}
EVIDENCE_TYPES = list(EVIDENCE_BASE_POINTS.keys())
SUBSTANTIATION_MIN_SCORE = 60
ANCHOR_TYPES = ("UNDERCOVER_BUY", "INVENTORY_PURCHASE_MISMATCH")


def decay_multiplier(age_days):
    if age_days <= 180:
        return Fraction(1)
    if age_days <= 365:
        return Fraction(3, 4)
    if age_days <= 730:
        return Fraction(1, 2)
    return Fraction(0)


def evidence_multiplier(item, current):
    observed = item["observed_at"]
    age_days = whole_days_between(current, observed)
    return decay_multiplier(age_days)


def trafficking_score(items, current):
    total = Fraction(0)
    for item in items or []:
        base = EVIDENCE_BASE_POINTS.get(item.get("evidence_type"), 0)
        total += base * evidence_multiplier(item, current)
    return min(100, round_half_up(total))


def has_live_anchor(items, current):
    for item in items or []:
        if (item.get("evidence_type") in ANCHOR_TYPES
                and evidence_multiplier(item, current) > 0):
            return True
    return False


def has_live_item(items, current):
    for item in items or []:
        if evidence_multiplier(item, current) > 0:
            return True
    return False


# --- disqualification_period_months --------------------------------------
TRAFFICKING_ALLOWED_SANCTIONS = ("PERMANENT_DISQUALIFICATION", "CMP_IN_LIEU")
HARDSHIP_ALLOWED_SANCTIONS = ("TEMPORARY_DISQUALIFICATION", "CMP_IN_LIEU")
STOCK_FAILURE_ALLOWED_SANCTIONS = ("WARNING", "TEMPORARY_DISQUALIFICATION")

ALLOWED_SANCTIONS = {
    "TRAFFICKING": TRAFFICKING_ALLOWED_SANCTIONS,
    "INELIGIBLE_ITEMS_HARDSHIP": HARDSHIP_ALLOWED_SANCTIONS,
    "STOCK_FAILURE": STOCK_FAILURE_ALLOWED_SANCTIONS,
}


def prior_final_sanction_count(case, store):
    owner_id = store["owner_id"]
    store_ids = {s["id"] for s in db.stores.values() if s["owner_id"] == owner_id}
    store_ids.add(store["id"])
    count = 0
    for other in db.sanction_cases.values():
        if other["id"] == case["id"]:
            continue
        if other["store_id"] not in store_ids:
            continue
        if other["status"] not in ("SANCTION_FINAL", "ENFORCED"):
            continue
        if other.get("sanction_type") in ("PERMANENT_DISQUALIFICATION",
                                          "TEMPORARY_DISQUALIFICATION"):
            count += 1
    return count


def disqualification_months(violation_type, sanction_type, prior):
    """Months of disqualification, or None."""
    if sanction_type == "WARNING":
        return None
    if violation_type == "TRAFFICKING":
        if sanction_type == "PERMANENT_DISQUALIFICATION":
            return None
        return None  # CMP_IN_LIEU on trafficking uses the fixed 10-month multiplier
    if violation_type == "INELIGIBLE_ITEMS_HARDSHIP":
        if prior == 0:
            return 3
        if prior == 1:
            return 6
        return 12
    if violation_type == "STOCK_FAILURE":
        return 0 if prior == 0 else 6
    return None


# --- civil_money_penalty_amount ------------------------------------------
CMP_RATE_BPS = 1000
CMP_CAP_CENTS = 6900000
TRAFFICKING_CMP_MONTHS = 10
SEASONING_DAYS = 365
TRAILING_PERIOD_COUNT = 12
PEAK_PERIOD_COUNT = 3


def cmp_basis_pool(store_id, as_of):
    return [p for p in db.redemption_periods.values()
            if p["store_id"] == store_id and p["status"] == "CLOSED"
            and p["period_end"] <= as_of]


def cmp_quote(store, as_of, month_multiplier):
    """Returns dict of CMP fields, or None when the basis pool is empty."""
    pool = cmp_basis_pool(store["id"], as_of)
    if not pool:
        return None
    authorized_at = store.get("authorized_at")
    if authorized_at is None:
        basis_days = 0
    else:
        basis_days = whole_days_between(as_of, authorized_at)
    if basis_days >= SEASONING_DAYS:
        variant = "TRAILING_12_PERIOD_AVERAGE"
        basis = sorted(pool, key=lambda p: -p["period_index"])
        basis = basis[:min(len(pool), TRAILING_PERIOD_COUNT)]
    else:
        variant = "PEAK_3_PERIOD_AVERAGE"
        basis = sorted(pool, key=lambda p: (-(p.get("redemption_total_cents") or 0),
                                            -p["period_index"],
                                            p["created_at"], p.get("_seq", 0)))
        basis = basis[:min(len(pool), PEAK_PERIOD_COUNT)]
    total = sum((p.get("redemption_total_cents") or 0) for p in basis)
    avg = round_half_up(Fraction(total, len(basis)))
    monthly = round_half_up(Fraction(avg * CMP_RATE_BPS, 10000))
    multiplier = month_multiplier or 0
    product = monthly * multiplier
    return {
        "cmp_basis_variant": variant,
        "cmp_basis_period_ids": [p["id"] for p in basis],
        "avg_monthly_redemption_cents": avg,
        "monthly_penalty_cents": monthly,
        "cmp_amount_cents": min(product, CMP_CAP_CENTS),
        "cmp_capped": product > CMP_CAP_CENTS,
    }


def cmp_month_multiplier(violation_type, months):
    if violation_type == "TRAFFICKING":
        return TRAFFICKING_CMP_MONTHS
    return months or 0


# --- cmp_in_lieu_eligibility ---------------------------------------------
CMP_ELECTION_WINDOW_DAYS = 10


def cmp_in_lieu_available(case, store):
    if not store.get("hardship_designated"):
        return False
    due = case.get("cmp_election_due_at")
    elections = [e for e in db.cmp_elections.values()
                 if e["sanction_case_id"] == case["id"] and e["status"] == "ELECTED"]
    if due is None or not any(e["elected_at"] < due for e in elections):
        return False
    owner_id = store["owner_id"]
    store_ids = {s["id"] for s in db.stores.values() if s["owner_id"] == owner_id}
    for other in db.sanction_cases.values():
        if other["store_id"] in store_ids \
                and other["status"] in ("SANCTION_FINAL", "ENFORCED") \
                and other.get("violation_type") == "TRAFFICKING":
            return False
    return True


# --- penalty_ledger_balance ----------------------------------------------
def case_ledger_entries(case_id):
    return ordered([e for e in db.penalty_ledger_entries.values()
                    if e["sanction_case_id"] == case_id])


def case_outstanding(case_id):
    return sum(e["amount_cents"] for e in case_ledger_entries(case_id))


def append_ledger_entry(case, entry_type, amount_cents, reason_code):
    from core import new_id, now
    entry = {
        "id": new_id(),
        "created_at": now(),
        "_seq": db.next_seq(),
        "sanction_case_id": case["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reason_code": reason_code,
    }
    db.penalty_ledger_entries[entry["id"]] = entry
    entry["balance_after_cents"] = case_outstanding(case["id"])
    case["cmp_outstanding_cents"] = entry["balance_after_cents"]
    return entry


def recompute_balances(case_id):
    running = 0
    for entry in case_ledger_entries(case_id):
        running += entry["amount_cents"]
        entry["balance_after_cents"] = running
    return running


# --- depot_unit_ledger ---------------------------------------------------
def depot_counters(depot):
    terminals = [t for t in db.ebt_terminals.values() if t["depot_id"] == depot["id"]]
    counts = {"RESERVED": 0, "DEPLOYED": 0, "PENDING_RETURN": 0, "RETIRED": 0}
    for terminal in terminals:
        if terminal["status"] in counts:
            counts[terminal["status"]] += 1
    reserved = counts["RESERVED"]
    deployed = counts["DEPLOYED"]
    pending = counts["PENDING_RETURN"]
    retired = counts["RETIRED"]
    return {
        "units_reserved": reserved,
        "units_deployed": deployed,
        "units_pending_return": pending,
        "units_retired": retired,
        "units_in_stock": depot["total_units_owned"] - reserved - deployed
                          - pending - retired,
    }


# --- inspector_committed_minutes -----------------------------------------
TRAVEL_BUFFER_MINUTES = 60
TRAVEL_BUFFER = timedelta(minutes=TRAVEL_BUFFER_MINUTES)
COMMITTED_VISIT_STATUSES = ("SCHEDULED", "IN_PROGRESS")


def window_minutes(window_start, window_end):
    return int((window_end - window_start).total_seconds() // 60)


def inspector_committed_minutes(inspector_id):
    total = 0
    for visit in db.store_visits.values():
        if visit["inspector_id"] == inspector_id \
                and visit["status"] in COMMITTED_VISIT_STATUSES:
            total += visit["window_minutes"]
    return total


def inspector_day_minutes(inspector_id, day):
    total = 0
    for visit in db.store_visits.values():
        if visit["inspector_id"] != inspector_id:
            continue
        if visit["status"] not in COMMITTED_VISIT_STATUSES:
            continue
        if visit["window_start"].date() == day:
            total += visit["window_minutes"]
    return total


# --- equipment_order_totals ----------------------------------------------
UNIT_PRICE_CENTS = {
    "EBT_ONLY_WIRELESS_TERMINAL": 42500,
    "EBT_ONLY_DIAL_TERMINAL": 31000,
    "COMMERCIAL_POS_INTEGRATION": 185000,
    "MANUAL_VOUCHER_KIT": 4500,
    "SIGNAGE_PACK": 2200,
    "RECEIPT_PAPER_CASE": 4000,
}
ITEM_CODES = list(UNIT_PRICE_CENTS.keys())
SUBSIDIZED_ITEM_CODES = ("EBT_ONLY_WIRELESS_TERMINAL", "EBT_ONLY_DIAL_TERMINAL",
                         "MANUAL_VOUCHER_KIT", "SIGNAGE_PACK")
SUBSIDY_SALES_CEILING_CENTS = 500000000
FREE_HANDLING_THRESHOLD_CENTS = 25000
HANDLING_FEE_CENTS = 1500


def equipment_totals(lines, store):
    subtotal = 0
    subsidizable = 0
    for line in lines:
        price = UNIT_PRICE_CENTS[line["item_code"]] * int(line["qty"])
        subtotal += price
        if line["item_code"] in SUBSIDIZED_ITEM_CODES:
            subsidizable += price
    eligible = (store["authorization_status"] == "AUTHORIZED"
                and store["annual_gross_sales_cents"] <= SUBSIDY_SALES_CEILING_CENTS)
    subsidy = subsidizable if eligible else 0
    net = subtotal - subsidy
    if net == 0:
        fee = 0
    elif net >= FREE_HANDLING_THRESHOLD_CENTS:
        fee = 0
    else:
        fee = HANDLING_FEE_CENTS
    return {
        "subtotal_cents": subtotal,
        "subsidy_cents": subsidy,
        "net_equipment_cents": net,
        "handling_fee_cents": fee,
        "total_due_cents": net + fee,
    }


# --- owner_sanction_rollup -----------------------------------------------
BARRED_PERMANENT_DQ_COUNT = 2


def owner_rollup(owner_id):
    store_ids = {s["id"] for s in db.stores.values() if s["owner_id"] == owner_id}
    perm = 0
    outstanding = 0
    for case in db.sanction_cases.values():
        if case["store_id"] not in store_ids:
            continue
        if case["status"] in ("SANCTION_FINAL", "ENFORCED") \
                and case.get("sanction_type") == "PERMANENT_DISQUALIFICATION":
            perm += 1
        outstanding += case.get("cmp_outstanding_cents") or 0
    if perm >= 1:
        flag = "PERMANENTLY_DISQUALIFIED"
    elif outstanding > 0:
        flag = "HAS_ACTIVE_CMP_DEBT"
    else:
        flag = "CLEAR"
    return {
        "permanent_disqualification_count": perm,
        "cmp_outstanding_cents": outstanding,
        "sanction_flag": flag,
        "status": "BARRED" if perm >= BARRED_PERMANENT_DQ_COUNT else "ACTIVE",
    }


# --- interval_overlap_rules ----------------------------------------------
def visit_conflicts(inspector_id, start, end, exclude_id=None):
    for visit in db.store_visits.values():
        if visit["inspector_id"] != inspector_id:
            continue
        if visit["id"] == exclude_id:
            continue
        if visit["status"] not in COMMITTED_VISIT_STATUSES:
            continue
        if start < visit["window_end"] + TRAVEL_BUFFER \
                and visit["window_start"] - TRAVEL_BUFFER < end:
            return True
    return False


OPEN_DEPLOYMENT_STATUSES = ("RESERVED", "ACTIVE", "RECALL_PENDING")


def deployment_conflicts(terminal_id, start, end, exclude_id=None):
    for dep in db.terminal_deployments.values():
        if dep["terminal_id"] != terminal_id:
            continue
        if dep["id"] == exclude_id:
            continue
        if dep["status"] not in OPEN_DEPLOYMENT_STATUSES:
            continue
        if start <= dep["deploy_end"] and dep["deploy_start"] <= end:
            return True
    return False


def store_slot_peak(store_id, start, end, exclude_id=None):
    """Max number of existing open deployments overlapping any instant in
    [start, end] (closed interval)."""
    existing = []
    for dep in db.terminal_deployments.values():
        if dep["store_id"] != store_id:
            continue
        if dep["id"] == exclude_id:
            continue
        if dep["status"] not in OPEN_DEPLOYMENT_STATUSES:
            continue
        if dep["deploy_start"] <= end and start <= dep["deploy_end"]:
            existing.append(dep)
    if not existing:
        return 0
    candidates = [start] + [d["deploy_start"] for d in existing if start <= d["deploy_start"] <= end]
    peak = 0
    for instant in candidates:
        count = sum(1 for d in existing
                    if d["deploy_start"] <= instant <= d["deploy_end"])
        peak = max(peak, count)
    return peak


def period_overlaps(store_id, start, end, exclude_id=None):
    for period in db.redemption_periods.values():
        if period["store_id"] != store_id:
            continue
        if period["id"] == exclude_id:
            continue
        if start < period["period_end"] and period["period_start"] < end:
            return True
    return False
