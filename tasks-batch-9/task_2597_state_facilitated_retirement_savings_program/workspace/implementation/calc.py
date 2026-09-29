"""Every calculation rule of the programme (SCAFFOLD 1.3 / PRD 2.11-2.12, 3.x).

All money is integer cents, all rates integer basis points, and every division
by 10000 rounds half up exactly where the specification names the rounding
point -- never on a value that is about to be multiplied again.
"""
from decimal import Decimal

from errors import fail
from store import db
from util import (add_days, add_years, bp_of, ceil_div, days_between, fmt_date,
                  month_day_in_year, mul_div_round, parse_date, parse_instant,
                  round_half_up)

# ---- statutory constants that are not program-year dials --------------------
WAVE_1_DEADLINE = "2026-06-30"
WAVE_2_DEADLINE = "2026-12-31"
WAVE_3_DEADLINE = "2027-06-30"
SMALL_EMPLOYER_CEILING = 4
WAVE_3_FLOOR = 5
WAVE_2_FLOOR = 50
WAVE_1_FLOOR = 100

CATCH_UP_AGE_FLOOR = 50
MIN_PARTICIPANT_RATE_BP = 100
MAX_PARTICIPANT_RATE_BP = 1500
EXCISE_TAX_RATE_BP = 600
NORMAL_RETIREMENT_AGE = 65
FULL_ALLOCATION_BP = 10000

FEE_TIER_1_CEILING_CENTS = 500000
FEE_TIER_1_BP = 40
FEE_TIER_2_CEILING_CENTS = 950000
FEE_TIER_2_BP = 50
FEE_TIER_3_BP = 60
INDIRECT_WITHHOLDING_BP = 1000
INDIRECT_SETTLE_DAYS = 60
ROLLOVER_FREQUENCY_WINDOW_DAYS = 365
ROLLOVER_FREQUENCY_TRAILING_DAYS = 364

PROGRAM_YEAR_DEFAULTS = {
    "catch_up_limit_cents": 100000,
    "escalation_increment_bp": 100,
    "escalation_cap_bp": 800,
    "escalation_seasoning_days": 180,
    "opt_out_window_days": 30,
    "remittance_due_days": 7,
    "notice_period_days": 90,
    "sustained_notice_days": 180,
    "register_penalty_initial_cents_per_employee": 25000,
    "register_penalty_sustained_cents_per_employee": 50000,
    "remit_penalty_monthly_rate_bp": 150,
    "remit_penalty_floor_cents": 10000,
    "remit_penalty_cap_bp": 5000,
    "nia_daily_rate_bp": 2,
    "correction_deadline_month_day": "04-15",
}


# =============================================================== program year

def find_program_year(calendar_year):
    for row in db.program_years.values():
        if row["calendar_year"] == calendar_year:
            return row
    return None


def program_year(required=True):
    """The statutory dial row for the calendar year of the current logical clock."""
    row = find_program_year(db.year())
    if row is None and required:
        fail("ERR_PROGRAM_YEAR_NOT_CONFIGURED",
             "no program year is configured for %d" % db.year())
    return row


def dial(name):
    """A dial value, falling back to its statutory default when no row exists yet."""
    row = program_year(required=False)
    if row is not None and row.get(name) is not None:
        return row[name]
    return PROGRAM_YEAR_DEFAULTS.get(name)


# ========================================================= employer_coverage_tier

def coverage_tier(employee_count):
    count = int(employee_count)
    if count >= WAVE_1_FLOOR:
        return "WAVE_1", WAVE_1_DEADLINE
    if count >= WAVE_2_FLOOR:
        return "WAVE_2", WAVE_2_DEADLINE
    if count >= WAVE_3_FLOOR:
        return "WAVE_3", WAVE_3_DEADLINE
    return "NOT_COVERED", None


# ============================================ employer_compliance_and_unremitted

def employer_remittances(employer_id):
    return [r for r in db.payroll_remittances.values() if r["employer_id"] == employer_id]


def overdue_remittances(employer_id, as_of=None):
    """DRAFT/SUBMITTED batches whose pay_date + remittance_due_days is strictly
    earlier than the evaluation date."""
    as_of = as_of or db.today()
    due_days = dial("remittance_due_days")
    out = []
    for row in employer_remittances(employer_id):
        if row["status"] not in ("DRAFT", "SUBMITTED"):
            continue
        due = add_days(parse_date(row["pay_date"]), due_days)
        if due < as_of:
            out.append(row)
    return out


def unremitted_deduction_cents(employer_id, as_of=None):
    return sum(int(r["total_deducted_cents"]) for r in overdue_remittances(employer_id, as_of))


def employer_referrals(employer_id):
    out = []
    for referral in db.enforcement_referrals.values():
        penalty = db.penalty_assessments.get(referral["penalty_id"])
        if penalty is not None and penalty["employer_id"] == employer_id:
            out.append(referral)
    return out


def has_open_referral(employer_id):
    return any(r["status"] == "OPEN" for r in employer_referrals(employer_id))


def employer_assessments(employer_id):
    return [p for p in db.penalty_assessments.values() if p["employer_id"] == employer_id]


def compliance_status(employer, as_of=None):
    """Derived enforcement posture, highest applicable condition first (PRD 3.8)."""
    as_of = as_of or db.today()
    employer_id = employer["id"]
    if has_open_referral(employer_id):
        return "REFERRED"
    for penalty in employer_assessments(employer_id):
        if penalty["status"] in ("ASSESSED", "AFFIRMED"):
            return "PENALIZED"
    if unremitted_deduction_cents(employer_id, as_of) > 0:
        return "DELINQUENT"
    deadline = employer.get("registration_deadline")
    if employer["registration_status"] == "PENDING_REGISTRATION" and deadline:
        if as_of > parse_date(deadline):
            return "DELINQUENT"
    return "COMPLIANT"


# ================================================== participant / account maths

def participant_age_at_year_end(participant):
    dob = parse_date(participant["date_of_birth"])
    return db.year() - dob.year


def catch_up_eligible(participant):
    return participant_age_at_year_end(participant) >= CATCH_UP_AGE_FLOOR


def annual_ceiling_cents(participant):
    row = program_year(required=False)
    if row is None:
        return 0
    ceiling = int(row["ira_annual_limit_cents"])
    if catch_up_eligible(participant):
        ceiling += int(row["catch_up_limit_cents"])
    return ceiling


def account_lines(account_id):
    return [l for l in db.remittance_lines.values() if l.get("_account_id") == account_id]


def account_ytd_contribution_cents(account):
    """Posted contributions with a pay_date inside the current program year,
    net of completed excess corrections (PRD 3.5)."""
    row = program_year(required=False)
    if row is None:
        return 0
    year = int(row["calendar_year"])
    total = 0
    for line in account_lines(account["id"]):
        if line["status"] != "POSTED":
            continue
        remittance = db.payroll_remittances.get(line["remittance_id"])
        if remittance is None:
            continue
        pay_date = parse_date(remittance["pay_date"])
        if pay_date.year != year:
            continue
        total += int(line["allocated_cents"])
    for case in account_cases(account["id"]):
        if case["status"] == "COMPLETED" and int(case.get("calendar_year") or 0) == year:
            total -= int(case["detected_excess_cents"])
    return total


def account_remaining_headroom_cents(account):
    participant = db.participants.get(account["participant_id"])
    if participant is None:
        return 0
    ceiling = annual_ceiling_cents(participant)
    return max(0, ceiling - account_ytd_contribution_cents(account))


def account_cases(account_id):
    return [c for c in db.excess_cases.values() if c["account_id"] == account_id]


def account_transfers_out(account_id):
    return [t for t in db.portability_transfers.values() if t["source_account_id"] == account_id]


def uncorrected_excess_cents(account):
    return sum(int(c["detected_excess_cents"]) for c in account_cases(account["id"])
               if c["status"] == "EXPIRED")


def account_posture(account):
    """PRD 2.12 -- a single pass over the account's children."""
    if account["account_status"] in ("CLOSURE_PENDING", "CLOSED"):
        return "LOCKED"
    for case in account_cases(account["id"]):
        if case["status"] in ("DETECTED", "METHOD_ELECTED", "EXPIRED"):
            return "RESTRICTED"
    for transfer in account_transfers_out(account["id"]):
        if transfer["status"] == "REQUESTED":
            return "RESTRICTED"
    return "UNRESTRICTED"


def active_election(account_id):
    rows = [e for e in db.investment_elections.values()
            if e["account_id"] == account_id and e["status"] == "ACTIVE"]
    rows.sort(key=lambda r: r.get("_seq", 0))
    return rows[-1] if rows else None


def account_elections(account_id):
    rows = [e for e in db.investment_elections.values() if e["account_id"] == account_id]
    rows.sort(key=lambda r: r.get("_seq", 0))
    return rows


def fund_allocation_split(account):
    """Re-split balance_cents from scratch; the last fund absorbs the remainder."""
    election = active_election(account["id"])
    if election is None:
        return []
    allocations = list(election["allocations"])
    allocations.sort(key=lambda a: (-int(a["allocation_bp"]), str(a["fund_code"])))
    balance = int(account["balance_cents"])
    out = []
    assigned = 0
    for index, allocation in enumerate(allocations):
        if index == len(allocations) - 1:
            amount = balance - assigned
        else:
            amount = bp_of(balance, allocation["allocation_bp"])
            assigned += amount
        out.append({"fund_code": allocation["fund_code"], "balance_cents": amount})
    return out


# ======================================================= penalty amount variants

def statutory_amount_cents(employee_count, notice_date, as_of):
    """Additive per-employee tiers: the sustained tier stacks on the initial one."""
    days = days_between(parse_date(notice_date) if isinstance(notice_date, str) else notice_date,
                        as_of)
    total = 0
    if days >= int(dial("notice_period_days")):
        total += int(employee_count) * int(dial("register_penalty_initial_cents_per_employee"))
    if days >= int(dial("sustained_notice_days")):
        total += int(employee_count) * int(dial("register_penalty_sustained_cents_per_employee"))
    return total


def months_late_for(employer_id, as_of):
    """Whole 30-day blocks of the *worst* overdue batch, rounded up."""
    due_days = int(dial("remittance_due_days"))
    worst = 0
    for row in overdue_remittances(employer_id, as_of):
        due = add_days(parse_date(row["pay_date"]), due_days)
        worst = max(worst, days_between(due, as_of))
    return ceil_div(worst, 30)


def graduated_amount_cents(shortfall_cents, months_late):
    """Floor first, cap second -- a tiny shortfall settles at its cap, not its floor."""
    shortfall = int(shortfall_cents)
    if shortfall <= 0:
        return 0
    raw = round_half_up(Decimal(shortfall) * Decimal(int(dial("remit_penalty_monthly_rate_bp")))
                        * Decimal(int(months_late)) / Decimal(10000))
    cap = bp_of(shortfall, dial("remit_penalty_cap_bp"))
    floored = max(raw, int(dial("remit_penalty_floor_cents")))
    return min(floored, cap)


def assessed_for(violation_type, statutory, graduated):
    if violation_type == "FAILURE_TO_REMIT":
        return max(int(statutory), int(graduated))
    return int(statutory)


def penalty_amounts(employer, violation_type, notice_date, employee_count, as_of):
    """The complete amount triple stored on every assessment."""
    statutory = statutory_amount_cents(employee_count, notice_date, as_of)
    shortfall = unremitted_deduction_cents(employer["id"], as_of)
    graduated = graduated_amount_cents(shortfall, months_late_for(employer["id"], as_of))
    return {
        "statutory_amount_cents": statutory,
        "graduated_amount_cents": graduated,
        "shortfall_basis_cents": shortfall,
        "months_late": months_late_for(employer["id"], as_of),
        "assessed_cents": assessed_for(violation_type, statutory, graduated),
    }


# ================================================ net income attributable (NIA)

def nia_adjusted_balance_cents(case, closing_fmv_cents, period_contributions_cents):
    adjusted_opening = (int(case["opening_fmv_cents"]) + int(period_contributions_cents)
                        - int(case["period_distributions_cents"]))
    if adjusted_opening == 0:
        return 0
    delta = Decimal(int(closing_fmv_cents)) - Decimal(adjusted_opening)
    return round_half_up(Decimal(int(case["detected_excess_cents"])) * delta / Decimal(adjusted_opening))


def nia_daily_prorata_cents(case, completion_date):
    start = parse_date(case["computation_period_start"])
    days = days_between(start, completion_date)
    return round_half_up(Decimal(int(days)) * Decimal(int(dial("nia_daily_rate_bp")))
                         * Decimal(int(case["detected_excess_cents"])) / Decimal(10000))


def nia_method_for(case, completion_instant):
    """DAILY_PRORATA exactly when the fund mix moved inside the computation period."""
    start = parse_date(case["computation_period_start"])
    for election in account_elections(case["account_id"]):
        stamp = election.get("superseded_at")
        if not stamp:
            continue
        moment = parse_instant(stamp)
        if moment is None:
            continue
        if moment.date() >= start and moment < completion_instant:
            return "DAILY_PRORATA"
    return "ADJUSTED_BALANCE"


def correction_deadline_date(calendar_year):
    return month_day_in_year(dial("correction_deadline_month_day"), int(calendar_year) + 1)


def excise_tax_cents(detected_excess_cents):
    return bp_of(detected_excess_cents, EXCISE_TAX_RATE_BP)


# ======================================================== portability settlement

def fee_tier_bp(gross_cents):
    gross = int(gross_cents)
    if gross <= FEE_TIER_1_CEILING_CENTS:
        return FEE_TIER_1_BP
    if gross <= FEE_TIER_2_CEILING_CENTS:
        return FEE_TIER_2_BP
    return FEE_TIER_3_BP


def transfer_money(gross_cents, transfer_kind, source_balance_cents, source_basis_cents):
    """The five figures, derived in the exact order PRD 3.7 fixes.

    The fee tier is keyed on the GROSS amount; keying it on a post-withholding
    figure is the error this ordering exists to prevent.
    """
    gross = int(gross_cents)
    fee = bp_of(gross, fee_tier_bp(gross))
    if int(source_balance_cents) == 0:
        basis_portion = 0
    else:
        basis_portion = mul_div_round(gross, int(source_basis_cents), int(source_balance_cents))
    taxable = gross - basis_portion
    withholding = bp_of(taxable, INDIRECT_WITHHOLDING_BP) if transfer_kind == "INDIRECT_60_DAY" else 0
    net = gross - fee - withholding
    return {
        "fee_cents": fee,
        "basis_portion_cents": basis_portion,
        "taxable_cents": taxable,
        "withholding_cents": withholding,
        "net_cents": net,
    }


def participant_indirect_transfers(participant_id):
    return [t for t in db.portability_transfers.values()
            if t["participant_id"] == participant_id and t["transfer_kind"] == "INDIRECT_60_DAY"]


def indirect_rollover_count(participant_id):
    return len([t for t in participant_indirect_transfers(participant_id)
                if t["status"] == "SETTLED"])


def rollover_frequency_blocked(participant_id, request_date):
    """Trailing 365-day window: [request_date - 364, request_date], both inclusive."""
    window_start = add_days(request_date, -ROLLOVER_FREQUENCY_TRAILING_DAYS)
    for transfer in participant_indirect_transfers(participant_id):
        if transfer["status"] not in ("SETTLED", "REQUESTED"):
            continue
        anchor = transfer.get("settled_on") or transfer.get("requested_on")
        anchor_date = parse_date(anchor)
        if anchor_date is None:
            continue
        if window_start <= anchor_date <= request_date:
            return True
    return False


# ============================================== escalation and default election

def escalation_candidate_rate(current_rate_bp):
    increment = int(dial("escalation_increment_bp"))
    cap = int(dial("escalation_cap_bp"))
    return min(int(current_rate_bp) + increment, cap)


def escalation_qualifies(enrollment, effective_date):
    if enrollment["enrollment_status"] != "ACTIVE":
        return False
    if enrollment.get("escalation_opt_out"):
        return False
    first = first_contribution_date(enrollment["id"])
    if not first:
        return False
    seasoning = int(dial("escalation_seasoning_days"))
    return days_between(parse_date(first), effective_date) >= seasoning


def default_fund_option(participant):
    """(option, selection_basis) or (None, None) when the menu cannot serve a default."""
    retirement_year = parse_date(participant["date_of_birth"]).year + NORMAL_RETIREMENT_AGE
    pool = [o for o in db.investment_options.values()
            if o["category"] == "TARGET_DATE" and o["status"] == "OPEN"
            and o["default_eligible"] and o.get("target_year") is not None
            and int(o["target_year"]) >= retirement_year]
    if pool:
        pool.sort(key=lambda o: (int(o["target_year"]), int(o["expense_ratio_bp"]),
                                 o.get("created_at") or "", o.get("_seq", 0)))
        return pool[0], "TARGET_DATE_GLIDE_PATH"
    fallback = [o for o in db.investment_options.values()
                if o["category"] == "CAPITAL_PRESERVATION" and o["status"] == "OPEN"
                and o["default_eligible"]]
    if fallback:
        fallback.sort(key=lambda o: (int(o["expense_ratio_bp"]), o.get("created_at") or "",
                                     o.get("_seq", 0)))
        return fallback[0], "CAPITAL_PRESERVATION_FALLBACK"
    return None, None


def expected_deduction_cents(gross_wages_cents, contribution_rate_bp):
    return bp_of(gross_wages_cents, contribution_rate_bp)


# ================================================================ account lookup

def participant_open_accounts(participant_id):
    rows = [a for a in db.participant_accounts.values()
            if a["participant_id"] == participant_id and a["account_status"] == "OPEN"]
    rows.sort(key=lambda a: (0 if a["account_type"] == "ROTH_IRA" else 1, a.get("_seq", 0)))
    return rows


def posting_target_account(participant_id):
    rows = participant_open_accounts(participant_id)
    return rows[0] if rows else None


def enrollment_lines(enrollment_id, statuses=None):
    rows = [l for l in db.remittance_lines.values() if l["enrollment_id"] == enrollment_id]
    if statuses is not None:
        rows = [l for l in rows if l["status"] in statuses]
    rows.sort(key=lambda l: l.get("_seq", 0))
    return rows


def lifetime_deducted_cents(enrollment_id):
    return sum(int(l["deducted_cents"]) for l in enrollment_lines(enrollment_id, ("POSTED",)))


def first_contribution_date(enrollment_id):
    dates = []
    for line in enrollment_lines(enrollment_id, ("POSTED",)):
        remittance = db.payroll_remittances.get(line["remittance_id"])
        if remittance is not None:
            dates.append(remittance["pay_date"])
    if not dates:
        return None
    return min(dates)


# ================================================ derived-figure refresh passes

def refresh_account(account, bump=False):
    """Recompute every purely derived figure of an account.

    Stored money (balance_cents, contribution_basis_cents, ytd_contribution_cents)
    is moved by the workflows; everything below is a function of that money plus
    the account's children, so it is refreshed here and never updated
    incrementally (PRD 2.11).
    """
    if account is None:
        return None
    election = active_election(account["id"])
    account["active_election_id"] = election["id"] if election else None
    account["fund_balances"] = fund_allocation_split(account)
    account["uncorrected_excess_cents"] = uncorrected_excess_cents(account)
    account["remaining_headroom_cents"] = account_remaining_headroom_cents_stored(account)
    account["posture"] = account_posture(account)
    if bump:
        db.touch(account)
    return account


def account_remaining_headroom_cents_stored(account):
    """Ceiling minus the account's stored year-to-date total, floored at zero."""
    participant = db.participants.get(account["participant_id"])
    if participant is None:
        return 0
    ceiling = annual_ceiling_cents(participant)
    return max(0, ceiling - int(account.get("ytd_contribution_cents") or 0))


def refresh_employer(employer, as_of=None, bump=False):
    """Recompute the employer's unremitted total and re-derive compliance_status.

    Called only at the points PRD 3.8 names -- remittance submission, posting,
    rejection and reversal, penalty creation and disposition, referral creation,
    the exemption cascade, and the compliance sweep -- so that enforcement
    advances with those events rather than silently with the clock.
    """
    if employer is None:
        return None
    as_of = as_of or db.today()
    before = (employer["unremitted_deduction_cents"], employer["compliance_status"])
    employer["unremitted_deduction_cents"] = unremitted_deduction_cents(employer["id"], as_of)
    employer["compliance_status"] = compliance_status(employer, as_of)
    after = (employer["unremitted_deduction_cents"], employer["compliance_status"])
    if bump and after != before:
        db.touch(employer)
    return employer


def refresh_remittance(remittance):
    if remittance is None:
        return None
    lines = [l for l in db.remittance_lines.values() if l["remittance_id"] == remittance["id"]]
    remittance["line_count"] = len(lines)
    posted = [l for l in lines if l["status"] == "POSTED"]
    remittance["total_allocated_cents"] = sum(int(l["allocated_cents"]) for l in posted)
    remittance["total_excess_cents"] = sum(int(l["excess_cents"]) for l in posted)
    return remittance


def remittance_lines_of(remittance_id):
    rows = [l for l in db.remittance_lines.values() if l["remittance_id"] == remittance_id]
    rows.sort(key=lambda l: l.get("_seq", 0))
    return rows
