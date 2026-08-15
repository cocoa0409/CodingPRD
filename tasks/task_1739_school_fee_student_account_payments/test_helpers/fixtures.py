"""Composite setup helpers — multi-step state builders used across the suite.

Every fixture builds preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before each test; nothing carries over).
All roles use opaque operator ids, so TEST_USERS constants are safe everywhere;
per-user builders are used only where segregation-of-duties compares recorded
operator ids (waiver review, write-off).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_school_year_payload,
    create_department_payload,
    create_fee_catalog_item_payload,
    create_optional_purchase_item_payload,
    create_offering_payload,
    create_student_payload,
    create_waiver_program_payload,
    create_payment_plan_payload,
)
from .test_users import (
    TEST_USERS,
    make_bookkeeper_headers,
    make_family_headers,
    make_superintendent_headers,
)

BK = TEST_USERS["bookkeeper_headers"]
FAM = TEST_USERS["family_headers"]
SUPT = TEST_USERS["superintendent_headers"]

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: year environment
# ---------------------------------------------------------------------------

def setup_open_year(**year_overrides):
    """Create a school year with one department and open it.

    Returns dict(year, department).
    """
    year = get_success_data(api_client.create_school_year(
        create_school_year_payload(**year_overrides), BK))
    dept = get_success_data(api_client.create_department(
        year["id"], create_department_payload(), BK))
    get_success_data(api_client.open_school_year(year["id"], BK))
    year = get_success_data(api_client.get_school_year(year["id"], BK))
    return {"year": year, "department": dept}


def setup_year_with_fee(fee_amount=1000, fee_overrides=None, year_overrides=None,
                        offering_overrides=None, with_offering=False):
    """OPEN year + department + fee catalog item (+ optionally one SCHEDULED offering).

    Returns dict(year, department, fee_item, offering|None).
    """
    env = setup_open_year(**(year_overrides or {}))
    fee_payload = create_fee_catalog_item_payload(
        amount_cents=fee_amount, department_id=env["department"]["id"],
        **(fee_overrides or {}))
    fee = get_success_data(api_client.create_fee_catalog_item(env["year"]["id"], fee_payload, BK))
    offering = None
    if with_offering:
        off_payload = create_offering_payload(
            department_id=env["department"]["id"], fee_item_id=fee["id"],
            **(offering_overrides or {}))
        offering = get_success_data(api_client.create_offering(env["year"]["id"], off_payload, BK))
    env.update({"fee_item": fee, "offering": offering})
    return env


def add_student_with_account(year_id, external_ref="S-1", grade_level=10, family_id="fam-a",
                             full_name="Ada"):
    """Register a student and open their account under the year. Returns (student, account)."""
    student = get_success_data(api_client.create_student(
        create_student_payload(external_ref=external_ref, full_name=full_name,
                               grade_level=grade_level, family_id=family_id), BK))
    account = get_success_data(api_client.create_student_account(
        year_id, {"student_id": student["id"]}, BK))
    return student, account


def set_clock(to_iso8601):
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, BK))


# ---------------------------------------------------------------------------
# Tier 2: accounts carrying assessments / enrollments
# ---------------------------------------------------------------------------

def setup_account_with_assessment(assessed_amount_cents=3000, grade_level=10,
                                  family_id="fam-a", year_overrides=None,
                                  fee_overrides=None, external_ref="S-1"):
    """OPEN year + fee item + student + account + one ad-hoc assessment.

    Returns dict(env fields..., student, account, assessment).
    """
    env = setup_year_with_fee(fee_amount=assessed_amount_cents,
                              fee_overrides=fee_overrides,
                              year_overrides=year_overrides)
    student, account = add_student_with_account(
        env["year"]["id"], external_ref=external_ref,
        grade_level=grade_level, family_id=family_id)
    assessment = get_success_data(api_client.create_fee_assessment(
        account["id"], {"fee_item_id": env["fee_item"]["id"],
                        "assessed_amount_cents": assessed_amount_cents}, BK))
    env.update({"student": student, "account": account, "assessment": assessment})
    return env


def setup_account_enrolled(fee_amount=1000, year_overrides=None, fee_overrides=None,
                           offering_overrides=None, grade_level=10, family_id="fam-a",
                           external_ref="S-1"):
    """OPEN year + fee + SCHEDULED offering + student + account + ACTIVE enrollment.

    The enrollment auto-creates an ASSESSED fee assessment pinning the catalog price.
    Returns dict(env fields..., student, account, enrollment, assessment).
    """
    env = setup_year_with_fee(fee_amount=fee_amount, fee_overrides=fee_overrides,
                              year_overrides=year_overrides,
                              offering_overrides=offering_overrides, with_offering=True)
    student, account = add_student_with_account(
        env["year"]["id"], external_ref=external_ref,
        grade_level=grade_level, family_id=family_id)
    enrollment = get_success_data(api_client.create_enrollment(
        account["id"], {"offering_id": env["offering"]["id"]}, BK))
    assessments = get_success_data(api_client.list_fee_assessments(account["id"], BK))
    assessment = assessments[0]
    env.update({"student": student, "account": account,
                "enrollment": enrollment, "assessment": assessment})
    return env


def pay_and_settle(account_id, amount_cents, idempotency_key="k1", method="CARD",
                   overpayment_policy=None, family_user_id=None):
    """Create + settle (SUCCEEDED) a payment. Returns the settled payment dict."""
    payload = {"amount_cents": amount_cents, "method": method,
               "idempotency_key": idempotency_key}
    if overpayment_policy is not None:
        payload["overpayment_policy"] = overpayment_policy
    headers = make_family_headers(family_user_id) if family_user_id else FAM
    payment = get_success_data(api_client.create_payment(account_id, payload, headers))
    settled = get_success_data(api_client.settle_payment(
        account_id, payment["id"], {"outcome": "SUCCEEDED"}, headers))
    return settled


def current_account_version(account_id):
    """Read the account and return its current version (for OCC-guarded writes)."""
    return get_success_data(api_client.get_student_account(account_id, BK))["version"]


# ---------------------------------------------------------------------------
# Tier 3: payment plans
# ---------------------------------------------------------------------------

def setup_account_with_plan(assessed_amount_cents=4000, installment_count=2,
                            first_due_date="2026-09-05", interval_days=30,
                            year_overrides=None):
    """Account with one ad-hoc assessment covered by an ACTIVE payment plan.

    Returns dict(env..., student, account, assessment, plan, installments).
    """
    yr = {"payment_plan_min_cents": 1000, "payment_plan_max_installments": 6}
    yr.update(year_overrides or {})
    env = setup_account_with_assessment(assessed_amount_cents=assessed_amount_cents,
                                        year_overrides=yr)
    a_v = current_account_version(env["account"]["id"])
    plan = get_success_data(api_client.create_payment_plan(
        env["account"]["id"],
        create_payment_plan_payload(installment_count=installment_count,
                                    first_due_date=first_due_date,
                                    interval_days=interval_days,
                                    expected_account_version=a_v), BK))
    installments = get_success_data(api_client.list_plan_installments(
        env["account"]["id"], plan["id"], BK))
    env.update({"plan": plan, "installments": installments})
    return env


# ---------------------------------------------------------------------------
# Tier 4: aging / collections / write-off chains
# ---------------------------------------------------------------------------

def age_account_to_collections(env, sweep_date="2026-08-12"):
    """Advance clock and run the aging sweep so the account's unpaid assessment
    becomes DELINQUENT and a CollectionsCase opens. Returns the case list."""
    set_clock(sweep_date)
    get_success_data(api_client.run_ops(env["year"]["id"], BK))
    return get_success_data(api_client.list_collections_cases(env["account"]["id"], BK))


def setup_account_with_collections_case(assessed_amount_cents=3000,
                                        year_overrides=None,
                                        case_open_date="2026-08-12"):
    """Account whose assessment has aged past k days: case OPEN after the sweep.

    Returns dict(env..., case). Clock ends at case_open_date.
    """
    env = setup_account_with_assessment(assessed_amount_cents=assessed_amount_cents,
                                        year_overrides=year_overrides)
    cases = age_account_to_collections(env, sweep_date=case_open_date)
    env["case"] = cases[0]
    return env


def advance_case_to_bucket3(env, bucket3_date="2026-09-11"):
    """Advance the clock so the OPEN case ages to BUCKET_3 and re-sweep."""
    set_clock(bucket3_date)
    get_success_data(api_client.run_ops(env["year"]["id"], BK))
    return get_success_data(api_client.get_collections_case(
        env["account"]["id"], env["case"]["id"], BK))


def setup_written_off_account(assessed_amount_cents=3000, writeoff_user_id="bk-9",
                              year_overrides=None):
    """Account fully written off: posture WRITTEN_OFF, case WRITTEN_OFF.

    Clock ends at 2026-09-11 (case at BUCKET_3). Returns dict(env..., case).
    """
    env = setup_account_with_collections_case(
        assessed_amount_cents=assessed_amount_cents, year_overrides=year_overrides)
    advance_case_to_bucket3(env)
    case = get_success_data(api_client.write_off_case(
        env["account"]["id"], env["case"]["id"],
        {"amount_cents": assessed_amount_cents},
        make_bookkeeper_headers(writeoff_user_id)))
    env["case"] = case
    return env


# ---------------------------------------------------------------------------
# Tier 5: waiver flows
# ---------------------------------------------------------------------------

def create_program(env, **overrides):
    """Create a waiver program under env's year. Returns the program dict."""
    return get_success_data(api_client.create_waiver_program(
        env["year"]["id"], create_waiver_program_payload(**overrides), BK))


def submit_and_approve_application(account_id, program_id, submitter_user_id="fam-1",
                                   reviewer_user_id="bk-1"):
    """Family submits an application; Bookkeeper approves with the fresh OCC version."""
    app = get_success_data(api_client.create_waiver_application(
        account_id, {"waiver_program_id": program_id},
        make_family_headers(submitter_user_id)))
    a_v = current_account_version(account_id)
    approved = get_success_data(api_client.approve_waiver_application(
        account_id, app["id"], {"expected_account_version": a_v},
        make_bookkeeper_headers(reviewer_user_id)))
    return approved


def setup_approved_waiver_account(fee_amount=8000, waiver_pct_bp=5000, grade_level=10,
                                  enroll=True, year_overrides=None, program_overrides=None):
    """Account with an APPROVED waiver application, optionally already enrolled.

    When enroll=True the enrollment happens AFTER approval, so the enrollment-driven
    assessment carries the provisional stacking waiver.
    Returns dict(env..., program, application, [enrollment, assessment]).
    """
    env = setup_year_with_fee(fee_amount=fee_amount, year_overrides=year_overrides,
                              with_offering=enroll)
    student, account = add_student_with_account(env["year"]["id"], grade_level=grade_level)
    env.update({"student": student, "account": account})
    program = create_program(env, **(program_overrides or {"waiver_pct_bp": waiver_pct_bp}))
    env["program"] = program
    env["application"] = submit_and_approve_application(account["id"], program["id"])
    if enroll:
        enrollment = get_success_data(api_client.create_enrollment(
            account["id"], {"offering_id": env["offering"]["id"]}, BK))
        assessment = get_success_data(api_client.list_fee_assessments(account["id"], BK))[0]
        env.update({"enrollment": enrollment, "assessment": assessment})
    return env
