"""Calculations, derivations and cascades (PRD 2.4-2.11 / 3.x)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, insert, public, setf, touch, whole_days
from errors import fail
from middleware import as_instant

# ------------------------------------------------------------------ constants
MONTHS_PER_YEAR = 12
UNAVAILABILITY_POINTS_PER_MINUTE = 2
CATEGORY_A_POINTS = 40
CATEGORY_B_POINTS = 10
SELF_REPORT_VARIANCE_TOLERANCE_PCT = Decimal("0.05")
UNDERSTATEMENT_UPLIFT_PCT = Decimal("1.25")
DEDUCTION_POINT_VALUE_CENTS = 1250
ANNUAL_DEDUCTION_CAP_PCT = Decimal("0.10")
PERSISTENT_BREACH_POINTS_THRESHOLD = 500
EQUITY_FIRST_PCT = Decimal("0.30")
CONSTRUCTION_START_PCT = Decimal("0.30")
CONSTRUCTION_SEED_PCT = Decimal("0.02")
HANDBACK_SHORTFALL_PENALTY_PCT = Decimal("0.15")
TIER1_MASP_MULTIPLE = Decimal("0.5")
TIER2_MASP_MULTIPLE = Decimal("1.5")
TIER1_AUTHORITY_PCT = Decimal("0.30")
TIER2_AUTHORITY_PCT = Decimal("0.50")
TIER3_AUTHORITY_PCT = Decimal("0.60")
RESERVE_SWEEP_PCT = Decimal("0.25")
MONTH_BASIS_DAYS = 30
BPS_DIVISOR = Decimal("10000")
AUTHORITY_DEFAULT_UPLIFT_PCT = Decimal("0.10")
RELIEF_NOTIFICATION_WINDOW_DAYS = 20
RELIEF_CLAIM_BUFFER_DAYS = 3
RELIEF_DAYS_ANNUAL_CAP = 60
CURE_PERIOD_DAYS = 90
DISPUTE_MAX_ROUNDS = 3
MINUTES_PER_DAY = 1440

LIVE_EVENT_STATUSES = ("ISSUED", "DISPUTED")
LIVE_CLAIM_STATUSES = ("GRANTED", "PARTIALLY_GRANTED")
FREEZING_ENFORCEMENT_STATUSES = ("NOTIFIED", "STEP_IN_ACTIVE", "COMPENSATION_CALCULATED")


def rhu(value):
    """Round half up to a whole cent/point."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_dp(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def as_float(dec):
    return float(dec)


# ------------------------------------------------------------------ selectors
def concession_periods(concession_id):
    return [p for p in db.all("periods") if p["concession_id"] == concession_id]


def period_events(period_id):
    rows = [e for e in db.all("events") if e["service_period_id"] == period_id]
    rows.sort(key=lambda e: e["sequence_no"])
    return rows


def period_reports(period_id):
    return [r for r in db.all("reports") if r["service_period_id"] == period_id]


def concession_claims(concession_id):
    return [c for c in db.all("claims") if c["concession_id"] == concession_id]


def concession_txns(concession_id):
    rows = [t for t in db.all("reserve_txns") if t["concession_id"] == concession_id]
    rows.sort(key=lambda t: t["sequence_no"])
    return rows


def concession_actions(concession_id):
    return [a for a in db.all("enforcements") if a["concession_id"] == concession_id]


def open_disputes_for_event(event_id):
    return [d for d in db.all("disputes")
            if d["deduction_event_id"] == event_id
            and d["status"] in ("RAISED", "REFERRED_BACK", "RESUBMITTED")]


# ------------------------------------------------------------------ charge
def monthly_unitary_charge_cents(concession):
    masp = Decimal(concession["masp_cents"])
    idx = Decimal(str(concession["indexation_pct"]))
    return rhu(masp / Decimal(MONTHS_PER_YEAR) * (Decimal(1) + idx))


def annual_cap_cents(concession):
    return rhu(Decimal(concession["masp_cents"]) * ANNUAL_DEDUCTION_CAP_PCT)


def report_points(minutes, cat_a, cat_b):
    return (UNAVAILABILITY_POINTS_PER_MINUTE * minutes
            + CATEGORY_A_POINTS * cat_a
            + CATEGORY_B_POINTS * cat_b)


def variance_pct(reported, verified):
    if reported > 0:
        return rhu_dp(Decimal(verified - reported) / Decimal(reported), 4)
    if verified == 0:
        return Decimal(0)
    return Decimal(1)


def understatement_points(reported, verified):
    return rhu(Decimal(verified - reported) * UNDERSTATEMENT_UPLIFT_PCT)


def availability_ratio(days_in_period, unavailable_minutes):
    total = Decimal(days_in_period * MINUTES_PER_DAY)
    if total == 0:
        return None
    return rhu_dp((total - Decimal(unavailable_minutes)) / total, 4)


# ------------------------------------------------------------------ enforcement
def enforcement_freeze_guard(concession):
    for action in concession_actions(concession["id"]):
        if action["status"] in FREEZING_ENFORCEMENT_STATUSES:
            fail("ERR_CONCESSION_UNDER_ENFORCEMENT")


# ------------------------------------------------------------------ allocation
def allocate_period(period):
    """Both cap variants over the period's live deduction events."""
    events = [e for e in period_events(period["id"]) if e["status"] in LIVE_EVENT_STATUSES]
    cap = period["deduction_cap_cents"]
    raw_total = sum(e["raw_amount_cents"] for e in events)

    headroom = cap
    for event in events:
        allowed = min(event["raw_amount_cents"], headroom)
        setf(event, "allowed_amount_cents", allowed)
        headroom -= allowed

    if raw_total <= cap:
        for event in events:
            setf(event, "pro_rata_amount_cents", event["raw_amount_cents"])
    else:
        floors = {}
        for event in events:
            floors[event["id"]] = (event["raw_amount_cents"] * cap) // raw_total
        residue = cap - sum(floors.values())
        order = sorted(events, key=lambda e: (-e["raw_amount_cents"], e["sequence_no"]))
        index = 0
        while residue > 0 and order:
            target = order[index % len(order)]
            floors[target["id"]] += 1
            residue -= 1
            index += 1
        for event in events:
            setf(event, "pro_rata_amount_cents", floors[event["id"]])

    setf(period, "deduction_points_total", sum(e["points"] for e in events))
    setf(period, "total_deduction_cents", sum(e["allowed_amount_cents"] for e in events))
    return events


def relief_credit_cents(period):
    """Union of granted COMPENSATION_EVENT days clipped to the half-open period."""
    concession_id = period["concession_id"]
    start = as_instant(period["period_start"]).date()
    days_in_period = period["days_in_period"]
    last_day = start + timedelta(days=days_in_period - 1)
    covered = set()
    for claim in concession_claims(concession_id):
        if claim["claim_type"] != "COMPENSATION_EVENT":
            continue
        if claim["status"] not in LIVE_CLAIM_STATUSES:
            continue
        c_start = as_instant(claim["event_start"]).date()
        c_end = as_instant(claim["event_end"]).date()
        lo = max(c_start, start)
        hi = min(c_end, last_day)
        cursor = lo
        while cursor <= hi:
            covered.add(cursor)
            cursor += timedelta(days=1)
    credited = min(len(covered), days_in_period)
    if credited == 0:
        return 0
    gross = Decimal(period["gross_unitary_charge_cents"])
    return rhu(gross * Decimal(credited) / Decimal(days_in_period))


def price_period(period):
    """The pinned four-step chain (PRD 2.4): cap -> total -> relief -> net."""
    allocate_period(period)
    setf(period, "relief_credit_cents", relief_credit_cents(period))
    net = period["gross_unitary_charge_cents"] - max(
        0, period["total_deduction_cents"] - period["relief_credit_cents"])
    setf(period, "net_payment_cents", net)
    return period


def mark_adjusted_if_repriced(period, unconditional=False):
    """PAID -> ADJUSTED when the re-priced deduction total differs from at-payment."""
    if period["payment_status"] != "PAID":
        return
    if unconditional or period.get("_total_deduction_at_paid") != period["total_deduction_cents"]:
        setf(period, "payment_status", "ADJUSTED")


# ------------------------------------------------------------------ concession totals
def recompute_ytd(concession):
    total = 0
    for period in concession_periods(concession["id"]):
        if period["reporting_status"] == "VERIFIED":
            total += period["total_deduction_cents"]
    setf(concession, "availability_deduction_ytd_cents", total)
    return total


def recompute_points_and_breach(concession):
    points = 0
    for period in concession_periods(concession["id"]):
        for event in period_events(period["id"]):
            if event["status"] in LIVE_EVENT_STATUSES:
                points += event["points"]
    setf(concession, "deduction_points_ytd", points)
    was_flagged = bool(concession["persistent_breach_flag"])
    now_flagged = points >= PERSISTENT_BREACH_POINTS_THRESHOLD
    setf(concession, "persistent_breach_flag", now_flagged)
    if was_flagged and not now_flagged:
        cure_persistent_breach_step_in(concession)
    return points


def cure_persistent_breach_step_in(concession):
    """Cascade A link 4: a cleared breach cures a live persistent-breach step-in."""
    for action in concession_actions(concession["id"]):
        if (action["action_type"] == "STEP_IN"
                and action["trigger_reason"] == "PERSISTENT_BREACH"
                and action["status"] == "STEP_IN_ACTIVE"):
            setf(action, "status", "CURED")
            setf(action, "cure_note", "PERSISTENT_BREACH_CLEARED")
            setf(action, "cured_at", db.now_str())
            if concession["status"] == "STEP_IN":
                setf(concession, "status", "OPERATIONS")
            sponsor = db.tables["concessionaires"].get(concession["concessionaire_id"])
            if sponsor is not None and sponsor["status"] == "STEPPED_IN":
                setf(sponsor, "status", "ACTIVE")


def annual_cap_guard(concession, projected):
    if projected > annual_cap_cents(concession):
        fail("ERR_ANNUAL_DEDUCTION_CAP_EXCEEDED")


def next_event_sequence(period_id):
    existing = [e["sequence_no"] for e in period_events(period_id)]
    return (max(existing) + 1) if existing else 1


def issue_deduction_event(period, deduction_type, points, issued_by, report_id=None):
    event = {
        "service_period_id": period["id"],
        "performance_report_id": report_id,
        "sequence_no": next_event_sequence(period["id"]),
        "deduction_type": deduction_type,
        "points": points,
        "raw_amount_cents": points * DEDUCTION_POINT_VALUE_CENTS,
        "allowed_amount_cents": 0,
        "pro_rata_amount_cents": 0,
        "status": "ISSUED",
        "issued_by_user_id": issued_by,
        "issued_at": db.now_str(),
        "withdrawal_reason": None,
    }
    return insert("events", event)


# ------------------------------------------------------------------ ledger
def append_ledger(concession, txn_type, amount_cents, reason, created_by_role,
                  reverses_txn_id=None, signed_amount_cents=None):
    existing = concession_txns(concession["id"])
    seq = (existing[-1]["sequence_no"] + 1) if existing else 1
    if signed_amount_cents is None:
        if txn_type in ("CONTRIBUTION", "HANDBACK_TOPUP"):
            signed_amount_cents = amount_cents
        else:
            signed_amount_cents = -amount_cents
    row = {
        "concession_id": concession["id"],
        "sequence_no": seq,
        "txn_type": txn_type,
        "amount_cents": amount_cents,
        "signed_amount_cents": signed_amount_cents,
        "reason": reason,
        "reverses_txn_id": reverses_txn_id,
        "resulting_balance_cents": 0,
        "created_by_role": created_by_role,
    }
    insert("reserve_txns", row, versioned=False)
    replay_ledger(concession)
    return row


def replay_ledger(concession):
    running = 0
    for txn in concession_txns(concession["id"]):
        running += txn["signed_amount_cents"]
        txn["resulting_balance_cents"] = running
    setf(concession, "lifecycle_reserve_balance_cents", running)
    return running


def reserve_balance(concession):
    txns = concession_txns(concession["id"])
    return txns[-1]["resulting_balance_cents"] if txns else 0


# ------------------------------------------------------------------ drawdowns
def drawdown_split(concession, certified_cost_cents):
    ceiling = min(
        rhu(Decimal(concession["total_project_cost_cents"]) * EQUITY_FIRST_PCT),
        concession["equity_committed_cents"],
    )
    room = max(0, ceiling - concession["equity_drawn_cents"])
    equity_portion = min(certified_cost_cents, room)
    debt_portion = certified_cost_cents - equity_portion
    return equity_portion, debt_portion


def commitment_guard(concession, equity_portion, debt_portion):
    debt_room = concession["senior_debt_committed_cents"] - concession["senior_debt_drawn_cents"]
    if debt_portion > debt_room:
        fail("ERR_COMMITMENT_EXCEEDED")
    if concession["equity_drawn_cents"] + equity_portion > concession["equity_committed_cents"]:
        fail("ERR_COMMITMENT_EXCEEDED")
    if concession["senior_debt_drawn_cents"] + debt_portion > concession["senior_debt_committed_cents"]:
        fail("ERR_COMMITMENT_EXCEEDED")


def cumulative_drawn(concession):
    total = concession["equity_drawn_cents"] + concession["senior_debt_drawn_cents"]
    return rhu_dp(Decimal(total) / Decimal(concession["total_project_cost_cents"]), 4)


# ------------------------------------------------------------------ liquidated damages
def liquidated_damages(concession, actual_commencement):
    scheduled = as_instant(concession["scheduled_service_commencement"])
    gross_late_days = max(0, whole_days(scheduled, actual_commencement))
    excused = 0
    for claim in concession_claims(concession["id"]):
        if claim["claim_type"] == "RELIEF_EVENT" and claim["status"] in LIVE_CLAIM_STATUSES:
            excused += claim["granted_relief_days"]
    net_late_days = max(0, gross_late_days - excused)
    return min(net_late_days * concession["ld_daily_rate_cents"], concession["ld_cap_cents"])


# ------------------------------------------------------------------ handback
def handback_assessment(concession, rectification_cost_cents):
    balance = concession["lifecycle_reserve_balance_cents"]
    shortfall_pre = max(0, rectification_cost_cents - balance)
    penalty = rhu(Decimal(shortfall_pre) * HANDBACK_SHORTFALL_PENALTY_PCT)
    required = rectification_cost_cents + penalty
    shortfall = max(0, required - balance)
    status = "CERTIFIED" if shortfall == 0 else "FAILED"
    return required, shortfall, status


def latest_verified_period(concession_id):
    candidates = [p for p in concession_periods(concession_id)
                  if p["reporting_status"] == "VERIFIED"]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p["period_index"])


# ------------------------------------------------------------------ refinancing
def refinancing_gain(new_senior_debt, outstanding, cost):
    return new_senior_debt - outstanding - cost


def refinancing_tier(concession, gross_gain):
    tier1 = rhu(Decimal(concession["masp_cents"]) * TIER1_MASP_MULTIPLE)
    tier2 = rhu(Decimal(concession["masp_cents"]) * TIER2_MASP_MULTIPLE)
    if gross_gain <= tier1:
        return TIER1_AUTHORITY_PCT
    if gross_gain <= tier2:
        return TIER2_AUTHORITY_PCT
    return TIER3_AUTHORITY_PCT


# ------------------------------------------------------------------ compensation
def termination_compensation(concession, action, termination_dt):
    commencement = as_instant(concession["actual_service_commencement"]) \
        if concession["actual_service_commencement"] else None
    if commencement is None:
        elapsed_months = 0
    else:
        elapsed_months = max(0, whole_days(commencement, termination_dt)) // MONTH_BASIS_DAYS

    equity_drawn = concession["equity_drawn_cents"]
    accrued = rhu(
        Decimal(equity_drawn) * Decimal(concession["base_case_equity_irr_bps"]) / BPS_DIVISOR
        * Decimal(elapsed_months) / Decimal(MONTHS_PER_YEAR)
    )

    unpaid = 0
    for period in concession_periods(concession["id"]):
        if period["payment_status"] == "INVOICED":
            unpaid += period["net_payment_cents"]

    offset = 0
    for period in concession_periods(concession["id"]):
        for event in period_events(period["id"]):
            if event["status"] in LIVE_EVENT_STATUSES:
                offset += event["allowed_amount_cents"]

    reason = action["trigger_reason"]
    debt = action["outstanding_senior_debt_cents"] or 0
    if reason == "AUTHORITY_VOLUNTARY":
        total = debt + equity_drawn + accrued + unpaid - offset
    elif reason == "CONCESSIONAIRE_DEFAULT":
        total = ((action["market_value_estimate_cents"] or 0)
                 - (action["rectification_cost_cents"] or 0)
                 - (action["authority_reprocurement_cost_cents"] or 0)
                 - offset)
    elif reason == "AUTHORITY_DEFAULT":
        uplift = rhu(Decimal(equity_drawn) * AUTHORITY_DEFAULT_UPLIFT_PCT)
        total = debt + equity_drawn + accrued + uplift + unpaid
    else:  # FORCE_MAJEURE
        total = debt + equity_drawn + unpaid - offset
    return {
        "elapsed_operational_months": elapsed_months,
        "accrued_equity_return_cents": accrued,
        "unpaid_invoiced_cents": unpaid,
        "deduction_offset_cents": offset,
        "compensation_cents": max(0, total),
    }


# ------------------------------------------------------------------ relief windows
def relief_notification_guard(event_start_dt):
    elapsed = whole_days(event_start_dt, db.now())
    if elapsed < 0:
        elapsed = 0
    if elapsed > RELIEF_NOTIFICATION_WINDOW_DAYS:
        fail("ERR_RELIEF_NOTIFICATION_LATE")


def relief_window_conflict_guard(concession_id, claim_type, start_dt, end_dt):
    buffer_days = timedelta(days=RELIEF_CLAIM_BUFFER_DAYS)
    new_lo = start_dt.date() - buffer_days
    new_hi = end_dt.date() + buffer_days
    for claim in concession_claims(concession_id):
        if claim["claim_type"] != claim_type:
            continue
        if claim["status"] not in ("NOTIFIED", "GRANTED", "PARTIALLY_GRANTED"):
            continue
        old_lo = as_instant(claim["event_start"]).date() - buffer_days
        old_hi = as_instant(claim["event_end"]).date() + buffer_days
        if new_lo <= old_hi and old_lo <= new_hi:
            fail("ERR_RELIEF_WINDOW_CONFLICT")


def granted_relief_days_total(concession_id):
    total = 0
    for claim in concession_claims(concession_id):
        if claim["status"] in LIVE_CLAIM_STATUSES:
            total += claim["granted_relief_days"]
    return total


def periods_touching_window(concession_id, start_dt, end_dt):
    """Service periods whose half-open span intersects a closed claim window."""
    hits = []
    c_start = start_dt.date()
    c_end = end_dt.date()
    for period in concession_periods(concession_id):
        p_start = as_instant(period["period_start"]).date()
        p_last = p_start + timedelta(days=period["days_in_period"] - 1)
        if c_start <= p_last and p_start <= c_end:
            hits.append(period)
    return hits


# ------------------------------------------------------------------ summary
def payment_summary(concession):
    sequential_total = 0
    pro_rata_total = 0
    unpaid_invoiced = 0
    for period in concession_periods(concession["id"]):
        if period["reporting_status"] == "VERIFIED":
            sequential_total += period["total_deduction_cents"]
            for event in period_events(period["id"]):
                pro_rata_total += event["pro_rata_amount_cents"]
        if period["payment_status"] == "INVOICED":
            unpaid_invoiced += period["net_payment_cents"]
    return {
        "concession_id": concession["id"],
        "monthly_unitary_charge_cents": concession["monthly_unitary_charge_cents"],
        "availability_deduction_ytd_cents": concession["availability_deduction_ytd_cents"],
        "annual_cap_cents": annual_cap_cents(concession),
        "deduction_points_ytd": concession["deduction_points_ytd"],
        "persistent_breach_flag": concession["persistent_breach_flag"],
        "lifecycle_reserve_balance_cents": concession["lifecycle_reserve_balance_cents"],
        "sequential_total_cents": sequential_total,
        "pro_rata_total_cents": pro_rata_total,
        "unpaid_invoiced_cents": unpaid_invoiced,
    }
