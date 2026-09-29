"""Lookups, terminal-state guards, derived-field recomputation and the
named calculations of PRD section 3."""
from decimal import Decimal

from common import (ZERO6, add_days, dec, month_last_day, q2, q6, rhu, today,
                    touch)
from errors import fail
from store import by_created, db, order_key, rows

# ---------------------------------------------------------------- constants

PLUG_BASE_CENTS = 3500000
DEPTH_RATE_CENTS_PER_FT = 1200
PLUG_CAP_CENTS = 25000000
BOND_COVERAGE_FACTOR = Decimal("1.25")

DRILLING_RATE_CENTS_PER_MONTH = 950000
PRODUCING_RATE_CENTS_PER_MONTH = 95000
WAGE_INDEX_ADJ = Decimal("1.042")
PCT_CAPITAL = Decimal("0.05")
PCT_OPERATING = Decimal("0.03")
OVERHEAD_FLOOR_CENTS = 25000
OVERHEAD_CAP_CENTS = 1500000

SEVERANCE_TAX_RATE_OIL = Decimal("0.046")
SEVERANCE_TAX_RATE_GAS = Decimal("0.075")
STATUTORY_DAYS_OIL = 60
STATUTORY_DAYS_GAS = 90
STATUTORY_INTEREST_ANNUAL_PCT = Decimal("0.12")
SUSPENSE_INTEREST_ANNUAL_PCT = Decimal("0.06")
DAY_BASIS = Decimal("365")

SHUT_IN_FIRST_PAYMENT_DAYS = 90
SHUT_IN_ANNIVERSARY_DAYS = 365
MAX_SHUT_IN_PAYMENTS = 2
OBLIGATION_WARNING_DAYS = 30
CONTINUOUS_DEV_DEFAULT_DAYS = 180
MAX_DISPUTE_ROUNDS = 2

PAYMENT_TERMS_DAYS = 30
DISPUTE_RESPONSE_DAYS = 60
DISPUTE_REBUTTAL_DAYS = 30
PPR_NOTICE_DAYS = 30

BILLED_STATEMENT_STATUSES = ("ISSUED", "DISPUTED", "SETTLED")
LIVE_DISPUTE_STATUSES = ("OPEN", "OPERATOR_RESPONDED", "ESCALATED")

# ---------------------------------------------------------------- path lookups

def _find(table, key, error_id):
    if not isinstance(key, str):
        fail(error_id)
    record = getattr(db, table).get(key)
    if record is None:
        fail(error_id)
    return record


def get_lease(key):
    return _find("leases", key, "ERR_LEASE_NOT_FOUND")


def get_well(key):
    return _find("wells", key, "ERR_WELL_NOT_FOUND")


def get_owner(key):
    return _find("owners", key, "ERR_INTEREST_OWNER_NOT_FOUND")


def get_interest(key):
    return _find("interests", key, "ERR_WELL_INTEREST_NOT_FOUND")


def get_afe(key):
    return _find("afes", key, "ERR_AFE_NOT_FOUND")


def get_statement(key):
    return _find("statements", key, "ERR_JIB_STATEMENT_NOT_FOUND")


def get_dispute(key):
    return _find("disputes", key, "ERR_DISPUTE_NOT_FOUND")


def get_revenue(key):
    return _find("revenues", key, "ERR_PRODUCTION_REVENUE_NOT_FOUND")


def get_disbursement(key):
    return _find("disbursements", key, "ERR_DISBURSEMENT_NOT_FOUND")


def get_transfer(key):
    return _find("transfers", key, "ERR_TRANSFER_NOT_FOUND")


def get_allocation(key):
    return _find("allocations", key, "ERR_WELL_NOT_FOUND")


def get_cost_entry(key):
    return _find("cost_entries", key, "ERR_WELL_NOT_FOUND")


def get_election(key):
    return _find("elections", key, "ERR_AFE_NOT_FOUND")


# ---------------------------------------------------------------- rung 11

TERMINAL = {
    "lease": ("tenure_status", ("EXPIRED",)),
    "well": ("well_status", ("PLUGGED",)),
    "statement": ("statement_status", ("ADJUSTED", "SETTLED", "VOID")),
    "dispute": ("dispute_status", ("RESOLVED_UPHELD", "RESOLVED_ADJUSTED", "EXPIRED")),
    "transfer": ("transfer_status", ("CLOSED",)),
    "disbursement": ("disbursement_status", ("PAID",)),
    "interest": ("interest_status", ("TERMINATED",)),
}


def guard_terminal(kind, record):
    field, values = TERMINAL[kind]
    if record.get(field) in values:
        fail("ERR_TERMINAL_STATE")


# ---------------------------------------------------------------- collections

def well_allocations(well_id, committed_only=False):
    found = [a for a in rows("allocations") if a["well_id"] == well_id]
    if committed_only:
        found = [a for a in found if a["allocation_status"] == "COMMITTED"]
    return by_created(found)


def lease_allocations(lease_id, committed_only=False):
    found = [a for a in rows("allocations") if a["lease_id"] == lease_id]
    if committed_only:
        found = [a for a in found if a["allocation_status"] == "COMMITTED"]
    return by_created(found)


def well_interests(well_id, status=None):
    found = [i for i in rows("interests") if i["well_id"] == well_id]
    if status:
        found = [i for i in found if i["interest_status"] == status]
    return by_created(found)


def owner_interests(owner_id, status=None):
    found = [i for i in rows("interests") if i["owner_id"] == owner_id]
    if status:
        found = [i for i in found if i["interest_status"] == status]
    return by_created(found)


def active_position(well_id, owner_id):
    for i in well_interests(well_id, "ACTIVE"):
        if i["owner_id"] == owner_id:
            return i
    return None


def operator_interest(well_id):
    for i in well_interests(well_id, "ACTIVE"):
        if i.get("is_operator"):
            return i
    return None


def well_statements(well_id):
    return by_created([s for s in rows("statements") if s["well_id"] == well_id])


def statement_line_items(statement_id):
    return by_created([l for l in rows("line_items") if l["statement_id"] == statement_id])


def statement_disputes(statement_id):
    return by_created([d for d in rows("disputes") if d["statement_id"] == statement_id])


def has_live_dispute(statement_id, exclude_id=None):
    for d in statement_disputes(statement_id):
        if exclude_id is not None and d["id"] == exclude_id:
            continue
        if d["dispute_status"] in LIVE_DISPUTE_STATUSES:
            return True
    return False


def well_revenues(well_id):
    return by_created([r for r in rows("revenues") if r["well_id"] == well_id])


def revenue_disbursements(revenue_id):
    return by_created([d for d in rows("disbursements") if d["revenue_id"] == revenue_id])


def owner_disbursements(owner_id):
    return by_created([d for d in rows("disbursements") if d["owner_id"] == owner_id])


def afe_elections(afe_id):
    return by_created([e for e in rows("elections") if e["afe_id"] == afe_id])


# ---------------------------------------------------------------- derived fields

def plugging_liability(total_depth_ft):
    return min(PLUG_BASE_CENTS + DEPTH_RATE_CENTS_PER_FT * int(total_depth_ft),
               PLUG_CAP_CENTS)


def recompute_lease_acres(lease):
    committed = lease_allocations(lease["id"], committed_only=True)
    total = sum((a["committed_acres"] for a in committed), dec(0))
    total = q2(total)
    if lease["tenure_status"] == "EXPIRED":
        held = q2(dec(0))
    else:
        held = q2(min(lease["gross_acres"], total))
    if lease["committed_acres_total"] != total or lease["held_acres"] != held:
        lease["committed_acres_total"] = total
        lease["held_acres"] = held
        touch(lease)


def recompute_allocation_factors(well):
    """unit_allocation_factor: committed rows only; signed residual to the
    largest committed_acres, ties by earliest created_at."""
    committed = well_allocations(well["id"], committed_only=True)
    if not committed:
        if well["allocation_factor_total"] != ZERO6:
            well["allocation_factor_total"] = ZERO6
            touch(well)
        return
    total_acres = sum((a["committed_acres"] for a in committed), dec(0))
    provisional = {}
    if total_acres <= 0:
        for a in committed:
            provisional[a["id"]] = ZERO6
    else:
        for a in committed:
            provisional[a["id"]] = q6(dec(a["committed_acres"]) / dec(total_acres))
        residual = dec(1) - sum(provisional.values(), dec(0))
        if residual != 0:
            target = sorted(committed,
                            key=lambda a: (-a["committed_acres"], order_key(a)))[0]
            provisional[target["id"]] = q6(provisional[target["id"]] + residual)
    for a in committed:
        value = provisional[a["id"]]
        if a["allocation_factor"] != value:
            a["allocation_factor"] = value
            touch(a)
    grand = q6(sum(provisional.values(), dec(0)))
    if well["allocation_factor_total"] != grand:
        well["allocation_factor_total"] = grand
        touch(well)
    seen = set()
    for a in committed:
        if a["lease_id"] in seen:
            continue
        seen.add(a["lease_id"])
        lease = db.leases.get(a["lease_id"])
        if lease is not None:
            recompute_lease_acres(lease)


def recompute_consent_wi(well):
    total = dec(0)
    for i in well_interests(well["id"], "ACTIVE"):
        if not i["non_consent_flag"]:
            total += i["working_interest_pct"]
    value = q6(total)
    if well["consent_working_interest_pct"] != value:
        well["consent_working_interest_pct"] = value
        return True
    return False


def bond_requirement(owner_id, extra_rows=()):
    """bond_coverage_requirement: per-well products rounded first, then the
    1.25 coverage factor applied to their sum and rounded."""
    subtotal = 0
    for i in owner_interests(owner_id, "ACTIVE"):
        well = db.wells.get(i["well_id"])
        if well is None or well["well_status"] == "PLUGGED":
            continue
        subtotal += rhu(dec(i["working_interest_pct"]) * dec(well["plugging_liability_cents"]))
    for well_id, wi_pct in extra_rows:
        well = db.wells.get(well_id)
        if well is None or well["well_status"] == "PLUGGED":
            continue
        subtotal += rhu(dec(wi_pct) * dec(well["plugging_liability_cents"]))
    return rhu(BOND_COVERAGE_FACTOR * dec(subtotal))


def recompute_required_bond(owner):
    value = bond_requirement(owner["id"])
    if owner["required_bond_cents"] != value:
        owner["required_bond_cents"] = value
        touch(owner)


def recompute_suspense_balance(owner):
    total = 0
    for d in owner_disbursements(owner["id"]):
        if d["disbursement_status"] == "SUSPENDED":
            total += d["net_amount_cents"]
    if owner["suspense_balance_cents"] != total:
        owner["suspense_balance_cents"] = total
        touch(owner)


# ---------------------------------------------------------------- obligation dates

def shut_in_next_due(lease):
    if lease.get("shut_in_start_date") is None:
        return None
    return add_days(lease["shut_in_start_date"],
                    SHUT_IN_FIRST_PAYMENT_DAYS
                    + SHUT_IN_ANNIVERSARY_DAYS * int(lease["shut_in_payments_made"]))


def continuous_dev_deadline(lease):
    if lease.get("last_operation_end_date") is None:
        return None
    return add_days(lease["last_operation_end_date"], lease["continuous_dev_window_days"])


def open_obligation_date(lease):
    """Earlier of the two deadlines ignoring nulls; ties go to the shut-in date."""
    shut_in = lease.get("shut_in_next_due_date")
    cont = lease.get("continuous_dev_deadline")
    if shut_in is None:
        return cont
    if cont is None:
        return shut_in
    return shut_in if shut_in <= cont else cont


# ---------------------------------------------------------------- cost pool / overhead

def statement_cost_pool(statement):
    start = statement["billing_period_start"]
    end = statement["billing_period_end"]
    pool = []
    for entry in by_created([c for c in rows("cost_entries")
                             if c["well_id"] == statement["well_id"]]):
        if statement["cost_basis"] == "ACCRUAL":
            if entry["cost_status"] in ("ACCRUED", "PAID") \
                    and start <= entry["incurred_date"] <= end:
                pool.append(entry)
        else:
            if entry["cost_status"] == "PAID" and entry.get("paid_date") is not None \
                    and start <= entry["paid_date"] <= end:
                pool.append(entry)
    capital = sum(e["amount_cents"] for e in pool if e["cost_class"] == "CAPITAL")
    operating = sum(e["amount_cents"] for e in pool if e["cost_class"] == "OPERATING")
    return pool, int(capital), int(operating)


def billable_month_count(start, end):
    if start > end:
        return 0
    count = 0
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        count += 1
        month += 1
        if month == 13:
            month = 1
            year += 1
    return count


def overhead_amount(statement, months, capital, operating):
    """joint_account_overhead: round the raw figure first, then clamp."""
    if statement["overhead_rate_class"] == "FIXED_RATE":
        rate = (DRILLING_RATE_CENTS_PER_MONTH
                if statement["activity_class"] == "DRILLING"
                else PRODUCING_RATE_CENTS_PER_MONTH)
        raw = WAGE_INDEX_ADJ * dec(rate) * dec(months)
    else:
        raw = PCT_CAPITAL * dec(capital) + PCT_OPERATING * dec(operating)
    rounded = rhu(raw)
    return min(max(rounded, OVERHEAD_FLOOR_CENTS), OVERHEAD_CAP_CENTS)


def recompute_statement_totals(statement):
    pool, capital, operating = statement_cost_pool(statement)
    months = billable_month_count(statement["billing_period_start"],
                                  statement["billing_period_end"])
    overhead = overhead_amount(statement, months, capital, operating)
    statement["capital_direct_cents"] = capital
    statement["operating_direct_cents"] = operating
    statement["direct_cost_cents"] = capital + operating
    statement["billable_months"] = months
    statement["overhead_cents"] = overhead
    statement["total_billed_cents"] = capital + operating + overhead
    return pool


def statutory_due_date(production_month, product_type):
    year = int(production_month[0:4])
    month = int(production_month[5:7])
    last = month_last_day(year, month)
    days = STATUTORY_DAYS_OIL if product_type == "OIL" else STATUTORY_DAYS_GAS
    return add_days(last, days)


def severance_rate(product_type):
    return SEVERANCE_TAX_RATE_OIL if product_type == "OIL" else SEVERANCE_TAX_RATE_GAS


# ---------------------------------------------------------------- ledger

def add_billed(well, amount):
    well["billed_to_date_cents"] = well["billed_to_date_cents"] + int(amount)
    touch(well)


def reverse_issued_statement(statement):
    """Compensating reversal applied when an ISSUED statement is superseded or
    voided: de-bill the well and unwind accrued non-consent balances."""
    well = db.wells.get(statement["well_id"])
    if well is None:
        return
    add_billed(well, -statement["total_billed_cents"])
    for line in statement_line_items(statement["id"]):
        if line["penalty_accrued_cents"] > 0:
            position = active_position(well["id"], line["owner_id"])
            if position is None:
                continue
            position["non_consent_recoverable_balance_cents"] = (
                position["non_consent_recoverable_balance_cents"]
                - line["non_consent_withheld_cents"]
                - line["penalty_accrued_cents"])
            touch(position)


# ---------------------------------------------------------------- cascades

def new_counters():
    return {
        "leases_expired": 0,
        "leases_flagged_obligation_due": 0,
        "leases_in_breach": 0,
        "disputes_escalated": 0,
        "disputes_expired": 0,
        "transfers_deemed_waived": 0,
        "allocations_withdrawn": 0,
        "revenues_suspended": 0,
        "disbursements_suspended": 0,
    }


def suspend_pooling_terminated_revenue(well, counters):
    """Cascade hops 3 and 4: pooling termination suspends revenue and the
    accrued disbursements that hang off it."""
    affected_owners = []
    for revenue in well_revenues(well["id"]):
        if revenue["distribution_status"] not in ("ACCRUED", "RELEASED"):
            continue
        revenue["distribution_status"] = "SUSPENDED"
        touch(revenue)
        counters["revenues_suspended"] += 1
        for disb in revenue_disbursements(revenue["id"]):
            if disb["disbursement_status"] != "ACCRUED":
                continue
            disb["disbursement_status"] = "SUSPENDED"
            disb["suspense_reason"] = "POOLING_TERMINATED"
            touch(disb)
            counters["disbursements_suspended"] += 1
            if disb["owner_id"] not in affected_owners:
                affected_owners.append(disb["owner_id"])
    for owner_id in affected_owners:
        owner = db.owners.get(owner_id)
        if owner is not None:
            recompute_suspense_balance(owner)


def expire_lease(lease, counters):
    """Four-hop lease-expiry cascade (PRD 3.1)."""
    lease["tenure_status"] = "EXPIRED"
    lease["obligation_status"] = "IN_BREACH"
    lease["held_acres"] = q2(dec(0))
    touch(lease)
    counters["leases_expired"] += 1

    affected_wells = []
    for alloc in lease_allocations(lease["id"], committed_only=True):
        alloc["allocation_status"] = "WITHDRAWN"
        alloc["withdrawn_reason"] = "LEASE_EXPIRED"
        touch(alloc)
        counters["allocations_withdrawn"] += 1
        well = db.wells.get(alloc["well_id"])
        if well is not None and well["id"] not in [w["id"] for w in affected_wells]:
            affected_wells.append(well)

    for well in affected_wells:
        recompute_allocation_factors(well)
        remaining = well_allocations(well["id"], committed_only=True)
        if len(remaining) < 2 and well["pooling_status"] != "POOLED_TERMINATED":
            well["pooling_status"] = "POOLED_TERMINATED"
            touch(well)
            suspend_pooling_terminated_revenue(well, counters)

    lease["committed_acres_total"] = q2(sum(
        (a["committed_acres"] for a in lease_allocations(lease["id"], committed_only=True)),
        dec(0)))
    lease["held_acres"] = q2(dec(0))
