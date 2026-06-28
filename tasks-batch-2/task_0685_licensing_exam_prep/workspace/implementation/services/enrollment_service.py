"""Enrollment aggregate: financing schedule, ledger, readiness, mastery, CE,
cascades. Implements scaffold §1.3 calculations and §1.2 side-effects verbatim
to PRD §3.2-§3.8.
"""
from db import db, stamp_create, touch
from services.calc import round_half_up

# readiness blend coefficients (scaffold readiness_score constants)
DOMAIN_WEIGHT_COEFF = 0.60
MOCK_WEIGHT_COEFF = 0.40
# EWMA smoothing (scaffold domain_mastery_update)
ALPHA = 0.40
# pass-guarantee thresholds (scaffold pass_guarantee_eligibility)
MIN_QUESTIONS = 200
MIN_MOCKS = 2
READINESS_THRESHOLD = 75


# --------------------------------------------------------------------------- #
# Installments under an enrollment
# --------------------------------------------------------------------------- #
def installments_of(enrollment_id):
    rows = [i for i in db.installments.values() if i["enrollment_id"] == enrollment_id]
    rows.sort(key=lambda r: r["sequence_no"])
    return rows


def domains_of(enrollment_id):
    return [d for d in db.study_plan_domains.values()
            if d["enrollment_id"] == enrollment_id]


def practice_sessions_of(enrollment_id):
    return [p for p in db.practice_sessions.values()
            if p["enrollment_id"] == enrollment_id]


def mocks_of(enrollment_id):
    return [m for m in db.mock_exams.values() if m["enrollment_id"] == enrollment_id]


def memberships_of(enrollment_id):
    return [m for m in db.cohort_memberships.values()
            if m["enrollment_id"] == enrollment_id]


# --------------------------------------------------------------------------- #
# financing_schedule (calc) — waterfall allocation, PRD §3.2
# --------------------------------------------------------------------------- #
def build_installments(enrollment, plan):
    """Materialize the installment schedule. Caller has cleared any prior set.

    financed=false -> single installment of total_price_cents (variant paid_in_full).
    financed=true  -> seq 1 = down payment; seq 2..n = base; seq n+1 = base+remainder.
    """
    total = plan["total_price_cents"]
    created = []
    if not enrollment["financed"]:
        rec = _new_installment(enrollment["id"], 1, total)
        created.append(rec)
        return created

    down = round_half_up(total * _as_float(plan["down_payment_pct"]))
    financed_remainder = total - down
    n = plan["financing_months"]
    base = financed_remainder // n  # integer floor in cents
    remainder = financed_remainder - base * n

    # seq 1 = down payment
    created.append(_new_installment(enrollment["id"], 1, down))
    # seq 2..n = base
    for k in range(2, n + 1):
        created.append(_new_installment(enrollment["id"], k, base))
    # seq n+1 = base + remainder (last absorbs remainder)
    created.append(_new_installment(enrollment["id"], n + 1, base + remainder))
    return created


def _new_installment(enrollment_id, sequence_no, amount_cents):
    rec = {
        "enrollment_id": enrollment_id,
        "sequence_no": sequence_no,
        "amount_cents": amount_cents,
        "status": "DUE",
    }
    stamp_create(rec)
    db.installments[rec["id"]] = rec
    return rec


def _as_float(v):
    return float(v)


# --------------------------------------------------------------------------- #
# financing_ledger (calc) — aggregation, PRD §3.2
# --------------------------------------------------------------------------- #
def recompute_ledger(enrollment):
    paid = sum(i["amount_cents"] for i in installments_of(enrollment["id"])
               if i["status"] == "PAID")
    enrollment["financing_paid_cents"] = paid
    balance = enrollment["financing_total_due_cents"] - paid
    enrollment["financing_balance_cents"] = max(0, balance)


# --------------------------------------------------------------------------- #
# domain_mastery_update (calc) — EWMA, PRD §3.4
# --------------------------------------------------------------------------- #
def apply_mastery_update(domain, batch_pct):
    old = domain["mastery"]
    new_mastery = round_half_up(ALPHA * batch_pct + (1 - ALPHA) * old)
    domain["mastery"] = max(0, min(100, new_mastery))


# --------------------------------------------------------------------------- #
# readiness_score (calc) — conservative + projected, PRD §3.4
# --------------------------------------------------------------------------- #
def _latest_mock(enrollment_id):
    """COMPLETED mock with greatest completed_at; tie-break earliest created_at
    ASC then earliest creation order (PRD §3.4)."""
    completed = [m for m in mocks_of(enrollment_id) if m["status"] == "COMPLETED"]
    if not completed:
        return None
    # Sort ascending by (completed_at, created_at, _seq); the last element is the
    # greatest completed_at, and among equal completed_at it is NOT what we want —
    # we want the earliest created_at on ties. So pick the max by completed_at,
    # then the min created_at/_seq among that group.
    max_completed_at = max(m["completed_at"] for m in completed)
    tied = [m for m in completed if m["completed_at"] == max_completed_at]
    tied.sort(key=lambda m: (m["created_at"], m["_seq"]))
    return tied[0]


def recompute_readiness(enrollment):
    domains = domains_of(enrollment["id"])
    weighted_domain_mastery = sum(
        _as_float(d["weight"]) * d["mastery"] for d in domains
    )

    completed = [m for m in mocks_of(enrollment["id"]) if m["status"] == "COMPLETED"]

    latest = _latest_mock(enrollment["id"])
    latest_mock_score = latest["scaled_score"] if latest else 0
    enrollment["readiness_score"] = round_half_up(
        DOMAIN_WEIGHT_COEFF * weighted_domain_mastery
        + MOCK_WEIGHT_COEFF * latest_mock_score
    )

    if completed:
        avg_mock_score = round_half_up(
            sum(m["scaled_score"] for m in completed) / len(completed)
        )
    else:
        avg_mock_score = 0
    enrollment["projected_readiness_score"] = round_half_up(
        DOMAIN_WEIGHT_COEFF * weighted_domain_mastery
        + MOCK_WEIGHT_COEFF * avg_mock_score
    )


# --------------------------------------------------------------------------- #
# pass_guarantee_eligibility (calc) — threshold, PRD §3.5
# --------------------------------------------------------------------------- #
def guarantee_eligible(enrollment, plan):
    return (
        bool(plan["pass_guarantee"])
        and enrollment["questions_answered_total"] >= MIN_QUESTIONS
        and enrollment["completed_mock_count"] >= MIN_MOCKS
        and enrollment["readiness_score"] >= READINESS_THRESHOLD
    )


# --------------------------------------------------------------------------- #
# guarantee_refund (calc) — per-installment round THEN sum, PRD §3.5
# --------------------------------------------------------------------------- #
def compute_refund(enrollment, plan):
    paid = [i for i in installments_of(enrollment["id"]) if i["status"] == "PAID"]
    # installments_of already sorts by sequence_no ASC.
    pct = _as_float(plan["guarantee_refund_pct"])
    total = 0
    for inst in paid:
        total += round_half_up(inst["amount_cents"] * pct)
    return total


# --------------------------------------------------------------------------- #
# Cascades (PRD §3.5, §3.6, §2.7)
# --------------------------------------------------------------------------- #
def drop_joined_memberships(enrollment_id):
    """Drop every JOINED membership of the enrollment; recompute each cohort."""
    for m in memberships_of(enrollment_id):
        if m["status"] == "JOINED":
            _drop_membership(m)


def _drop_membership(m):
    m["status"] = "DROPPED"
    touch(m)
    cohort = db.cohorts.get(m["cohort_id"])
    if cohort is not None:
        recompute_cohort_after_seat_change(cohort)


def void_due_installments(enrollment_id):
    for i in installments_of(enrollment_id):
        if i["status"] == "DUE":
            i["status"] = "VOID"
            touch(i)


# --------------------------------------------------------------------------- #
# Cohort seat recompute (PRD §3.8)
# --------------------------------------------------------------------------- #
def recompute_cohort_after_seat_change(cohort):
    """Recount JOINED memberships, refresh derived status (FULL<->OPEN), re-version.

    CLOSED is terminal and is never flipped by seat changes.
    """
    seats = sum(
        1 for m in db.cohort_memberships.values()
        if m["cohort_id"] == cohort["id"] and m["status"] == "JOINED"
    )
    changed_status = False
    cohort["seats_taken"] = seats
    if cohort["status"] != "CLOSED":
        if seats >= cohort["capacity"]:
            if cohort["status"] != "FULL":
                cohort["status"] = "FULL"
                changed_status = True
        else:
            if cohort["status"] != "OPEN":
                cohort["status"] = "OPEN"
                changed_status = True
    # A cohort that loses/gains a member is mutated (PRD §2.7): re-version.
    touch(cohort)
    return changed_status
