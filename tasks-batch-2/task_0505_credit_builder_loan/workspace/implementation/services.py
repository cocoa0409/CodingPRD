"""Business logic: posture, state transitions, payment allocation, sweeps.

Every behavior traces to a PRD §3 sentence. Helpers here are called from routes.
"""
from db import store
from clock import fmt_iso, add_months, whole_months_between, parse_iso
from common import stamp_create, touch, touch_time_only
from constants import (
    GRACE_DAYS, LATE_FEE_CENTS, LATE_FEE_CAP_CENTS, GRADUATION_MIN_STREAK,
    DAYS_PER_MONTH, BUREAUS,
)
import calculations as calc


# ---------------------------------------------------------------------------
# Account posture (PRD §2.6)
# ---------------------------------------------------------------------------
def recompute_posture(account):
    """ELIGIBLE iff kyc VERIFIED AND disclosure ACKNOWLEDGED AND status OPEN;
    FROZEN when status FROZEN; BLOCKED otherwise."""
    if account["status"] == "FROZEN":
        account["posture"] = "FROZEN"
    elif (
        account["kyc_status"] == "VERIFIED"
        and account["disclosure_status"] == "ACKNOWLEDGED"
        and account["status"] == "OPEN"
    ):
        account["posture"] = "ELIGIBLE"
    else:
        account["posture"] = "BLOCKED"


# ---------------------------------------------------------------------------
# Loan ownership chain (PRD §2.1)
# ---------------------------------------------------------------------------
def loan_schedules(loan_id):
    return [s for s in store.schedules.values() if s["loan_id"] == loan_id]


def card_for_account(account_id):
    """Return a (non-closed-preferred) secured card for the account, if any.
    Used for graduation flagging / release linkage."""
    cards = [c for c in store.secured_cards.values() if c["account_id"] == account_id]
    return cards


def linked_loan_for_card(card):
    """Find the loan whose graduation flagged this card (same account)."""
    loans = [
        l for l in store.loans.values()
        if l["account_id"] == card["account_id"]
    ]
    # Prefer a GRADUATED loan; otherwise any loan of the account.
    grads = [l for l in loans if l["lifecycle_status"] == "GRADUATED"]
    if grads:
        return sorted(grads, key=lambda l: (l["created_at"], l.get("_seq", 0)))[0]
    if loans:
        return sorted(loans, key=lambda l: (l["created_at"], l.get("_seq", 0)))[0]
    return None


# ---------------------------------------------------------------------------
# On-time streak (PRD §3.6)
# ---------------------------------------------------------------------------
def _grace_deadline(due_iso):
    from datetime import timedelta
    return parse_iso(due_iso) + timedelta(days=GRACE_DAYS)


def mark_installments_paid_and_streak(loan, schedules, posted_at):
    """After allocation, mark installments PAID oldest-first and advance on_time_streak
    for each newly-PAID installment whose amount_due was fully covered at/before
    due_date + GRACE_DAYS. (PRD §3.4 / §3.6)"""
    now = posted_at
    for s in sorted(schedules, key=lambda x: x["period_index"]):
        if s["status"] == "PAID":
            continue
        if s["amount_paid_cents"] >= s["amount_due_cents"]:
            was_late = s["status"] == "LATE"
            s["status"] = "PAID"
            touch(s)
            # on-time iff fully covered at or before due+grace and not previously LATE
            if not was_late and now <= _grace_deadline(s["due_date"]):
                loan["on_time_streak"] += 1


# ---------------------------------------------------------------------------
# Payment posting (PRD §3.4) + delinquency cure (PRD §3.5) + payoff (PRD §3.7)
# ---------------------------------------------------------------------------
def apply_payment(loan, amount_cents, source, posted_at):
    """Allocate a payment, mutate loan/schedules, handle cure + payoff cascade.
    Returns the created Payment entity (not yet stored)."""
    schedules = loan_schedules(loan["id"])
    result = calc.allocate_payment(loan, schedules, amount_cents)

    # Mark installments paid + advance streak for on-time coverage
    mark_installments_paid_and_streak(loan, schedules, posted_at)

    # Overpayment -> wallet (PRD §3.4)
    if result["overpay_cents"] > 0:
        acct = store.accounts[loan["account_id"]]
        acct["wallet_cents"] += result["overpay_cents"]
        touch(acct)

    # Delinquency cure (PRD §3.5): if after allocation no installment is past
    # due+grace, cure back to CURRENT from DPD_30/DPD_60.
    cure_delinquency(loan, posted_at)

    # Payoff (PRD §3.7): outstanding principal reaches 0 -> ACTIVE -> PAID_OFF
    if loan["lifecycle_status"] == "ACTIVE" and loan["outstanding_principal_cents"] == 0:
        drive_paid_off(loan)

    payment = {
        "id": store.new_id(),
        "loan_id": loan["id"],
        "amount_cents": amount_cents,
        "source": source,
        "applied_principal_cents": result["applied_principal_cents"],
        "applied_interest_cents": result["applied_interest_cents"],
        "applied_fee_cents": result["applied_fee_cents"],
        "posted_at": fmt_iso(posted_at),
        "status": "POSTED",
    }
    stamp_create(payment)
    return payment


def cure_delinquency(loan, now):
    """If no unpaid installment remains past due+grace, cure to CURRENT (PRD §3.5)."""
    if loan["delinquency_status"] in ("DPD_30", "DPD_60"):
        schedules = loan_schedules(loan["id"])
        still_past = any(
            s["status"] in ("SCHEDULED", "LATE")
            and now > _grace_deadline(s["due_date"])
            for s in schedules
        )
        if not still_past:
            loan["delinquency_status"] = "CURRENT"
            loan["on_time_streak"] = 0  # resumes from 0 (PRD §3.5)
            touch(loan)


def drive_paid_off(loan):
    """ACTIVE -> PAID_OFF (PRD §3.7): mark schedule PAID, set CURRENT,
    release principal_paid_cents to wallet."""
    schedules = loan_schedules(loan["id"])
    for s in schedules:
        if s["status"] in ("SCHEDULED", "LATE"):
            s["status"] = "PAID"
            touch(s)
    acct = store.accounts[loan["account_id"]]
    acct["wallet_cents"] += loan["principal_paid_cents"]
    touch(acct)
    loan["lifecycle_status"] = "PAID_OFF"
    loan["delinquency_status"] = "CURRENT"
    touch(loan)


# ---------------------------------------------------------------------------
# Delinquency sweep (PRD §3.5) — ONE bucket advance per sweep run.
# ---------------------------------------------------------------------------
_DPD_LADDER = ["CURRENT", "DPD_30", "DPD_60", "DPD_90", "CHARGED_OFF"]
_NEXT_THRESHOLD = {"DPD_30": 1, "DPD_60": 31, "DPD_90": 61, "CHARGED_OFF": 91}


def _oldest_unpaid(schedules):
    unpaid = [s for s in schedules if s["status"] in ("SCHEDULED", "LATE")]
    if not unpaid:
        return None
    return sorted(unpaid, key=lambda s: s["period_index"])[0]


def _assess_late_fee(loan):
    """Flat fee per bucket crossing, capped over the loan (PRD §3.5)."""
    total_assessed = loan.get("total_late_fees_assessed", 0)
    if total_assessed + LATE_FEE_CENTS <= LATE_FEE_CAP_CENTS:
        add = LATE_FEE_CENTS
    else:
        add = max(0, LATE_FEE_CAP_CENTS - total_assessed)
    loan["outstanding_late_fee_cents"] = loan.get("outstanding_late_fee_cents", 0) + add
    loan["total_late_fees_assessed"] = total_assessed + add


def delinquency_sweep_one(loan, now):
    """Age a single ACTIVE loan one bucket against the current clock (PRD §3.5)."""
    if loan["lifecycle_status"] != "ACTIVE":
        return
    oldest = _oldest_unpaid(loan_schedules(loan["id"]))
    if oldest is None:
        return
    deadline = _grace_deadline(oldest["due_date"])
    if now <= deadline:
        return  # within grace — still CURRENT
    bg = (now - parse_iso(oldest["due_date"])).days - GRACE_DAYS  # days beyond grace
    if bg < 1:
        return
    state = loan["delinquency_status"]
    idx = _DPD_LADDER.index(state)
    if idx >= len(_DPD_LADDER) - 1:
        return  # already CHARGED_OFF
    nxt = _DPD_LADDER[idx + 1]
    if bg < _NEXT_THRESHOLD[nxt]:
        return  # not yet far enough for the next bucket

    # Advance exactly one bucket. Sweep-driven loan changes use touch_time_only so
    # the payment-OCC version (PRD §2.8) is not advanced by a system sweep.
    if nxt == "DPD_30":
        # newly missed: increment missed_count, reset streak, mark LATE, assess fee
        if oldest["status"] != "LATE":
            loan["missed_count"] += 1
        oldest["status"] = "LATE"
        touch(oldest)
        loan["on_time_streak"] = 0
        loan["delinquency_status"] = "DPD_30"
        _assess_late_fee(loan)
        touch_time_only(loan)
    elif nxt in ("DPD_60", "DPD_90"):
        loan["delinquency_status"] = nxt
        _assess_late_fee(loan)
        touch_time_only(loan)
    elif nxt == "CHARGED_OFF":
        loan["delinquency_status"] = "CHARGED_OFF"
        # couple into lifecycle: ACTIVE -> DEFAULTED, release principal_paid only
        acct = store.accounts[loan["account_id"]]
        acct["wallet_cents"] += loan["principal_paid_cents"]
        touch(acct)
        loan["lifecycle_status"] = "DEFAULTED"
        touch_time_only(loan)


def run_delinquency_sweep():
    for loan in list(store.loans.values()):
        delinquency_sweep_one(loan, store.now())


# ---------------------------------------------------------------------------
# Autopay sweep (PRD §3.11)
# ---------------------------------------------------------------------------
def _installment_amount_for_draft(loan):
    """The current (oldest unpaid) installment's amount_due for an autopay draft."""
    oldest = _oldest_unpaid(loan_schedules(loan["id"]))
    if oldest is None:
        return None, None
    return oldest, oldest["amount_due_cents"] - oldest["amount_paid_cents"]


def _already_drafted_in_window(loan, now):
    """Idempotency: was an AUTOPAY payment already posted within the half-open
    monthly billing-cycle window [cycle_start, cycle_start+1month) that contains
    `now`? (PRD §3.11)

    The cycle is anchored on funded_at: the window is
    [funded_at + k months, funded_at + (k+1) months) for the largest k with
    funded_at + k months <= now. Anchoring on funded_at (not the oldest-unpaid
    installment) keeps the window stable across the same cycle even after a draft
    marks the current installment paid, so re-running the sweep in the same cycle
    drafts nothing.
    """
    if not loan.get("funded_at"):
        return True
    cycle_start = parse_iso(loan["funded_at"])
    while add_months(cycle_start, 1) <= now:
        cycle_start = add_months(cycle_start, 1)
    cycle_end = add_months(cycle_start, 1)
    for p in store.payments.values():
        if p["loan_id"] != loan["id"] or p["source"] != "AUTOPAY":
            continue
        posted = parse_iso(p["posted_at"])
        if cycle_start <= posted < cycle_end:
            return True
    return False


def run_autopay():
    """Draft for all ACTIVE enrollments whose day_of_month matches the clock date."""
    now = store.now()
    today = now.day
    for enr in list(store.autopay_enrollments.values()):
        if enr["status"] != "ACTIVE":
            continue
        loan = store.loans.get(enr["loan_id"])
        if loan is None or loan["lifecycle_status"] != "ACTIVE":
            continue
        # clamp day_of_month to month length (PRD §3.11): day_of_month in [1,28]
        # so it always exists; match against the clock date.
        if enr["day_of_month"] != today:
            continue
        # idempotency within the billing cycle window
        if _already_drafted_in_window(loan, now):
            continue
        oldest, draft_amount = _installment_amount_for_draft(loan)
        if oldest is None or draft_amount is None or draft_amount <= 0:
            continue
        acct = store.accounts[loan["account_id"]]
        if enr["funding_wallet"]:
            if acct["wallet_cents"] < draft_amount:
                # autopay never overdrafts the wallet (PRD §3.11): the draft is
                # rejected — no payment is created for this enrollment — but the
                # sweep capability as a whole still returns 200 OK (PRD §4: "The
                # clock and sweep capabilities return 200 OK"). So skip the draft
                # rather than aborting the entire sweep.
                continue
            acct["wallet_cents"] -= draft_amount
            touch(acct)
        payment = apply_payment(loan, draft_amount, "AUTOPAY", now)
        touch(loan)
        store.payments[payment["id"]] = payment


# ---------------------------------------------------------------------------
# Bureau sweep + score (PRD §3.12)
# ---------------------------------------------------------------------------
_RATING_BY_DELQ = {
    "CURRENT": "ON_TIME",
    "DPD_30": "LATE_30",
    "DPD_60": "LATE_60",
    "DPD_90": "LATE_90",
    "CHARGED_OFF": "CHARGE_OFF",
}


def _cycle_label(dt):
    return f"{dt.year:04d}-{dt.month:02d}"


def _bureau_exists(loan_id, tradeline_kind, cycle_label):
    for r in store.bureau_reports.values():
        if (
            r["loan_id"] == loan_id
            and r["tradeline_kind"] == tradeline_kind
            and r["cycle_label"] == cycle_label
        ):
            return True
    return False


def _emit_bureau(loan_id, tradeline_kind, cycle_label, payment_rating, balance):
    report = {
        "id": store.new_id(),
        "loan_id": loan_id,
        "tradeline_kind": tradeline_kind,
        "cycle_label": cycle_label,
        "payment_rating": payment_rating,
        "reported_balance_cents": balance,
        "bureaus": list(BUREAUS),
    }
    # BureauReport is append-only: id + created_at only (common_fields:false)
    report["created_at"] = store.now_iso()
    report["_seq"] = store.next_seq()
    store.bureau_reports[report["id"]] = report
    return report


def _account_marks(account_id):
    """Count on-time and late marks from persisted LOAN BureauReport rows for the
    account (PRD §3.12 payment_history)."""
    on_time = 0
    late = 0
    for r in store.bureau_reports.values():
        if r["tradeline_kind"] != "LOAN":
            continue
        loan = store.loans.get(r["loan_id"])
        if loan is None or loan["account_id"] != account_id:
            continue
        if r["payment_rating"] == "ON_TIME":
            on_time += 1
        elif r["payment_rating"] in ("LATE_30", "LATE_60", "LATE_90", "CHARGE_OFF"):
            late += 1
    return on_time, late


def _account_card(account_id):
    cards = [c for c in store.secured_cards.values() if c["account_id"] == account_id]
    actives = [c for c in cards if c["status"] == "ACTIVE"]
    if actives:
        return sorted(actives, key=lambda c: (c["created_at"], c.get("_seq", 0)))[0]
    if cards:
        return sorted(cards, key=lambda c: (c["created_at"], c.get("_seq", 0)))[0]
    return None


def _first_funded_at(account_id):
    funded = [
        l for l in store.loans.values()
        if l["account_id"] == account_id and l.get("funded_at")
    ]
    if not funded:
        return None
    return sorted(funded, key=lambda l: parse_iso(l["funded_at"]))[0]["funded_at"]


def compute_account_score(account_id, now, projection=None):
    """Compute simulated_score for an account at `now` (PRD §3.12).
    projection='optimistic' adds one on-time mark for the in-flight cycle."""
    on_time, late = _account_marks(account_id)
    if projection == "optimistic":
        on_time += 1
    card = _account_card(account_id)
    if card is not None:
        credit_limit = card["credit_limit_cents"]
        balance = card["balance_cents"]
    else:
        credit_limit = 0
        balance = 0
    first_funded = _first_funded_at(account_id)
    if first_funded is not None:
        months = whole_months_between(parse_iso(first_funded), now)
    else:
        months = 0
    return calc.compute_score(on_time, late, credit_limit, balance, months)


def run_bureau_sweep():
    now = store.now()
    cycle = _cycle_label(now)

    # 1. Emit BureauReport rows for every ACTIVE/GRADUATED loan and ACTIVE card.
    for loan in list(store.loans.values()):
        if loan["lifecycle_status"] in ("ACTIVE", "GRADUATED"):
            if not _bureau_exists(loan["id"], "LOAN", cycle):
                rating = _RATING_BY_DELQ.get(loan["delinquency_status"], "ON_TIME")
                _emit_bureau(loan["id"], "LOAN", cycle, rating, loan["outstanding_principal_cents"])
    for card in list(store.secured_cards.values()):
        if card["status"] == "ACTIVE":
            link = linked_loan_for_card(card)
            if link is None:
                continue
            if not _bureau_exists(link["id"], "SECURED_CARD", cycle):
                _emit_bureau(link["id"], "SECURED_CARD", cycle, "ON_TIME", card["balance_cents"])

    # 2. Persist one ScoreSnapshot per account per cycle.
    for account in list(store.accounts.values()):
        # only accounts that have at least one funded loan or any bureau activity
        existing = [
            s for s in store.score_snapshots.values()
            if s["account_id"] == account["id"] and s["cycle_label"] == cycle
        ]
        if existing:
            continue
        # Only snapshot accounts with a funded loan (have reportable history)
        if _first_funded_at(account["id"]) is None:
            continue
        score = compute_account_score(account["id"], now, projection=None)
        prior = sorted(
            [s for s in store.score_snapshots.values() if s["account_id"] == account["id"]],
            key=lambda s: (s["created_at"], s.get("_seq", 0)),
        )
        prior_score = prior[-1]["simulated_score"] if prior else None
        delta = score - prior_score if prior_score is not None else 0
        snap = {
            "id": store.new_id(),
            "account_id": account["id"],
            "cycle_label": cycle,
            "simulated_score": score,
            "score_delta": delta,
        }
        snap["created_at"] = store.now_iso()
        snap["_seq"] = store.next_seq()
        store.score_snapshots[snap["id"]] = snap


# ---------------------------------------------------------------------------
# Graduation cascade (PRD §3.6) — final bureau report emission
# ---------------------------------------------------------------------------
def graduate_emit_final_report(loan):
    cycle = _cycle_label(store.now())
    rating = _RATING_BY_DELQ.get(loan["delinquency_status"], "ON_TIME")
    if not _bureau_exists(loan["id"], "LOAN", cycle):
        _emit_bureau(loan["id"], "LOAN", cycle, rating, loan["outstanding_principal_cents"])
