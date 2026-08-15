"""Business logic: constants, aging derivation, sweeps, guards, calculations,
serializers, and cascading side effects (PRD section 3 / SCAFFOLD 1.2-1.3)."""

from datetime import date, timedelta

from db import db
from util import iso_ms, parse_dt, touch, today


# ---------------------------------------------------------------------------
# configured constants (SCAFFOLD 1.3 + design pins)
# ---------------------------------------------------------------------------

STATEMENT_CYCLE_DAYS = 30
EARLY_OUT_RECALL_DAYS = 90          # guarantor_liability_date + 90 (design pin)
AGENCY_RECALL_WINDOW_DAYS = 90      # placed_at + 90
DISPUTE_INVESTIGATION_DAYS = 30     # filed_at + 30
INSTALLMENT_INTERVAL_DAYS = 30
PAYMENT_PLAN_DEFAULT_MISSED_THRESHOLD = 2
MAX_INSTALLMENTS = 12
REQUIRED_STATEMENTS_BEFORE_AGENCY = 3
REQUIRED_STATEMENTS_BEFORE_WRITEOFF = 3
WRITE_OFF_REVERSAL_WINDOW_DAYS = 90
RECALL_FEE_BPS = 1500
RECALL_FEE_CAP_CENTS = 50000
VENDOR_MIN_RECOVERY_BPS = 1200

FPL_TABLE = {
    1: 1506000, 2: 2044000, 3: 2582000, 4: 3120000,
    5: 3658000, 6: 4196000, 7: 4734000, 8: 5272000,
}
FULL_CHARITY_FPL_CAP = 200
PARTIAL_CHARITY_FPL_CAP = 300
SCORE_FULL_CHARITY_MIN = 700
SCORE_PARTIAL_CHARITY_MIN = 550

DEFAULT_RESERVE_METHODOLOGY = "DIRECT"

ELIGIBLE_OUTCOMES = ("FULL_CHARITY", "PARTIAL_CHARITY")
STATEMENT_ELIGIBLE_STATUSES = ("OPEN", "IN_EARLY_OUT", "IN_COLLECTIONS")
SCREENABLE_STATUSES = ("OPEN", "IN_EARLY_OUT", "IN_COLLECTIONS")


# ---------------------------------------------------------------------------
# aging bucket derivation (SCAFFOLD 1.3 aging_bucket_derivation)
# Recomputed on account reads only — the clock sweep deliberately does NOT
# rewrite accounts ("aging_bucket recomputed on next account read", §1.5
# clock endpoint side effects), so write paths consult the stored bucket.
# ---------------------------------------------------------------------------

def bucket_for_days(days):
    if days < 30:
        return "CURRENT"
    if days < 60:
        return "BUCKET_30"
    if days < 90:
        return "BUCKET_60"
    if days < 120:
        return "BUCKET_90"
    return "BUCKET_120_PLUS"


def derive_bucket(account):
    gl = date.fromisoformat(account["guarantor_liability_date"])
    return bucket_for_days((today() - gl).days)


def recompute_aging_on_read(account):
    """Refresh the derived bucket on read; aging_bucket_entered_at resets only
    when the bucket value actually changes. Derived refresh is not a client
    mutation: version and updated_at are untouched."""
    b = derive_bucket(account)
    if b != account["aging_bucket"]:
        account["aging_bucket"] = b
        account["aging_bucket_entered_at"] = iso_ms(db.now)


# ---------------------------------------------------------------------------
# computed / aggregate reads
# ---------------------------------------------------------------------------

def statements_sent_count(account_id):
    """Count of statements currently SENT or DELIVERED (RETURNED_UNDELIVERABLE
    is excluded)."""
    return sum(
        1 for s in db.statements.values()
        if s["account_id"] == account_id and s["status"] in ("SENT", "DELIVERED")
    )


def placement_recovered_cents(placement_id):
    """Gross sum of RecoveryTransaction amounts attributed to a placement."""
    return sum(
        r["amount_cents"] for r in db.recovery_transactions.values()
        if r.get("attributed_placement_id") == placement_id
    )


def installments_paid_count(plan_id):
    """Count of INSTALLMENT RecoveryTransaction rows attributed to a plan."""
    return sum(
        1 for r in db.recovery_transactions.values()
        if r["payment_kind"] == "INSTALLMENT" and r.get("payment_plan_id") == plan_id
    )


def plan_paid_cents(plan_id):
    return sum(
        r["amount_cents"] for r in db.recovery_transactions.values()
        if r["payment_kind"] == "INSTALLMENT" and r.get("payment_plan_id") == plan_id
    )


def post_writeoff_recoveries_cents(write_off_id):
    return sum(
        r["amount_cents"] for r in db.recovery_transactions.values()
        if r["payment_kind"] == "POST_WRITEOFF_RECOVERY"
        and r.get("write_off_id") == write_off_id
    )


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------

def active_early_out(account_id):
    for p in db.early_out_placements.values():
        if p["account_id"] == account_id and p["status"] == "ACTIVE":
            return p
    return None


def active_agency_placement(account_id):
    for p in db.agency_placements.values():
        if p["account_id"] == account_id and p["status"] == "ACTIVE":
            return p
    return None


def eligible_evaluated_screening(account_id):
    for s in db.screenings.values():
        if (s["account_id"] == account_id and s["status"] == "EVALUATED"
                and s["eligibility_outcome"] in ELIGIBLE_OUTCOMES):
            return s
    return None


def open_dispute(account_id):
    for d in db.disputes.values():
        if d["account_id"] == account_id and d["status"] == "OPEN":
            return d
    return None


def active_payment_plan(account_id):
    for p in db.payment_plans.values():
        if p["account_id"] == account_id and p["status"] == "ACTIVE":
            return p
    return None


# ---------------------------------------------------------------------------
# charity eligibility calculation (SCAFFOLD 1.3 charity_eligibility)
# ---------------------------------------------------------------------------

def evaluate_eligibility(screening):
    """Returns (eligibility_outcome, charity_writeoff_percent, fpl_percent)."""
    if screening["screening_model"] == "FPL_TIERED":
        base = FPL_TABLE[screening["household_size"]]
        fpl_percent = (screening["household_income_cents"] * 100) // base  # floor
        if fpl_percent <= FULL_CHARITY_FPL_CAP:
            return "FULL_CHARITY", 100, fpl_percent
        if fpl_percent <= PARTIAL_CHARITY_FPL_CAP:
            return "PARTIAL_CHARITY", 50, fpl_percent
        return "NOT_ELIGIBLE", 0, fpl_percent
    # SCORE_BASED: fpl_percent stays null
    score = screening["third_party_score"]
    if score >= SCORE_FULL_CHARITY_MIN:
        return "FULL_CHARITY", 100, None
    if score >= SCORE_PARTIAL_CHARITY_MIN:
        return "PARTIAL_CHARITY", 50, None
    return "NOT_ELIGIBLE", 0, None


# ---------------------------------------------------------------------------
# agency recall fee (SCAFFOLD 1.3 agency_recall_fee): 1500 bps of placement
# balance, capped at 50000 cents, rounded DOWN; audit-only bookkeeping.
# ---------------------------------------------------------------------------

def agency_recall_fee_cents(placement):
    fee = (placement["placement_balance_cents"] * RECALL_FEE_BPS) // 10000
    return min(fee, RECALL_FEE_CAP_CENTS)


# ---------------------------------------------------------------------------
# balance-driven closure cascade (PRD 3.8): when a posting drives the account
# balance to zero the account closes CLOSED_PAID and any active placement
# closes with it (COMPLETED_PAID early-out / CLOSED_PAID agency).
# ---------------------------------------------------------------------------

def close_account_paid_if_zero(account):
    if account["current_balance_cents"] != 0:
        return
    if account["status"] not in ("OPEN", "IN_EARLY_OUT", "IN_COLLECTIONS"):
        return
    eop = active_early_out(account["id"])
    if eop is not None:
        eop["status"] = "COMPLETED_PAID"
        touch(eop)
    ap = active_agency_placement(account["id"])
    if ap is not None:
        ap["status"] = "CLOSED_PAID"
        touch(ap)
    account["status"] = "CLOSED_PAID"
    account["status_reason"] = "balance recovered in full"


# ---------------------------------------------------------------------------
# clock-advance sweeps (PRD 2.4, 3.6, 3.7): payment-plan default sweep then
# dispute-expiry sweep, run after the new logical time is installed.
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    plans_flagged = 0
    plans = sorted(
        db.payment_plans.values(),
        key=lambda p: (p["first_installment_due"], p["_seq"]),
    )
    for plan in plans:
        if plan["status"] != "ACTIVE":
            continue
        first = date.fromisoformat(plan["first_installment_due"])
        due_count = 0
        for i in range(plan["installment_count"]):
            due_date = first + timedelta(days=i * INSTALLMENT_INTERVAL_DAYS)
            if due_date <= today():  # an installment due today counts as due
                due_count += 1
        missed = max(0, due_count - installments_paid_count(plan["id"]))
        changed = missed != plan["missed_installment_count"]
        plan["missed_installment_count"] = missed
        if missed >= PAYMENT_PLAN_DEFAULT_MISSED_THRESHOLD:
            plan["status"] = "IN_DEFAULT"
            plan["default_flagged_at"] = iso_ms(db.now)
            plans_flagged += 1
            changed = True
        if changed:
            touch(plan)

    disputes_expired = 0
    for d in sorted(db.disputes.values(), key=lambda r: r["_seq"]):
        if d["status"] != "OPEN":
            continue
        if today() > date.fromisoformat(d["investigation_due_at"]):
            d["status"] = "EXPIRED"
            d["resolution_outcome"] = "UNRESOLVED_EXPIRED"
            d["resolved_at"] = iso_ms(db.now)
            touch(d)
            disputes_expired += 1
            account = db.accounts.get(d["account_id"])
            if account is not None:
                # bureau reporting stands; a frozen status reverts to REPORTED
                if account["credit_reporting_status"] == "FROZEN_BY_DISPUTE":
                    account["credit_reporting_status"] = "REPORTED"
                touch(account)

    return plans_flagged, disputes_expired


# ---------------------------------------------------------------------------
# serializers (computed fields are attached here)
# ---------------------------------------------------------------------------

def serialize_account(account):
    from util import serialize
    return serialize(account, {
        "statements_sent_count": statements_sent_count(account["id"]),
    })


def serialize_statement(stmt):
    from util import serialize
    return serialize(stmt)


def serialize_screening(scr):
    from util import serialize
    return serialize(scr)


def serialize_early_out(p):
    from util import serialize
    return serialize(p, {"recovered_cents": placement_recovered_cents(p["id"])})


def serialize_agency_placement(p):
    from util import serialize
    return serialize(p, {"recovered_cents": placement_recovered_cents(p["id"])})


def serialize_dispute(d):
    from util import serialize
    return serialize(d)


def serialize_plan(plan):
    from util import serialize
    return serialize(plan, {
        "installments_paid_count": installments_paid_count(plan["id"]),
    })


def serialize_write_off(wo):
    from util import serialize
    return serialize(wo)


def serialize_log_entry(entry):
    from util import serialize
    return serialize(entry)


def serialize_recovery(rec):
    from util import serialize
    return serialize(rec)


def serialize_snapshot(snap):
    from util import serialize
    return serialize(snap)


# ---------------------------------------------------------------------------
# Medicare log entry creation (SCAFFOLD 1.3 medicare_collection_effort_days)
# ---------------------------------------------------------------------------

def build_medicare_log_entry(write_off, account, append_only_record):
    posted_at = parse_dt(write_off["posted_at"])
    gl = date.fromisoformat(account["guarantor_liability_date"])
    indigence = False
    for s in db.screenings.values():
        if (s["account_id"] == account["id"]
                and s["status"] in ("EVALUATED", "APPLIED")
                and s["eligibility_outcome"] in ELIGIBLE_OUTCOMES
                and s.get("screened_at")
                and parse_dt(s["screened_at"]) <= posted_at):
            indigence = True
            break
    entry = append_only_record()
    entry.update({
        "write_off_id": write_off["id"],
        "account_id": account["id"],
        "cost_report_year": write_off["medicare_cost_report_year"],
        "claimed_amount_cents": write_off["amount_cents"],
        "indigence_documented": indigence,
        "collection_effort_days": (posted_at.date() - gl).days,
        "logged_at": iso_ms(db.now),
        "voided_at": None,
    })
    db.medicare_log_entries[entry["id"]] = entry
    return entry
