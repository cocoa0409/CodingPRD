"""Calculation rules: crew_daily_billing, per_diem_claim_amount, mobilization_fee, invoice_totals."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import db
from services.core import crews_of_request


def round_half_up(value):
    """Round a Decimal to whole cents using ROUND_HALF_UP, return int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def find_effective_schedule(event_id, responding_utility_id, for_date):
    """PUBLISHED or LOCKED schedule for (event, utility) whose inclusive window covers for_date."""
    target = db.parse_date(for_date) if not hasattr(for_date, "year") else for_date
    candidates = []
    for s in db.billing_rate_schedules.values():
        if s["event_id"] != event_id:
            continue
        if s["responding_utility_id"] != responding_utility_id:
            continue
        if s["status"] not in ("PUBLISHED", "LOCKED"):
            continue
        start = db.parse_date(s["effective_start_date"])
        end = db.parse_date(s["effective_end_date"])
        if start <= target <= end:
            candidates.append(s)
    # At most one candidate is guaranteed by the overlap ban; take latest created if duplicates
    if not candidates:
        return None
    candidates.sort(key=lambda s: s["created_at"])
    return candidates[-1]


def crew_daily_billing(timesheet, crew, schedule, event):
    """Compute the day's bill amount (whole cents)."""
    cls = timesheet["day_classification"]
    rate_line = next(
        (rl for rl in schedule["rate_lines"] if rl.get("crew_type") == crew["crew_type"]),
        None,
    )
    if rate_line is None:
        # No rate line for this crew type -> bill zero for that line
        base = 0
    else:
        base = int(rate_line.get("hourly_rate_cents", 0))

    if cls == "REST":
        return 0

    if cls == "TRAVEL":
        # travel minutes at straight base; no OT, no premium, no equipment
        minutes = int(timesheet.get("reported_travel_minutes", 0) or 0)
        labor = round_half_up(Decimal(minutes) * Decimal(base) / Decimal(60))
        return labor

    if cls == "STANDBY":
        # flat 8h at base; equipment bills; no premium
        labor = round_half_up(Decimal(480) * Decimal(base) / Decimal(60))
        return labor + int(crew.get("equipment_daily_total_cents", 0))

    # WORK
    m = int(timesheet.get("reported_work_minutes", 0) or 0)
    ot_threshold = int(schedule.get("ot_threshold_minutes", 480))
    dt_threshold = int(schedule.get("dt_threshold_minutes", 960))
    ot_bps = int(schedule.get("ot_multiplier_bps", 15000))
    dt_bps = int(schedule.get("dt_multiplier_bps", 20000))

    reg = min(m, ot_threshold)
    ot = min(max(m - ot_threshold, 0), dt_threshold - ot_threshold)
    dt = max(m - dt_threshold, 0)

    labor = (
        round_half_up(Decimal(reg) * Decimal(base) / Decimal(60))
        + round_half_up(Decimal(ot) * Decimal(base) * Decimal(ot_bps) / (Decimal(60) * Decimal(10000)))
        + round_half_up(Decimal(dt) * Decimal(base) * Decimal(dt_bps) / (Decimal(60) * Decimal(10000)))
    )

    # Storm premium
    work_date = db.parse_date(timesheet["work_date"])
    p_start = db.parse_date(event["premium_window_start"])
    p_end = db.parse_date(event["premium_window_end"])
    if p_start <= work_date <= p_end:
        premium_bps = int(schedule.get("storm_premium_bps", 0))
        labor = round_half_up(Decimal(labor) * Decimal(10000 + premium_bps) / Decimal(10000))

    return labor + int(crew.get("equipment_daily_total_cents", 0))


def per_diem_claim_amount(member_count, meals_provided_count, day_factor_type, receipts_total_cents, schedule):
    """Returns (method_applied, amount_cents)."""
    method = schedule["per_diem_method"]
    per_diem_rate = int(schedule["per_diem_rate_cents"])
    day_factor = Decimal("1.0") if day_factor_type == "FULL" else Decimal("0.75")
    meal_factor = Decimal(3 - int(meals_provided_count)) / Decimal(3)

    if method == "STANDARD":
        raw = (
            Decimal(int(member_count))
            * Decimal(per_diem_rate)
            * day_factor
            * meal_factor
        )
        amount = round_half_up(raw)
    else:  # ACTUAL
        cap = round_half_up(
            Decimal(int(member_count)) * Decimal(per_diem_rate) * Decimal("1.5")
        )
        amount = min(int(receipts_total_cents), cap)
    return method, amount


def mobilization_fee(subtotal_cents, tiers):
    """Select the LAST tier with min_subtotal_cents <= S; fee = round_half_up(S * fee_bps / 10000)."""
    ordered = sorted(tiers, key=lambda t: int(t.get("min_subtotal_cents", 0)))
    chosen = None
    for t in ordered:
        if int(t.get("min_subtotal_cents", 0)) <= subtotal_cents:
            chosen = t
        else:
            break
    if chosen is None:
        return 0
    fee_bps = int(chosen.get("fee_bps", 0))
    return round_half_up(Decimal(subtotal_cents) * Decimal(fee_bps) / Decimal(10000))


def invoice_period_sweep(invoice, request, schedule):
    """Compute final-variant totals: CERTIFIED timesheets in period with billed_invoice_id NULL,
    APPROVED claims in period not swept by a non-VOID invoice.
    Returns (labor_subtotal, per_diem_subtotal, swept_timesheet_ids, swept_claim_ids)."""
    p_start = db.parse_date(invoice["billing_period_start"])
    p_end = db.parse_date(invoice["billing_period_end"])
    crews = crews_of_request(request["id"])
    crew_ids = {c["id"] for c in crews}

    labor = 0
    swept_ts = []
    for t in db.timesheets.values():
        if t["crew_id"] not in crew_ids:
            continue
        if t["status"] != "CERTIFIED":
            continue
        if t.get("billed_invoice_id"):
            continue
        wd = db.parse_date(t["work_date"])
        if not (p_start <= wd <= p_end):
            continue
        labor += int(t.get("certified_amount_cents") or 0)
        swept_ts.append(t["id"])

    perdiem = 0
    swept_pd = []
    # Claims not yet swept by a non-VOID invoice
    swept_by_non_void = set()
    for inv in db.invoices.values():
        if inv["id"] == invoice["id"]:
            continue
        if inv["status"] == "VOID":
            continue
        for cid in inv.get("_swept_claim_ids", []) or []:
            swept_by_non_void.add(cid)
    for c in db.per_diem_claims.values():
        if c["crew_id"] not in crew_ids:
            continue
        if c["status"] != "APPROVED":
            continue
        if c["id"] in swept_by_non_void:
            continue
        cd = db.parse_date(c["claim_date"])
        if not (p_start <= cd <= p_end):
            continue
        perdiem += int(c.get("amount_cents") or 0)
        swept_pd.append(c["id"])

    return labor, perdiem, swept_ts, swept_pd


def invoice_provisional(invoice, request, schedule, event):
    """Provisional variant: CERTIFIED + priced SUBMITTED timesheets + APPROVED + SUBMITTED claims in period."""
    p_start = db.parse_date(invoice["billing_period_start"])
    p_end = db.parse_date(invoice["billing_period_end"])
    crews = crews_of_request(request["id"])
    crew_map = {c["id"]: c for c in crews}

    labor = 0
    for t in db.timesheets.values():
        if t["crew_id"] not in crew_map:
            continue
        wd = db.parse_date(t["work_date"])
        if not (p_start <= wd <= p_end):
            continue
        if t["status"] == "CERTIFIED":
            if t.get("billed_invoice_id"):
                continue
            labor += int(t.get("certified_amount_cents") or 0)
        elif t["status"] == "SUBMITTED":
            # Estimate via crew_daily_billing on reported minutes
            crew = crew_map[t["crew_id"]]
            labor += crew_daily_billing(t, crew, schedule, event)

    perdiem = 0
    swept_by_non_void = set()
    for inv in db.invoices.values():
        if inv["id"] == invoice["id"]:
            continue
        if inv["status"] == "VOID":
            continue
        for cid in inv.get("_swept_claim_ids", []) or []:
            swept_by_non_void.add(cid)
    for c in db.per_diem_claims.values():
        if c["crew_id"] not in crew_map:
            continue
        if c["id"] in swept_by_non_void:
            continue
        cd = db.parse_date(c["claim_date"])
        if not (p_start <= cd <= p_end):
            continue
        if c["status"] in ("APPROVED", "SUBMITTED"):
            perdiem += int(c.get("amount_cents") or 0)

    subtotal = labor + perdiem
    fee = mobilization_fee(subtotal, schedule["mobilization_fee_tiers"])
    return subtotal, fee, subtotal + fee
