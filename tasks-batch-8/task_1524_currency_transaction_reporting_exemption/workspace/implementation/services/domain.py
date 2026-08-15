"""Business derivations: daily aggregation, CTR reportability cascade,
structuring detection, Phase II eligibility, and the exemption clock sweep.

All formulas implement SCAFFOLD.yaml §1.3 and PRD §3 literally.
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from db import (
    CTR_THRESHOLD_CENTS,
    EFILE_DEADLINE_DAYS,
    ELIGIBILITY_WINDOW_DAYS,
    FEE_BPS,
    MIN_FEE_CENTS,
    NEAR_THRESHOLD_LOW_CENTS,
    PAPER_DEADLINE_DAYS,
    PHASE_II_MIN_ACCOUNT_AGE_DAYS,
    PHASE_II_MIN_QUALIFYING_DAYS,
    STRUCTURING_WINDOW_DAYS,
    TRAILING_RECOMPUTE_DATES,
    due_date_str,
    now_iso,
    parse_date_strict,
    parse_dt,
    stamp_new,
    store,
    today,
    touch,
)
from serializers import serialize_ctr, serialize_exemption
from services.audit import add_fx, system_event

CTR_LIVE_STATUSES = ("DRAFT", "VALIDATED", "FILED", "ACKNOWLEDGED", "AMENDMENT_REQUIRED")


# ---------------------------------------------------------------------------
# Instrument fee (SCAFFOLD instrument_fee_calc; PRD §3.3)
# ---------------------------------------------------------------------------
def compute_fee_cents(amount_cents):
    """max(150, round_half_up(amount_cents * 50 / 10000)) — rounded per
    instrument first; daily totals then sum the per-instrument fees."""
    fee = (Decimal(amount_cents) * Decimal(FEE_BPS) / Decimal(10000)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return max(MIN_FEE_CENTS, int(fee))


# ---------------------------------------------------------------------------
# Daily cash aggregation (SCAFFOLD daily_cash_aggregation; PRD §3.4)
# ---------------------------------------------------------------------------
def get_or_create_aggregation(customer_id, business_date):
    key = (customer_id, business_date)
    row = store.aggregations.get(key)
    if row is None:
        row = {
            "customer_id": customer_id,
            "business_date": business_date,
            "total_cash_in_cents": 0,
            "total_cash_out_cents": 0,
            "transaction_count": 0,
            "instrument_sale_count": 0,
            "instrument_fee_total_cents": 0,
            "raw_reportable_in": False,
            "raw_reportable_out": False,
            "covered_in": False,
            "covered_out": False,
            "ctr_required": False,
            "last_recomputed_at": now_iso(),
        }
        stamp_new(row)
        store.aggregations[key] = row
    return row


def recompute_aggregation(customer_id, business_date):
    """Recompute totals for (customer, date); VOIDED records contribute
    nothing. Always followed immediately by the CTR reportability cascade."""
    row = get_or_create_aggregation(customer_id, business_date)
    txns = [
        t
        for t in store.cash_transactions.values()
        if t["customer_id"] == customer_id
        and t["business_date"] == business_date
        and t["status"] == "POSTED"
    ]
    sales = [
        s
        for s in store.instrument_sales.values()
        if s["customer_id"] == customer_id
        and s["business_date"] == business_date
        and s["status"] == "RECORDED"
    ]
    row["total_cash_in_cents"] = sum(
        t["amount_cents"] for t in txns if t["direction"] == "CASH_IN"
    ) + sum(s["amount_cents"] for s in sales)
    row["total_cash_out_cents"] = sum(
        t["amount_cents"] for t in txns if t["direction"] == "CASH_OUT"
    )
    row["transaction_count"] = len(txns)
    row["instrument_sale_count"] = len(sales)
    row["instrument_fee_total_cents"] = sum(s["fee_cents"] for s in sales)
    row["last_recomputed_at"] = now_iso()
    touch(row)
    recompute_reportability(customer_id, business_date)


# ---------------------------------------------------------------------------
# CTR reportability (SCAFFOLD ctr_reportability; PRD §3.4)
# ---------------------------------------------------------------------------
def active_designation(customer):
    """The customer's ExemptionDesignation currently in ACTIVE status, if any.
    REVIEW_DUE / PENDING_REVIEW / DENIED / REVOKED never cover."""
    if customer is None:
        return None
    eid = customer.get("active_exemption_id")
    if not eid:
        return None
    d = store.exemptions.get(eid)
    if d is not None and d["status"] == "ACTIVE":
        return d
    return None


def create_ctr(customer_id, business_date, filing_type, prior_ctr_id, amendment_reason):
    row = store.aggregations.get((customer_id, business_date))
    snap_in = row["total_cash_in_cents"] if row is not None else 0
    snap_out = row["total_cash_out_cents"] if row is not None else 0
    bd = parse_date_strict(business_date)
    ctr = {
        "customer_id": customer_id,
        "business_date": business_date,
        "filing_type": filing_type,
        "prior_ctr_id": prior_ctr_id,
        "amendment_reason": amendment_reason,
        "snapshot_cash_in_cents": snap_in,
        "snapshot_cash_out_cents": snap_out,
        "due_date_efile": due_date_str(bd, EFILE_DEADLINE_DAYS),
        "due_date_paper": due_date_str(bd, PAPER_DEADLINE_DAYS),
        "status": "DRAFT",
        "validated_by_id": None,
        "filed_by_id": None,
        "filing_channel": None,
        "filed_at": None,
        "filed_late": None,
        "acknowledged_at": None,
        "regulator_tracking_id": None,
    }
    stamp_new(ctr)
    store.ctrs[ctr["id"]] = ctr
    return ctr


def recompute_reportability(customer_id, business_date):
    """Pinned evaluation order:
    (1) read aggregation totals; (2) raw reportability (strictly greater);
    (3) coverage from the customer's ACTIVE designation; (4) ctr_required.
    Then flip handling: auto-create DRAFT on false->true with no live CTR;
    void DRAFT/VALIDATED on true->false; FILED/ACKNOWLEDGED whose frozen
    snapshot diverges from current totals -> AMENDMENT_REQUIRED.
    """
    row = store.aggregations.get((customer_id, business_date))
    if row is None:
        return
    customer = store.customers.get(customer_id)
    d = active_designation(customer)
    total_in = row["total_cash_in_cents"]
    total_out = row["total_cash_out_cents"]
    raw_in = total_in > CTR_THRESHOLD_CENTS
    raw_out = total_out > CTR_THRESHOLD_CENTS
    covered_in = d is not None and (d["phase"] == "PHASE_I" or d["covers_cash_in"])
    covered_out = d is not None and (d["phase"] == "PHASE_I" or d["covers_cash_out"])
    required = (raw_in and not covered_in) or (raw_out and not covered_out)

    changed = (
        row["raw_reportable_in"] != raw_in
        or row["raw_reportable_out"] != raw_out
        or row["covered_in"] != covered_in
        or row["covered_out"] != covered_out
        or row["ctr_required"] != required
    )
    row["raw_reportable_in"] = raw_in
    row["raw_reportable_out"] = raw_out
    row["covered_in"] = covered_in
    row["covered_out"] = covered_out
    row["ctr_required"] = required
    if changed:
        touch(row)

    live = [
        c
        for c in store.ctrs.values()
        if c["customer_id"] == customer_id
        and c["business_date"] == business_date
        and c["status"] in CTR_LIVE_STATUSES
    ]
    live.sort(key=lambda c: c["_seq"])

    if required and not live:
        ctr = create_ctr(customer_id, business_date, "INITIAL", None, None)
        system_event("SYSTEM_AUTO", "CTR", ctr["id"], None, serialize_ctr(ctr))
        add_fx({"type": "ctr_auto_created", "ctr_id": ctr["id"],
                "business_date": business_date})
    elif not required:
        for c in live:
            if c["status"] in ("DRAFT", "VALIDATED"):
                before = serialize_ctr(c)
                c["status"] = "VOIDED"
                c["validated_by_id"] = None
                touch(c)
                system_event("SYSTEM_AUTO", "CTR", c["id"], before, serialize_ctr(c))
                add_fx({"type": "ctr_auto_voided", "ctr_id": c["id"],
                        "business_date": business_date})

    for c in live:
        if c["status"] in ("FILED", "ACKNOWLEDGED"):
            if (
                c["snapshot_cash_in_cents"] != total_in
                or c["snapshot_cash_out_cents"] != total_out
            ):
                before = serialize_ctr(c)
                c["status"] = "AMENDMENT_REQUIRED"
                touch(c)
                system_event("SYSTEM_AUTO", "CTR", c["id"], before, serialize_ctr(c))
                add_fx({"type": "ctr_amendment_required", "ctr_id": c["id"],
                        "business_date": business_date})


def recompute_trailing_45(customer_id):
    """Re-evaluate reportability for the customer's aggregations across the
    trailing 45 calendar dates ending at the current logical date."""
    end = today()
    start = end - timedelta(days=TRAILING_RECOMPUTE_DATES - 1)
    dates = sorted(
        bd
        for (cid, bd) in store.aggregations
        if cid == customer_id
        and parse_date_strict(bd) is not None
        and start <= parse_date_strict(bd) <= end
    )
    for bd in dates:
        recompute_reportability(customer_id, bd)


# ---------------------------------------------------------------------------
# Structuring detection (SCAFFOLD structuring_detection; PRD §3.7)
# ---------------------------------------------------------------------------
def evaluate_structuring(customer_id, business_date):
    """Five-day window [d-4, d]. Fire exactly when all five conditions hold;
    condition 5 dedupes silently against overlapping live alert windows."""
    d = parse_date_strict(business_date)
    window = [d - timedelta(days=i) for i in range(STRUCTURING_WINDOW_DAYS - 1, -1, -1)]
    wdates = [x.isoformat() for x in window]
    totals = []
    for wd in wdates:
        row = store.aggregations.get((customer_id, wd))
        totals.append(row["total_cash_in_cents"] if row is not None else 0)
    window_sum = sum(totals)
    max_day = max(totals)
    # (1) window sum strictly greater than the threshold
    if window_sum <= CTR_THRESHOLD_CENTS:
        return None
    # (2) no single reportable day
    if max_day > CTR_THRESHOLD_CENTS:
        return None
    days_positive = sum(1 for t in totals if t > 0)
    # (3) at least two days with cash-in
    if days_positive < 2:
        return None
    wset = set(wdates)
    branches = set()
    for t in store.cash_transactions.values():
        if (
            t["customer_id"] == customer_id
            and t["business_date"] in wset
            and t["status"] == "POSTED"
            and t["direction"] == "CASH_IN"
        ):
            branches.add(t["branch_id"])
    for s in store.instrument_sales.values():
        if (
            s["customer_id"] == customer_id
            and s["business_date"] in wset
            and s["status"] == "RECORDED"
        ):
            branches.add(s["branch_id"])
    # (4) multi-branch or spread across at least three days
    if not (len(branches) >= 2 or days_positive >= 3):
        return None
    # (5) closed-interval overlap dedupe against live alerts
    ws, we = window[0], window[-1]
    for a in store.alerts.values():
        if a["customer_id"] != customer_id or a["status"] not in ("OPEN", "UNDER_REVIEW"):
            continue
        a_start = parse_date_strict(a["window_start_date"])
        a_end = parse_date_strict(a["window_end_date"])
        if a_start is not None and a_end is not None and a_start <= we and ws <= a_end:
            return None  # silently deduplicated

    customer = store.customers.get(customer_id)
    prior_referral_count = customer["structuring_referral_count"] if customer else 0
    near_threshold_flag = 1 if NEAR_THRESHOLD_LOW_CENTS <= max_day <= CTR_THRESHOLD_CENTS else 0
    risk_score = min(
        100,
        40
        + 8 * min(len(branches), 4)
        + 6 * min(days_positive, 5)
        + 15 * near_threshold_flag
        + 10 * min(prior_referral_count, 3),
    )
    alert = {
        "customer_id": customer_id,
        "detection_source": "AUTO",
        "window_start_date": wdates[0],
        "window_end_date": wdates[-1],
        "detected_amount_cents": window_sum,
        "distinct_day_count": days_positive,
        "distinct_branch_count": len(branches),
        "risk_score": risk_score,
        "status": "OPEN",
        "note": None,
        "referred_at": None,
    }
    stamp_new(alert)
    store.alerts[alert["id"]] = alert
    add_fx({"type": "structuring_alert_auto_created", "alert_id": alert["id"],
            "window_start_date": wdates[0], "window_end_date": wdates[-1]})
    return alert


# ---------------------------------------------------------------------------
# Phase II eligibility (SCAFFOLD phase_ii_eligibility; PRD §3.6)
# ---------------------------------------------------------------------------
def phase_ii_eligibility(customer, variant):
    """variant: 'initial_designation' (>=5 qualifying days AND account age
    >= 60 days) or 'annual_review' (>=5 qualifying days AND no referred alert
    in window). Window: 365 UTC dates [anchor-364, anchor], anchor = today."""
    anchor = today()
    window_start = anchor - timedelta(days=ELIGIBILITY_WINDOW_DAYS - 1)
    qualifying_day_count = 0
    covered_direction = (
        "raw_reportable_in"
        if customer["customer_type"] == "BUSINESS_NONLISTED"
        else "raw_reportable_out"
    )
    for (cid, bd), row in store.aggregations.items():
        if cid != customer["id"]:
            continue
        dt = parse_date_strict(bd)
        if dt is None or dt < window_start or dt > anchor:
            continue
        if row[covered_direction]:
            qualifying_day_count += 1
    opened = parse_dt(customer["account_opened_date"])
    account_age_days = (anchor - opened.date()).days if opened is not None else 0
    referred_alert_in_window = False
    for a in store.alerts.values():
        if (
            a["customer_id"] == customer["id"]
            and a["status"] == "REFERRED"
            and a["referred_at"]
        ):
            rd = parse_dt(a["referred_at"])
            if rd is not None and window_start <= rd.date() <= anchor:
                referred_alert_in_window = True
                break
    snapshot = {
        "window_start": window_start.isoformat(),
        "window_end": anchor.isoformat(),
        "qualifying_day_count": qualifying_day_count,
        "account_age_days": account_age_days,
        "referred_alert_in_window": referred_alert_in_window,
    }
    if variant == "initial_designation":
        passed = (
            qualifying_day_count >= PHASE_II_MIN_QUALIFYING_DAYS
            and account_age_days >= PHASE_II_MIN_ACCOUNT_AGE_DAYS
        )
    else:  # annual_review
        passed = (
            qualifying_day_count >= PHASE_II_MIN_QUALIFYING_DAYS
            and not referred_alert_in_window
        )
    return passed, snapshot


# ---------------------------------------------------------------------------
# Clock sweep (SCAFFOLD ExemptionDesignation machine; PRD §3.6)
# ---------------------------------------------------------------------------
def sweep_review_due():
    """ACTIVE designations whose review_due_date is earlier than the current
    logical date flip to REVIEW_DUE; coverage lapses immediately and
    reportability is recomputed across the trailing 45 dates."""
    swept = []
    current_date = today()
    for d in list(store.exemptions.values()):
        if d["status"] != "ACTIVE" or not d["review_due_date"]:
            continue
        due = parse_date_strict(d["review_due_date"])
        if due is None or due >= current_date:
            continue
        before = serialize_exemption(d)
        d["status"] = "REVIEW_DUE"
        touch(d)
        customer = store.customers.get(d["customer_id"])
        if customer is not None and customer.get("active_exemption_id") == d["id"]:
            customer["active_exemption_id"] = None
            touch(customer)
        # Cascade CTR auto-creations first, then the sweep event itself.
        recompute_trailing_45(d["customer_id"])
        swept.append((d, before))
    return swept
