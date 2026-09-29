"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its own
preconditions from scratch using only the endpoints the PRD declares.  They are
plain functions (not pytest fixtures) so a single test can build several
independent worlds — two terms, two students, three funding sources — and still
control the exact order of the calls.

All helpers return the ``data`` object of the response they made, and they use
the lenient success reader so that a setup failure surfaces as a readable
KeyError on the caller's own assertion rather than a status-code assertion in
the middle of the setup chain.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    academic_term_payload,
    allocation_entry,
    appointment_payload,
    department_payload,
    funding_plan_payload,
    funding_source_payload,
    pay_period_payload,
    renewal_decision_payload,
    stipend_policy_payload,
    student_payload,
    tax_assessment_payload,
)
from .test_users import (
    DEPT_ADMIN,
    FACULTY,
    GRANT_ACCOUNTANT,
    GS_ADMIN,
)

# --------------------------------------------------------------------------- #
# Reusable pay-period calendars, expressed as
# (sequence_no, period_start, period_end_exclusive, pay_date).
# --------------------------------------------------------------------------- #

#: Four whole calendar months covering 2026-09-01 through 2026-12-31.
MONTHLY_PERIODS_AUTUMN_2026 = [
    (1, "2026-09-01", "2026-10-01", "2026-10-05"),
    (2, "2026-10-01", "2026-11-01", "2026-11-05"),
    (3, "2026-11-01", "2026-12-01", "2026-12-05"),
    (4, "2026-12-01", "2027-01-01", "2027-01-05"),
]

#: Four whole calendar months covering 2026-05-01 through 2026-08-31.
MONTHLY_PERIODS_SUMMER_2026 = [
    (1, "2026-05-01", "2026-06-01", "2026-06-05"),
    (2, "2026-06-01", "2026-07-01", "2026-07-05"),
    (3, "2026-07-01", "2026-08-01", "2026-08-05"),
    (4, "2026-08-01", "2026-09-01", "2026-09-05"),
]

#: One period spanning the whole 2026-09-01..2026-12-31 term.
SINGLE_PERIOD_AUTUMN_2026 = [(1, "2026-09-01", "2027-01-01", "2027-01-05")]

#: One period spanning a single September.
SINGLE_PERIOD_SEPTEMBER_2026 = [(1, "2026-09-01", "2026-10-01", "2026-10-05")]

#: The first two whole months of the autumn calendar.
MONTHLY_PERIODS_SEP_OCT_2026 = MONTHLY_PERIODS_AUTUMN_2026[:2]


# --------------------------------------------------------------------------- #
# Single-collection creators
# --------------------------------------------------------------------------- #

def make_department(headers=GS_ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_department(department_payload(**overrides), headers)
    )


def make_term(headers=GS_ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_academic_term(academic_term_payload(**overrides), headers)
    )


def make_policy(term_id: str, headers=GS_ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_stipend_policy(
            stipend_policy_payload(term_id, **overrides), headers
        )
    )


def make_pay_period(term_id: str, sequence_no: int, period_start: str,
                    period_end_exclusive: str, pay_date: str,
                    headers=GS_ADMIN) -> dict:
    return get_success_data(
        api_client.create_pay_period(
            pay_period_payload(
                term_id, sequence_no, period_start, period_end_exclusive, pay_date
            ),
            headers,
        )
    )


def make_pay_periods(term_id: str, periods, headers=GS_ADMIN) -> list:
    """``periods`` is an iterable of (sequence_no, start, end_exclusive, pay_date)."""
    return [
        make_pay_period(term_id, seq, start, end, pay_date, headers)
        for seq, start, end, pay_date in periods
    ]


def open_term(term_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(api_client.open_academic_term(term_id, headers))


def lock_term_payroll(term_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(api_client.lock_payroll(term_id, headers))


def close_term(term_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(api_client.close_academic_term(term_id, headers))


def make_student(headers=GS_ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_student(student_payload(**overrides), headers)
    )


def make_funding_source(department_id: str, headers=GRANT_ACCOUNTANT,
                        **overrides) -> dict:
    return get_success_data(
        api_client.create_funding_source(
            funding_source_payload(department_id, **overrides), headers
        )
    )


def suspend_source(source_id: str, reason: str, headers=GRANT_ACCOUNTANT) -> dict:
    return get_success_data(
        api_client.suspend_funding_source(source_id, {"reason": reason}, headers)
    )


def make_appointment(student_id: str, department_id: str, term_id: str,
                     headers=DEPT_ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_appointment(
            appointment_payload(student_id, department_id, term_id, **overrides),
            headers,
        )
    )


def set_clock(instant: str, headers=GS_ADMIN) -> dict:
    """Reposition the logical clock, which starts at 2026-08-01T00:00:00Z."""
    return get_success_data(api_client.set_current_utc(instant, headers))


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #

def read_appointment(appointment_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(api_client.get_appointment(appointment_id, headers))


def read_student(student_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(api_client.get_student(student_id, headers))


def read_term(term_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(api_client.get_academic_term(term_id, headers))


def read_source(source_id: str, headers=GRANT_ACCOUNTANT) -> dict:
    return get_success_data(api_client.get_funding_source(source_id, headers))


def read_allocation(allocation_id: str, headers=GRANT_ACCOUNTANT) -> dict:
    return get_success_data(api_client.get_funding_allocation(allocation_id, headers))


def read_disbursement(disbursement_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(
        api_client.get_stipend_disbursement(disbursement_id, headers)
    )


def read_renewal_decision(decision_id: str, headers=DEPT_ADMIN) -> dict:
    return get_success_data(api_client.get_renewal_decision(decision_id, headers))


def read_assessment(assessment_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(api_client.get_tax_assessment(assessment_id, headers))


def allocations_of(appointment_id: str, status: str = None,
                   headers=GRANT_ACCOUNTANT) -> list:
    """Allocations of one appointment, ordered by plan_sequence ascending."""
    params = {"appointment_id": appointment_id, "limit": 10, "offset": 0}
    if status is not None:
        params["status"] = status
    return get_success_data(api_client.list_funding_allocations(headers, params))


def disbursements_of(appointment_id: str, status: str = None,
                     headers=GS_ADMIN) -> list:
    """Disbursements of one appointment, ordered by pay period sequence_no."""
    params = {"appointment_id": appointment_id, "limit": 10, "offset": 0}
    if status is not None:
        params["status"] = status
    return get_success_data(api_client.list_stipend_disbursements(headers, params))


# --------------------------------------------------------------------------- #
# Funding plan and lifecycle drivers
# --------------------------------------------------------------------------- #

def set_funding_plan(appointment_id: str, allocations: list, headers=DEPT_ADMIN,
                     expected_version: int = None) -> dict:
    """Replace an appointment's funding plan, quoting its current version.

    ``allocations`` is a list of (funding_source_id, share_pct) pairs or of
    (funding_source_id, share_pct, is_cost_share) triples.
    """
    if expected_version is None:
        expected_version = read_appointment(appointment_id, headers)["version"]
    entries = [allocation_entry(*entry) for entry in allocations]
    return get_success_data(
        api_client.replace_funding_plan(
            appointment_id, funding_plan_payload(entries, expected_version), headers
        )
    )


def fund_wholly_from(appointment_id: str, source_id: str,
                     headers=DEPT_ADMIN) -> dict:
    """The common single-source plan: one allocation at 100.00 percent."""
    return set_funding_plan(
        appointment_id, [(source_id, 100.00, False)], headers
    )


def submit(appointment_id: str, headers=DEPT_ADMIN) -> dict:
    return get_success_data(api_client.submit_appointment(appointment_id, headers))


def verify_funding(appointment_id: str, headers=GRANT_ACCOUNTANT) -> dict:
    return get_success_data(api_client.verify_funding(appointment_id, headers))


def approve(appointment_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(api_client.approve_appointment(appointment_id, headers))


def activate(appointment_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(api_client.activate_appointment(appointment_id, headers))


def schedule_payroll(appointment_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(api_client.schedule_payroll(appointment_id, headers))


def pay(disbursement_id: str, headers=GS_ADMIN) -> dict:
    return get_success_data(
        api_client.pay_stipend_disbursement(disbursement_id, headers)
    )


#: Ordered lifecycle drive steps, keyed by the state each step lands in.
_DRIVE_ORDER = ["SUBMITTED", "FUNDING_VERIFIED", "APPROVED", "ACTIVE",
                "PAYROLL_SCHEDULED"]


def drive_appointment(appointment_id: str, target: str,
                      approver=GS_ADMIN) -> dict:
    """Walk an appointment forward through its approval axis.

    ``target`` is one of SUBMITTED, FUNDING_VERIFIED, APPROVED, ACTIVE or
    PAYROLL_SCHEDULED (the last one also runs schedule-payroll).  A funding plan
    must already be attached.
    """
    assert target in _DRIVE_ORDER, f"unknown drive target {target}"
    steps = _DRIVE_ORDER[: _DRIVE_ORDER.index(target) + 1]
    data = None
    for step in steps:
        if step == "SUBMITTED":
            data = submit(appointment_id)
        elif step == "FUNDING_VERIFIED":
            data = verify_funding(appointment_id)
        elif step == "APPROVED":
            data = approve(appointment_id, approver)
        elif step == "ACTIVE":
            data = activate(appointment_id, approver)
        else:
            data = schedule_payroll(appointment_id, approver)
    return data


# --------------------------------------------------------------------------- #
# Composite worlds
# --------------------------------------------------------------------------- #

def build_term_frame(term: dict = None, policy: dict = None,
                     extra_policies=(), pay_periods=MONTHLY_PERIODS_AUTUMN_2026,
                     department: dict = None, open_the_term: bool = True) -> dict:
    """Department + term + stipend policy + pay period calendar, optionally open.

    ``term``, ``policy`` and ``department`` are override dictionaries layered
    over the payload factories.  ``extra_policies`` is an iterable of further
    policy override dictionaries for the same term.
    """
    dept = make_department(**(department or {}))
    term_data = make_term(**(term or {}))
    term_id = term_data["id"]
    policies = [make_policy(term_id, **(policy or {}))]
    for extra in extra_policies:
        policies.append(make_policy(term_id, **extra))
    periods = make_pay_periods(term_id, pay_periods)
    if open_the_term:
        term_data = open_term(term_id)
    return {
        "department": dept,
        "department_id": dept["id"],
        "term": term_data,
        "term_id": term_id,
        "policy": policies[0],
        "policies": policies,
        "pay_periods": periods,
    }


def build_funded_appointment(term: dict = None, policy: dict = None,
                             pay_periods=MONTHLY_PERIODS_AUTUMN_2026,
                             department: dict = None, student: dict = None,
                             source: dict = None, appointment: dict = None,
                             advance_to: str = None,
                             lock_payroll_after: bool = False,
                             approver=GS_ADMIN) -> dict:
    """The dominant chain: a term frame, one student, one grant source and one
    appointment funded 100.00 percent from that source.

    ``advance_to`` optionally drives the appointment forward (see
    :func:`drive_appointment`); ``lock_payroll_after`` then moves the term to
    PAYROLL_LOCKED, which locks every pay period.
    """
    frame = build_term_frame(
        term=term, policy=policy, pay_periods=pay_periods,
        department=department, open_the_term=True,
    )
    stu = make_student(**(student or {}))
    src = make_funding_source(frame["department_id"], **(source or {}))
    appt = make_appointment(
        stu["id"], frame["department_id"], frame["term_id"], **(appointment or {})
    )
    fund_wholly_from(appt["id"], src["id"])
    if advance_to is not None:
        appt = drive_appointment(appt["id"], advance_to, approver=approver)
    if lock_payroll_after:
        lock_term_payroll(frame["term_id"])
    frame.update({
        "student": stu,
        "student_id": stu["id"],
        "source": src,
        "source_id": src["id"],
        "appointment": appt,
        "appointment_id": appt["id"],
    })
    return frame


def build_renewal_review(appointment_id: str, certify: bool = False,
                         creator=DEPT_ADMIN, certifier=FACULTY) -> dict:
    """A RenewalDecision on an ACTIVE appointment, optionally SAP-certified."""
    decision = get_success_data(
        api_client.create_renewal_decision(
            renewal_decision_payload(appointment_id), creator
        )
    )
    if certify:
        decision = get_success_data(
            api_client.certify_progress(decision["id"], certifier)
        )
    return decision


def build_assessment(student_id: str, term_id: str, finalize: bool = False,
                     headers=GS_ADMIN) -> dict:
    """A TaxAssessment quoting the student's freshly-read version."""
    student_version = read_student(student_id, headers)["version"]
    assessment = get_success_data(
        api_client.create_tax_assessment(
            tax_assessment_payload(student_id, term_id, student_version), headers
        )
    )
    if finalize:
        assessment = get_success_data(
            api_client.finalize_tax_assessment(assessment["id"], headers)
        )
    return assessment
