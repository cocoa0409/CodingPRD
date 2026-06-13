"""Core domain logic: calculations, derived fields, and cascades.

All numbers are integer cents. References to PRD sections inline.

Key sets / status vocab:
  Advance.status: REQUESTED, APPROVED, DISBURSED, RECOUPING, SETTLED,
                  DEFAULTED, WRITTEN_OFF, DECLINED
  Penalty set (drives Worker.advance_eligibility ON_HOLD): {DEFAULTED, WRITTEN_OFF}
  Non-terminal-recovery set (counts toward Employer.outstanding_principal_cents):
        everything NOT in {SETTLED, WRITTEN_OFF}
  Committed set (available_earnings netting & clamp c2):
        {APPROVED, DISBURSED, RECOUPING, DEFAULTED}
"""
from decimal import Decimal

import clock
import db
from timeutil import parse_iso8601
from services.money import round_half_up, floor_fraction

PENALTY_SET = {"DEFAULTED", "WRITTEN_OFF"}
COMMITTED_SET = {"APPROVED", "DISBURSED", "RECOUPING", "DEFAULTED"}
DISBURSED_OR_BEYOND = {"DISBURSED", "RECOUPING", "DEFAULTED", "SETTLED", "WRITTEN_OFF"}
NON_TERMINAL_OUTSTANDING = {"REQUESTED", "APPROVED", "DISBURSED", "RECOUPING", "DEFAULTED", "DECLINED"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def employer_advances(employer_id):
    return [a for a in db.advances.values() if a["employer_id"] == employer_id]


def worker_advances(worker_id):
    return [a for a in db.advances.values() if a["worker_id"] == worker_id]


def period_advances(pay_period_id):
    return [a for a in db.advances.values() if a["pay_period_id"] == pay_period_id]


def current_non_disbursed_period(employer_id):
    """The employer's current pay period whose status is OPEN or LOCKED.

    PRD §3.4 ('the employer's current pay period whose status is OPEN or LOCKED')
    and §3.2 ('the employer's current non-disbursed pay period'). If more than one
    is non-disbursed, prefer the most-recently-created (greatest period_index).
    """
    candidates = [
        p for p in db.pay_periods.values()
        if p["employer_id"] == employer_id and p["status"] in ("OPEN", "LOCKED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p["period_index"])
    return candidates[-1]


def active_fee_schedule(employer_id):
    scheds = [
        f for f in db.fee_schedules.values()
        if f["employer_id"] == employer_id and f["status"] == "ACTIVE"
    ]
    if not scheds:
        return None
    scheds.sort(key=lambda f: f["_seq"])
    return scheds[-1]


# ---------------------------------------------------------------------------
# Gross accrual (sum-then-round) — PRD §3.3, §3.4, §2.6
# ---------------------------------------------------------------------------
def posted_time_entries(pay_period_id, worker_id=None):
    out = []
    for te in db.time_entries.values():
        if te["pay_period_id"] != pay_period_id:
            continue
        if te["status"] != "POSTED":
            continue
        if worker_id is not None and te["worker_id"] != worker_id:
            continue
        out.append(te)
    return out


def gross_for_worker_in_period(pay_period_id, worker):
    """round_half_up(sum over POSTED entries of hours_worked * worker.hourly_rate_cents).

    Sum-then-round: accumulate the exact products then round once (PRD §3.4).
    """
    rate = worker["hourly_rate_cents"]
    total = Decimal("0")
    for te in posted_time_entries(pay_period_id, worker["id"]):
        total += Decimal(str(te["hours_worked"])) * Decimal(rate)
    return round_half_up(total)


def gross_accrued_for_period(pay_period):
    """PayPeriod.gross_accrued_cents — sum over all POSTED entries of all workers,
    rounding the entire sum once (PRD §3.3 / SCAFFOLD PayPeriod.gross_accrued_cents).
    """
    total = Decimal("0")
    for te in posted_time_entries(pay_period["id"]):
        worker = db.workers.get(te["worker_id"])
        if worker is None:
            continue
        total += Decimal(str(te["hours_worked"])) * Decimal(worker["hourly_rate_cents"])
    return round_half_up(total)


# ---------------------------------------------------------------------------
# Available earnings — PRD §3.4, calculations.available_earnings
# ---------------------------------------------------------------------------
def net_available_earnings(worker):
    employer = db.employers.get(worker["employer_id"])
    period = current_non_disbursed_period(worker["employer_id"])
    if employer is None or period is None:
        return 0
    gross = gross_for_worker_in_period(period["id"], worker)
    accessible = floor_fraction(gross, employer["max_advance_pct_of_available"])
    committed = 0
    for a in worker_advances(worker["id"]):
        if a["pay_period_id"] == period["id"] and a["status"] in COMMITTED_SET:
            committed += a.get("recoup_target_cents") or 0
    return max(0, accessible - committed)


# ---------------------------------------------------------------------------
# Worker computed counters — PRD §3.2
# ---------------------------------------------------------------------------
def compute_tenure_days(worker):
    """floor((server_clock - hire_date) / 1 day) (PRD §3.2). Never negative below 0
    is not clamped by spec, but a future hire_date would yield a negative floor; we
    leave the raw floor so the tier selection (min_tenure_days >= 0) handles it."""
    hire = parse_iso8601(worker["hire_date"])
    delta = clock.now() - hire
    return int(delta.total_seconds() // 86400)


def period_advance_count(worker):
    period = current_non_disbursed_period(worker["employer_id"])
    if period is None:
        return 0
    count = 0
    for a in worker_advances(worker["id"]):
        if a["pay_period_id"] == period["id"] and a["status"] in ("DISBURSED", "RECOUPING", "DEFAULTED"):
            count += 1
    return count


def lifetime_advanced(worker):
    """Sum of principal_cents across all advances ever DISBURSED.

    'ever disbursed' = reached DISBURSED or beyond (DISBURSED, RECOUPING,
    DEFAULTED, SETTLED, WRITTEN_OFF). principal_cents is the approved principal.
    """
    total = 0
    for a in worker_advances(worker["id"]):
        if a["status"] in DISBURSED_OR_BEYOND:
            total += a.get("principal_cents") or 0
    return total


def derive_advance_eligibility(worker):
    """ON_HOLD iff the worker has >= 1 advance in {DEFAULTED, WRITTEN_OFF}."""
    for a in worker_advances(worker["id"]):
        if a["status"] in PENALTY_SET:
            return "ON_HOLD"
    return "ELIGIBLE"


def refresh_worker_eligibility(worker):
    """Recompute advance_eligibility; bump version only if it changed (PRD §2.4)."""
    new_val = derive_advance_eligibility(worker)
    if worker["advance_eligibility"] != new_val:
        worker["advance_eligibility"] = new_val
        db.touch(worker)


# ---------------------------------------------------------------------------
# Employer posture & exposure — PRD §2.9
# ---------------------------------------------------------------------------
def outstanding_principal(employer_id):
    """Sum of principal_outstanding_cents across this employer's advances NOT in
    {SETTLED, WRITTEN_OFF} (SCAFFOLD Employer.outstanding_principal_cents)."""
    total = 0
    for a in employer_advances(employer_id):
        if a["status"] not in ("SETTLED", "WRITTEN_OFF"):
            total += a.get("principal_outstanding_cents") or 0
    return total


def has_disbursed_period_discrepancy(employer_id):
    """True if any reconciliation statement for a DISBURSED period is in DISCREPANCY.

    PRD §2.9: posture is FROZEN whenever any reconciliation statement for a
    disbursed period is in discrepancy.
    """
    for s in db.reconciliation_statements.values():
        if s["employer_id"] != employer_id:
            continue
        period = db.pay_periods.get(s["pay_period_id"])
        if period is None or period["status"] != "DISBURSED":
            continue
        if s["outcome"] == "DISCREPANCY":
            return True
    return False


def derive_posture(employer):
    """HEALTHY | RESTRICTED | FROZEN (PRD §2.9).

    FROZEN takes precedence (any disbursed-period discrepancy). Else RESTRICTED
    when funding has fallen below outstanding exposure. Else HEALTHY.
    """
    if has_disbursed_period_discrepancy(employer["id"]):
        return "FROZEN"
    outstanding = outstanding_principal(employer["id"])
    if employer["funding_balance_cents"] < outstanding:
        return "RESTRICTED"
    return "HEALTHY"


def refresh_employer(employer):
    """Recompute outstanding_principal_cents + posture; bump version if changed."""
    changed = False
    new_out = outstanding_principal(employer["id"])
    if employer.get("outstanding_principal_cents") != new_out:
        employer["outstanding_principal_cents"] = new_out
        changed = True
    new_posture = derive_posture(employer)
    if employer.get("posture") != new_posture:
        employer["posture"] = new_posture
        changed = True
    if changed:
        db.touch(employer)


# ---------------------------------------------------------------------------
# Principal clamp — PRD §3.6, calculations.principal_clamp
# ---------------------------------------------------------------------------
def select_tier(employer_id, tenure_days):
    """Among the employer's ACTIVE policies whose min_tenure_days <= tenure_days,
    choose the one with the GREATEST min_tenure_days; tie -> earliest created_at
    (use _seq for a deterministic created_at order). None if no policy qualifies.
    """
    qualifying = [
        p for p in db.advance_policies.values()
        if p["employer_id"] == employer_id
        and p["status"] == "ACTIVE"
        and p["min_tenure_days"] <= tenure_days
    ]
    if not qualifying:
        return None
    qualifying.sort(key=lambda p: (p["min_tenure_days"], -p["_seq"]))
    # greatest min_tenure_days last; among equal min_tenure_days we want earliest
    # created (smallest _seq). Sorting by (min_tenure_days asc, -_seq asc) puts the
    # greatest min_tenure_days last, and within it the largest -_seq (smallest _seq)
    # last -> earliest created wins.
    return qualifying[-1]


def clamp_principal(advance, worker, period, tier):
    """Return clamped principal_cents (PRD §3.6).

    c1 = tier.per_advance_ceiling_cents
    c2 = tier.cumulative_period_ceiling_cents
         - sum(principal_cents over this worker's advances in COMMITTED_SET for the period)
    c3 = worker.net_available_earnings_cents
    principal = max(0, min(requested, c1, c2, c3))
    """
    requested = advance["requested_principal_cents"]
    c1 = tier["per_advance_ceiling_cents"]
    committed_principal = 0
    for a in worker_advances(worker["id"]):
        if a["id"] == advance["id"]:
            continue
        if a["pay_period_id"] == period["id"] and a["status"] in COMMITTED_SET:
            committed_principal += a.get("principal_cents") or 0
    c2 = tier["cumulative_period_ceiling_cents"] - committed_principal
    c3 = net_available_earnings(worker)
    return max(0, min(requested, c1, c2, c3))


# ---------------------------------------------------------------------------
# Advance fees — PRD §3.7, calculations.advance_fee
# ---------------------------------------------------------------------------
def compute_fees(advance, principal_cents, fee_schedule):
    """Return (expedite_fee_cents, total_fee_cents).

    INSTANT: expedite = flat + round_half_up(principal * pct) (round-then-sum).
    Tip contributes only if tip_allowed. Combined fee capped at max_total_fee_cents,
    trimming the tip first (expedite never reduced).
    """
    if advance["disbursement_speed"] == "INSTANT":
        pct_component = round_half_up(
            Decimal(str(principal_cents)) * Decimal(str(fee_schedule["expedite_pct_fee"]))
        )
        expedite = fee_schedule["expedite_flat_fee_cents"] + pct_component
    else:
        expedite = 0

    tip = advance.get("tip_cents", 0) if fee_schedule["tip_allowed"] else 0
    raw_total = expedite + tip
    cap = fee_schedule["max_total_fee_cents"]
    if raw_total > cap:
        total_fee = cap
    else:
        total_fee = raw_total
    return expedite, total_fee


# ---------------------------------------------------------------------------
# Repayment helpers
# ---------------------------------------------------------------------------
def advance_repayments(advance_id):
    return [r for r in db.repayments.values() if r["advance_id"] == advance_id]


def fee_recouped_so_far(advance_id):
    return sum(r["amount_cents"] for r in advance_repayments(advance_id) if r["applied_to"] == "FEE")


def recompute_advance_recoup(advance):
    """Recompute amount_recouped_cents from its Repayment rows and
    principal_outstanding_cents = recoup_target - amount_recouped (while not terminal)."""
    recouped = sum(r["amount_cents"] for r in advance_repayments(advance["id"]))
    advance["amount_recouped_cents"] = recouped
    if advance["status"] not in ("SETTLED", "WRITTEN_OFF", "DECLINED"):
        advance["principal_outstanding_cents"] = (advance.get("recoup_target_cents") or 0) - recouped


# ---------------------------------------------------------------------------
# Reconciliation — PRD §3.11, calculations.reconciliation
# ---------------------------------------------------------------------------
def compute_reconciliation(statement):
    """Recompute the four aggregates + outcome on a statement (in place)."""
    period_id = statement["pay_period_id"]
    advs = period_advances(period_id)

    expected = 0
    for a in advs:
        if a["status"] in DISBURSED_OR_BEYOND:
            expected += a.get("recoup_target_cents") or 0

    actual = 0
    for b in db.repayment_batches.values():
        if b["pay_period_id"] == period_id and b["status"] in ("POSTED", "RECONCILED"):
            actual += b.get("total_recouped_cents") or 0

    written_off = 0
    for a in advs:
        if a["status"] == "WRITTEN_OFF":
            written_off += a.get("written_off_amount_cents") or 0

    drift = expected - actual - written_off
    statement["expected_recoup_cents"] = expected
    statement["actual_recouped_cents"] = actual
    statement["written_off_cents"] = written_off
    statement["drift_cents"] = drift
    statement["outcome"] = "CLEAN" if drift == 0 else "DISCREPANCY"


def get_period_statement(pay_period_id):
    for s in db.reconciliation_statements.values():
        if s["pay_period_id"] == pay_period_id:
            return s
    return None


def recompute_period_statement(pay_period_id, create_if_absent=False):
    """Recompute (and optionally create) the period's statement. Returns it or None.

    A recompute on a statement carrying version counts as a mutation (PRD §2.4),
    so bump version when its computed fields change.
    """
    stmt = get_period_statement(pay_period_id)
    if stmt is None:
        if not create_if_absent:
            return None
        period = db.pay_periods.get(pay_period_id)
        common = db.new_common_fields()
        stmt = {
            **common,
            "pay_period_id": pay_period_id,
            "employer_id": period["employer_id"],
            "expected_recoup_cents": 0,
            "actual_recouped_cents": 0,
            "written_off_cents": 0,
            "drift_cents": 0,
            "outcome": "CLEAN",
            "signed_by_user_id": None,
            "status": "DRAFT",
        }
        compute_reconciliation(stmt)
        db.reconciliation_statements[stmt["id"]] = stmt
        return stmt

    # existing statement: recompute, bump version only if values changed
    before = (
        stmt["expected_recoup_cents"], stmt["actual_recouped_cents"],
        stmt["written_off_cents"], stmt["drift_cents"], stmt["outcome"],
    )
    compute_reconciliation(stmt)
    after = (
        stmt["expected_recoup_cents"], stmt["actual_recouped_cents"],
        stmt["written_off_cents"], stmt["drift_cents"], stmt["outcome"],
    )
    if before != after:
        db.touch(stmt)
    return stmt


# ---------------------------------------------------------------------------
# Advance settlement (system transition RECOUPING -> SETTLED) — PRD §3.9
# ---------------------------------------------------------------------------
def maybe_settle(advance):
    """If a RECOUPING advance's outstanding hit 0, settle it and run its cascade.

    Side effects (PRD §3.9):
      - status -> SETTLED
      - employer.funding_balance_cents += recoup_target_cents
      - recompute employer outstanding + posture
      - re-evaluate worker advance_eligibility (clears hold if penalty set empty)
    """
    if advance["status"] != "RECOUPING":
        return
    if advance.get("principal_outstanding_cents", 0) != 0:
        return
    advance["status"] = "SETTLED"
    db.touch(advance)
    employer = db.employers.get(advance["employer_id"])
    if employer is not None:
        employer["funding_balance_cents"] += advance.get("recoup_target_cents") or 0
        db.touch(employer)
        refresh_employer(employer)
    worker = db.workers.get(advance["worker_id"])
    if worker is not None:
        refresh_worker_eligibility(worker)
