"""Case closure, expungement eligibility, and the suspension-day ledger
compensation."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_student_ledger_invariant,
    create_expungement_request_payload, create_expungement_decision_payload,
    set_clock, create_offense_code_with_bands, create_student, create_case,
    make_confirmed_case, close_case, setup_closed_case,
    make_parent_guardian_headers, make_district_admin_headers,
    TEST_USERS, ApiErrorId,
)

CLS = TEST_USERS["school_classifier_headers"]


def test_expungement_eligibility_730_day_boundary(api):
    """PRD §3.8: "the clock must have reached at least the day 730 days after
    `last_case_closed_at` — the two-year boundary is inclusive, so a request
    filed exactly 730 days after the last closure qualifies. Any shortfall is
    rejected with `ERR_EXPUNGEMENT_NOT_ELIGIBLE`."

    Design: Corner/calculations/expungement_eligibility_730_day_boundary
    """
    bundle = setup_closed_case(guardian_id="ge1", full_name="Stu Exp730")
    assert bundle["case"]["closed_at"] == "2026-05-13T00:00:00Z"

    # 729 days after the closure: one day short of the wait.
    set_clock("2028-05-11T00:00:00Z")
    res = api.create_expungement_request(
        create_expungement_request_payload(bundle["student"]["id"]),
        make_parent_guardian_headers("ge1"))
    validate_error(res, ApiErrorId.ERR_EXPUNGEMENT_NOT_ELIGIBLE,
                   expected_status=409)

    # Exactly 730 days (spanning the 2028 leap day): inclusive boundary.
    set_clock("2028-05-12T00:00:00Z")
    accepted = validate_success(api.create_expungement_request(
        create_expungement_request_payload(bundle["student"]["id"]),
        make_parent_guardian_headers("ge1")), 201)
    assert accepted["status"] == "SUBMITTED"


def test_expungement_with_open_case_returns_409(api):
    """PRD §3.8: "Eligibility is strict and threefold: the student must have
    at least one case in `CLOSED` status, every case of the student must stand
    `CLOSED` or `EXPUNGED`, and the clock must have reached at least the day
    730 days after `last_case_closed_at` ... Any shortfall is rejected with
    `ERR_EXPUNGEMENT_NOT_ELIGIBLE`."

    Design: Corner/validations/expungement_with_open_case_returns_409
    """
    bundle = setup_closed_case(guardian_id="ge2", full_name="Stu Open")
    # A second, non-terminal case: SUBMITTED is outside {CLOSED, EXPUNGED}.
    create_case(bundle["student"]["id"], "2026-05-14T08:00:00Z", "open one")
    set_clock("2028-06-01T00:00:00Z")  # wait satisfied; terminal-set is not
    res = api.create_expungement_request(
        create_expungement_request_payload(bundle["student"]["id"]),
        make_parent_guardian_headers("ge2"))
    validate_error(res, ApiErrorId.ERR_EXPUNGEMENT_NOT_ELIGIBLE,
                   expected_status=409)


# ─── Difficulty: ledger compensation invariant ────────

def _setup_two_confirmed_then_closed_cases(api):
    """Student (guardian g10) with case 1 confirmed at 4 days and closed, and
    case 2 confirmed at 2 days and closed: cumulative_suspension_days == 6,
    last_case_closed_at == 2026-05-27."""
    oc = create_offense_code_with_bands(bands=((1, 1, 3), (2, 2, 4)))
    student = create_student(full_name="Stu Ledg",
                             date_of_birth="2009-01-01T00:00:00Z",
                             grade_level=10, demographic_group="HISPANIC",
                             guardian_id="g10")
    case1 = make_confirmed_case(
        student["id"], oc["id"], incident_date="2026-05-04T08:00:00Z",
        sanction_days=4, override_justification="aggravated",
        work_clock="2026-05-04T09:00:00Z", confirm_clock="2026-05-11T00:00:00Z",
        description="case one")
    set_clock("2026-05-15T00:00:00Z")  # confirmed 05-11 + 4 days
    case1 = close_case(case1["id"])

    case2 = make_confirmed_case(
        student["id"], oc["id"], incident_date="2026-05-18T08:00:00Z",
        sanction_days=2, work_clock="2026-05-18T09:00:00Z",
        confirm_clock="2026-05-25T00:00:00Z", description="case two")
    set_clock("2026-05-27T00:00:00Z")  # confirmed 05-25 + 2 days
    case2 = close_case(case2["id"])
    return oc, student, case1, case2


def test_ledger_debits_two_confirms_before_expungement(api):
    """PRD §2.7: "Its value is defined, at any moment, as the sum of
    `sanction_days_final` over exactly the student's cases whose status is
    `CONFIRMED` or `CLOSED`. ... The ledger is debited at confirmation".
    PRD §3.4: "On success, `sanction_days_final` takes the proposed day count,
    `confirmed_at` is stamped at the clock, and the final days are debited
    into the student's `cumulative_suspension_days` ledger per §2.7."

    Design: Difficulty/compensating_invariant/suspension_day_ledger_confirm_then_expunge_restores_zero
    """
    oc, student, case1, case2 = _setup_two_confirmed_then_closed_cases(api)
    assert case1["status"] == "CLOSED" and case2["status"] == "CLOSED"
    assert case1["sanction_days_final"] == 4
    assert case2["sanction_days_final"] == 2

    before = validate_success(api.get_student(student["id"], CLS), 200)
    assert before["cumulative_suspension_days"] == 6, (
        f"4 + 2 debited by the two confirms, got "
        f"{before['cumulative_suspension_days']}")
    assert_student_ledger_invariant(before, [case1, case2])


def test_expungement_approval_restores_ledger_to_zero(api):
    """PRD §2.7: "confirming a case, then closing it, then approving an
    expungement restores the student's `cumulative_suspension_days` to
    precisely the value it held before the confirmation."
    PRD §3.8: "Approval cascades through the student's record: every `CLOSED`
    case of the student becomes `EXPUNGED`, and the student's
    `cumulative_suspension_days` is recomputed with the expunged rows
    excluded".

    Design: Difficulty/compensating_invariant/suspension_day_ledger_confirm_then_expunge_restores_zero
    """
    oc, student, case1, case2 = _setup_two_confirmed_then_closed_cases(api)
    # 731 days after the last closure (2026-05-27): the 730-day wait is met.
    set_clock("2028-05-27T00:00:00Z")
    request = validate_success(api.create_expungement_request(
        create_expungement_request_payload(student["id"]),
        make_parent_guardian_headers("g10")), 201)

    decided = validate_success(api.decide_expungement_request(
        request["id"],
        create_expungement_decision_payload("APPROVED",
                                            "statutory wait satisfied"),
        make_district_admin_headers("da_1")), 200)
    assert decided["status"] == "APPROVED"

    cases, meta = validate_paginated(
        api.list_cases(CLS, params={"student_id": student["id"]}))
    assert len(cases) == 2
    assert all(c["status"] == "EXPUNGED" for c in cases), (
        f"both CLOSED cases must become EXPUNGED, got "
        f"{[c['status'] for c in cases]}")

    after = validate_success(api.get_student(student["id"], CLS), 200)
    assert after["cumulative_suspension_days"] == 0, (
        "the compensating expunge restores the ledger to its pre-confirm "
        f"value 0, got {after['cumulative_suspension_days']}")
    assert_student_ledger_invariant(after, cases)
