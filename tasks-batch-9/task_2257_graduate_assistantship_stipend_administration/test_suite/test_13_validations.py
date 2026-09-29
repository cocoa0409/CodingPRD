"""Rejections, each one pinned to the check that the fixed ordering reaches first.

Every case here drives a request that must be refused, asserts the exact error
identifier and HTTP status the specification assigns to that check, and then
re-reads the rows involved to show the refusal left nothing behind.  Two cases
run the other way and assert that a value sitting exactly on a ceiling is
admitted.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    DEPARTMENT_ADMIN_USER_ID,
    DEPT_ADMIN,
    FACULTY,
    FACULTY_SUPERVISOR_USER_ID,
    GRAD_SCHOOL_ADMIN_USER_ID,
    GRANT_ACCOUNTANT,
    GS_ADMIN,
    SINGLE_PERIOD_AUTUMN_2026,
    academic_term_payload,
    allocations_of,
    api_client,
    appointment_payload,
    build_assessment,
    build_funded_appointment,
    build_renewal_review,
    build_term_frame,
    disbursements_of,
    funding_source_payload,
    fund_wholly_from,
    lock_term_payroll,
    make_appointment,
    make_funding_source,
    make_student,
    pay_period_payload,
    read_appointment,
    read_assessment,
    read_renewal_decision,
    read_source,
    read_student,
    set_clock,
    set_funding_plan,
    stipend_policy_payload,
    student_payload,
    tax_assessment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

_TEACHING_POLICY = {"assistantship_type": "TEACHING", "degree_level": "DOCTORAL"}
_ADMIN_POLICY = {"assistantship_type": "ADMINISTRATIVE", "degree_level": "DOCTORAL"}


# --------------------------------------------------------------------------- #
# The submission battery
# --------------------------------------------------------------------------- #


def test_four_broken_funding_plans_each_report_their_own_submission_error():
    """A missing plan, a short sum, a grant cost-share and a fellowship-paid class.

    PRD: "The appointment must have at least one allocation in `PROPOSED`; an
    empty plan is `ERR_FUNDING_ALLOCATION_MISSING`. The sum of `share_pct` over
    those `PROPOSED` allocations must equal exactly 100.00; anything else is
    `ERR_ALLOCATION_SHARES_INVALID`." PRD: "every allocation whose
    `is_cost_share` is true must reference a source whose `source_type` is
    `DEPARTMENTAL_BUDGET`, and a plan containing any cost-share allocation must
    also contain at least one allocation whose `is_cost_share` is false." PRD:
    "No allocation may reference a source whose `source_type` is `FELLOWSHIP`
    when the appointment's `assistantship_type` is `TEACHING`, because a
    fellowship may not purchase instructional service; violating that is
    `ERR_FELLOWSHIP_SERVICE_CONFLICT`."

    Design: Corner/validations/submit_referential_battery_rejected
    """
    frame = build_term_frame(
        extra_policies=[_TEACHING_POLICY],
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
    )
    grant_a = make_funding_source(frame["department_id"], source_code="NSF-A")
    grant_b = make_funding_source(frame["department_id"], source_code="NSF-B")
    fellowship = make_funding_source(
        frame["department_id"], source_code="FELL-C", source_type="FELLOWSHIP",
    )
    student = make_student(student_number="GS-1030")

    def _draft(**overrides):
        return make_appointment(
            student["id"], frame["department_id"], frame["term_id"],
            effort_pct=75, monthly_stipend_cents=300000, **overrides
        )

    no_plan = _draft()
    short_shares = _draft()
    set_funding_plan(short_shares["id"], [(grant_a["id"], 90.00, False)])
    grant_cost_share = _draft()
    set_funding_plan(grant_cost_share["id"], [
        (grant_a["id"], 50.00, True), (grant_b["id"], 50.00, False),
    ])
    fellowship_taught = _draft(assistantship_type="TEACHING")
    fund_wholly_from(fellowship_taught["id"], fellowship["id"])

    expected = [
        (no_plan, ApiErrorId.ERR_FUNDING_ALLOCATION_MISSING.value),
        (short_shares, ApiErrorId.ERR_ALLOCATION_SHARES_INVALID.value),
        (grant_cost_share, ApiErrorId.ERR_COST_SHARE_SOURCE_INVALID.value),
        (fellowship_taught, ApiErrorId.ERR_FELLOWSHIP_SERVICE_CONFLICT.value),
    ]
    for appointment, error_id in expected:
        body = validate_error(
            api_client.submit_appointment(appointment["id"], DEPT_ADMIN),
            error_id, 422,
        )
        assert body["error_id"] == error_id

    for appointment, _ in expected:
        rejected = read_appointment(appointment["id"])
        assert rejected["lifecycle_status"] == "DRAFT"
        assert rejected["total_stipend_cents"] == 0
        assert rejected["submitted_by_user_id"] is None

    assert read_student(student["id"])["total_effort_pct"] == 0, (
        "no submission succeeded, so the student carries no counted effort"
    )


def test_a_late_starting_grant_and_a_capped_grant_are_each_refused_at_submission():
    """The budget window must cover the whole window, and the cap binds per grant.

    PRD: "And every referenced source's budget window must cover the whole
    appointment window: the source's `budget_period_start` on or before the
    appointment's `start_date`, and the appointment's `end_date` on or before the
    source's `budget_period_end`, or `ERR_FUNDING_PERIOD_MISMATCH`." PRD: "The
    **grant effort cap** applies to each allocation whose source has
    `source_type` of `GRANT`: the effort that allocation draws from the grant is
    `effort_pct` multiplied by that allocation's `share_pct` divided by 100, and
    it must not exceed the source's `grant_effort_cap_pct`; exactly equal passes,
    above is `ERR_GRANT_EFFORT_CAP_EXCEEDED`."

    Design: Corner/validations/submit_temporal_and_grant_cap_battery_rejected
    """
    frame = build_term_frame(pay_periods=SINGLE_PERIOD_AUTUMN_2026)
    late_grant = make_funding_source(
        frame["department_id"], source_code="LATE-D",
        budget_period_start="2026-10-01", budget_period_end="2027-06-30",
    )
    capped_grant = make_funding_source(
        frame["department_id"], source_code="CAP-E", grant_effort_cap_pct=50,
    )
    student = make_student(student_number="GS-1031")

    late_funded = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=75, monthly_stipend_cents=300000,
    )
    fund_wholly_from(late_funded["id"], late_grant["id"])
    over_cap = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=75, monthly_stipend_cents=300000,
    )
    fund_wholly_from(over_cap["id"], capped_grant["id"])

    validate_error(
        api_client.submit_appointment(late_funded["id"], DEPT_ADMIN),
        ApiErrorId.ERR_FUNDING_PERIOD_MISMATCH.value, 422,
    )
    validate_error(
        api_client.submit_appointment(over_cap["id"], DEPT_ADMIN),
        ApiErrorId.ERR_GRANT_EFFORT_CAP_EXCEEDED.value, 422,
    )

    assert read_appointment(late_funded["id"])["lifecycle_status"] == "DRAFT"
    assert read_appointment(over_cap["id"])["lifecycle_status"] == "DRAFT"
    assert read_source(late_grant["id"])["committed_amount_cents"] == 0
    assert read_source(capped_grant["id"])["committed_amount_cents"] == 0


def test_creation_refuses_a_window_outside_the_term_and_a_missing_policy():
    """The two rules creation owns, each on its own draft attempt.

    PRD: "The appointment window must sit inside the term: the term's
    `term_start` must be on or before `start_date`, and `end_date` must be on or
    before the term's `term_end`, or the request is rejected with
    `ERR_APPOINTMENT_DATES_OUTSIDE_TERM`. And a governing policy must exist — the
    single stipend policy whose `term_id`, `assistantship_type` and
    `degree_level` equal the appointment's `term_id`, the appointment's
    `assistantship_type`, and the referenced student's `degree_level` — or the
    request is rejected with `ERR_STIPEND_POLICY_MISSING`."

    Design: Corner/validations/appointment_creation_battery_rejected
    """
    frame = build_term_frame(pay_periods=SINGLE_PERIOD_AUTUMN_2026)
    student = make_student(student_number="GS-1032")

    validate_error(
        api_client.create_appointment(appointment_payload(
            student["id"], frame["department_id"], frame["term_id"],
            start_date="2026-08-15",
        ), DEPT_ADMIN),
        ApiErrorId.ERR_APPOINTMENT_DATES_OUTSIDE_TERM.value, 422,
    )
    validate_error(
        api_client.create_appointment(appointment_payload(
            student["id"], frame["department_id"], frame["term_id"],
            assistantship_type="ADMINISTRATIVE",
        ), DEPT_ADMIN),
        ApiErrorId.ERR_STIPEND_POLICY_MISSING.value, 422,
    )

    _, meta = validate_paginated(api_client.list_appointments(
        GS_ADMIN, {"student_id": student["id"], "limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 0, "neither attempt created a row"


def test_teaching_and_administrative_at_once_is_a_dual_role_conflict():
    """The forbidden pair is refused even though the effort cap is not reached.

    PRD: "Then the **dual-role conflict**: taking the set of
    `assistantship_type` values over this appointment together with the student's
    counted appointments whose inclusive date windows intersect this one, that set
    must not contain both `TEACHING` and `ADMINISTRATIVE`; if it does, the
    submission is rejected with `ERR_DUAL_ROLE_CONFLICT`." PRD: "18.
    **Dual-role conflict** — `ERR_DUAL_ROLE_CONFLICT` (409)."

    Design: Corner/validations/dual_role_teaching_plus_administrative_overlap_rejected
    """
    frame = build_term_frame(
        policy=_TEACHING_POLICY, extra_policies=[_ADMIN_POLICY],
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
    )
    source = make_funding_source(frame["department_id"], source_code="NSF-A")
    student = make_student(student_number="GS-1033")

    teaching = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        assistantship_type="TEACHING", effort_pct=25,
        monthly_stipend_cents=100000,
    )
    fund_wholly_from(teaching["id"], source["id"])
    validate_success(api_client.submit_appointment(teaching["id"], DEPT_ADMIN))

    administrative = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        assistantship_type="ADMINISTRATIVE", effort_pct=25,
        monthly_stipend_cents=100000,
    )
    fund_wholly_from(administrative["id"], source["id"])

    body = validate_error(
        api_client.submit_appointment(administrative["id"], DEPT_ADMIN),
        ApiErrorId.ERR_DUAL_ROLE_CONFLICT.value, 409,
    )
    assert body["error_id"] != ApiErrorId.ERR_OVER_APPOINTMENT.value, (
        "a combined 50 percent sits well under the student's cap of 75"
    )

    assert read_appointment(administrative["id"])["lifecycle_status"] == "DRAFT"
    assert read_appointment(teaching["id"])["lifecycle_status"] == "SUBMITTED"
    assert read_student(student["id"])["total_effort_pct"] == 25


# --------------------------------------------------------------------------- #
# Verification, approval and payment
# --------------------------------------------------------------------------- #


def test_verifying_against_a_source_that_cannot_bear_the_charge_is_refused():
    """A grant authorised for less than the appointment costs fails sufficiency.

    PRD: "And each referenced source must be able to bear the charge: taking that
    source's `available_amount_cents` and subtracting the sum, over this
    appointment's allocations charged to that source, of `allocated_stipend_cents`
    plus `allocated_remission_cents`, the result must be at least 0; a negative
    result is `ERR_FUNDING_INSUFFICIENT`." PRD: "36. **Funding sufficiency** —
    `ERR_FUNDING_INSUFFICIENT` (422), guarding funding verification."

    Design: Corner/validations/verify_funding_with_insufficient_available_balance_rejected
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1034"},
        source={"source_code": "SMALL-F", "authorized_amount_cents": 100000},
        advance_to="SUBMITTED",
    )
    assert read_appointment(world["appointment_id"])["total_stipend_cents"] == 300000

    validate_error(
        api_client.verify_funding(world["appointment_id"], GRANT_ACCOUNTANT),
        ApiErrorId.ERR_FUNDING_INSUFFICIENT.value, 422,
    )

    assert read_appointment(world["appointment_id"])["lifecycle_status"] == "SUBMITTED"
    allocations = allocations_of(world["appointment_id"])
    assert len(allocations) == 1
    assert allocations[0]["status"] == "PROPOSED", (
        "a refused verification commits nothing"
    )
    source = read_source(world["source_id"])
    assert source["committed_amount_cents"] == 0
    assert source["available_amount_cents"] == 100000


def test_approving_a_student_on_probation_is_refused():
    """Approval demands standing of exactly SATISFACTORY, and PROBATION is not it.

    PRD: "Approval by a `GradSchoolAdmin` advances the appointment
    `FUNDING_VERIFIED → APPROVED`. It requires `FUNDING_VERIFIED`, requires the
    term to be `OPEN`, requires the student's `sap_status` to be exactly
    `SATISFACTORY` — anything else is `ERR_SAP_NOT_SATISFACTORY`". PRD: "15.
    **Satisfactory academic progress** — `ERR_SAP_NOT_SATISFACTORY` (422),
    guarding appointment approval and renewal certification."

    Design: Corner/validations/approve_with_probation_sap_status_rejected
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1035"},
        advance_to="FUNDING_VERIFIED",
    )
    downgraded = validate_success(api_client.patch_academic_progress(
        world["student_id"], {"sap_status": "PROBATION"}, FACULTY,
    ))
    assert downgraded["sap_status"] == "PROBATION"

    validate_error(
        api_client.approve_appointment(world["appointment_id"], GS_ADMIN),
        ApiErrorId.ERR_SAP_NOT_SATISFACTORY.value, 422,
    )

    appointment = read_appointment(world["appointment_id"])
    assert appointment["lifecycle_status"] == "FUNDING_VERIFIED"
    assert appointment["approved_by_user_id"] is None


def test_certifying_a_review_below_a_three_point_zero_average_is_refused():
    """The renewal certification reads the grade average as well as the standing.

    PRD: "The review must be in `DRAFT`, the student's `sap_status` must be
    exactly `SATISFACTORY`, and the student's `cumulative_gpa` must be at least
    3.00; either standing failure is `ERR_SAP_NOT_SATISFACTORY`."

    Design: Corner/validations/certify_progress_below_min_renewal_gpa_rejected
    """
    set_clock("2026-09-05T00:00:00Z")
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1036"},
        advance_to="ACTIVE",
    )
    review = build_renewal_review(world["appointment_id"])
    assert review["status"] == "DRAFT"

    validate_success(api_client.patch_academic_progress(
        world["student_id"], {"cumulative_gpa": 2.90}, FACULTY,
    ))

    validate_error(
        api_client.certify_progress(review["id"], FACULTY),
        ApiErrorId.ERR_SAP_NOT_SATISFACTORY.value, 422,
    )

    unchanged = read_renewal_decision(review["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["sap_certified"] is False
    assert unchanged["certified_by_user_id"] is None
    assert unchanged["certified_at"] is None

    student = read_student(world["student_id"])
    assert float(student["cumulative_gpa"]) == pytest.approx(2.90, abs=0.001)
    assert student["sap_status"] == "SATISFACTORY", (
        "the standing itself was never downgraded; only the average fell"
    )


def test_paying_a_disbursement_while_its_period_is_still_open_is_refused():
    """Payment waits for the payroll lock, and succeeds the moment it arrives.

    PRD: "The disbursement must be `SCHEDULED`
    (`ERR_INVALID_DISBURSEMENT_STATE`), its pay period's `status` must be exactly
    `LOCKED` — an `OPEN` or already-`CLOSED` period yields
    `ERR_PAY_PERIOD_NOT_LOCKED` — and the appointment's `payroll_status` must be
    `SCHEDULED` or `PARTIALLY_DISBURSED`, else `ERR_INVALID_APPOINTMENT_STATE`."
    PRD: "Locking sets `locked_at` to the current logical-clock instant and moves
    every pay period of the term still `OPEN` to `LOCKED`, which is exactly what
    makes disbursement payment possible."

    Design: Corner/validations/paying_a_disbursement_before_pay_period_lock_rejected
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1037"},
        advance_to="PAYROLL_SCHEDULED",
    )
    scheduled = disbursements_of(world["appointment_id"])
    assert len(scheduled) == 1
    disbursement_id = scheduled[0]["id"]

    validate_error(
        api_client.pay_stipend_disbursement(disbursement_id, GS_ADMIN),
        ApiErrorId.ERR_PAY_PERIOD_NOT_LOCKED.value, 409,
    )

    before = disbursements_of(world["appointment_id"])[0]
    assert before["status"] == "SCHEDULED"
    assert before["paid_at"] is None
    periods, _ = validate_paginated(api_client.list_term_pay_periods(
        world["term_id"], GS_ADMIN, {"limit": 10, "offset": 0},
    ))
    assert periods[0]["status"] == "OPEN"

    lock_term_payroll(world["term_id"])
    periods, _ = validate_paginated(api_client.list_term_pay_periods(
        world["term_id"], GS_ADMIN, {"limit": 10, "offset": 0},
    ))
    assert periods[0]["status"] == "LOCKED"

    paid = validate_success(
        api_client.pay_stipend_disbursement(disbursement_id, GS_ADMIN)
    )
    assert paid["status"] == "PAID"
    assert paid["paid_at"] is not None
    assert read_appointment(world["appointment_id"])["payroll_status"] == (
        "FULLY_DISBURSED"
    )
    source = read_source(world["source_id"])
    assert source["expended_amount_cents"] == 300000
    assert source["committed_amount_cents"] == 0


# --------------------------------------------------------------------------- #
# The renewal window and its notice deadline
# --------------------------------------------------------------------------- #


def test_a_review_opened_before_the_window_is_refused_and_admitted_afterwards():
    """The window opens 120 days before the end date, and not one day earlier.

    PRD: "Creation computes two dates from the appointment and its department:
    `renewal_window_open_date` is the appointment's `end_date` minus 120 days,
    and `notice_deadline_date` is the appointment's `end_date` minus the
    appointing department's `non_renewal_notice_days` days." PRD: "Creation is
    permitted only once the window has opened — the current logical-clock date
    must fall on or after `renewal_window_open_date`, and an earlier attempt is
    `ERR_RENEWAL_WINDOW_NOT_OPEN`."

    Design: Corner/validations/renewal_decision_before_window_open_rejected
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1038"},
        advance_to="ACTIVE",
    )

    validate_error(
        api_client.create_renewal_decision(
            {"appointment_id": world["appointment_id"]}, DEPT_ADMIN,
        ),
        ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN.value, 422,
    )
    _, meta = validate_paginated(api_client.list_renewal_decisions(
        DEPT_ADMIN,
        {"appointment_id": world["appointment_id"], "limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 0

    set_clock("2026-09-02T00:00:00Z")

    review = validate_success(api_client.create_renewal_decision(
        {"appointment_id": world["appointment_id"]}, DEPT_ADMIN,
    ), expected_status=201)

    assert review["status"] == "DRAFT"
    assert review["decision"] == "PENDING"
    assert review["renewal_window_open_date"] == "2026-09-02", (
        "2026-12-31 minus 120 days"
    )
    assert review["notice_deadline_date"] == "2026-11-01", (
        "2026-12-31 minus the department's 60 notice days"
    )
    assert review["revision_count"] == 0
    assert review["sap_certified"] is False


def test_a_non_renewal_notice_one_day_late_is_refused_while_a_renewal_stands():
    """The deadline binds only the NON_RENEW branch; RENEW may still be issued.

    PRD: "when the `decision` is `NON_RENEW` the current logical-clock date must
    fall on or before `notice_deadline_date`, and a later date is
    `ERR_NOTICE_DEADLINE_PASSED`". PRD: "On success the review's `decision` is
    recorded, `issued_by_user_id` records the acting user, and `notice_sent_date`
    is set to the current logical-clock date."

    Design: Corner/validations/non_renew_notice_after_deadline_rejected
    """
    world = build_funded_appointment(
        department={"code": "CHEM", "name": "Chemistry",
                    "non_renewal_notice_days": 60},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1039"},
        appointment={"end_date": "2026-12-15"},
        advance_to="ACTIVE",
    )
    set_clock("2026-10-17T00:00:00Z")
    review = build_renewal_review(
        world["appointment_id"], certify=True, creator=DEPT_ADMIN,
        certifier=FACULTY,
    )
    assert review["status"] == "SAP_CERTIFIED"
    assert review["certified_by_user_id"] == FACULTY_SUPERVISOR_USER_ID
    assert review["renewal_window_open_date"] == "2026-08-17", (
        "2026-12-15 minus 120 days"
    )
    assert review["notice_deadline_date"] == "2026-10-16", (
        "2026-12-15 minus the department's 60 notice days"
    )

    validate_error(
        api_client.issue_notice(
            review["id"], {"decision": "NON_RENEW"}, DEPT_ADMIN,
        ),
        ApiErrorId.ERR_NOTICE_DEADLINE_PASSED.value, 422,
    )

    held = read_renewal_decision(review["id"])
    assert held["status"] == "SAP_CERTIFIED"
    assert held["decision"] == "PENDING"
    assert held["notice_sent_date"] is None
    assert read_appointment(world["appointment_id"])["lifecycle_status"] == "ACTIVE"

    renewed = validate_success(api_client.issue_notice(
        review["id"], {"decision": "RENEW"}, DEPT_ADMIN,
    ))
    assert renewed["status"] == "NOTICE_ISSUED"
    assert renewed["decision"] == "RENEW"
    assert renewed["notice_sent_date"] == "2026-10-17"
    assert renewed["issued_by_user_id"] == DEPARTMENT_ADMIN_USER_ID
    assert read_appointment(world["appointment_id"])["renewal_eligible"] is True


def test_a_second_review_for_the_same_appointment_is_refused():
    """One live review per appointment, and the first one keeps the field.

    PRD: "At most one review per appointment may exist in any state other than
    `ACKNOWLEDGED`; a second is `ERR_RENEWAL_DECISION_EXISTS`." PRD: "32.
    **Renewal review uniqueness** — `ERR_RENEWAL_DECISION_EXISTS` (409)."

    Design: Corner/validations/second_renewal_decision_for_same_appointment_rejected
    """
    set_clock("2026-09-05T00:00:00Z")
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1040"},
        advance_to="ACTIVE",
    )
    first = build_renewal_review(world["appointment_id"])

    validate_error(
        api_client.create_renewal_decision(
            {"appointment_id": world["appointment_id"]}, DEPT_ADMIN,
        ),
        ApiErrorId.ERR_RENEWAL_DECISION_EXISTS.value, 409,
    )

    rows, meta = validate_paginated(api_client.list_renewal_decisions(
        DEPT_ADMIN,
        {"appointment_id": world["appointment_id"], "limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["status"] == "DRAFT"


# --------------------------------------------------------------------------- #
# Assessment, allocation and source refusals
# --------------------------------------------------------------------------- #


def test_a_final_assessment_refuses_both_an_empty_amendment_and_a_new_row():
    """Amendment needs a changed benefit, and creation needs no final row.

    PRD: "It requires the assessment to be `FINAL`, and it requires the
    recomputation under `CALENDAR_YEAR_FINAL` to yield a `benefit_cents`
    different from the stored value; when nothing has actually changed the
    amendment is refused with `ERR_NO_ASSESSMENT_DELTA`." PRD: "Creation is
    refused outright when an assessment for that pair is already `FINAL` or
    `AMENDED`: that is `ERR_ASSESSMENT_ALREADY_FINAL`."

    Design: Corner/validations/assessment_finalize_conflicts_rejected
    """
    world = build_funded_appointment(
        policy={"term_insurance_premium_cents": 0},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1041", "enrolled_credit_hours": 9},
        advance_to="ACTIVE",
    )
    assessment = build_assessment(
        world["student_id"], world["term_id"], finalize=True,
    )
    assert assessment["status"] == "FINAL"
    assert assessment["benefit_cents"] == 450000
    assert assessment["exempt_cents"] == 450000
    assert assessment["taxable_cents"] == 0

    validate_error(
        api_client.amend_tax_assessment(
            assessment["id"], {"amendment_reason": "REVIEW_NO_CHANGE"}, GS_ADMIN,
        ),
        ApiErrorId.ERR_NO_ASSESSMENT_DELTA.value, 409,
    )
    still_final = read_assessment(assessment["id"])
    assert still_final["status"] == "FINAL"
    assert still_final["amendment_reason"] is None

    current_version = read_student(world["student_id"])["version"]
    validate_error(
        api_client.create_tax_assessment(tax_assessment_payload(
            world["student_id"], world["term_id"], current_version,
        ), GS_ADMIN),
        ApiErrorId.ERR_ASSESSMENT_ALREADY_FINAL.value, 409,
    )

    _, meta = validate_paginated(api_client.list_tax_assessments(
        GS_ADMIN, {"student_id": world["student_id"], "limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 1, "exactly one assessment for the pair"


def test_releasing_the_funding_of_an_approved_appointment_is_refused():
    """Approval locks the plan even though nothing has been disbursed yet.

    PRD: "Release requires the allocation to be in `COMMITTED` — otherwise
    `ERR_INVALID_ALLOCATION_STATE` — requires its `disbursed_amount_cents` to be
    exactly 0, since money already paid cannot be released
    (`ERR_ALLOCATION_PARTIALLY_DISBURSED`), and requires the funded appointment's
    `lifecycle_status` to be neither `APPROVED` nor `ACTIVE`, because an approved
    or active appointment's funding is locked
    (`ERR_ALLOCATION_LOCKED_BY_APPROVAL`)."

    Design: Corner/validations/release_allocation_of_approved_appointment_rejected
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1042"},
        advance_to="APPROVED",
    )
    committed = allocations_of(world["appointment_id"], status="COMMITTED")
    assert len(committed) == 1
    assert committed[0]["disbursed_amount_cents"] == 0

    validate_error(
        api_client.release_funding_allocation(
            committed[0]["id"], {"release_reason": "SPONSOR_REBUDGET"},
            GRANT_ACCOUNTANT,
        ),
        ApiErrorId.ERR_ALLOCATION_LOCKED_BY_APPROVAL.value, 409,
    )

    still_committed = allocations_of(world["appointment_id"])[0]
    assert still_committed["status"] == "COMMITTED"
    assert still_committed["allocated_stipend_cents"] == 300000
    source = read_source(world["source_id"])
    assert source["committed_amount_cents"] == 300000
    assert source["available_amount_cents"] == 4700000


def test_releasing_an_allocation_that_has_already_paid_out_is_refused():
    """Disbursed money outranks the approval lock in the fixed ordering.

    PRD: "37. **Allocation not yet disbursed** —
    `ERR_ALLOCATION_PARTIALLY_DISBURSED` (409), guarding allocation release. 38.
    **Allocation not locked by approval** — `ERR_ALLOCATION_LOCKED_BY_APPROVAL`
    (409), guarding allocation release." PRD: "Payment moves money along the
    ledger: for each element of `allocation_split`, the named allocation's
    `disbursed_amount_cents` is increased by that element's `amount_cents`, and
    the corresponding source's `committed_amount_cents` falls while its
    `expended_amount_cents` rises by that same amount."

    Design: Corner/validations/release_allocation_with_paid_disbursement_rejected
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1043"},
        advance_to="PAYROLL_SCHEDULED",
        lock_payroll_after=True,
    )
    disbursement = disbursements_of(world["appointment_id"])[0]
    validate_success(
        api_client.pay_stipend_disbursement(disbursement["id"], GS_ADMIN)
    )
    committed = allocations_of(world["appointment_id"], status="COMMITTED")
    assert len(committed) == 1
    assert committed[0]["disbursed_amount_cents"] == 300000

    body = validate_error(
        api_client.release_funding_allocation(
            committed[0]["id"], {"release_reason": "SPONSOR_REBUDGET"},
            GRANT_ACCOUNTANT,
        ),
        ApiErrorId.ERR_ALLOCATION_PARTIALLY_DISBURSED.value, 409,
    )
    assert body["error_id"] != ApiErrorId.ERR_ALLOCATION_LOCKED_BY_APPROVAL.value, (
        "the disbursement check is evaluated before the approval lock"
    )

    unchanged = allocations_of(world["appointment_id"])[0]
    assert unchanged["status"] == "COMMITTED"
    assert unchanged["disbursed_amount_cents"] == 300000
    source = read_source(world["source_id"])
    assert source["expended_amount_cents"] == 300000
    assert source["committed_amount_cents"] == 0


def test_a_source_still_carrying_an_encumbrance_cannot_be_closed():
    """Closure waits for the commitment to be released, then goes through.

    PRD: "Closing a source is permitted from either `ACTIVE` or `SUSPENDED` and
    moves it to the terminal `CLOSED` with `suspension_reason` cleared, but only
    when `committed_amount_cents` is exactly 0; a source still carrying
    encumbrances is rejected with `ERR_FUNDING_SOURCE_HAS_COMMITMENTS`."

    Design: Corner/validations/closing_a_funding_source_with_commitments_rejected
    """
    world = build_funded_appointment(
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1044"},
        advance_to="FUNDING_VERIFIED",
    )
    committed = allocations_of(world["appointment_id"], status="COMMITTED")
    assert len(committed) == 1
    assert read_source(world["source_id"])["committed_amount_cents"] == 300000

    validate_error(
        api_client.close_funding_source(world["source_id"], GRANT_ACCOUNTANT),
        ApiErrorId.ERR_FUNDING_SOURCE_HAS_COMMITMENTS.value, 409,
    )
    assert read_source(world["source_id"])["status"] == "ACTIVE"

    validate_success(api_client.release_funding_allocation(
        committed[0]["id"], {"release_reason": "SPONSOR_REBUDGET"},
        GRANT_ACCOUNTANT,
    ))
    assert read_source(world["source_id"])["committed_amount_cents"] == 0

    closed = validate_success(
        api_client.close_funding_source(world["source_id"], GRANT_ACCOUNTANT)
    )
    assert closed["status"] == "CLOSED"
    assert closed["suspension_reason"] is None


def test_each_natural_key_reports_its_own_duplicate_error():
    """Five collections, five distinct 409s, none of them overwriting a row.

    PRD: "9. **Uniqueness** — `term_code` is unique across academic terms
    (`ERR_DUPLICATE_TERM_CODE`), `student_number` across graduate students
    (`ERR_DUPLICATE_STUDENT_NUMBER`), `source_code` across funding sources
    (`ERR_DUPLICATE_FUNDING_SOURCE_CODE`), one stipend policy per combination of
    `term_id`, `assistantship_type` and `degree_level`
    (`ERR_DUPLICATE_STIPEND_POLICY`), and one pay period per combination of
    `term_id` and `sequence_no` (`ERR_DUPLICATE_PAY_PERIOD_SEQUENCE`). All are
    HTTP 409."

    Design: Corner/validations/duplicate_natural_keys_rejected
    """
    frame = build_term_frame(
        pay_periods=[(1, "2026-09-01", "2026-11-01", "2026-11-05")],
        open_the_term=False,
    )
    term_id = frame["term_id"]
    make_student(student_number="GS-1050")
    make_funding_source(frame["department_id"], source_code="NSF-A")

    attempts = [
        (api_client.create_academic_term(academic_term_payload(), GS_ADMIN),
         ApiErrorId.ERR_DUPLICATE_TERM_CODE.value),
        (api_client.create_student(student_payload(
            student_number="GS-1050", full_name="Other Person",
            degree_level="MASTERS", is_international=True, cumulative_gpa=3.00,
         ), GS_ADMIN),
         ApiErrorId.ERR_DUPLICATE_STUDENT_NUMBER.value),
        (api_client.create_funding_source(funding_source_payload(
            frame["department_id"], source_code="NSF-A",
         ), GRANT_ACCOUNTANT),
         ApiErrorId.ERR_DUPLICATE_FUNDING_SOURCE_CODE.value),
        (api_client.create_stipend_policy(
            stipend_policy_payload(term_id), GS_ADMIN),
         ApiErrorId.ERR_DUPLICATE_STIPEND_POLICY.value),
        (api_client.create_pay_period(pay_period_payload(
            term_id, 1, "2026-11-01", "2027-01-01", "2027-01-05",
         ), GS_ADMIN),
         ApiErrorId.ERR_DUPLICATE_PAY_PERIOD_SEQUENCE.value),
    ]
    for response, error_id in attempts:
        body = validate_error(response, error_id, 409)
        assert body["error_id"] == error_id

    _, meta = validate_paginated(api_client.list_term_pay_periods(
        term_id, GS_ADMIN, {"limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 1, "the duplicate sequence number added nothing"
    assert frame["term"]["proration_method"] == "CALENDAR_DAY"

    policies, policy_meta = validate_paginated(
        api_client.list_term_stipend_policies(
            term_id, GS_ADMIN, {"limit": 10, "offset": 0},
        )
    )
    assert policy_meta["total_count"] == 1
    assert policies[0]["assistantship_type"] == "RESEARCH"


# --------------------------------------------------------------------------- #
# Ceilings that admit the boundary value
# --------------------------------------------------------------------------- #


def test_an_international_student_at_exactly_twenty_hours_may_be_submitted():
    """Twenty hours is the ceiling, and the ceiling itself is admitted.

    PRD: "Then the **international hour ceiling**: when the student is
    international and the term's `session_type` is `IN_SESSION`, the student's
    `assigned_hours_per_week` computed with this appointment included, plus the
    student's `external_weekly_hours`, must not exceed 20.0 hours; exactly 20.0
    passes, more is `ERR_INTERNATIONAL_HOUR_LIMIT_EXCEEDED`."

    Design: Corner/validations/international_student_at_exactly_twenty_hours_passes
    """
    frame = build_term_frame(
        policy={"term_insurance_premium_cents": 0},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
    )
    source = make_funding_source(frame["department_id"], source_code="NSF-A")
    student = make_student(
        student_number="GS-1051", full_name="Wei Chen", degree_level="DOCTORAL",
        is_international=True, cumulative_gpa=3.80, visa_type="F1",
        enrolled_credit_hours=9, external_weekly_hours=0,
    )
    appointment = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=50, monthly_stipend_cents=200000,
    )
    fund_wholly_from(appointment["id"], source["id"])

    submitted = validate_success(
        api_client.submit_appointment(appointment["id"], DEPT_ADMIN)
    )

    assert submitted["lifecycle_status"] == "SUBMITTED"
    assert float(submitted["weekly_hours"]) == pytest.approx(20.0, abs=0.01)
    assert submitted["total_stipend_cents"] == 200000
    assert submitted["tuition_remission_pct"] == 75
    assert submitted["tuition_remission_cents"] == 337500, (
        "nine credits at 50000 cents, at the 75 percent band"
    )

    aggregate = read_student(student["id"])
    assert aggregate["total_effort_pct"] == 50
    assert float(aggregate["assigned_hours_per_week"]) == pytest.approx(
        20.0, abs=0.01
    )


def test_an_effort_cap_override_admits_a_full_hundred_percent_of_effort():
    """A raised ceiling of 100 lets two half-time appointments coexist.

    PRD: "The effort-cap override is a `GradSchoolAdmin` capability that raises a
    single student's ceiling. It takes `approved_max_effort_pct`, which becomes
    the student's new `effort_cap_pct`, and `justification`, which is stored as
    `cap_override_justification`; the acting `X-User-ID` is stored as
    `cap_override_by_user_id` and the student's `version` is incremented." PRD:
    "Then the **aggregate effort cap**: the student's `total_effort_pct` computed
    with this appointment included must not exceed the student's
    `effort_cap_pct`, with a value exactly equal to the cap passing and anything
    above rejected as `ERR_OVER_APPOINTMENT`."

    Design: Corner/validations/effort_cap_override_admits_one_hundred_percent_aggregate
    """
    frame = build_term_frame(pay_periods=SINGLE_PERIOD_AUTUMN_2026)
    source = make_funding_source(frame["department_id"], source_code="NSF-A")
    student = make_student(student_number="GS-1052")
    assert student["effort_cap_pct"] == 75

    raised = validate_success(api_client.effort_cap_override(
        student["id"],
        {"approved_max_effort_pct": 100,
         "justification":
             "Dual-funded training grant appointment approved by the dean."},
        GS_ADMIN,
    ))
    assert raised["effort_cap_pct"] == 100
    assert raised["cap_override_by_user_id"] == GRAD_SCHOOL_ADMIN_USER_ID

    halves = []
    for _ in range(2):
        appointment = make_appointment(
            student["id"], frame["department_id"], frame["term_id"],
            effort_pct=50, monthly_stipend_cents=200000,
        )
        fund_wholly_from(appointment["id"], source["id"])
        halves.append(validate_success(
            api_client.submit_appointment(appointment["id"], DEPT_ADMIN)
        ))

    for half in halves:
        assert half["lifecycle_status"] == "SUBMITTED"
        assert half["total_stipend_cents"] == 200000

    aggregate = read_student(student["id"])
    assert aggregate["total_effort_pct"] == 100, (
        "a value exactly equal to the raised cap passes"
    )
    assert float(aggregate["assigned_hours_per_week"]) == pytest.approx(
        40.0, abs=0.01
    )
