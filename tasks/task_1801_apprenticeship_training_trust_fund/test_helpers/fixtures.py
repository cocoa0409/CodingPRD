"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server, so nothing carries over).
Lenient get_success_data is used internally so setup failures surface as
clear "Setup failed" errors instead of confusing assertion failures.

Identity threading (PRD §2.1): EmployerRep calls that are ownership-gated
(report create/submit/resubmit/remit) always thread the acting employer's id
through make_employer_rep_headers; pay-claim creation threads the class's
instructor_user_id through make_instructor_headers.
"""
from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    approve_allocation_payload,
    complete_class_payload,
    create_apprentice_payload,
    create_class_payload,
    create_contribution_report_payload,
    create_employer_payload,
    create_enrollment_payload,
    create_equipment_purchase_payload,
    create_funding_allocation_payload,
    create_pay_claim_payload,
    create_trust_fund_payload,
    record_decision_payload,
    remit_payload,
    report_line,
    submit_registration_payload,
)
from .test_users import (
    TEST_USERS,
    make_committee_member_headers,
    make_employer_rep_headers,
    make_instructor_headers,
    make_trust_admin_headers,
)

ADMIN = TEST_USERS["trust_admin_headers"]
ADMIN2 = TEST_USERS["trust_admin2_headers"]
CM1 = TEST_USERS["committee_member_headers"]
CM2 = TEST_USERS["committee_member2_headers"]

DEFAULT_RATE = TEST_DEFAULTS["EMPLOYER_RATE_CENTS_PER_HOUR"]
DEFAULT_BASE_RATE = TEST_DEFAULTS["JOURNEYMAN_BASE_RATE_CENTS"]
DEFAULT_INSTRUCTOR_RATE = TEST_DEFAULTS["INSTRUCTOR_RATE_CENTS_PER_HOUR"]


# ---------------------------------------------------------------------------
# Trust fund / logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Set the logical clock (PRD §2.11)."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    get_success_data(resp)


def create_fund(name: str = TEST_DEFAULTS["FUND_NAME"]) -> dict:
    resp = api_client.create_trust_fund(create_trust_fund_payload(name=name), ADMIN)
    return get_success_data(resp)


def get_fund(fund_id: str) -> dict:
    return get_success_data(api_client.get_trust_fund(fund_id, ADMIN))


def run_ops(fund_id: str) -> dict:
    return get_success_data(api_client.run_ops(fund_id, ADMIN))


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------

def create_employer(fund_id: str, rate: int = DEFAULT_RATE,
                    legal_name: str = TEST_DEFAULTS["EMPLOYER_LEGAL_NAME"]) -> dict:
    resp = api_client.create_employer(
        create_employer_payload(fund_id, legal_name=legal_name,
                                agreement_rate_cents_per_hour=rate),
        ADMIN,
    )
    return get_success_data(resp)


def get_employer(employer_id: str) -> dict:
    return get_success_data(api_client.get_employer(employer_id, ADMIN))


def update_employer_rate(employer_id: str, new_rate: int) -> dict:
    resp = api_client.update_employer(
        employer_id, {"agreement_rate_cents_per_hour": new_rate}, ADMIN,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Apprentices (registration + indenture lifecycle)
# ---------------------------------------------------------------------------

def create_apprentice(fund_id: str, employer_id: str,
                      full_name: str = TEST_DEFAULTS["APPRENTICE_FULL_NAME"],
                      trade: str = TEST_DEFAULTS["APPRENTICE_TRADE"],
                      base_rate: int = DEFAULT_BASE_RATE) -> dict:
    resp = api_client.create_apprentice(
        create_apprentice_payload(
            fund_id, employer_id, full_name=full_name, trade=trade,
            journeyman_base_rate_cents=base_rate,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def get_apprentice(apprentice_id: str) -> dict:
    return get_success_data(api_client.get_apprentice(apprentice_id, ADMIN))


def submit_registration(apprentice_id: str, agency: str = "STATE") -> dict:
    resp = api_client.submit_registration(
        apprentice_id, submit_registration_payload(agency), ADMIN,
    )
    return get_success_data(resp)


def record_registration_decision(apprentice_id: str, outcome: str) -> dict:
    resp = api_client.record_registration_decision(
        apprentice_id, record_decision_payload(outcome), ADMIN,
    )
    return get_success_data(resp)


def indenture_apprentice(apprentice_id: str) -> dict:
    return get_success_data(api_client.indenture_apprentice(apprentice_id, ADMIN))


def create_registered_apprentice(fund_id: str, employer_id: str,
                                 agency: str = "STATE", **kwargs) -> dict:
    """Apprentice at APPLICANT with registration REGISTERED."""
    apprentice = create_apprentice(fund_id, employer_id, **kwargs)
    submit_registration(apprentice["id"], agency)
    record_registration_decision(apprentice["id"], "REGISTERED")
    return get_apprentice(apprentice["id"])


def create_indentured_apprentice(fund_id: str, employer_id: str,
                                 **kwargs) -> dict:
    """Apprentice walked to INDENTURED with registration REGISTERED."""
    apprentice = create_registered_apprentice(fund_id, employer_id, **kwargs)
    indenture_apprentice(apprentice["id"])
    return get_apprentice(apprentice["id"])


def setup_fund_employer_apprentice(
    rate: int = DEFAULT_RATE,
    base_rate: int = DEFAULT_BASE_RATE,
    clock: Optional[str] = "2026-07-01T00:00:00Z",
    indentured: bool = True,
) -> Tuple[dict, dict, dict]:
    """Fund + employer + one apprentice (INDENTURED/REGISTERED by default).

    Returns (fund, employer, apprentice).
    """
    if clock is not None:
        set_clock(clock)
    fund = create_fund()
    employer = create_employer(fund["id"], rate=rate)
    if indentured:
        apprentice = create_indentured_apprentice(
            fund["id"], employer["id"], base_rate=base_rate,
        )
    else:
        apprentice = create_apprentice(
            fund["id"], employer["id"], base_rate=base_rate,
        )
    return fund, employer, apprentice


# ---------------------------------------------------------------------------
# Contribution reports
# ---------------------------------------------------------------------------

def create_report(employer: dict, period_year: int, period_month: int,
                  lines: List[dict]) -> dict:
    """Create a DRAFT contribution report as the owning EmployerRep."""
    resp = api_client.create_contribution_report(
        create_contribution_report_payload(
            employer["id"], period_year, period_month, lines,
        ),
        make_employer_rep_headers(employer["id"]),
    )
    return get_success_data(resp)


def get_report(report_id: str) -> dict:
    return get_success_data(api_client.get_contribution_report(report_id, ADMIN))


def submit_report(employer: dict, report_id: str) -> dict:
    resp = api_client.submit_report(
        report_id, make_employer_rep_headers(employer["id"]),
    )
    return get_success_data(resp)


def flag_report(report_id: str, reason: str = "audit review") -> dict:
    resp = api_client.flag_report(report_id, {"reason": reason}, ADMIN)
    return get_success_data(resp)


def resubmit_report(employer: dict, report_id: str, lines: List[dict]) -> dict:
    resp = api_client.resubmit_report(
        report_id, {"lines": lines}, make_employer_rep_headers(employer["id"]),
    )
    return get_success_data(resp)


def remit_report(employer: dict, report_id: str, amount_tendered_cents: int) -> dict:
    resp = api_client.remit_report(
        report_id, remit_payload(amount_tendered_cents),
        make_employer_rep_headers(employer["id"]),
    )
    return get_success_data(resp)


def setup_submitted_report(
    hours: float = 100,
    rate: int = DEFAULT_RATE,
    base_rate: int = DEFAULT_BASE_RATE,
    period: Tuple[int, int] = (2026, 6),
    clock: Optional[str] = "2026-07-01T00:00:00Z",
) -> Tuple[dict, dict, dict, dict]:
    """Fund + employer + INDENTURED apprentice + one SUBMITTED report.

    Returns (fund, employer, apprentice, report). The report carries a single
    line of `hours` for the apprentice.
    """
    fund, employer, apprentice = setup_fund_employer_apprentice(
        rate=rate, base_rate=base_rate, clock=clock,
    )
    report = create_report(
        employer, period[0], period[1], [report_line(apprentice["id"], hours)],
    )
    report = submit_report(employer, report["id"])
    return fund, employer, apprentice, report


def setup_paid_report(
    hours: float = 1000,
    rate: int = DEFAULT_RATE,
    base_rate: int = DEFAULT_BASE_RATE,
    period: Tuple[int, int] = (2026, 3),
    clock: Optional[str] = "2026-07-01T00:00:00Z",
) -> Tuple[dict, dict, dict, dict]:
    """Fund with one fully PAID report: contributions_received == hours * rate
    (per-line rounding is exact for whole hours)."""
    fund, employer, apprentice, report = setup_submitted_report(
        hours=hours, rate=rate, base_rate=base_rate, period=period, clock=clock,
    )
    due = report["contribution_due_cents"]
    report = remit_report(employer, report["id"], due)
    return fund, employer, apprentice, report


def setup_delinquent_employer(
    fund: dict,
    legal_name: str = "Beacon Mechanical",
    period: Tuple[int, int] = (2026, 5),
    overdue_to: str = "2026-06-16T00:00:00Z",
    draft: bool = True,
    hours: float = 10,
    rate: int = DEFAULT_RATE,
) -> Tuple[dict, dict]:
    """Add a second employer whose overdue report flips it DELINQUENT via an
    ops run (PRD §3.3), pulling the fund posture to COMPLIANCE_HOLD.

    Returns (employer, report). Caller must have the clock set before the
    report's period start and must tolerate the clock moving to `overdue_to`.
    """
    employer = create_employer(fund["id"], rate=rate, legal_name=legal_name)
    apprentice = create_apprentice(fund["id"], employer["id"],
                                   full_name="Late Apprentice", trade="HVAC",
                                   base_rate=3800)
    report = create_report(
        employer, period[0], period[1], [report_line(apprentice["id"], hours)],
    )
    if not draft:
        # A submitted overdue report requires an hour-eligible apprentice.
        submit_registration(apprentice["id"], "STATE")
        record_registration_decision(apprentice["id"], "REGISTERED")
        indenture_apprentice(apprentice["id"])
        report = submit_report(employer, report["id"])
    set_clock(overdue_to)
    run_ops(fund["id"])
    return get_employer(employer["id"]), get_report(report["id"])


# ---------------------------------------------------------------------------
# Training classes / enrollments
# ---------------------------------------------------------------------------

def create_training_class(
    fund_id: str,
    course_code: str = "CN-101",
    instructor_user_id: str = TEST_DEFAULTS["INSTRUCTOR_USER_ID"],
    instructor_name: str = TEST_DEFAULTS["INSTRUCTOR_NAME"],
    rate: int = DEFAULT_INSTRUCTOR_RATE,
    facility: str = TEST_DEFAULTS["FACILITY"],
    rti_credit_value: int = TEST_DEFAULTS["RTI_CREDIT_VALUE"],
    capacity: int = TEST_DEFAULTS["CLASS_CAPACITY"],
    start_minute: int = TEST_DEFAULTS["CLASS_START_MINUTE"],
    end_minute: int = TEST_DEFAULTS["CLASS_END_MINUTE"],
) -> dict:
    resp = api_client.create_class(
        create_class_payload(
            fund_id,
            course_code=course_code,
            instructor_user_id=instructor_user_id,
            instructor_name=instructor_name,
            instructor_rate_cents_per_hour=rate,
            facility=facility,
            rti_credit_value=rti_credit_value,
            capacity=capacity,
            start_minute=start_minute,
            end_minute=end_minute,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def get_class(class_id: str) -> dict:
    return get_success_data(api_client.get_class(class_id, ADMIN))


def enroll(class_id: str, apprentice_id: str) -> dict:
    resp = api_client.create_enrollment(
        create_enrollment_payload(class_id, apprentice_id), ADMIN,
    )
    return get_success_data(resp)


def get_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, ADMIN))


def complete_class(class_id: str, attended_enrollment_ids: List[str]) -> dict:
    resp = api_client.complete_class(
        class_id, complete_class_payload(attended_enrollment_ids), ADMIN,
    )
    return get_success_data(resp)


def setup_completed_class(
    fund_id: Optional[str] = None,
    course_code: str = "CN-101",
    instructor_user_id: str = TEST_DEFAULTS["INSTRUCTOR_USER_ID"],
    rate: int = DEFAULT_INSTRUCTOR_RATE,
    facility: str = TEST_DEFAULTS["FACILITY"],
    start_minute: int = TEST_DEFAULTS["CLASS_START_MINUTE"],
    end_minute: int = TEST_DEFAULTS["CLASS_END_MINUTE"],
) -> dict:
    """A COMPLETED class with an empty attendance list. Creates its own fund
    when fund_id is not supplied."""
    if fund_id is None:
        fund_id = create_fund()["id"]
    klass = create_training_class(
        fund_id,
        course_code=course_code,
        instructor_user_id=instructor_user_id,
        rate=rate,
        facility=facility,
        start_minute=start_minute,
        end_minute=end_minute,
    )
    return complete_class(class_id=klass["id"], attended_enrollment_ids=[])


def award_rti_credits(apprentice: dict, fund_id: str, credits: int,
                      course_code: str = "RTI-CRED",
                      instructor_user_id: str = "inst-credit",
                      facility: str = "SHOP-R",
                      start_minute: int = 1000,
                      end_minute: int = 1120) -> Tuple[dict, dict]:
    """Award `credits` RTI credits to an apprentice by completing a class the
    apprentice attended. Returns (completed_class, enrollment)."""
    klass = create_training_class(
        fund_id,
        course_code=course_code,
        instructor_user_id=instructor_user_id,
        facility=facility,
        rti_credit_value=credits,
        start_minute=start_minute,
        end_minute=end_minute,
    )
    enrollment = enroll(klass["id"], apprentice["id"])
    complete_class(klass["id"], [enrollment["id"]])
    return get_class(klass["id"]), get_enrollment(enrollment["id"])


def setup_apprentice_with_hours_and_credits(
    hours: float,
    credits: int,
    rate: int = DEFAULT_RATE,
    base_rate: int = DEFAULT_BASE_RATE,
    clock: Optional[str] = "2026-07-01T00:00:00Z",
) -> Tuple[dict, dict, dict]:
    """INDENTURED + REGISTERED apprentice with `hours` OJT hours credited by a
    submitted report and `credits` RTI credits awarded by a completed class.
    Returns (fund, employer, apprentice)."""
    fund, employer, apprentice = setup_fund_employer_apprentice(
        rate=rate, base_rate=base_rate, clock=clock,
    )
    if credits:
        award_rti_credits(apprentice, fund["id"], credits)
    if hours:
        report = create_report(
            employer, 2026, 6, [report_line(apprentice["id"], hours)],
        )
        submit_report(employer, report["id"])
    return fund, employer, get_apprentice(apprentice["id"])


# ---------------------------------------------------------------------------
# Instructor pay claims
# ---------------------------------------------------------------------------

def create_pay_claim(klass: dict, pay_basis: str = "SCHEDULED",
                     actual_minutes: Optional[int] = None) -> dict:
    """File a pay claim as the class's own instructor (PRD §3.5)."""
    resp = api_client.create_pay_claim(
        create_pay_claim_payload(klass["id"], pay_basis, actual_minutes),
        make_instructor_headers(klass["instructor_user_id"]),
    )
    return get_success_data(resp)


def get_pay_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_pay_claim(claim_id, ADMIN))


def approve_claim(claim_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.approve_pay_claim(claim_id, headers or CM1),
    )


def setup_approved_claim(
    start_minute: int = 600,
    end_minute: int = 720,
    rate: int = DEFAULT_INSTRUCTOR_RATE,
    pay_basis: str = "SCHEDULED",
    actual_minutes: Optional[int] = None,
    instructor_user_id: str = TEST_DEFAULTS["INSTRUCTOR_USER_ID"],
) -> Tuple[dict, dict]:
    """Fund + completed class + pay claim walked to APPROVED.

    Returns (fund, claim).
    """
    fund = create_fund()
    klass = setup_completed_class(
        fund_id=fund["id"],
        instructor_user_id=instructor_user_id,
        rate=rate,
        start_minute=start_minute,
        end_minute=end_minute,
    )
    claim = create_pay_claim(klass, pay_basis=pay_basis,
                             actual_minutes=actual_minutes)
    claim = approve_claim(claim["id"])
    return get_fund(fund["id"]), claim


# ---------------------------------------------------------------------------
# Funding allocations / equipment purchases
# ---------------------------------------------------------------------------

def propose_allocation(fund_id: str, amount_cents: int,
                       category: str = "EQUIPMENT", fiscal_year: int = 2026,
                       proposer_headers: Optional[Dict] = None) -> dict:
    resp = api_client.create_funding_allocation(
        create_funding_allocation_payload(
            fund_id, amount_cents, category=category, fiscal_year=fiscal_year,
        ),
        proposer_headers or ADMIN,
    )
    return get_success_data(resp)


def get_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_funding_allocation(allocation_id, ADMIN))


def approve_allocation(allocation_id: str,
                       approver_headers: Optional[Dict] = None,
                       expected_trust_fund_version: Optional[int] = None,
                       fund_id: Optional[str] = None) -> dict:
    """Approve a PROPOSED allocation, reading the current fund version first
    unless an explicit expected_trust_fund_version is supplied (PRD §2.9)."""
    if expected_trust_fund_version is None:
        if fund_id is None:
            fund_id = get_allocation(allocation_id)["trust_fund_id"]
        expected_trust_fund_version = get_fund(fund_id)["version"]
    resp = api_client.approve_funding_allocation(
        allocation_id,
        approve_allocation_payload(expected_trust_fund_version),
        approver_headers or CM1,
    )
    return get_success_data(resp)


def setup_active_allocation(
    amount_cents: int = 500000,
    funded_hours: float = 1000,
    rate: int = DEFAULT_RATE,
    proposer_user_id: str = "admin-1",
    approver_headers: Optional[Dict] = None,
) -> Tuple[dict, dict, dict]:
    """Funded fund (one PAID report of funded_hours at rate) plus an ACTIVE
    allocation of amount_cents. Returns (fund, employer, allocation)."""
    fund, employer, _apprentice, _report = setup_paid_report(
        hours=funded_hours, rate=rate,
    )
    allocation = propose_allocation(
        fund["id"], amount_cents,
        proposer_headers=make_trust_admin_headers(proposer_user_id),
    )
    allocation = approve_allocation(
        allocation["id"], approver_headers=approver_headers or CM1,
    )
    return get_fund(fund["id"]), employer, allocation


def create_purchase(allocation_id: str, amount_cents: int,
                    description: str = "Training equipment",
                    requester_headers: Optional[Dict] = None) -> dict:
    resp = api_client.create_equipment_purchase(
        create_equipment_purchase_payload(
            allocation_id, amount_cents, description=description,
        ),
        requester_headers or ADMIN,
    )
    return get_success_data(resp)


def get_purchase(purchase_id: str) -> dict:
    return get_success_data(api_client.get_equipment_purchase(purchase_id, ADMIN))


def approve_purchase(purchase_id: str,
                     approver_headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.approve_equipment_purchase(purchase_id, approver_headers or CM1),
    )
