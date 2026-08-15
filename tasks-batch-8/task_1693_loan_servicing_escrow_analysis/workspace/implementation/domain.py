"""Business-logic services: ledger, advances, sweep, calculations, cascades."""

from datetime import timedelta
from decimal import Decimal

from errors import ApiError, ERR_ADVANCE_CAP
from store import store
from util import (
    ADVANCE_CAP_CENTS,
    add_business_days,
    add_months,
    bump,
    days_30360,
    fmt_date,
    new_ledger_entry,
    new_record,
    now_dt,
    now_ts,
    parse_date,
    rhu,
    rhu_div,
    today,
)

# ----------------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------------

def account_of_loan(loan_id):
    for a in store.accounts.values():
        if a["loan_id"] == loan_id:
            return a
    return None


def line_items_of_account(account_id, active_only=False):
    rows = [li for li in store.line_items.values() if li["escrow_account_id"] == account_id]
    if active_only:
        rows = [li for li in rows if li["status"] == "ACTIVE"]
    return sorted(rows, key=lambda r: r["_seq"])


def entries_of_account(account_id):
    rows = [e for e in store.ledger_entries.values() if e["escrow_account_id"] == account_id]
    # Chronological replay order: effective_date ASC, created order ASC.
    return sorted(rows, key=lambda e: (e["effective_date"], e["_seq"]))


def advances_of_account(account_id, open_only=False):
    rows = [a for a in store.advances.values() if a["escrow_account_id"] == account_id]
    if open_only:
        rows = [a for a in rows if a["status"] in ("OUTSTANDING", "RECOVERING")]
    return sorted(rows, key=lambda r: r["_seq"])

# ----------------------------------------------------------------------------
# Ledger
# ----------------------------------------------------------------------------

def post_ledger(account, entry_type, amount_cents, effective_date, src_type, src_id, note=""):
    entry = new_ledger_entry({
        "escrow_account_id": account["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "effective_date": effective_date,
        "running_balance_cents": 0,
        "source_entity_type": src_type,
        "source_entity_id": src_id,
        "note": note,
    })
    store.ledger_entries[entry["id"]] = entry
    replay(account)
    return entry


def replay(account):
    """Recompute running balances and account balance from the ledger."""
    bal = 0
    for e in entries_of_account(account["id"]):
        bal += e["amount_cents"]
        e["running_balance_cents"] = bal
    account["balance_cents"] = bal

# ----------------------------------------------------------------------------
# Cushion / monthly escrow (initial_cushion_and_payment)
# ----------------------------------------------------------------------------

def recompute_cushion(account):
    total = sum(li["expected_annual_amount_cents"] for li in line_items_of_account(account["id"], True))
    account["target_cushion_cents"] = rhu_div(total, 6)


def base_monthly_sum(account_id):
    """Pinned order: round each line's monthly share FIRST, then sum."""
    return sum(rhu_div(li["expected_annual_amount_cents"], 12)
               for li in line_items_of_account(account_id, True))

# ----------------------------------------------------------------------------
# Advances
# ----------------------------------------------------------------------------

def advance_outstanding(a):
    return a["amount_cents"] - a["recovered_cents"] - a["written_off_cents"]


def advance_sync(a):
    a["outstanding_cents"] = advance_outstanding(a)
    if a["status"] in ("OUTSTANDING", "RECOVERING"):
        if a["outstanding_cents"] == 0:
            a["status"] = "RECOVERED"
        elif a["recovered_cents"] > 0:
            a["status"] = "RECOVERING"
        else:
            a["status"] = "OUTSTANDING"


def check_advance_cap(account_id, new_amount):
    total = sum(advance_outstanding(a) for a in advances_of_account(account_id, True))
    if total + new_amount > ADVANCE_CAP_CENTS:
        raise ApiError(ERR_ADVANCE_CAP, 422,
                       "Advance would push total outstanding above ADVANCE_CAP_CENTS")


def new_advance(account, reason, amount_cents, disbursement_id=None):
    a = new_record({
        "escrow_account_id": account["id"],
        "disbursement_id": disbursement_id,
        "reason": reason,
        "amount_cents": amount_cents,
        "recovered_cents": 0,
        "written_off_cents": 0,
        "outstanding_cents": amount_cents,
        "status": "OUTSTANDING",
    })
    store.advances[a["id"]] = a
    return a


def recovery_waterfall(account, amount, effective_date):
    """Allocate amount FIFO (created_at ASC, ties: larger outstanding first)
    across OUTSTANDING/RECOVERING advances; post ADVANCE_RECOVERY entries."""
    remaining = amount
    cands = [a for a in advances_of_account(account["id"], True)]
    cands.sort(key=lambda a: (a["_seq"], -a["outstanding_cents"]))
    for a in cands:
        if remaining <= 0:
            break
        take = min(remaining, a["outstanding_cents"])
        if take <= 0:
            continue
        post_ledger(account, "ADVANCE_RECOVERY", -take, effective_date,
                    "EscrowAdvance", a["id"])
        a["recovered_cents"] += take
        advance_sync(a)
        bump(a)
        remaining -= take

# ----------------------------------------------------------------------------
# Tax penalty accrual (tax_penalty_accrual)
# ----------------------------------------------------------------------------

def compute_penalty(rec, as_of):
    if not rec["delinquent_since"]:
        return 0
    days = days_30360(parse_date(rec["delinquent_since"]), as_of)
    months = days // 30
    if months <= 0:
        return 0
    rate = Decimal(rec["monthly_penalty_rate_bps"]) / Decimal(10000)
    if rec["penalty_method"] == "SIMPLE":
        return rhu(Decimal(rec["amount_due_cents"]) * rate * months)
    # COMPOUND: per-month rounding pinned inside the loop
    bal = rec["amount_due_cents"]
    for _ in range(months):
        bal = bal + rhu(Decimal(bal) * rate)
    return bal - rec["amount_due_cents"]

# ----------------------------------------------------------------------------
# Sweep (POST /_clock/set_current_utc)
# ----------------------------------------------------------------------------

def run_sweep():
    now_date = today()
    transitions = 0

    # --- Payees: VERIFIED -> EXPIRED past verification_expires_at ---
    for p in sorted(store.payees.values(), key=lambda r: r["_seq"]):
        if p["verification_status"] == "VERIFIED" and p["verification_expires_at"]:
            if now_date > parse_date(p["verification_expires_at"]):
                p["verification_status"] = "EXPIRED"
                bump(p)
                transitions += 1
                for d in sorted(store.disbursements.values(), key=lambda r: r["_seq"]):
                    if d["payee_id"] == p["id"] and d["status"] == "SCHEDULED":
                        d["status"] = "BLOCKED"
                        bump(d)
                        transitions += 1

    # --- Insurance lapse / expiry detection ---
    for pol in sorted(store.policies.values(), key=lambda r: r["_seq"]):
        if pol["status"] != "ACTIVE":
            continue
        if parse_date(pol["coverage_end_date"]) >= now_date:
            continue
        covered = False
        for other in store.policies.values():
            if (other["id"] != pol["id"] and other["loan_id"] == pol["loan_id"]
                    and other["policy_type"] == pol["policy_type"]
                    and other["status"] == "ACTIVE"
                    and parse_date(other["coverage_start_date"]) <= now_date
                    < parse_date(other["coverage_end_date"])):
                covered = True
                break
        pol["status"] = "EXPIRED_CLOSED" if covered else "LAPSED"
        bump(pol)
        transitions += 1

    # --- Tax records: DUE_SOON / DELINQUENT / PENALTY_ACCRUING / REDEMPTION_RISK ---
    for rec in sorted(store.tax_records.values(), key=lambda r: r["_seq"]):
        changed = False
        while True:
            st = rec["status"]
            due = parse_date(rec["due_date"])
            grace_end = due + timedelta(days=rec["grace_period_days"])
            if st == "MONITORING":
                if now_date > grace_end:
                    rec["status"] = "DELINQUENT"
                    rec["delinquent_since"] = fmt_date(grace_end + timedelta(days=1))
                    changed = True
                    continue
                if due - timedelta(days=30) <= now_date <= grace_end:
                    rec["status"] = "DUE_SOON"
                    changed = True
                    continue
                break
            if st == "DUE_SOON":
                if now_date > grace_end:
                    rec["status"] = "DELINQUENT"
                    rec["delinquent_since"] = fmt_date(grace_end + timedelta(days=1))
                    changed = True
                    continue
                break
            if st == "DELINQUENT":
                pen = compute_penalty(rec, now_date)
                if pen != rec["accrued_penalty_cents"]:
                    rec["accrued_penalty_cents"] = pen
                    changed = True
                if pen > 0:
                    rec["status"] = "PENALTY_ACCRUING"
                    changed = True
                    continue
                break
            if st == "PENALTY_ACCRUING":
                pen = compute_penalty(rec, now_date)
                if pen != rec["accrued_penalty_cents"]:
                    rec["accrued_penalty_cents"] = pen
                    changed = True
                if now_date > parse_date(rec["delinquent_since"]) + timedelta(days=730):
                    rec["status"] = "REDEMPTION_RISK"
                    changed = True
                    continue
                break
            if st == "REDEMPTION_RISK":
                pen = compute_penalty(rec, now_date)
                if pen != rec["accrued_penalty_cents"]:
                    rec["accrued_penalty_cents"] = pen
                    changed = True
                break
            break
        if changed:
            bump(rec)
            transitions += 1

    return transitions

# ----------------------------------------------------------------------------
# Annual escrow analysis (trial_balance_projection + shortage_deficiency_surplus
# + monthly_escrow_payment)
# ----------------------------------------------------------------------------

def compute_analysis_fields(account, cycle):
    start = parse_date(cycle["projection_start_date"])
    window_end = cycle["window_end_date"]
    lines = line_items_of_account(account["id"], active_only=True)

    # Installments per window month m = 0..11
    per_month = [0] * 12
    total_disb = 0
    for li in lines:
        amt = rhu_div(li["expected_annual_amount_cents"], li["installments_per_year"])
        step = 12 // li["installments_per_year"]
        k = 0
        first = parse_date(li["first_due_date"])
        while True:
            due = add_months(first, k * step)
            if fmt_date(due) > window_end:
                break
            if due >= start:
                m = (due.year - start.year) * 12 + (due.month - start.month)
                if 0 <= m < 12:
                    per_month[m] += amt
                    total_disb += amt
            k += 1
            if k > 1200:
                break

    # Start balance per method variant
    if cycle["method"] == "PROSPECTIVE":
        start_balance = account["balance_cents"]
    else:  # LEDGER_ACTUAL
        start_balance = sum(
            e["amount_cents"]
            for e in entries_of_account(account["id"])
            if e["effective_date"] < cycle["projection_start_date"]
        )

    # 12-month projection using the CURRENT (old) monthly escrow for every month
    monthly = account["monthly_escrow_cents"] or 0
    bal = start_balance
    lowest = None
    for m in range(12):
        bal = bal + monthly - per_month[m]
        if lowest is None or bal < lowest:
            lowest = bal

    cushion_target = rhu_div(total_disb, 6)
    deficiency = max(0, -lowest)
    shortage = (cushion_target - max(lowest, 0)) if lowest < cushion_target else 0
    surplus = max(0, start_balance - cushion_target)
    base = base_monthly_sum(account["id"])
    spread_total = shortage + deficiency
    spread_monthly = spread_total // 12
    spread_first = spread_total - 11 * spread_monthly

    cycle["start_balance_cents"] = start_balance
    cycle["projected_annual_disbursements_cents"] = total_disb
    cycle["cushion_target_cents"] = cushion_target
    cycle["lowest_projected_balance_cents"] = lowest
    cycle["shortage_cents"] = shortage
    cycle["deficiency_cents"] = deficiency
    cycle["surplus_cents"] = surplus
    cycle["base_monthly_escrow_cents"] = base
    cycle["spread_monthly_cents"] = spread_monthly
    cycle["spread_first_month_cents"] = spread_first
    cycle["new_monthly_escrow_cents"] = base + spread_monthly
    cycle["computed_at"] = now_ts()

# ----------------------------------------------------------------------------
# Cascades
# ----------------------------------------------------------------------------

def close_account_for_loan(loan):
    """Payoff / transfer-out cascade."""
    account = account_of_loan(loan["id"])
    if account and account["account_status"] in ("ACTIVE", "SUSPENDED"):
        if account["balance_cents"] > 0:
            post_ledger(account, "SURPLUS_REFUND", -account["balance_cents"],
                        fmt_date(today()), "Loan", loan["id"])
        account["account_status"] = "CLOSED"
        bump(account)
        for d in sorted(store.disbursements.values(), key=lambda r: r["_seq"]):
            if d["escrow_account_id"] == account["id"] and d["status"] in ("SCHEDULED", "BLOCKED"):
                d["status"] = "CANCELLED"
                bump(d)


def void_notices_of_analysis(analysis_id, include_acknowledged=True):
    states = ("DRAFT", "SENT", "ACKNOWLEDGED") if include_acknowledged else ("DRAFT", "SENT")
    for n in sorted(store.notices.values(), key=lambda r: r["_seq"]):
        if n["analysis_id"] == analysis_id and n["status"] in states:
            n["status"] = "VOIDED"
            bump(n)


def make_notice(account, cycle):
    finalize_date = today()
    eff = add_months(finalize_date.replace(day=1), 2)
    send_by = eff - timedelta(days=30)
    if cycle["deficiency_cents"] and cycle["deficiency_cents"] > 0:
        ntype = "DEFICIENCY"
    elif cycle["shortage_cents"] and cycle["shortage_cents"] > 0:
        ntype = "SHORTAGE"
    elif cycle["surplus_cents"] and cycle["surplus_cents"] > 0:
        ntype = "SURPLUS"
    else:
        ntype = "PAYMENT_CHANGE"
    notice = new_record({
        "analysis_id": cycle["id"],
        "notice_type": ntype,
        "old_monthly_escrow_cents": account["monthly_escrow_cents"],
        "new_monthly_escrow_cents": cycle["new_monthly_escrow_cents"],
        "shortage_option": None,
        "effective_date": fmt_date(eff),
        "send_by_date": fmt_date(send_by),
        "sent_at": None,
        "timeliness": None,
        "status": "DRAFT",
    })
    store.notices[notice["id"]] = notice
    return notice
