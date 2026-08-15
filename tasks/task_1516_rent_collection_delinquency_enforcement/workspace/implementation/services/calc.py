"""Calculation rules (scaffold 1.3 / PRD 3.x). All money is integer cents;
round-half-up is done in exact integer arithmetic — never floats (PRD 2.4)."""

from datetime import date, timedelta

import db


def parse_d(s):
    return date.fromisoformat(s)


def round_half_up_div(p, q):
    """round_half_up(p / q) for p >= 0, q > 0, in exact integer arithmetic."""
    return (2 * p + q) // (2 * q)


def add_months(d, n):
    """d + n calendar months, clamping the day to the target month's length."""
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    next_first = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    last_day = (next_first - timedelta(days=1)).day
    return date(y, m, min(d.day, last_day))


FEE_KINDS = ("LATE_FEE", "NSF_FEE", "PLAN_SETUP_FEE", "DAMAGE_FEE")


def property_of(lease):
    return db.properties[lease["property_id"]]


def net_applied_cents(charge_id):
    """Sum of APPLY minus REVERSE allocations on a charge (PRD 3.2)."""
    total = 0
    for a in db.allocations.values():
        if a["charge_id"] != charge_id:
            continue
        total += a["amount_cents"] if a["direction"] == "APPLY" else -a["amount_cents"]
    return total


def late_fee_cents(lease, charge, prop, as_of):
    """late_fee_assessment (PRD 3.6): grace-reduced days late, then the lease's
    FLAT or PERCENT_PLUS_DAILY formula, clamped by the property cap (the fee may
    land exactly on the cap)."""
    days_late = max(0, (as_of - parse_d(charge["due_date"])).days - lease["grace_period_days"])
    if days_late < 1:
        return 0
    if lease["late_fee_type"] == "FLAT":
        raw = lease["late_fee_flat_cents"]
    else:
        raw = round_half_up_div(
            charge["amount_cents"] * lease["late_fee_percent_bps"], 10000
        ) + lease["late_fee_daily_cents"] * days_late
    return min(raw, prop["late_fee_cap_cents"])


def has_late_fee_for_period(lease_id, rent_charge):
    """At most one non-VOID LATE_FEE per (lease, period) (PRD 3.6)."""
    for c in db.charges.values():
        if (
            c["lease_id"] == lease_id
            and c["kind"] == "LATE_FEE"
            and c["status"] != "VOID"
            and c["period_start_date"] == rent_charge["period_start_date"]
            and c["period_end_date"] == rent_charge["period_end_date"]
        ):
            return True
    return False


def open_charges(lease_id):
    return [
        c
        for c in db.charges.values()
        if c["lease_id"] == lease_id and c["status"] in ("OPEN", "PARTIALLY_PAID")
    ]


def total_outstanding(lease_id):
    """Sum of outstanding over the lease's OPEN/PARTIALLY_PAID charges (PRD 3.3)."""
    return sum(c["outstanding_cents"] for c in open_charges(lease_id))


def waterfall_candidates(lease_id, policy):
    """payment_waterfall_allocation (PRD 3.3): OPEN/PARTIALLY_PAID charges with
    positive outstanding, ordered by class rank per the property's posting
    priority policy, then due_date ASC, then created_at ASC (ids never used)."""
    cands = [c for c in open_charges(lease_id) if c["outstanding_cents"] > 0]
    if policy == "FEES_FIRST":
        rank = lambda c: 0 if c["kind"] in FEE_KINDS else 1
    else:  # RENT_FIRST
        rank = lambda c: 0 if c["kind"] == "RENT" else 1
    cands.sort(key=lambda c: (rank(c), c["due_date"], c["created_at"]))
    return cands


def move_out_balances(lease):
    """move_out_reconciliation (PRD 3.9). Returns (forward, chronological).

    forward: sum of outstanding over OPEN/PARTIALLY_PAID charges (acceleration
    view; counts charges due after move-out at face).
    chronological: only charges with due_date <= reference date contribute; a
    RENT charge straddling the move-out is prorated round-half-up by occupied
    days (the move-out day itself not counted) over period days (both endpoints
    counted), reduced by waived and net applied cents, floored at zero. For a
    lease that has not ended, today's date stands in and nothing prorates."""
    forward = sum(c["outstanding_cents"] for c in open_charges(lease["id"]))
    if lease["status"] == "ENDED" and lease["move_out_date"]:
        ref = parse_d(lease["move_out_date"])
        prorate = True
    else:
        ref = db.clock_date()
        prorate = False
    chronological = 0
    for c in db.charges.values():
        if c["lease_id"] != lease["id"] or c["status"] == "VOID":
            continue
        if parse_d(c["due_date"]) > ref:
            continue
        if (
            prorate
            and c["kind"] == "RENT"
            and parse_d(c["period_start_date"]) <= ref < parse_d(c["period_end_date"])
        ):
            occupied = (ref - parse_d(c["period_start_date"])).days
            days_in_period = (parse_d(c["period_end_date"]) - parse_d(c["period_start_date"])).days + 1
            prorated = round_half_up_div(c["amount_cents"] * occupied, days_in_period)
            chronological += max(0, prorated - c["waived_cents"] - net_applied_cents(c["id"]))
        else:
            chronological += c["outstanding_cents"]
    return forward, chronological


def notice_demand(notice):
    """notice_demand_amount (PRD 3.7): covered outstanding plus, per covered
    RENT charge with positive outstanding and no non-VOID LATE_FEE for the same
    period, a provisional late fee evaluated as of today + cure period."""
    lease = db.leases[notice["lease_id"]]
    prop = property_of(lease)
    total = 0
    for cid in notice["charge_ids"]:
        total += db.charges[cid]["outstanding_cents"]
    as_of = db.clock_date() + timedelta(days=prop["notice_cure_period_days"])
    for cid in notice["charge_ids"]:
        c = db.charges[cid]
        if (
            c["kind"] == "RENT"
            and c["outstanding_cents"] > 0
            and not has_late_fee_for_period(lease["id"], c)
        ):
            total += late_fee_cents(lease, c, prop, as_of)
    return total


def installment_schedule(scheduled_total_cents, count, first_installment_date):
    """installment_split (PRD 3.8): floor the per-installment share first, then
    distribute the remainder one cent each to the EARLIEST sequence numbers;
    due dates one calendar month apart."""
    per = scheduled_total_cents // count
    remainder = scheduled_total_cents - per * count
    first = parse_d(first_installment_date)
    out = []
    for i in range(1, count + 1):
        out.append(
            {
                "sequence_number": i,
                "due_date": add_months(first, i - 1).isoformat(),
                "amount_cents": per + 1 if i <= remainder else per,
                "status": "PENDING",
            }
        )
    return out


def month_key(d):
    return "%04d-%02d" % (d.year, d.month)


def property_month_waived_cents(property_id, month):
    """waiver_monthly_cap (PRD 3.5): waived cents applied in the calendar month
    across every charge of every lease of the property."""
    return sum(
        e["amount_cents"]
        for e in db.waiver_events
        if e["property_id"] == property_id and e["month"] == month
    )
