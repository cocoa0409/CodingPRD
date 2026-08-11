"""Business logic: compliance posture derivation, the deterministic sweep,
billing calculations (per-line subsidy rounding, pool waterfall, payer split),
triage quota, outbreak rolling-window count, stock reorder flag, and invoice
balance/status derivation."""
from datetime import timedelta, time as dtime
from decimal import Decimal, ROUND_HALF_UP

from store import db, clock, bump, new_entity, by_seq

VISIT_SUBSIDY_CENTS = 12000
OUTBREAK_EMERGENCY_DEBIT_CENTS = 25000
OUTBREAK_THRESHOLD = 3
OUTBREAK_WINDOW_HOURS = 168
TRIAGE_DAILY_QUOTA = 4
SUBSIDY_PCT = Decimal("0.5")
REPORT_WINDOW_HOURS = 24
ELECTIVE_VISIT_TYPES = {"SPORTS_PHYSICAL", "TRAVEL_CLINIC"}
FEE_COVERED_VISIT_TYPES = {"PRIMARY_URGENT", "SAME_DAY_TRIAGE", "FOLLOW_UP"}


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def open_pool():
    """At most one HealthFeePool with status OPEN exists at any time."""
    for p in sorted(db["pools"].values(), key=by_seq):
        if p["status"] == "OPEN":
            return p
    return None


def find_verified_policy(student_id):
    for p in sorted(db["policies"].values(), key=by_seq):
        if p["student_id"] == student_id and p["status"] == "VERIFIED":
            return p
    return None


def compute_fee_covered(visit_type, student):
    return (visit_type in FEE_COVERED_VISIT_TYPES
            and student["enrollment_status"] == "ENROLLED")


# --------------------------------------------------------------------------
# Compliance posture (calculations.compliance_posture_derivation)
# --------------------------------------------------------------------------

def recompute_posture(student_id):
    student = db["students"].get(student_id)
    if student is None:
        return
    records = [r for r in db["records"].values() if r["student_id"] == student_id]
    invoices = [i for i in db["invoices"].values() if i["student_id"] == student_id]
    immunization_hold = any(r["status"] == "OVERDUE" for r in records)
    provisional_hold = (not immunization_hold) and any(r["status"] == "GRACE" for r in records)
    financial_hold = any(i["status"] == "OVERDUE" for i in invoices)
    if immunization_hold or financial_hold:
        posture = "REGISTRATION_HOLD"
    elif provisional_hold:
        posture = "PROVISIONAL_HOLD"
    else:
        posture = "CLEAR"
    holds = []
    if immunization_hold:
        holds.append("IMMUNIZATION")
    if financial_hold:
        holds.append("FINANCIAL")
    if student["compliance_posture"] != posture or student["active_hold_types"] != holds:
        student["compliance_posture"] = posture
        student["active_hold_types"] = holds
        bump(student)


def cancel_future_electives(student_id):
    """Auto-cancel the student's still-BOOKED elective appointments whose
    scheduled_start lies in the future; cancel_reason = HOLD."""
    now = clock.now()
    for a in sorted(db["appointments"].values(), key=by_seq):
        if (a["student_id"] == student_id and a["status"] == "BOOKED"
                and a["visit_type"] in ELECTIVE_VISIT_TYPES
                and a["scheduled_start"] > now):
            a["status"] = "CANCELLED"
            a["cancel_reason"] = "HOLD"
            bump(a)


def transition_record_overdue(rec):
    rec["status"] = "OVERDUE"
    bump(rec)
    recompute_posture(rec["student_id"])
    cancel_future_electives(rec["student_id"])


def transition_invoice_overdue(inv):
    inv["status"] = "OVERDUE"
    bump(inv)
    recompute_posture(inv["student_id"])
    cancel_future_electives(inv["student_id"])


# --------------------------------------------------------------------------
# Deterministic daily sweep (PRD section 2.4): pinned order (1)-(5), posture
# recomputed after each step, elective cancellations after each posture change.
# --------------------------------------------------------------------------

def run_sweep():
    now = clock.now()
    today = now.date()

    # (1) Invoice aging.
    for inv in sorted(db["invoices"].values(), key=by_seq):
        if (inv["status"] in ("ISSUED", "PARTIALLY_PAID")
                and inv["due_date"] is not None and inv["due_date"] < today
                and inv["balance_cents"] > 0):
            transition_invoice_overdue(inv)

    # (2) Immunization deadlines: PENDING -> GRACE -> OVERDUE (direct
    # PENDING -> OVERDUE when already past deadline + grace).
    for rec in sorted(db["records"].values(), key=by_seq):
        req = db["requirements"].get(rec["requirement_id"])
        if req is None:
            continue
        overdue_boundary = req["deadline_date"] + timedelta(days=req["grace_period_days"])
        if rec["status"] == "PENDING":
            if today > overdue_boundary:
                transition_record_overdue(rec)
            elif today > req["deadline_date"]:
                rec["status"] = "GRACE"
                bump(rec)
                recompute_posture(rec["student_id"])
        elif rec["status"] == "GRACE":
            if today > overdue_boundary:
                transition_record_overdue(rec)

    # (3) Policy expiry.
    for pol in sorted(db["policies"].values(), key=by_seq):
        if pol["status"] in ("UNVERIFIED", "VERIFIED") and pol["coverage_end"] < now:
            pol["status"] = "EXPIRED"
            bump(pol)

    # (4) No-show detection.
    for appt in sorted(db["appointments"].values(), key=by_seq):
        if appt["status"] == "BOOKED" and appt["scheduled_end"] < now:
            appt["status"] = "NO_SHOW"
            bump(appt)

    # (5) Pool closure.
    for pool in sorted(db["pools"].values(), key=by_seq):
        if pool["status"] == "OPEN" and today > pool["term_end_date"]:
            pool["status"] = "CLOSED"
            bump(pool)


# --------------------------------------------------------------------------
# Billing calculations
# --------------------------------------------------------------------------

def compute_line_subsidies(encounter, lines):
    """calculations.invoice_line_subsidy_rounding + pool_subsidy_waterfall.

    PINNED: subsidy rounded PER LINE first (round half up), then summed.
    Waterfall: pool remaining snapshotted BEFORE this invoice; lines walked in
    request order; pool debited once after the invoice is built.
    Returns (applied_subsidies, charge_total_cents, subsidy_cents, pool)."""
    pool = open_pool()
    tentative = []
    for line in lines:
        if (line["service_category"] == "TRAVEL_VACCINE"
                and encounter["visit_type"] == "TRAVEL_CLINIC"
                and pool is not None and pool["status"] == "OPEN"
                and not pool["exhausted"]):
            tentative.append(
                round_half_up_cents(Decimal(line["charge_cents"]) * SUBSIDY_PCT))
        else:
            tentative.append(0)
    applied = []
    remaining = max(0, pool["budget_cents"] - pool["spent_cents"]) if pool else 0
    for t in tentative:
        a = min(t, remaining)
        applied.append(a)
        remaining -= a
    subsidy_cents = sum(applied)
    charge_total_cents = sum(
        line["charge_cents"] - a for line, a in zip(lines, applied))
    return applied, charge_total_cents, subsidy_cents, pool


def debit_pool(pool, amount):
    if pool is None or amount <= 0:
        return
    pool["spent_cents"] += amount
    pool["exhausted"] = pool["spent_cents"] >= pool["budget_cents"]
    bump(pool)


def final_payer_split(invoice):
    """calculations.invoice_payer_split, FINAL variant. Adjudicated split when
    a VERIFIED policy exists at issue time, else self-pay fallback. Applies
    deductible accumulation as a side effect of issue."""
    policy = find_verified_policy(invoice["student_id"])
    charge_total = invoice["charge_total_cents"]
    if policy is not None:
        after_copay = max(0, charge_total - policy["copay_cents"])
        ded_remaining = max(0, policy["deductible_cents"] - policy["deductible_met_cents"])
        ded_applied = min(after_copay, ded_remaining)
        coins_base = after_copay - ded_applied
        coins_patient = round_half_up_cents(
            Decimal(coins_base) * Decimal(str(policy["coinsurance_pct"])))
        invoice["insurer_pays_cents"] = (
            charge_total - policy["copay_cents"] - ded_applied - coins_patient)
        invoice["patient_responsibility_cents"] = (
            policy["copay_cents"] + ded_applied + coins_patient)
        if ded_applied:
            policy["deductible_met_cents"] += ded_applied
            bump(policy)
    else:
        invoice["insurer_pays_cents"] = 0
        invoice["patient_responsibility_cents"] = charge_total


def posted_payment_sum(invoice_id):
    return sum(p["amount_cents"] for p in db["payments"].values()
               if p["invoice_id"] == invoice_id and p["status"] == "POSTED")


def rederive_invoice_balance_status(inv):
    """calculations.invoice_balance_and_status. Money conservation invariant:
    patient_responsibility == balance + sum(POSTED payments)."""
    balance = inv["patient_responsibility_cents"] - posted_payment_sum(inv["id"])
    inv["balance_cents"] = balance
    today = clock.now().date()
    if balance == 0:
        inv["status"] = "PAID"
    elif inv["due_date"] is not None and inv["due_date"] < today:
        inv["status"] = "OVERDUE"
    elif balance == inv["patient_responsibility_cents"]:
        inv["status"] = "ISSUED"
    else:
        inv["status"] = "PARTIALLY_PAID"
    bump(inv)
    recompute_posture(inv["student_id"])


# --------------------------------------------------------------------------
# Outbreak threshold (calculations.outbreak_case_count, ROLLING variant)
# --------------------------------------------------------------------------

def evaluate_outbreak_on_confirm(case):
    now = clock.now()
    window_start = now - timedelta(hours=OUTBREAK_WINDOW_HOURS)
    count = sum(
        1 for c in db["cases"].values()
        if c["disease_code"] == case["disease_code"]
        and c["status"] in ("CONFIRMED", "REPORTED")
        and c["confirmed_at"] is not None
        and window_start <= c["confirmed_at"] <= now)
    if count < OUTBREAK_THRESHOLD:
        return
    existing = None
    for inv in sorted(db["investigations"].values(), key=by_seq):
        if (inv["disease_code"] == case["disease_code"]
                and inv["status"] in ("ACTIVE", "CONTAINED")):
            existing = inv
            break
    if existing is None:
        inv = new_entity()
        inv.update({
            "disease_code": case["disease_code"],
            "status": "ACTIVE",
            "opened_at": now,
            "opened_case_count": count,
        })
        db["investigations"][inv["id"]] = inv
        debit_pool(open_pool(), OUTBREAK_EMERGENCY_DEBIT_CENTS)
    elif existing["status"] == "CONTAINED":
        existing["status"] = "ACTIVE"
        bump(existing)


# --------------------------------------------------------------------------
# Scheduling checks
# --------------------------------------------------------------------------

def triage_count(provider_id, day):
    """calculations.triage_daily_quota: same provider, same UTC calendar date,
    SAME_DAY_TRIAGE, statuses BOOKED/CHECKED_IN."""
    return sum(
        1 for a in db["appointments"].values()
        if a["provider_id"] == provider_id
        and a["visit_type"] == "SAME_DAY_TRIAGE"
        and a["status"] in ("BOOKED", "CHECKED_IN")
        and a["scheduled_start"].date() == day)


def slot_conflict(provider_id, start, end):
    """Half-open [start, end) overlap; adjacency allowed."""
    for a in db["appointments"].values():
        if (a["provider_id"] == provider_id
                and a["status"] in ("BOOKED", "CHECKED_IN")
                and a["scheduled_start"] < end
                and start < a["scheduled_end"]):
            return True
    return False


def is_after_hours(now):
    """Business hours are [08:00, 17:00) UTC daily."""
    t = now.time()
    return not (dtime(8, 0) <= t < dtime(17, 0))


def has_oncall_coverage(now):
    """Covering shift: shift_start <= now < shift_end (any provider)."""
    return any(s["shift_start"] <= now < s["shift_end"]
               for s in db["shifts"].values())
