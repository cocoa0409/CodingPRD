"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors, not confusing assertion failures.

Calendar shorthand used throughout (see PRD sections 3.1 and 3.4):
  T1: term 2026-08-24..2026-12-11 plus a 5-day break 2026-11-25..29
      -> calendar_days 110, deductible 5, total_days 105.
      Day 63 = 2026-10-25 -> 63/105 = 0.600 exactly (cap NOT applied).
      Day 64 = 2026-10-26 -> 0.610 (cap applies: earned_pct 1.000).
      Midpoint day 53 of 105 = 2026-10-15 -> 0.505.
  T2: term 2026-09-01..2026-12-09, no breaks -> total_days 100;
      midpoint day 50 = 2026-10-20 -> 0.500.

Ownership: Student-role calls are always made with
make_student_headers(student["id"]) — never the shared constant — because
ownership checks compare X-User-ID to the enrollment's student_id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TERM_T1, TERM_T2
from .factories import (
    create_award_payload,
    create_break_payload,
    create_clock_payload,
    create_disbursement_payload,
    create_enrollment_payload,
    create_student_payload,
    create_term_payload,
)
from .test_users import TEST_USERS, make_student_headers

ADMIN = TEST_USERS["system_admin_headers"]
REGISTRAR = TEST_USERS["registrar_clerk_headers"]
OFFICER = TEST_USERS["financial_aid_officer_headers"]
BURSAR = TEST_USERS["bursar_clerk_headers"]

# Default officer identity pinned for calculation calls; segregation-of-duties
# tests rely on this value matching the case's calculated_by_user_id.
OFFICER_1_ID = "officer-1"
OFFICER_2_ID = "officer-2"


def officer_headers(user_id=OFFICER_1_ID):
    from .test_users import make_financial_aid_officer_headers
    return make_financial_aid_officer_headers(user_id)


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}")


def _ok(step, resp):
    data = get_success_data(resp)
    if data is None:
        _fail(step, resp)
    return data


# ---------------------------------------------------------------------------
# Tier 1 — terms, students, enrollments
# ---------------------------------------------------------------------------

def create_term(with_break=False, **overrides):
    """Create an academic term; optionally register the canonical 5-day
    break 2026-11-25..29 (only meaningful for the T1 date range).
    Returns the term dict (post-break when with_break is True)."""
    resp = api_client.create_term(create_term_payload(**overrides), REGISTRAR)
    term = _ok("create_term", resp)
    if with_break:
        create_break(term["id"])
        term = _ok("get_term", api_client.get_term(term["id"], REGISTRAR))
    return term


def create_term_t1(with_break=True, **overrides):
    """The canonical T1 term: 2026-08-24..2026-12-11; with the deductible
    5-day break this yields total_days 105."""
    return create_term(with_break=with_break, **overrides)


def create_term_t2(**overrides):
    """The canonical T2 term: 2026-09-01..2026-12-09 (100 days, no breaks)."""
    defaults = {"name": TERM_T2["name"], "start_date": TERM_T2["start_date"],
                "end_date": TERM_T2["end_date"]}
    defaults.update(overrides)
    return create_term(**defaults)


def create_break(term_id, **overrides):
    resp = api_client.create_break(term_id, create_break_payload(**overrides),
                                   REGISTRAR)
    return _ok("create_break", resp)


def create_student(**overrides):
    resp = api_client.create_student(create_student_payload(**overrides),
                                     REGISTRAR)
    return _ok("create_student", resp)


def create_enrollment(student_id, term_id, **overrides):
    resp = api_client.create_enrollment(
        student_id, create_enrollment_payload(term_id, **overrides), REGISTRAR)
    return _ok("create_enrollment", resp)


def setup_term_student_enrollment(charges=600_000, term_overrides=None,
                                  with_break=True):
    """T1 term + student + enrollment. Returns (term, student, enrollment)."""
    term = create_term_t1(with_break=with_break, **(term_overrides or {}))
    student = create_student()
    enrollment = create_enrollment(student["id"], term["id"],
                                   institutional_charges_cents=charges)
    return term, student, enrollment


# ---------------------------------------------------------------------------
# Tier 2 — awards and disbursements
# ---------------------------------------------------------------------------

def create_award(enrollment_id, program="PELL_GRANT", amount_cents=200_000):
    resp = api_client.create_award(
        enrollment_id,
        create_award_payload(program=program, amount_cents=amount_cents),
        OFFICER)
    return _ok("create_award", resp)


def accept_award(award_id, student_id):
    """Student accepts their own loan award (ownership-gated)."""
    resp = api_client.accept_award(award_id, make_student_headers(student_id))
    return _ok("accept_award", resp)


def schedule_disbursement(award_id, amount_cents):
    resp = api_client.create_disbursement(
        award_id, create_disbursement_payload(amount_cents=amount_cents),
        OFFICER)
    return _ok("schedule_disbursement", resp)


def disburse(disbursement_id):
    resp = api_client.disburse_disbursement(disbursement_id, OFFICER)
    return _ok("disburse", resp)


def create_and_fund_award(enrollment_id, student_id, program, amount_cents,
                          disburse_cents=None):
    """Create an award, accept it when it is a loan (grants start ACCEPTED),
    schedule a disbursement and release it. Returns the award dict."""
    award = create_award(enrollment_id, program=program,
                         amount_cents=amount_cents)
    if program != "PELL_GRANT":
        accept_award(award["id"], student_id)
    if disburse_cents is not None:
        disb = schedule_disbursement(award["id"], disburse_cents)
        disburse(disb["id"])
    return _ok("get_award", api_client.get_award(award["id"], OFFICER))


# ---------------------------------------------------------------------------
# Tier 3 — withdrawal and calculation lifecycle
# ---------------------------------------------------------------------------

def withdraw_enrollment(enrollment_id, payload, headers=None):
    resp = api_client.withdraw_enrollment(enrollment_id, payload,
                                          headers or REGISTRAR)
    return _ok("withdraw_enrollment", resp)


def withdraw_official(enrollment_id, notification_date, headers=None):
    return withdraw_enrollment(
        enrollment_id,
        {"withdrawal_type": "OFFICIAL", "notification_date": notification_date},
        headers=headers)


def withdraw_unofficial(enrollment_id, last_attendance_date=None,
                        headers=None):
    payload = {"withdrawal_type": "UNOFFICIAL"}
    if last_attendance_date is not None:
        payload["last_attendance_date"] = last_attendance_date
    return withdraw_enrollment(enrollment_id, payload, headers=headers)


def calculate_case(case_id, officer_id=OFFICER_1_ID):
    resp = api_client.calculate_case(case_id, officer_headers(officer_id))
    return _ok("calculate_case", resp)


def recalculate_case(case_id, expected_version, officer_id=OFFICER_1_ID,
                     **corrections):
    payload = {"expected_withdrawal_case_version": expected_version}
    payload.update(corrections)
    resp = api_client.recalculate_case(case_id, payload,
                                       officer_headers(officer_id))
    return _ok("recalculate_case", resp)


def set_clock(to_iso8601):
    resp = api_client.set_current_utc(create_clock_payload(to_iso8601), ADMIN)
    return _ok("set_current_utc", resp)


def list_obligations(case_id):
    resp = api_client.list_case_obligations(case_id, OFFICER)
    return _ok("list_case_obligations", resp)


def list_offers(case_id):
    resp = api_client.list_case_offers(case_id, OFFICER)
    return _ok("list_case_offers", resp)


def list_account_entries(enrollment_id=None, entry_type=None,
                         reversal_of_entry_id=None):
    params = {}
    if enrollment_id is not None:
        params["enrollment_id"] = enrollment_id
    if entry_type is not None:
        params["entry_type"] = entry_type
    if reversal_of_entry_id is not None:
        params["reversal_of_entry_id"] = reversal_of_entry_id
    resp = api_client.list_account_entries(OFFICER, params=params)
    return _ok("list_account_entries", resp)


def get_enrollment(enrollment_id):
    return _ok("get_enrollment",
               api_client.get_enrollment(enrollment_id, OFFICER))


def get_case(case_id):
    return _ok("get_withdrawal_case",
               api_client.get_withdrawal_case(case_id, OFFICER))


# ---------------------------------------------------------------------------
# Tier 4 — named composite scenarios
# ---------------------------------------------------------------------------

def setup_pell_only_case(withdraw_date=TERM_T1["day_63"], charges=600_000,
                         pell_amount=200_000, calculate=True,
                         officer_id=OFFICER_1_ID):
    """Canonical "PELL-only case A": T1 term + enrollment with `charges` +
    a fully disbursed PELL grant + OFFICIAL withdrawal on `withdraw_date`.
    When withdraw_date is day 63 (0.600): earned 120000, return 80000,
    school share min(240000, 80000) = 80000, one SCHOOL obligation.
    Returns a dict with term/student/enrollment/case and (when calculated)
    obligations."""
    term = create_term_t1()
    student = create_student()
    enrollment = create_enrollment(student["id"], term["id"],
                                   institutional_charges_cents=charges)
    pell = create_and_fund_award(enrollment["id"], student["id"],
                                 "PELL_GRANT", pell_amount, pell_amount)
    case = withdraw_official(enrollment["id"], withdraw_date)
    result = {
        "term": term, "student": student, "enrollment": enrollment,
        "pell": pell, "case": case,
    }
    if calculate:
        result["case"] = calculate_case(case["id"], officer_id=officer_id)
        result["obligations"] = list_obligations(case["id"])
    return result


def setup_full_aid_case(charges=600_000, pell_amount=200_000,
                        loan_amount=300_000,
                        withdraw_date=TERM_T1["day_63"],
                        calculate=True, officer_id=OFFICER_1_ID,
                        term_overrides=None, with_break=True):
    """T1 term + enrollment + PELL fully disbursed + SUBSIDIZED_LOAN accepted
    and fully disbursed, then an OFFICIAL withdrawal. At day 63 (0.600):
    earned 300000 of 500000; return_amount 200000; school share 200000.
    Returns dict with all artifacts."""
    term = create_term_t1(with_break=with_break, **(term_overrides or {}))
    student = create_student()
    enrollment = create_enrollment(student["id"], term["id"],
                                   institutional_charges_cents=charges)
    pell = create_and_fund_award(enrollment["id"], student["id"],
                                 "PELL_GRANT", pell_amount, pell_amount)
    loan = create_and_fund_award(enrollment["id"], student["id"],
                                 "SUBSIDIZED_LOAN", loan_amount, loan_amount)
    case = withdraw_official(enrollment["id"], withdraw_date)
    result = {
        "term": term, "student": student, "enrollment": enrollment,
        "pell": pell, "loan": loan, "case": case,
    }
    if calculate:
        result["case"] = calculate_case(case["id"], officer_id=officer_id)
        result["obligations"] = list_obligations(case["id"])
    return result


def setup_t2_split_case(charges=100_000, clock="2026-11-15T00:00:00Z",
                        record_school_return=False):
    """T2 term (100 days, midpoint 0.500) + PELL 200000 and SUB 300000 both
    fully disbursed; UNOFFICIAL withdrawal processed at `clock`.
    Earned 250000 of 500000; return_amount 250000; unearned_pct 0.500.
    charges 100000 -> school = min(50000, 250000) = 50000;
    student grant base min(200000, 100000) = 100000 -> grant return 50000;
    loan deferred 100000. Due dates: determination + 45d = 2026-12-30.
    charges 80000 -> school 40000, student 50000.
    Returns dict with artifacts; obligations ordered SCHOOL then STUDENT."""
    term = create_term_t2()
    student = create_student()
    enrollment = create_enrollment(student["id"], term["id"],
                                   institutional_charges_cents=charges)
    pell = create_and_fund_award(enrollment["id"], student["id"],
                                 "PELL_GRANT", 200_000, 200_000)
    loan = create_and_fund_award(enrollment["id"], student["id"],
                                 "SUBSIDIZED_LOAN", 300_000, 300_000)
    set_clock(clock)
    case = withdraw_unofficial(enrollment["id"])
    case = calculate_case(case["id"])
    result = {
        "term": term, "student": student, "enrollment": enrollment,
        "pell": pell, "loan": loan, "case": case,
        "obligations": list_obligations(case["id"]),
    }
    if record_school_return:
        school_ob = result["obligations"][0]
        resp = api_client.record_return(
            school_ob["id"], {"amount_cents": school_ob["amount_cents"]},
            BURSAR)
        result["school_return"] = _ok("record_return(school)", resp)
        result["case"] = get_case(case["id"])
    return result


def setup_pwd_case(charges=500_000, clock="2026-10-26T09:00:00Z",
                   withdraw_date=TERM_T1["day_63"], calculate=True):
    """Post-withdrawal-disbursement scenario on T1: PELL 200000 (100000
    DISBURSED + 100000 SCHEDULED) and SUBSIDIZED_LOAN 300000 accepted
    (100000 DISBURSED + 200000 SCHEDULED). At day 63 (0.600): earned
    300000 > disbursed 200000 -> grant PWD 20000 auto-credited, loan offer
    80000 SENT. Returns dict with artifacts and (when calculated) offers."""
    term = create_term_t1()
    student = create_student()
    enrollment = create_enrollment(student["id"], term["id"],
                                   institutional_charges_cents=charges)
    pell = create_award(enrollment["id"], "PELL_GRANT", 200_000)
    disburse(schedule_disbursement(pell["id"], 100_000)["id"])
    schedule_disbursement(pell["id"], 100_000)
    loan = create_award(enrollment["id"], "SUBSIDIZED_LOAN", 300_000)
    accept_award(loan["id"], student["id"])
    disburse(schedule_disbursement(loan["id"], 100_000)["id"])
    schedule_disbursement(loan["id"], 200_000)
    case = withdraw_official(enrollment["id"], withdraw_date)
    set_clock(clock)
    result = {
        "term": term, "student": student, "enrollment": enrollment,
        "pell": _ok("get_award", api_client.get_award(pell["id"], OFFICER)),
        "loan": _ok("get_award", api_client.get_award(loan["id"], OFFICER)),
        "case": case,
    }
    if calculate:
        result["case"] = calculate_case(case["id"])
        result["offers"] = list_offers(case["id"])
    return result
