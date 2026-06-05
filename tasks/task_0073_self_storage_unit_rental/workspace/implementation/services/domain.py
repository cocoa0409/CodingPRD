"""Core domain logic: ledger, balances, billing cycle, state transitions, cascades."""
from db import db
from models import make_common, touch, now
from services import calc


# ---- Ledger & balance -------------------------------------------------------

def append_ledger(lease, entry_type, amount_cents, source_type, source_id):
    """Append an immutable LedgerEntry and adjust the lease's denormalized balance."""
    entry = make_common(with_version=False)
    entry.update({
        "lease_id": lease["id"],
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "source_type": source_type,
        "source_id": source_id,
    })
    db.ledger_entries[entry["id"]] = entry
    lease["balance_cents"] += int(amount_cents)
    return entry


def replay_balance(lease_id):
    """ledger_replay_balance variant: sum signed amounts in created_at ASC order."""
    rows = [e for e in db.ledger_entries.values() if e["lease_id"] == lease_id]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return sum(e["amount_cents"] for e in rows)


# ---- Occupancy --------------------------------------------------------------

def recompute_occupied(facility_id):
    facility = db.facilities.get(facility_id)
    if facility is None:
        return
    count = sum(
        1 for u in db.units.values()
        if u["facility_id"] == facility_id and u["status"] == "OCCUPIED"
    )
    if facility["occupied_unit_count"] != count:
        facility["occupied_unit_count"] = count
        touch(facility)
    else:
        facility["occupied_unit_count"] = count


# ---- Invoice helpers --------------------------------------------------------

OPEN_STATUSES = ("OPEN", "PARTIAL", "OVERDUE")


def lease_open_invoices(lease_id):
    return [
        inv for inv in db.invoices.values()
        if inv["lease_id"] == lease_id and inv["status"] in OPEN_STATUSES
    ]


def outstanding_for_lease(lease_id):
    return sum(
        inv["total_amount_cents"] - inv["amount_paid_cents"]
        for inv in lease_open_invoices(lease_id)
    )


def active_policy_for_lease(lease_id):
    for p in db.insurance_policies.values():
        if p["lease_id"] == lease_id and p["status"] == "ACTIVE":
            return p
    return None


def recompute_days_past_due(lease):
    """Whole days between clock and due_date of the oldest OPEN/PARTIAL/OVERDUE invoice."""
    open_invs = lease_open_invoices(lease["id"])
    if not open_invs:
        new_val = 0
    else:
        oldest = min(open_invs, key=lambda inv: inv["due_date"])
        d = calc.whole_days_between(now(), oldest["due_date"])
        new_val = max(0, d)
    if lease.get("days_past_due") != new_val:
        lease["days_past_due"] = new_val
    return new_val


def make_invoice(lease, period_start, period_end, due_date, base, climate, insurance):
    inv = make_common()
    inv.update({
        "lease_id": lease["id"],
        "period_start": period_start,
        "period_end": period_end,
        "due_date": due_date,
        "base_amount_cents": int(base),
        "climate_amount_cents": int(climate),
        "insurance_amount_cents": int(insurance),
        "late_fee_cents": 0,
        "total_amount_cents": int(base) + int(climate) + int(insurance),
        "amount_paid_cents": 0,
        "status": "OPEN",
    })
    db.invoices[inv["id"]] = inv
    return inv


# ---- Billing period helpers -------------------------------------------------

def add_months(dt, n):
    month = dt.month - 1 + n
    year = dt.year + month // 12
    month = month % 12 + 1
    import calendar as _cal
    day = min(dt.day, _cal.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def next_billing_date(after_dt, billing_day):
    """The next datetime on day==billing_day strictly after after_dt (date-wise)."""
    import calendar as _cal
    candidate = after_dt
    # build candidate for current month
    year, month = after_dt.year, after_dt.month
    dim = _cal.monthrange(year, month)[1]
    day = min(billing_day, dim)
    candidate = after_dt.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
    if candidate <= after_dt:
        nxt = add_months(after_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0), 1)
        dim2 = _cal.monthrange(nxt.year, nxt.month)[1]
        day2 = min(billing_day, dim2)
        candidate = nxt.replace(day=day2)
    return candidate


def billing_date_for(ref_dt, billing_day):
    """The billing-day datetime within ref_dt's own month (clamped to month length)."""
    import calendar as _cal
    dim = _cal.monthrange(ref_dt.year, ref_dt.month)[1]
    day = min(billing_day, dim)
    return ref_dt.replace(day=day, hour=0, minute=0, second=0, microsecond=0)


# ---- Activation -------------------------------------------------------------

def generate_first_invoice(lease, facility):
    """Prorated first invoice covering [start_date, next billing day)."""
    start = lease["start_date"]
    period_end = next_billing_date(start, lease["billing_day"])
    policy = active_policy_for_lease(lease["id"])
    insurance_premium = policy["monthly_premium_cents"] if policy else 0
    base, climate, insurance, monthly_total = calc.monthly_components(
        lease["monthly_rate_cents"], lease["climate_controlled"],
        facility["climate_premium_pct"], insurance_premium,
    )
    prorated_total, _, _ = calc.prorate_first(monthly_total, start)
    # Distribute the proration factor across each rounded component is NOT what the
    # spec says: prorate the full monthly total once. We store the prorated total as
    # base_amount_cents and keep climate/insurance components implicit-in-total only
    # if non-prorated. PRD: "prorated base is the full monthly total * days/days".
    # So base_amount_cents holds the prorated full-month figure; climate & insurance
    # sub-components for the first period are folded into the single prorated number.
    inv = make_common()
    inv.update({
        "lease_id": lease["id"],
        "period_start": start,
        "period_end": period_end,
        "due_date": start,
        "base_amount_cents": int(prorated_total),
        "climate_amount_cents": 0,
        "insurance_amount_cents": 0,
        "late_fee_cents": 0,
        "total_amount_cents": int(prorated_total),
        "amount_paid_cents": 0,
        "status": "OPEN",
    })
    db.invoices[inv["id"]] = inv
    # First monthly invoice begins where the prorated period ends.
    lease["_next_bill_date"] = period_end
    append_ledger(lease, "CHARGE", prorated_total, "INVOICE", inv["id"])
    return inv


# ---- Billing cycle ----------------------------------------------------------

def run_billing_cycle(facility):
    """Generate due invoices, assess late fees, advance delinquency, lapse insurance."""
    clock = now()
    leases = [
        l for l in db.leases.values()
        if l["facility_id"] == facility["id"] and l["status"] in ("ACTIVE", "DELINQUENT", "PRE_LIEN")
    ]
    leases.sort(key=lambda l: (l["created_at"], l["_seq"]))

    # 1. Generate monthly invoices for leases whose billing day(s) are due.
    for lease in leases:
        if lease["status"] not in ("ACTIVE", "DELINQUENT", "PRE_LIEN"):
            continue
        _generate_due_invoices(lease, facility, clock)

    # 2. Assess late fees on OPEN/PARTIAL invoices past grace.
    for lease in leases:
        _assess_late_fees(lease, facility, clock)

    # 3. Advance lease delinquency states + insurance lapse + recompute dpd.
    for lease in leases:
        recompute_days_past_due(lease)
        _advance_delinquency(lease, facility)
        _lapse_insurance(lease)
        recompute_days_past_due(lease)


def _generate_due_invoices(lease, facility, clock):
    billing_day = lease["billing_day"]
    cursor = lease.get("_next_bill_date")
    if cursor is None:
        return
    guard = 0
    while cursor <= clock and guard < 600:
        guard += 1
        period_start = cursor
        period_end = next_billing_date(cursor, billing_day)
        policy = active_policy_for_lease(lease["id"])
        insurance_premium = policy["monthly_premium_cents"] if policy else 0
        base, climate, insurance, total = calc.monthly_components(
            lease["monthly_rate_cents"], lease["climate_controlled"],
            facility["climate_premium_pct"], insurance_premium,
        )
        inv = make_invoice(lease, period_start, period_end, period_start,
                           base, climate, insurance)
        append_ledger(lease, "CHARGE", inv["total_amount_cents"], "INVOICE", inv["id"])
        lease["_next_bill_date"] = period_end
        touch(lease)
        cursor = period_end


def _assess_late_fees(lease, facility, clock):
    grace = facility["late_fee_grace_days"]
    fee = facility["late_fee_cents"]
    invs = [inv for inv in db.invoices.values()
            if inv["lease_id"] == lease["id"] and inv["status"] in ("OPEN", "PARTIAL")]
    invs.sort(key=lambda inv: (inv["created_at"], inv["_seq"]))
    for inv in invs:
        if inv["late_fee_cents"] != 0:
            continue
        dpd = calc.whole_days_between(clock, inv["due_date"])
        if dpd >= grace:
            inv["late_fee_cents"] = fee
            inv["total_amount_cents"] += fee
            inv["status"] = "OVERDUE"
            touch(inv)
            append_ledger(lease, "LATE_FEE", fee, "INVOICE", inv["id"])
            touch(lease)


def _advance_delinquency(lease, facility):
    has_overdue = any(
        inv["lease_id"] == lease["id"] and inv["status"] == "OVERDUE"
        for inv in db.invoices.values()
    )
    if lease["status"] == "ACTIVE" and has_overdue:
        lease["status"] = "DELINQUENT"
        touch(lease)
    if lease["status"] == "DELINQUENT":
        dpd = lease.get("days_past_due", 0)
        # PRD §3.5: a DELINQUENT lease whose days_past_due reaches at least 30
        # advances to PRE_LIEN. The lower boundary (>= 30) is the operative
        # trigger; a lease that crosses straight past 30 in a single late billing
        # run must still reach PRE_LIEN so the foreclosure path stays reachable.
        if dpd >= 30:
            lease["status"] = "PRE_LIEN"
            touch(lease)


def _lapse_insurance(lease):
    for p in db.insurance_policies.values():
        if p["lease_id"] != lease["id"] or p["status"] != "ACTIVE":
            continue
        # PRD §3.5: "When the invoice that carries an active policy's premium becomes
        # OVERDUE, that InsurancePolicy moves ACTIVE -> LAPSED on the billing run."
        # An ACTIVE policy's premium for a period is carried by that period's invoice;
        # any OVERDUE invoice on the lease means that period's premium went unpaid. (The
        # first invoice folds the prorated premium into its base, so we cannot key off
        # insurance_amount_cents alone.)
        overdue = any(
            inv["lease_id"] == lease["id"] and inv["status"] == "OVERDUE"
            for inv in db.invoices.values()
        )
        if overdue:
            p["status"] = "LAPSED"
            touch(p)


# ---- Cure cascade -----------------------------------------------------------

def apply_cure_cascade(lease):
    """When balance reaches zero, cure delinquency, cancel open proceedings, reactivate
    lapsed insurance (PRD §3.5/§3.6)."""
    if lease["balance_cents"] != 0:
        return
    # Cancel open auction proceedings in NOTICE_SENT or LIEN_FILED.
    cancelled_proceeding = False
    for ap in db.auction_proceedings.values():
        if ap["lease_id"] == lease["id"] and ap["status"] in ("NOTICE_SENT", "LIEN_FILED"):
            ap["status"] = "CANCELLED"
            touch(ap)
            cancelled_proceeding = True
    # Return the lease to ACTIVE: a DELINQUENT/PRE_LIEN lease cures directly; a LIEN
    # lease whose NOTICE_SENT/LIEN_FILED proceeding was just cancelled also returns
    # to ACTIVE (PRD §3.6 cure cascade / proceeding-cancel side effect).
    if lease["status"] in ("DELINQUENT", "PRE_LIEN") or (cancelled_proceeding and lease["status"] == "LIEN"):
        lease["status"] = "ACTIVE"
        lease["days_past_due"] = 0
        touch(lease)
    # Reactivate lapsed insurance.
    for p in db.insurance_policies.values():
        if p["lease_id"] == lease["id"] and p["status"] == "LAPSED":
            p["status"] = "ACTIVE"
            touch(p)
