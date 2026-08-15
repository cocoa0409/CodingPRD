"""Domain services: logical-clock sweep, scan pricing, inventory ledger,
shrink audit cascades, settlement math, and seasonal penalties.

Every formula traces to scaffold Section 1.3 / PRD Section 3. All money is
integer cents; every rounding is round half-up (0.5 away from zero).
"""
import datetime
from decimal import Decimal

from db import store, fmt_dt, fmt_date
from common import (
    new_entity, touch, rhu, dec, add_days, add_months, months_between,
)

CATEGORIES = ["SNACKS", "BEVERAGES", "IMPULSE", "HOUSEWARES", "SEASONAL", "PERSONAL_CARE"]
CADENCES = ["WEEKLY", "BIWEEKLY", "MONTHLY"]
LIVE_AGREEMENT_STATES = {"DRAFT", "PENDING_ACCEPTANCE", "ACTIVE", "SUSPENDED"}

# Seasonal teardown penalty constants (scaffold Section 1.3).
GRACE_DAYS = 2
PENALTY_PER_DAY_CENTS = 2500
PENALTY_CAP_CENTS = 100000

# Blended-retail shrink valuation weights (scaffold Section 1.3).
COST_W = Decimal("0.6")
RETAIL_W = Decimal("0.4")

# Retailer margin split constants (scaffold Section 1.3).
PROMO_DRAG_PCT = Decimal("0.01")
PROMO_DRAG_SHARE = Decimal("0.30")


# =============================================================================
# Logical clock sweep (PRD Section 2.6)
# =============================================================================

def run_sweep():
    """Fire every automatic time-based transition; return the count."""
    count = 0
    today = store.today_str()
    now = store.now_iso()

    # 1. Scheduled service visits whose scheduled_date has passed -> MISSED.
    for v in list(store.service_visits.values()):
        if v["status"] == "SCHEDULED" and v["scheduled_date"] < today:
            v["status"] = "MISSED"
            touch(v)
            count += 1

    # 2. Promotions: SCHEDULED -> ACTIVE when the window covers the clock;
    #    ACTIVE | SUSPENDED -> ENDED once end_date has passed.
    for p in list(store.promotions.values()):
        if p["status"] == "SCHEDULED" and p["start_date"] <= today <= p["end_date"]:
            p["status"] = "ACTIVE"
            touch(p)
            count += 1
        elif p["status"] in ("ACTIVE", "SUSPENDED") and today > p["end_date"]:
            p["status"] = "ENDED"
            touch(p)
            count += 1

    # 3. Approved markdowns still unapplied 14 days after approval -> EXPIRED.
    for m in list(store.markdown_authorizations.values()):
        if m["status"] == "APPROVED" and m.get("approved_at"):
            approved_date = m["approved_at"][:10]
            expiry = fmt_date(add_days(datetime.date.fromisoformat(approved_date), 14))
            if today > expiry:
                m["status"] = "EXPIRED"
                touch(m)
                count += 1

    # 4. Active-season sets past teardown_deadline -> TEARDOWN_DUE.
    for s in list(store.seasonal_sets.values()):
        if s["status"] == "ACTIVE_SEASON" and today > s["teardown_deadline"]:
            s["status"] = "TEARDOWN_DUE"
            touch(s)
            count += 1

    # 5. Planned space allocations whose window has opened -> ACTIVE,
    #    provided the agreement is ACTIVE at that moment.
    for a in list(store.space_allocations.values()):
        if a["status"] == "PLANNED" and a["window_start_date"] <= today < a["window_end_date"]:
            agreement = store.agreements.get(a["store_agreement_id"])
            if agreement is not None and agreement["status"] == "ACTIVE":
                a["status"] = "ACTIVE"
                touch(a)
                count += 1

    # 6. Scheduled price directives reaching effectivity -> EFFECTIVE,
    #    superseding the incumbent EFFECTIVE directive for (agreement, product).
    scheduled = [
        d for d in store.price_directives.values()
        if d["status"] == "SCHEDULED" and d["effective_from"] <= now
    ]
    scheduled.sort(key=lambda d: (d["effective_from"], d["_seq"]))
    for d in scheduled:
        incumbent = _effective_directive(d["store_agreement_id"], d["product_id"])
        if incumbent is not None:
            incumbent["status"] = "SUPERSEDED"
            incumbent["superseded_at"] = now
            touch(incumbent)
            count += 1
        d["status"] = "EFFECTIVE"
        touch(d)
        count += 1

    return count


# =============================================================================
# Price directives and promotions (PRD Sections 3.2 / 3.3)
# =============================================================================

def _effective_directive(agreement_id, product_id):
    """The single EFFECTIVE directive for (agreement, product), if any."""
    for d in store.price_directives.values():
        if (
            d["store_agreement_id"] == agreement_id
            and d["product_id"] == product_id
            and d["status"] == "EFFECTIVE"
        ):
            return d
    return None


def directive_at(agreement_id, product_id, at_iso):
    """EFFECTIVE directive for (agreement, product) with effective_from <= at."""
    d = _effective_directive(agreement_id, product_id)
    if d is not None and d["effective_from"] <= at_iso:
        return d
    return None


def active_promotion(program_id, product_id, date_str):
    """ACTIVE promotion covering date_str (closed window). Eligibility when
    several match: greatest depth_pct; tie-break earliest start_date, then
    created_at ASC (PRD Section 3.6)."""
    candidates = [
        p for p in store.promotions.values()
        if p["program_id"] == program_id
        and p["product_id"] == product_id
        and p["status"] == "ACTIVE"
        and p["start_date"] <= date_str <= p["end_date"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["start_date"], p["_seq"]))
    best = None
    best_depth = None
    for p in candidates:
        depth = dec(p["depth_pct"])
        if best is None or depth > best_depth:
            best = p
            best_depth = depth
    return best


# =============================================================================
# Inventory balances (PRD Section 3.6)
# =============================================================================

def get_balance(agreement_id, product_id):
    for b in store.inventory_balances.values():
        if b["store_agreement_id"] == agreement_id and b["product_id"] == product_id:
            return b
    return None


def get_or_create_balance(agreement_id, product_id):
    """Auto-created on first confirmed restock or first matched scan."""
    b = get_balance(agreement_id, product_id)
    if b is not None:
        return b
    product = store.products[product_id]
    b = new_entity({
        "store_agreement_id": agreement_id,
        "product_id": product_id,
        "on_hand_units": 0,
        "lifetime_delivered_units": 0,
        "lifetime_scanned_units": 0,
        "lifetime_customer_return_units": 0,
        "lifetime_shrink_units": 0,
        "lifetime_rma_units": 0,
        "reorder_point_units": product["units_per_facing"],
        "stock_posture": "DEPLETED",
    })
    store.inventory_balances[b["id"]] = b
    return b


def recompute_posture(balance):
    """DEPLETED (on_hand <= 0) | LOW (0 < on_hand <= reorder) | NORMAL."""
    product = store.products.get(balance["product_id"])
    if product is not None:
        balance["reorder_point_units"] = product["units_per_facing"]
    on_hand = balance["on_hand_units"]
    if on_hand <= 0:
        balance["stock_posture"] = "DEPLETED"
    elif on_hand <= balance["reorder_point_units"]:
        balance["stock_posture"] = "LOW"
    else:
        balance["stock_posture"] = "NORMAL"


def reorder_cascade(balance):
    """PRD Section 3.6: when a matched scan leaves a balance at/below its
    reorder point, flag the agreement's next SCHEDULED visit."""
    if balance["on_hand_units"] > balance["reorder_point_units"]:
        return
    today = store.today_str()
    candidates = [
        v for v in store.service_visits.values()
        if v["store_agreement_id"] == balance["store_agreement_id"]
        and v["status"] == "SCHEDULED"
        and v["scheduled_date"] >= today
    ]
    if not candidates:
        return  # empty candidate set: no visit is mutated, no error
    target = min(candidates, key=lambda v: (v["scheduled_date"], v["_seq"]))
    target["auto_restock_flag"] = True
    target["suggested_restock_units"] = max(
        0, 2 * balance["reorder_point_units"] - balance["on_hand_units"]
    )
    touch(target)


# =============================================================================
# Scan valuation (PRD Section 3.6 / scaffold scan_pricing_resolution)
# =============================================================================

def match_preconditions_hold(scan, agreement, product):
    """The three MATCHED preconditions: ACTIVE agreement, product in the
    agreement's program, and an EFFECTIVE directive with
    effective_from <= scanned_at."""
    if agreement["status"] != "ACTIVE":
        return False
    if product["program_id"] != agreement["program_id"]:
        return False
    directive = directive_at(agreement["id"], product["id"], scan["scanned_at"])
    return directive is not None


def price_scan(scan, agreement, product):
    """Resolve unit price, line value, and promo funding for a matched scan.

    VOID copies its target's unit price / promo flag and negates its line
    value and funding (compensating entry).
    """
    if scan["event_type"] == "VOID":
        target = store.scan_events[scan["void_of_event_id"]]
        scan["unit_price_cents"] = target["unit_price_cents"]
        scan["line_value_cents"] = -target["line_value_cents"]
        scan["is_promo_priced"] = target["is_promo_priced"]
        scan["jobber_funding_cents"] = -target["jobber_funding_cents"]
        return

    directive = directive_at(agreement["id"], product["id"], scan["scanned_at"])
    base = directive["price_cents"]
    qty = scan["quantity"]
    promo = active_promotion(agreement["program_id"], product["id"], scan["scanned_at"][:10])
    if promo is not None:
        promo_price = rhu(dec(base) * (Decimal(1) - dec(promo["depth_pct"])))
        unit_price = min(base, promo_price)
        is_promo = unit_price < base
        # promo_funding_split: per-unit discount * qty * funding share,
        # rounded half-up per line (pinned rounding order).
        discount_unit = base - unit_price
        funding = rhu(dec(discount_unit) * qty * dec(promo["jobber_funding_pct"]))
    else:
        unit_price = base
        is_promo = False
        funding = 0
    scan["unit_price_cents"] = unit_price
    scan["line_value_cents"] = unit_price * qty if scan["event_type"] == "SALE" else -unit_price * qty
    scan["is_promo_priced"] = is_promo
    scan["jobber_funding_cents"] = funding


def apply_scan_to_inventory(scan):
    """Move the consignment ledger for a matched scan, then reorder cascade."""
    agreement_id = scan["store_agreement_id"]
    product_id = scan["product_id"]
    qty = scan["quantity"]
    balance = get_or_create_balance(agreement_id, product_id)
    if scan["event_type"] == "SALE":
        balance["on_hand_units"] -= qty
        balance["lifetime_scanned_units"] += qty
    elif scan["event_type"] == "RETURN":
        balance["on_hand_units"] += qty
        balance["lifetime_customer_return_units"] += qty
    else:  # VOID reverses its target's units and counters
        target = store.scan_events[scan["void_of_event_id"]]
        if target["event_type"] == "SALE":
            balance["on_hand_units"] += qty
            balance["lifetime_scanned_units"] -= qty
        else:  # target RETURN
            balance["on_hand_units"] -= qty
            balance["lifetime_customer_return_units"] -= qty
    recompute_posture(balance)
    touch(balance)
    reorder_cascade(balance)


# =============================================================================
# Agreement cumulative counters and the suspension posture (PRD 3.1 / 3.7)
# =============================================================================

def recompute_shrink_ratio(agreement):
    delivered = agreement["cumulative_delivered_units"]
    if delivered == 0:
        agreement["cumulative_shrink_ratio"] = 0.0
    else:
        agreement["cumulative_shrink_ratio"] = (
            agreement["cumulative_shrink_units"] * 1.0 / delivered
        )


def suspend_agreement(agreement):
    """ACTIVE -> SUSPENDED; cancels every still-SCHEDULED service visit."""
    for v in store.service_visits.values():
        if v["store_agreement_id"] == agreement["id"] and v["status"] == "SCHEDULED":
            v["status"] = "CANCELLED"
            touch(v)
    agreement["status"] = "SUSPENDED"
    touch(agreement)


def evaluate_suspension(agreement):
    """shrink_ratio_posture: >= boundary suspends (exactly equal suspends)."""
    if (
        agreement["status"] == "ACTIVE"
        and agreement["cumulative_shrink_ratio"] >= agreement["shrink_suspend_ratio"]
    ):
        suspend_agreement(agreement)


# =============================================================================
# Audit valuation (scaffold audit_variance_valuation / shrink_allocation)
# =============================================================================

def product_valuation_cents(agreement, product):
    """Per-unit shrink valuation for one product at certify time."""
    if agreement["shrink_valuation_mode"] == "BLENDED_RETAIL":
        directive = _effective_directive(agreement["id"], product["id"])
        retail = directive["price_cents"] if directive is not None else product["jobber_cost_cents"]
        return rhu(COST_W * product["jobber_cost_cents"] + RETAIL_W * retail)
    return product["jobber_cost_cents"]


def audit_valuation_unit_cents(audit, agreement):
    """Audit-level valuation_unit_cents. Single-product audits value at that
    product's unit; multi-product audits use the shrink-weighted average of
    per-product unit valuations (weighted_scoring), which is exact for the
    single-product case."""
    lines = audit["counted_lines"] or []
    if not lines:
        return None
    total_pos = 0
    weighted = Decimal(0)
    for line in lines:
        product = store.products.get(line["product_id"])
        if product is None:
            continue
        pos = max(0, line.get("_book_on_hand", 0) - line["counted_units"])
        unit = product_valuation_cents(agreement, product)
        total_pos += pos
        weighted += dec(pos) * unit
    if total_pos == 0:
        product = store.products.get(lines[0]["product_id"])
        return product_valuation_cents(agreement, product) if product else None
    return rhu(weighted / dec(total_pos))


def book_on_hand(agreement_id, product_id):
    """Current book on-hand for (agreement, product); 0 when no balance."""
    balance = get_balance(agreement_id, product_id)
    return balance["on_hand_units"] if balance is not None else 0


# =============================================================================
# Settlement periods and money fields (PRD Section 3.9)
# =============================================================================

def period_window(agreement, period_index):
    """Half-open [period_start, period_end) anchored at activated_at.

    WEEKLY = 7 days, BIWEEKLY = 14 days, MONTHLY = one calendar month.
    """
    anchor = datetime.date.fromisoformat(agreement["activated_at"][:10])
    cadence = agreement["settlement_cadence"]
    if cadence == "WEEKLY":
        start = add_days(anchor, 7 * period_index)
        end = add_days(anchor, 7 * (period_index + 1))
    elif cadence == "BIWEEKLY":
        start = add_days(anchor, 14 * period_index)
        end = add_days(anchor, 14 * (period_index + 1))
    else:  # MONTHLY
        start = add_months(anchor, period_index)
        end = add_months(anchor, period_index + 1)
    return start, end


def current_period_window(agreement, today):
    """The period window containing `today`; None before activation."""
    if not agreement.get("activated_at"):
        return None
    anchor = datetime.date.fromisoformat(agreement["activated_at"][:10])
    if today < anchor:
        return None
    cadence = agreement["settlement_cadence"]
    if cadence == "WEEKLY":
        idx = (today - anchor).days // 7
    elif cadence == "BIWEEKLY":
        idx = (today - anchor).days // 14
    else:
        idx = months_between(anchor, today)
    return period_window(agreement, idx)


def _window_bounds(period_start, period_end):
    start_dt = datetime.datetime(
        period_start.year, period_start.month, period_start.day,
        tzinfo=datetime.timezone.utc,
    )
    end_dt = datetime.datetime(
        period_end.year, period_end.month, period_end.day,
        tzinfo=datetime.timezone.utc,
    )
    return fmt_dt(start_dt), fmt_dt(end_dt)


def scans_in_window(agreement_id, period_start, period_end):
    """MATCHED scans of the agreement with scanned_at in [start, end)."""
    lo, hi = _window_bounds(period_start, period_end)
    return [
        s for s in store.scan_events.values()
        if s["store_agreement_id"] == agreement_id
        and s["status"] == "MATCHED"
        and lo <= s["scanned_at"] < hi
    ]


def _signed_units(scan):
    """Net unit contribution: SALE +q, RETURN -q, VOID reverses its target."""
    if scan["event_type"] == "SALE":
        return scan["quantity"]
    if scan["event_type"] == "RETURN":
        return -scan["quantity"]
    target = store.scan_events.get(scan["void_of_event_id"])
    if target is not None and target["event_type"] == "SALE":
        return -scan["quantity"]
    return scan["quantity"]  # VOID of a RETURN adds the units back


def compute_statement_fields(agreement, program, period_index, variant):
    """The pinned top-down evaluation order of settlement_net_payable."""
    period_start, period_end = period_window(agreement, period_index)
    scans = scans_in_window(agreement["id"], period_start, period_end)

    # 1. gross scanned sales (cap keys on gross, never net).
    gross = sum(s["line_value_cents"] for s in scans)
    # 2. net scanned units and promo-priced units.
    scanned_units = sum(_signed_units(s) for s in scans)
    promo_scan_units = sum(_signed_units(s) for s in scans if s["is_promo_priced"])
    # 3. per-line-rounded promo funding, merely summed here.
    funding = sum(s["jobber_funding_cents"] for s in scans)
    # 4. markdown credit: raw vs cap keyed on gross.
    lo, hi = _window_bounds(period_start, period_end)
    raw_markdown = sum(
        m["credit_cents"]
        for m in store.markdown_authorizations.values()
        if m["store_agreement_id"] == agreement["id"]
        and m["auth_type"] == "MARKDOWN"
        and m["status"] == "APPLIED"
        and m.get("applied_at") is not None
        and lo <= m["applied_at"] < hi
    )
    markdown_cap = rhu(dec(agreement["markdown_cap_pct_of_gross"]) * gross)
    markdown_credit = min(raw_markdown, markdown_cap)
    # 5. net sales.
    net_sales = gross - markdown_credit
    # 6. margin: tier thresholds read NET sales; tiers replace, not stack.
    if net_sales >= agreement["tier2_threshold_cents"]:
        uplift = dec(agreement["tier2_uplift_pct"])
    elif net_sales >= agreement["tier1_threshold_cents"]:
        uplift = dec(agreement["tier1_uplift_pct"])
    else:
        uplift = Decimal(0)
    if scanned_units == 0:
        promo_share = Decimal(0)
    else:
        promo_share = dec(promo_scan_units) / dec(scanned_units)
    drag = PROMO_DRAG_PCT if promo_share > PROMO_DRAG_SHARE else Decimal(0)
    margin = dec(agreement["base_margin_pct"]) + uplift - drag
    margin = max(dec(agreement["min_margin_pct"]), min(dec(agreement["max_margin_pct"]), margin))
    # 7. retailer margin cents, round half-up.
    retailer_margin = rhu(dec(net_sales) * margin)
    # 8. shrink retailer charge — the variant divergence point.
    if variant == "FINAL":
        shrink_charge = sum(
            a["retailer_charge_cents"]
            for a in store.audit_counts.values()
            if a["store_agreement_id"] == agreement["id"]
            and a["status"] in ("CERTIFIED", "LOCKED")
            and a.get("certified_at") is not None
            and lo <= a["certified_at"] < hi
        )
    else:  # PROVISIONAL estimate; audits ignored entirely.
        est_units = rhu(dec(scanned_units) * dec(agreement["estimated_shrink_rate"]))
        if scanned_units == 0:
            avg_cost = 0
        else:
            weighted = sum(
                dec(_signed_units(s)) * store.products[s["product_id"]]["jobber_cost_cents"]
                for s in scans
            )
            avg_cost = rhu(weighted / dec(scanned_units))
        shrink_charge = rhu(
            dec(est_units) * avg_cost * dec(agreement["shrink_retailer_share_pct"])
        )
    # 9. teardown penalties reconciled in the window.
    teardown = sum(
        s["penalty_cents"]
        for s in store.seasonal_sets.values()
        if s["store_agreement_id"] == agreement["id"]
        and s["status"] == "RECONCILED"
        and s.get("_reconciled_at") is not None
        and lo <= s["_reconciled_at"] < hi
    )
    # 10. net payable to the jobber.
    net_payable = net_sales - retailer_margin + shrink_charge - teardown

    return {
        "period_start": fmt_date(period_start),
        "period_end": fmt_date(period_end),
        "variant_used": variant,
        "gross_scanned_sales_cents": gross,
        "scanned_units": scanned_units,
        "promo_scan_units": promo_scan_units,
        "promo_jobber_funding_cents": funding,
        "markdown_credit_cents": markdown_credit,
        "net_sales_cents": net_sales,
        "margin_pct": float(margin),
        "retailer_margin_cents": retailer_margin,
        "shrink_retailer_charge_cents": shrink_charge,
        "teardown_penalty_cents": teardown,
        "net_payable_to_jobber_cents": net_payable,
    }


# =============================================================================
# Seasonal teardown penalty (scaffold seasonal_teardown_penalty)
# =============================================================================

def teardown_penalty_cents(teardown_deadline_str, actual_teardown_date_str):
    deadline = datetime.date.fromisoformat(teardown_deadline_str)
    actual = datetime.date.fromisoformat(actual_teardown_date_str)
    days_late = max(0, (actual - deadline).days - GRACE_DAYS)
    return min(PENALTY_CAP_CENTS, days_late * PENALTY_PER_DAY_CENTS)
