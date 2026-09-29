"""Domain logic: the logical clock, the cap ledger, the tax ledger, persistence
scoring, the award/settlement arithmetic and every cascade.

Every rule here traces to a sentence in PRD.md; section references are inline.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import fail
from store import by_created, db, new_record, touch
from validate import iso_date

# --------------------------------------------------------------------------- #
# constants (PRD 2.10, 3.6, 3.8)
# --------------------------------------------------------------------------- #
TAX_EXCLUSION_LIMIT_CENTS = 525000

GRADE_BONUS_PCT = Decimal("0.10")
GRADE_BONUS_MIN_POINTS = Decimal("3.50")

ADMIN_FEE_PCT_TIER_1 = Decimal("0.05")
ADMIN_FEE_PCT_TIER_2 = Decimal("0.04")
ADMIN_FEE_PCT_TIER_3 = Decimal("0.03")
ADMIN_FEE_TIER_1_MAX_CENTS = 5000000
ADMIN_FEE_TIER_2_MAX_CENTS = 20000000

BASE_RISK_BY_CREDENTIAL = {"CERTIFICATE": 10, "ASSOCIATE": 20, "BACHELOR": 30, "MASTER": 25}
OUTCOME_PENALTY = 30
STALENESS_PENALTY = 20
COACH_STALE_DAYS = 45
ENGAGEMENT_PER_SESSION = 5
ENGAGEMENT_CAP = 20
FLAG_WEIGHT = 5
FLAG_COUNT_CAP = 4

OPEN_ACADEMIC_STATES = ("REGISTERED", "IN_PROGRESS")
CLOSED_ACADEMIC_STATES = ("PASSED", "FAILED", "WITHDRAWN", "INCOMPLETE")
OPEN_INVOICE_STATES = ("ISSUED", "APPROVED_FOR_PAYMENT")
OPEN_OBLIGATION_STATES = ("ASSESSED", "PARTIALLY_PAID")
HOLDING_OBLIGATION_STATES = ("ASSESSED", "PARTIALLY_PAID", "WAIVED")


# --------------------------------------------------------------------------- #
# clock / arithmetic helpers
# --------------------------------------------------------------------------- #

def clock():
    return db.clock


def clock_date():
    return db.clock.date()


def clock_year():
    return db.clock.year


def round_half_up(value):
    """Round a Decimal to a whole unit, half away from zero-up."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_rate_4(numerator, denominator):
    if denominator == 0:
        return 0.0
    quotient = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(quotient)


def whole_months(start, end):
    """Whole months from start to end; a month completes once the day-of-month
    is reached or passed (PRD 3.1, 3.7)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def add_days(day, count):
    return day + timedelta(days=count)


def plan_year_of(day, employer):
    """PRD 2.6."""
    if day.month >= employer["fiscal_year_start_month"]:
        return day.year
    return day.year - 1


# --------------------------------------------------------------------------- #
# lookups
# --------------------------------------------------------------------------- #

def must(collection, key, error_id):
    row = collection.get(key) if isinstance(key, str) else None
    if row is None:
        fail(error_id, "%s: %s" % (error_id, key))
    return row


def employees_of(employer_id):
    return by_created([e for e in db.employees.values() if e["employer_id"] == employer_id])


def enrollments_of_employee(employee_id):
    return by_created([e for e in db.enrollments.values() if e["employee_id"] == employee_id])


def outcomes_of(enrollment_id):
    return by_created([o for o in db.outcomes.values() if o["enrollment_id"] == enrollment_id])


def latest_outcome(enrollment_id):
    rows = outcomes_of(enrollment_id)
    return rows[-1] if rows else None


def invoices_of(enrollment_id):
    return by_created([i for i in db.invoices.values() if i["enrollment_id"] == enrollment_id])


def claims_of(enrollment_id):
    return by_created([c for c in db.claims.values() if c["enrollment_id"] == enrollment_id])


def obligations_of(enrollment_id):
    return by_created([o for o in db.obligations.values() if o["enrollment_id"] == enrollment_id])


def obligation_of(enrollment_id):
    rows = obligations_of(enrollment_id)
    return rows[-1] if rows else None


def sessions_of(enrollment_id):
    """Coaching sessions ordered session_date DESC, created_at ASC (PRD 3.8)."""
    rows = by_created([s for s in db.sessions.values() if s["enrollment_id"] == enrollment_id])
    return sorted(rows, key=lambda s: s["session_date"], reverse=True)


def tax_entries_of(employee_id, tax_year=None):
    rows = [t for t in db.tax_entries.values() if t["employee_id"] == employee_id]
    if tax_year is not None:
        rows = [t for t in rows if t["tax_year"] == tax_year]
    return sorted(by_created(rows), key=lambda t: t["posted_at"])


def enrollment_school_id(enrollment):
    listing = db.listings[enrollment["catalog_listing_id"]]
    program = db.programs[listing["program_id"]]
    return program["school_id"]


def current_policy(employer_id):
    """The employer's current BenefitPolicy: ACTIVE with
    effective_from <= clock date < effective_to (PRD 3.1)."""
    day = clock_date()
    candidates = [
        p
        for p in db.policies.values()
        if p["employer_id"] == employer_id
        and p["status"] == "ACTIVE"
        and iso_date(p["effective_from"]) <= day < iso_date(p["effective_to"])
    ]
    if not candidates:
        return None
    return by_created(candidates)[0]


# --------------------------------------------------------------------------- #
# employee derived state (PRD 2.6, 3.1, 3.8)
# --------------------------------------------------------------------------- #

DERIVED_EMPLOYEE_FIELDS = (
    "tenure_months",
    "eligibility_status",
    "cap_plan_year",
    "cap_reserved_cents",
    "cap_disbursed_cents",
    "cap_clawback_hold_cents",
    "cap_available_cents",
    "taxable_excluded_cents_ytd",
    "imputed_income_cents_ytd",
    "open_repayment_balance_cents",
    "coaching_hold",
)


def refresh_employee(employee):
    employer = db.employers.get(employee["employer_id"])
    policy = current_policy(employee["employer_id"])
    day = clock_date()

    employee["tenure_months"] = max(0, whole_months(iso_date(employee["hire_date"]), day))

    if policy is None:
        eligibility = "INELIGIBLE_NO_POLICY"
    elif employee["employment_status"] != "ACTIVE":
        eligibility = "INELIGIBLE_EMPLOYMENT"
    elif employee["tenure_months"] < policy["min_tenure_months"]:
        eligibility = "INELIGIBLE_TENURE"
    elif Decimal(str(employee["weekly_hours"])) < Decimal(str(policy["min_weekly_hours"])):
        eligibility = "INELIGIBLE_HOURS"
    elif employee["job_family"] not in policy["eligible_job_families"]:
        eligibility = "INELIGIBLE_JOB_FAMILY"
    else:
        eligibility = "ELIGIBLE"
    employee["eligibility_status"] = eligibility

    plan_year = plan_year_of(day, employer) if employer else day.year
    employee["cap_plan_year"] = plan_year

    all_enrollments = enrollments_of_employee(employee["id"])
    scope = [e for e in all_enrollments if e["plan_year"] == plan_year]

    reserved = sum(
        e["employer_reserved_cents"] for e in scope if e["funding_status"] in ("RESERVED", "BILLED")
    )
    disbursed = sum(e["employer_disbursed_cents"] for e in scope if e["funding_status"] == "SETTLED")
    hold = 0
    for enrollment in scope:
        if enrollment["funding_status"] != "CLAWED_BACK":
            continue
        obligation = obligation_of(enrollment["id"])
        if obligation is not None and obligation["status"] in HOLDING_OBLIGATION_STATES:
            hold += enrollment["employer_disbursed_cents"]

    employee["cap_reserved_cents"] = reserved
    employee["cap_disbursed_cents"] = disbursed
    employee["cap_clawback_hold_cents"] = hold
    if policy is None:
        employee["cap_available_cents"] = 0
    else:
        employee["cap_available_cents"] = policy["annual_cap_cents"] - reserved - disbursed - hold

    year_entries = tax_entries_of(employee["id"], clock_year())
    employee["taxable_excluded_cents_ytd"] = sum(t["excluded_cents"] for t in year_entries)
    employee["imputed_income_cents_ytd"] = sum(t["imputed_income_cents"] for t in year_entries)

    open_balance = 0
    for enrollment in all_enrollments:
        for obligation in obligations_of(enrollment["id"]):
            if obligation["status"] in OPEN_OBLIGATION_STATES:
                open_balance += obligation["balance_cents"]
    employee["open_repayment_balance_cents"] = open_balance

    employee["coaching_hold"] = any(
        e["academic_status"] in ("REGISTERED", "IN_PROGRESS", "INCOMPLETE")
        and e["persistence_tier"] == "HIGH"
        for e in all_enrollments
    )
    return employee


def refresh_all_employees():
    """Called at the start of every request so that clock-driven drift never
    counts as a mutation of the employee row."""
    for employee in list(db.employees.values()):
        refresh_employee(employee)


def refresh_and_touch(employee):
    """Recompute; when a stored derived field actually changed, the row was
    touched by this request and its updated_at/version move (PRD 2.8)."""
    before = {field: employee.get(field) for field in DERIVED_EMPLOYEE_FIELDS}
    refresh_employee(employee)
    after = {field: employee.get(field) for field in DERIVED_EMPLOYEE_FIELDS}
    if before != after:
        touch(employee)
    return employee


def employer_of_employee(employee):
    return db.employers[employee["employer_id"]]


def employee_of_enrollment(enrollment):
    return db.employees[enrollment["employee_id"]]


# --------------------------------------------------------------------------- #
# employer roll-ups (PRD 2.8) — derived, never client supplied
# --------------------------------------------------------------------------- #

def employer_total_disbursed(employer_id):
    ids = {e["id"] for e in db.employees.values() if e["employer_id"] == employer_id}
    return sum(
        e["employer_disbursed_cents"]
        for e in db.enrollments.values()
        if e["employee_id"] in ids and e["funding_status"] == "SETTLED"
    )


def employer_total_admin_fee(employer_id):
    ids = {e["id"] for e in db.employees.values() if e["employer_id"] == employer_id}
    total = 0
    for claim in db.claims.values():
        if claim["status"] != "APPROVED":
            continue
        enrollment = db.enrollments.get(claim["enrollment_id"])
        if enrollment is not None and enrollment["employee_id"] in ids:
            total += claim["platform_admin_fee_cents"]
    return total


def employer_total_imputed_income(employer_id):
    ids = {e["id"] for e in db.employees.values() if e["employer_id"] == employer_id}
    year = clock_year()
    return sum(
        t["imputed_income_cents"]
        for t in db.tax_entries.values()
        if t["employee_id"] in ids and t["tax_year"] == year
    )


# --------------------------------------------------------------------------- #
# persistence risk (PRD 3.8)
# --------------------------------------------------------------------------- #

def recompute_persistence(enrollment):
    listing = db.listings[enrollment["catalog_listing_id"]]
    program = db.programs[listing["program_id"]]
    base = BASE_RISK_BY_CREDENTIAL[program["credential_type"]]

    outcome = latest_outcome(enrollment["id"])
    outcome_penalty = (
        OUTCOME_PENALTY
        if outcome is not None and outcome["completion_status"] in ("FAILED", "INCOMPLETE")
        else 0
    )

    sessions = sessions_of(enrollment["id"])
    day = clock_date()
    enrollment["last_session_date"] = sessions[0]["session_date"] if sessions else None

    if not sessions:
        staleness_penalty = STALENESS_PENALTY
    else:
        gap = (day - iso_date(sessions[0]["session_date"])).days
        staleness_penalty = STALENESS_PENALTY if gap > COACH_STALE_DAYS else 0

    recent = [s for s in sessions if (day - iso_date(s["session_date"])).days <= COACH_STALE_DAYS]
    engagement_credit = min(ENGAGEMENT_CAP, ENGAGEMENT_PER_SESSION * len(recent))

    last_three = sessions[:3]
    flag_count = sum(len(s["risk_flags"]) for s in last_three)
    flag_penalty = FLAG_WEIGHT * min(FLAG_COUNT_CAP, flag_count)

    score = base + outcome_penalty + staleness_penalty + flag_penalty - engagement_credit
    score = max(0, min(100, score))
    enrollment["persistence_risk_score"] = score
    if score < 30:
        tier = "LOW"
    elif score < 60:
        tier = "MEDIUM"
    else:
        tier = "HIGH"
    enrollment["persistence_tier"] = tier
    return score


# --------------------------------------------------------------------------- #
# tax ledger (PRD 2.10, 3.5, 3.7)
# --------------------------------------------------------------------------- #

def _append_tax_entry(employee_id, enrollment_id, entry_type, tax_year, benefit, excluded, imputed):
    from store import iso_ms

    entry = new_record(
        {
            "employee_id": employee_id,
            "enrollment_id": enrollment_id,
            "entry_type": entry_type,
            "tax_year": tax_year,
            "benefit_cents": benefit,
            "excluded_cents": excluded,
            "imputed_income_cents": imputed,
            "posted_at": iso_ms(clock()),
        },
        common=False,
    )
    db.tax_entries[entry["id"]] = entry
    return entry


def append_benefit_entry(employee, enrollment, amount_cents):
    year = clock_year()
    prior_excluded = sum(t["excluded_cents"] for t in tax_entries_of(employee["id"], year))
    headroom = max(0, TAX_EXCLUSION_LIMIT_CENTS - prior_excluded)
    excluded = min(amount_cents, headroom)
    imputed = amount_cents - excluded
    return _append_tax_entry(
        employee["id"], enrollment["id"], "BENEFIT", year, amount_cents, excluded, imputed
    )


def append_reversal_entry(employee, enrollment, principal_cents):
    year = clock_year()
    origin = None
    for entry in tax_entries_of(employee["id"], year):
        if entry["entry_type"] == "BENEFIT" and entry["enrollment_id"] == enrollment["id"]:
            origin = entry
            break
    origin_excluded = origin["excluded_cents"] if origin is not None else 0
    reversed_excluded = min(principal_cents, origin_excluded)
    return _append_tax_entry(
        employee["id"],
        enrollment["id"],
        "REVERSAL",
        year,
        -principal_cents,
        -reversed_excluded,
        -(principal_cents - reversed_excluded),
    )


# --------------------------------------------------------------------------- #
# money movement helpers
# --------------------------------------------------------------------------- #

def void_open_invoices(enrollment):
    for invoice in invoices_of(enrollment["id"]):
        if invoice["status"] in OPEN_INVOICE_STATES:
            invoice["status"] = "VOIDED"
            touch(invoice)


def release_funding(enrollment):
    """RESERVED/BILLED -> RELEASED with open invoices voided (PRD 3.5)."""
    if enrollment["funding_status"] not in ("RESERVED", "BILLED"):
        return False
    if enrollment["funding_status"] == "BILLED" and any(
        i["status"] == "PAID" for i in invoices_of(enrollment["id"])
    ):
        return False
    enrollment["funding_status"] = "RELEASED"
    void_open_invoices(enrollment)
    touch(enrollment)
    return True


def assess_obligation(enrollment, trigger_reason, termination_date=None):
    """SETTLED -> CLAWED_BACK with a RepaymentObligation and a REVERSAL entry
    (PRD 3.7).  Returns the obligation, or None when nothing is assessed."""
    if enrollment["funding_status"] != "SETTLED":
        return None
    if enrollment["employer_disbursed_cents"] <= 0:
        return None

    policy = db.policies.get(enrollment["policy_id"])
    disbursed = enrollment["employer_disbursed_cents"]

    if trigger_reason == "EARLY_DEPARTURE":
        commitment = policy["service_commitment_months"] if policy else 1
        elapsed = max(0, whole_months(iso_date(enrollment["term_end_date"]), termination_date))
        remaining = max(0, commitment - elapsed)
        if remaining == 0:
            return None
        principal = round_half_up(Decimal(disbursed) * Decimal(remaining) / Decimal(commitment))
    else:
        principal = disbursed

    obligation = new_record(
        {
            "enrollment_id": enrollment["id"],
            "trigger_reason": trigger_reason,
            "principal_cents": principal,
            "paid_cents": 0,
            "waived_cents": 0,
            "balance_cents": principal,
            "status": "ASSESSED",
            "assessed_on": clock_date().isoformat(),
        }
    )
    db.obligations[obligation["id"]] = obligation

    enrollment["funding_status"] = "CLAWED_BACK"
    touch(enrollment)

    employee = employee_of_enrollment(enrollment)
    append_reversal_entry(employee, enrollment, principal)
    return obligation


def settle_direct_bill(invoice, enrollment, employee):
    """Variant direct_bill_upfront_final (PRD 3.5)."""
    amount = invoice["amount_cents"]
    enrollment["funding_status"] = "SETTLED"
    enrollment["employer_settled_cents"] = amount
    enrollment["employer_disbursed_cents"] = amount
    touch(enrollment)
    append_benefit_entry(employee, enrollment, amount)


# --------------------------------------------------------------------------- #
# award computation (PRD 3.4, 3.6)
# --------------------------------------------------------------------------- #

def provisional_reserve(listing, policy, credits, funding_model, cap_available):
    gross = listing["negotiated_tuition_per_credit_cents"] * credits
    if funding_model == "DIRECT_BILL":
        uncapped = gross
    else:
        uncapped = round_half_up(Decimal(gross) * Decimal(str(policy["reimbursement_pct"])))
    reserved = min(uncapped, cap_available)
    return gross, reserved


def reimbursement_final(enrollment, policy, outcome, cap_available):
    """Variant reimbursement_outcome_conditioned_final (PRD 3.6 step one)."""
    gross = enrollment["gross_tuition_cents"]
    credits = enrollment["credits"]
    earned = outcome["credits_earned"] if outcome else 0
    earned_base = round_half_up(Decimal(gross) * Decimal(earned) / Decimal(credits))

    effective_pct = Decimal(str(policy["reimbursement_pct"]))
    grade_points = outcome.get("grade_points") if outcome else None
    if grade_points is not None and Decimal(str(grade_points)) >= GRADE_BONUS_MIN_POINTS:
        effective_pct = effective_pct + GRADE_BONUS_PCT
    if effective_pct > Decimal("1.00"):
        effective_pct = Decimal("1.00")

    uncapped_final = round_half_up(Decimal(earned_base) * effective_pct)
    ceiling = enrollment["employer_reserved_cents"] + cap_available
    return min(uncapped_final, ceiling)


def admin_fee_pct(fee_basis_cents):
    if fee_basis_cents < ADMIN_FEE_TIER_1_MAX_CENTS:
        return ADMIN_FEE_PCT_TIER_1
    if fee_basis_cents < ADMIN_FEE_TIER_2_MAX_CENTS:
        return ADMIN_FEE_PCT_TIER_2
    return ADMIN_FEE_PCT_TIER_3


# --------------------------------------------------------------------------- #
# academic-axis helpers
# --------------------------------------------------------------------------- #

def append_system_outcome(enrollment, completion_status):
    outcome = new_record(
        {
            "enrollment_id": enrollment["id"],
            "term_code": enrollment["term_code"],
            "completion_status": completion_status,
            "grade_points": None,
            "credits_earned": 0,
            "posted_on": clock_date().isoformat(),
            "posted_by_role": "SYSTEM",
        },
        common=False,
    )
    db.outcomes[outcome["id"]] = outcome
    enrollment["credits_earned"] = 0
    return outcome


# --------------------------------------------------------------------------- #
# cascades (PRD 2.8, 3.2, 3.7)
# --------------------------------------------------------------------------- #

def cascade_agreement_termination(agreement):
    affected_employees = []

    # hop 1: CURATED listings under this agreement -> SUSPENDED (created_at ASC)
    listings = by_created(
        [
            l
            for l in db.listings.values()
            if l["agreement_id"] == agreement["id"] and l["status"] == "CURATED"
        ]
    )
    for listing in listings:
        listing["status"] = "SUSPENDED"
        touch(listing)

        # hop 2: REGISTERED enrollments on the listing -> WITHDRAWN / RELEASED
        listing_enrollments = by_created(
            [e for e in db.enrollments.values() if e["catalog_listing_id"] == listing["id"]]
        )
        for enrollment in listing_enrollments:
            if enrollment["academic_status"] != "REGISTERED":
                continue
            enrollment["academic_status"] = "WITHDRAWN"
            touch(enrollment)
            # hop 3: open invoices VOIDED, employee cap ledger recomputed
            if enrollment["funding_status"] in ("RESERVED", "BILLED"):
                enrollment["funding_status"] = "RELEASED"
                void_open_invoices(enrollment)
            employee = employee_of_enrollment(enrollment)
            if employee not in affected_employees:
                affected_employees.append(employee)

    # hop 2b: open approval requests for this school's programs -> REJECTED
    school_program_ids = {
        p["id"] for p in db.programs.values() if p["school_id"] == agreement["school_id"]
    }
    for request_row in by_created(list(db.requests.values())):
        if request_row["status"] in ("SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED") and request_row[
            "program_id"
        ] in school_program_ids:
            request_row["status"] = "REJECTED"
            request_row["decision_note"] = "school partnership terminated"
            touch(request_row)

    for employee in affected_employees:
        refresh_and_touch(employee)


def cascade_employment_termination(employee, termination_date):
    enrollments = enrollments_of_employee(employee["id"])

    # open coursework is withdrawn and its reservation released
    for enrollment in enrollments:
        if enrollment["academic_status"] in OPEN_ACADEMIC_STATES:
            enrollment["academic_status"] = "WITHDRAWN"
            touch(enrollment)
            if enrollment["funding_status"] in ("RESERVED", "BILLED"):
                enrollment["funding_status"] = "RELEASED"
                void_open_invoices(enrollment)

    # separately: settled benefits inside the service commitment are clawed back
    assessed = 0
    for enrollment in enrollments:
        if enrollment["funding_status"] != "SETTLED":
            continue
        if assess_obligation(enrollment, "EARLY_DEPARTURE", termination_date) is not None:
            assessed += 1
    return assessed


def utilization_report(employer):
    """PRD 3.9 / calculations.employer_utilization_report."""
    plan_year = plan_year_of(clock_date(), employer)
    employees = employees_of(employer["id"])
    employee_ids = {e["id"] for e in employees}
    eligible = [e for e in employees if e["eligibility_status"] == "ELIGIBLE"]
    scope = [
        e
        for e in db.enrollments.values()
        if e["employee_id"] in employee_ids and e["plan_year"] == plan_year
    ]

    eligible_count = len(eligible)
    participants = {e["employee_id"] for e in scope}
    participating_count = len(participants)

    participation_rate = (
        0.0 if eligible_count == 0 else round_rate_4(participating_count, eligible_count)
    )

    closed = [e for e in scope if e["academic_status"] in CLOSED_ACADEMIC_STATES]
    completions = [e for e in closed if e["academic_status"] == "PASSED"]
    completion_rate = 0.0 if not closed else round_rate_4(len(completions), len(closed))

    retained = {
        employee_id
        for employee_id in participants
        if db.employees[employee_id]["employment_status"] == "ACTIVE"
    }
    retention_rate = (
        0.0 if participating_count == 0 else round_rate_4(len(retained), participating_count)
    )

    tracks = set()
    for enrollment in completions:
        listing = db.listings[enrollment["catalog_listing_id"]]
        program = db.programs[listing["program_id"]]
        tracks.add((enrollment["employee_id"], program["skill_track"]))

    total_disbursed = sum(
        e["employer_disbursed_cents"] for e in scope if e["funding_status"] == "SETTLED"
    )
    year = clock_year()
    total_imputed = sum(
        t["imputed_income_cents"]
        for t in db.tax_entries.values()
        if t["employee_id"] in employee_ids and t["tax_year"] == year
    )
    cost_per_completion = (
        0
        if not completions
        else round_half_up(Decimal(total_disbursed) / Decimal(len(completions)))
    )

    return {
        "plan_year": plan_year,
        "eligible_employee_count": eligible_count,
        "participating_employee_count": participating_count,
        "participation_rate": participation_rate,
        "completion_rate": completion_rate,
        "retention_rate": retention_rate,
        "skill_attainment_count": len(tracks),
        "total_employer_disbursed_cents": total_disbursed,
        "total_imputed_income_cents": total_imputed,
        "cost_per_completion_cents": cost_per_completion,
    }


def annual_true_up(tax_year):
    """PRD 3.9 step five — the aggregate reading of the exclusion limit."""
    appended = 0
    for employee in by_created(list(db.employees.values())):
        entries = tax_entries_of(employee["id"], tax_year)
        if not entries:
            continue
        net_benefit = sum(t["benefit_cents"] for t in entries)
        target_excluded = min(net_benefit, TAX_EXCLUSION_LIMIT_CENTS)
        target_imputed = net_benefit - target_excluded
        delta_excluded = target_excluded - sum(t["excluded_cents"] for t in entries)
        delta_imputed = target_imputed - sum(t["imputed_income_cents"] for t in entries)
        if delta_excluded == 0 and delta_imputed == 0:
            continue
        _append_tax_entry(
            employee["id"], None, "TRUE_UP", tax_year, 0, delta_excluded, delta_imputed
        )
        appended += 1
        refresh_and_touch(employee)
    return appended


def supersede_elapsed_policies():
    """PRD 3.9 step one."""
    day = clock_date()
    employers_touched = []
    count = 0
    for policy in by_created(list(db.policies.values())):
        if policy["status"] != "ACTIVE":
            continue
        if iso_date(policy["effective_to"]) > day:
            continue
        policy["status"] = "SUPERSEDED"
        touch(policy)
        count += 1
        if policy["employer_id"] not in employers_touched:
            employers_touched.append(policy["employer_id"])
    for employer_id in employers_touched:
        for employee in employees_of(employer_id):
            refresh_employee(employee)
            touch(employee)
    return count


def run_clawback_or_release(enrollment):
    """Applied to a FAILED / INCOMPLETE outcome (PRD 3.7)."""
    if enrollment["funding_status"] == "SETTLED":
        return assess_obligation(enrollment, "ACADEMIC_FAILURE")
    if enrollment["funding_status"] in ("RESERVED", "BILLED"):
        enrollment["funding_status"] = "RELEASED"
        void_open_invoices(enrollment)
    return None
