"""Operations whose interesting behaviour lives in the response they return.

Wholesale plan replacement, the term's live calendar count, the appointment list
with its filters and pages, and the two payroll-axis moves that read the
appointment's payment history rather than its request payload.
"""
import pytest

from test_helpers import (
    DEPT_ADMIN,
    GRANT_ACCOUNTANT,
    GS_ADMIN,
    SINGLE_PERIOD_AUTUMN_2026,
    api_client,
    assert_page_meta,
    build_funded_appointment,
    build_term_frame,
    disbursements_of,
    fund_wholly_from,
    make_appointment,
    make_funding_source,
    make_pay_periods,
    make_policy,
    make_student,
    make_term,
    read_appointment,
    read_source,
    read_term,
    set_funding_plan,
    validate_paginated,
    validate_success,
)

_TWO_SIXTY_ONE_DAY_PERIODS = [
    (1, "2026-09-01", "2026-11-01", "2026-11-05"),
    (2, "2026-11-01", "2027-01-01", "2027-01-05"),
]


def test_replacing_a_plan_releases_the_old_line_and_splits_across_the_new_two():
    """One source becomes two, and the superseded row is kept with zeroed amounts.

    PRD: "First, every existing `FundingAllocation` of the appointment whose
    `status` is `PROPOSED` or `COMMITTED` moves to the terminal `RELEASED` with
    `release_reason` set to `PLAN_SUPERSEDED` and both `allocated_stipend_cents`
    and `allocated_remission_cents` zeroed." PRD: "Second, one new
    `FundingAllocation` row is created per element of `allocations`, each in
    `PROPOSED`, each carrying the appointment's identifier as `appointment_id`,
    the element's `funding_source_id`, `share_pct` and `is_cost_share`, and each
    stamped with `plan_sequence` equal to its 1-based index in the submitted
    array." PRD: "Each one's `allocated_stipend_cents` is the basis multiplied by
    its `share_pct`, divided by 100, truncated toward zero to a whole cent."

    Design: Corner/endpoints/funding_plan_replacement_supersedes_prior_allocations
    """
    frame = build_term_frame(
        policy={"term_insurance_premium_cents": 0},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
    )
    grant_a = make_funding_source(frame["department_id"], source_code="NSF-A")
    grant_b = make_funding_source(frame["department_id"], source_code="NSF-B")
    student = make_student(student_number="GS-1060")
    appointment = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=75, monthly_stipend_cents=300000,
    )
    assert appointment["version"] == 1
    fund_wholly_from(appointment["id"], grant_a["id"])

    replaced = set_funding_plan(
        appointment["id"], [(grant_a["id"], 60.00), (grant_b["id"], 40.00)],
    )
    assert replaced["version"] == 3
    submitted = validate_success(
        api_client.submit_appointment(appointment["id"], DEPT_ADMIN)
    )

    released, released_meta = validate_paginated(api_client.list_funding_allocations(
        GRANT_ACCOUNTANT,
        {"appointment_id": appointment["id"], "status": "RELEASED",
         "limit": 10, "offset": 0},
    ))
    assert released_meta["total_count"] == 1
    assert released[0]["release_reason"] == "PLAN_SUPERSEDED"
    assert released[0]["allocated_stipend_cents"] == 0
    assert released[0]["allocated_remission_cents"] == 0

    proposed, proposed_meta = validate_paginated(api_client.list_funding_allocations(
        GRANT_ACCOUNTANT,
        {"appointment_id": appointment["id"], "status": "PROPOSED",
         "limit": 10, "offset": 0},
    ))
    assert proposed_meta["total_count"] == 2
    first, second = proposed
    assert first["plan_sequence"] == 1
    assert first["funding_source_id"] == grant_a["id"]
    assert float(first["share_pct"]) == pytest.approx(60.00, abs=0.001)
    assert first["allocated_stipend_cents"] == 180000
    assert second["plan_sequence"] == 2
    assert second["funding_source_id"] == grant_b["id"]
    assert float(second["share_pct"]) == pytest.approx(40.00, abs=0.001)
    assert second["allocated_stipend_cents"] == 120000

    assert submitted["total_stipend_cents"] == 300000
    assert submitted["version"] == 4, (
        "creation, two plan replacements and the submit each add one"
    )


def test_the_terms_pay_period_count_tracks_the_calendar_as_it_is_appended():
    """Zero on a fresh term, two once two periods reference it.

    PRD: "A newly created term has `pay_period_count` of 0 and both `locked_at`
    and `closed_at` null." PRD: "Each accepted period recomputes the term's
    `pay_period_count`, which is simply the number of pay periods whose `term_id`
    is that term." PRD: "a term's pay-period calendar is ordered by `sequence_no`
    ascending"

    Design: Corner/endpoints/term_pay_period_count_reflects_calendar
    """
    term = make_term()
    assert term["status"] == "PLANNING"
    assert read_term(term["id"])["pay_period_count"] == 0

    make_policy(term["id"])
    make_pay_periods(term["id"], _TWO_SIXTY_ONE_DAY_PERIODS)

    assert read_term(term["id"])["pay_period_count"] == 2

    periods, period_meta = validate_paginated(api_client.list_term_pay_periods(
        term["id"], GS_ADMIN, {"limit": 10, "offset": 0},
    ))
    assert_page_meta(period_meta, 10, 0, 2, False)
    assert periods[0]["sequence_no"] == 1
    assert periods[1]["sequence_no"] == 2
    assert periods[0]["status"] == "OPEN"

    policies, policy_meta = validate_paginated(
        api_client.list_term_stipend_policies(
            term["id"], GS_ADMIN,
            {"assistantship_type": "RESEARCH", "limit": 10, "offset": 0},
        )
    )
    assert policy_meta["total_count"] == 1
    assert policies[0]["degree_level"] == "DOCTORAL"


def test_the_appointment_list_pages_and_filters_over_three_drafts():
    """Two pages, a student filter and a status filter that matches nothing.

    PRD: "The `limit` parameter caps the number of rows returned; it defaults to
    10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The
    `offset` parameter is the number of rows to skip; it defaults to 0 and its
    minimum accepted value is 0." PRD: "Every list response carries `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the
    envelope, alongside `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/appointment_list_filter_and_limit_paginate
    """
    frame = build_term_frame(pay_periods=SINGLE_PERIOD_AUTUMN_2026)
    students = [
        make_student(student_number="GS-1061", full_name="Ada Vance"),
        make_student(student_number="GS-1062", full_name="Ben Ortiz"),
        make_student(student_number="GS-1063", full_name="Cara Nkemi"),
    ]
    appointments = [
        make_appointment(
            student["id"], frame["department_id"], frame["term_id"],
            effort_pct=75, monthly_stipend_cents=300000,
        )
        for student in students
    ]

    page_one, meta_one = validate_paginated(api_client.list_appointments(
        GS_ADMIN, {"term_id": frame["term_id"], "limit": 2, "offset": 0},
    ))
    assert len(page_one) == 2
    assert_page_meta(meta_one, 2, 0, 3, True)

    page_two, meta_two = validate_paginated(api_client.list_appointments(
        GS_ADMIN, {"term_id": frame["term_id"], "limit": 2, "offset": 2},
    ))
    assert len(page_two) == 1
    assert_page_meta(meta_two, 2, 2, 3, False)

    filtered, filtered_meta = validate_paginated(api_client.list_appointments(
        GS_ADMIN, {"student_id": students[1]["id"]},
    ))
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["id"] == appointments[1]["id"]
    assert filtered_meta["limit"] == 10, "the omitted limit defaults to 10"
    assert filtered_meta["offset"] == 0

    empty, empty_meta = validate_paginated(api_client.list_appointments(
        GS_ADMIN, {"term_id": frame["term_id"], "lifecycle_status": "SUBMITTED"},
    ))
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False

    for appointment in appointments:
        current = read_appointment(appointment["id"])
        assert current["lifecycle_status"] == "DRAFT"
        assert current["payroll_status"] == "NOT_SCHEDULED"


def test_paying_the_first_of_two_periods_is_partial_and_the_second_is_full():
    """The payroll axis reads how many siblings are still scheduled.

    PRD: "Payment then advances the appointment's payroll axis: `payroll_status`
    becomes `PARTIALLY_DISBURSED` when at least one sibling disbursement of the
    same appointment remains `SCHEDULED` after this payment, and
    `FULLY_DISBURSED` when none does." PRD: "`expended_amount_cents` is the sum
    of `disbursed_amount_cents` over the source's allocations whose `status` is
    `COMMITTED`, plus the sum of `allocated_stipend_cents` plus
    `allocated_remission_cents` over the source's allocations whose `status` is
    `EXPENDED`."

    Design: Corner/endpoints/payroll_progresses_partially_then_fully_disbursed
    """
    world = build_funded_appointment(
        policy={"term_insurance_premium_cents": 0},
        pay_periods=_TWO_SIXTY_ONE_DAY_PERIODS,
        student={"student_number": "GS-1064"},
        source={"source_code": "NSF-A", "authorized_amount_cents": 1000000},
        advance_to="PAYROLL_SCHEDULED",
        lock_payroll_after=True,
    )

    appointment = read_appointment(world["appointment_id"])
    assert appointment["projected_pay_period_count"] == 2
    assert appointment["total_stipend_cents"] == 600000

    rows = disbursements_of(world["appointment_id"])
    assert len(rows) == 2
    for row in rows:
        assert row["covered_units"] == 61
        assert row["period_units"] == 61
        assert row["gross_amount_cents"] == 300000

    validate_success(api_client.pay_stipend_disbursement(rows[0]["id"], GS_ADMIN))
    midway = read_appointment(world["appointment_id"])
    assert midway["payroll_status"] == "PARTIALLY_DISBURSED"
    assert midway["lifecycle_status"] == "ACTIVE", (
        "paying a stipend never touches the approval axis"
    )

    validate_success(api_client.pay_stipend_disbursement(rows[1]["id"], GS_ADMIN))
    assert read_appointment(world["appointment_id"])["payroll_status"] == (
        "FULLY_DISBURSED"
    )

    source = read_source(world["source_id"])
    assert source["expended_amount_cents"] == 600000
    assert source["committed_amount_cents"] == 0
    assert source["available_amount_cents"] == 400000


def test_resuming_pay_after_one_payment_returns_to_partially_disbursed():
    """Resumption branches on paid history, so it cannot land back on SCHEDULED.

    PRD: "Resuming pay moves the appointment out of `PAY_SUSPENDED` and clears
    `pay_suspension_reason` to null, and it branches on paid history with equal
    precision in both directions: when the appointment has no disbursement in
    `PAID`, `payroll_status` returns to `SCHEDULED`; when it has at least one
    disbursement in `PAID`, `payroll_status` returns to `PARTIALLY_DISBURSED`."
    PRD: "The appointment's `lifecycle_status` must be `ACTIVE` or
    `NON_RENEWAL_PENDING`, else `ERR_INVALID_APPOINTMENT_STATE` — and, critically,
    `lifecycle_status` is **not** modified by the suspension."

    Design: Corner/endpoints/resume_pay_returns_to_partially_disbursed_after_paid_history
    """
    world = build_funded_appointment(
        policy={"term_insurance_premium_cents": 0},
        pay_periods=_TWO_SIXTY_ONE_DAY_PERIODS,
        student={"student_number": "GS-1065"},
        source={"source_code": "NSF-A"},
        advance_to="PAYROLL_SCHEDULED",
        lock_payroll_after=True,
    )
    rows = disbursements_of(world["appointment_id"])
    validate_success(api_client.pay_stipend_disbursement(rows[0]["id"], GS_ADMIN))

    suspended = validate_success(api_client.suspend_pay(
        world["appointment_id"],
        {"pay_suspension_reason": "VISA_DOCUMENTATION_HOLD"},
        GS_ADMIN,
    ))
    assert suspended["payroll_status"] == "PAY_SUSPENDED"
    assert suspended["lifecycle_status"] == "ACTIVE"
    assert suspended["pay_suspension_reason"] == "VISA_DOCUMENTATION_HOLD"

    resumed = validate_success(
        api_client.resume_pay(world["appointment_id"], GS_ADMIN)
    )

    assert resumed["payroll_status"] == "PARTIALLY_DISBURSED"
    assert resumed["payroll_status"] != "SCHEDULED", (
        "one disbursement is already PAID, so SCHEDULED is not reachable"
    )
    assert resumed["pay_suspension_reason"] is None

    after = disbursements_of(world["appointment_id"])
    assert after[0]["status"] == "PAID"
    assert after[1]["status"] == "SCHEDULED"
