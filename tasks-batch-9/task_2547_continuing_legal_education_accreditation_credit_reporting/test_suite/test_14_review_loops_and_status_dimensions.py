"""Two cyclic review loops on one application, and a period's two status axes.

Neither record here moves along a single line: the application re-enters review
after an appeal with a refilled information budget, and the period's
administrative axis advances three times while its credit axis never moves.
"""
from test_helpers import (
    TEST_USERS,
    appellant_action,
    create_attorney,
    create_cycle,
    create_individual_course,
    credit_allocation_entry,
    list_fee_assessments,
    make_attorney_headers,
    make_panelist_headers,
    pay_fee_as_attorney,
    read_application,
    read_attorney,
    read_course,
    read_cycle,
    reinstate_attorney,
    remand_appeal,
    review_action,
    run_sweep,
    set_clock,
    submit_application,
    validate_error,
)

BOARD = TEST_USERS["board_admin_headers"]


def _application_with_its_information_budget_spent():
    """An attorney's own course application that has already been round-tripped
    through both permitted information requests."""
    attorney = create_attorney(
        bar_number="BAR-4004",
        full_name="Dorothy Achebe",
        admission_date="2011-03-01T00:00:00Z",
        compliance_group="GROUP_3",
        principal_office_jurisdiction="ST",
    )
    applicant_headers = make_attorney_headers(attorney["id"])
    course = create_individual_course(
        applicant_headers,
        title="Self-Directed Study of Fee Agreements",
        delivery_format="SELF_STUDY",
        total_minutes=180,
        presented_at="2026-06-01T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[credit_allocation_entry("ETHICS", 180)],
    )
    application = submit_application(course["id"], applicant_headers)
    for _ in range(2):
        review_action(application["id"], "REQUEST_INFO")
        appellant_action(application["id"], "SUPPLEMENT", applicant_headers)
    return {
        "attorney": attorney,
        "applicant_headers": applicant_headers,
        "course": course,
        "application": application,
    }


def _remanded_application():
    """The same application taken through denial and appeal to a remand, which
    puts it back in review with a fresh information budget."""
    world = _application_with_its_information_budget_spent()
    review_action(
        world["application"]["id"], "DENY",
        denial_reason="Materials still do not identify the ethics content.",
    )
    appellant_action(
        world["application"]["id"], "APPEAL", world["applicant_headers"],
        appeal_grounds="The ethics content is identified in the appended outline.",
    )
    world["remanded"] = remand_appeal(
        world["application"]["id"],
        decision_reason="Reviewer did not consider the appended outline.",
    )
    return world


def test_a_third_information_request_exhausts_the_two_round_budget(api):
    """Requesting information moves the application `SUBMITTED → INFO_REQUESTED` and raises `info_request_round` by one.
    The budget is two rounds: a request that would push `info_request_round` above 2 is rejected with `ERR_INFO_REQUEST_LIMIT_EXCEEDED`.
    Supplementing answers an information request and moves the application `INFO_REQUESTED → SUBMITTED`, raising `supplement_count` by one; together with the reviewer's information request this forms the review system's first loop, `SUBMITTED → INFO_REQUESTED → SUBMITTED`, bounded by the two-round budget.

    Design: Difficulty/non_linear_state_machine/course_application_info_request_loop_then_remand_refills_the_budget
    """
    world = _application_with_its_information_budget_spent()

    response = api.application_review_action(
        world["application"]["id"], {"action": "REQUEST_INFO"},
        TEST_USERS["accreditation_reviewer_headers"],
    )
    validate_error(response, "ERR_INFO_REQUEST_LIMIT_EXCEEDED")

    application = read_application(world["application"]["id"])
    assert application["status"] == "SUBMITTED"
    assert application["info_request_round"] == 2
    assert application["supplement_count"] == 2


def test_a_remand_sends_the_matter_back_and_clears_the_denial_it_answered(api):
    """`REMAND` moves the application `APPEALED → SUBMITTED` and sends the whole matter back for re-review: it raises `remand_count` by one, clears `reviewer_user_id`, `denial_reason` and `denied_at` back to null, resets `info_request_round` to 0 so the application re-enters review with a fresh two-round information budget, and cascades the course `DENIED → PENDING_APPROVAL` with the course's `denial_reason` cleared.
    All three dispositions record the acting identifier in `appeal_panelist_user_id`.

    Design: Difficulty/non_linear_state_machine/course_application_info_request_loop_then_remand_refills_the_budget
    """
    world = _remanded_application()

    application = read_application(world["application"]["id"])
    assert application["status"] == "SUBMITTED"
    assert application["remand_count"] == 1
    assert application["info_request_round"] == 0
    assert application["reviewer_user_id"] is None
    assert application["denial_reason"] is None
    assert application["denied_at"] is None
    assert application["appeal_panelist_user_id"] == "panelist-one"

    course = read_course(world["course"]["id"])
    assert course["status"] == "PENDING_APPROVAL"
    assert course["denial_reason"] is None


def test_the_refilled_budget_accepts_a_request_the_pre_remand_state_refused(api):
    """The budget is two rounds: a request that would push `info_request_round` above 2 is rejected with `ERR_INFO_REQUEST_LIMIT_EXCEEDED`.
    `REMAND` moves the application `APPEALED → SUBMITTED` and sends the whole matter back for re-review: it raises `remand_count` by one, clears `reviewer_user_id`, `denial_reason` and `denied_at` back to null, resets `info_request_round` to 0 so the application re-enters review with a fresh two-round information budget, and cascades the course `DENIED → PENDING_APPROVAL` with the course's `denial_reason` cleared.
    Supplementing answers an information request and moves the application `INFO_REQUESTED → SUBMITTED`, raising `supplement_count` by one; together with the reviewer's information request this forms the review system's first loop, `SUBMITTED → INFO_REQUESTED → SUBMITTED`, bounded by the two-round budget.

    Design: Difficulty/non_linear_state_machine/course_application_info_request_loop_then_remand_refills_the_budget
    """
    world = _remanded_application()

    requested = review_action(world["application"]["id"], "REQUEST_INFO")
    assert requested["status"] == "INFO_REQUESTED"
    assert requested["info_request_round"] == 1

    supplemented = appellant_action(
        world["application"]["id"], "SUPPLEMENT", world["applicant_headers"]
    )
    assert supplemented["status"] == "SUBMITTED"
    assert supplemented["supplement_count"] == 3


def test_the_second_remand_is_refused_while_the_first_one_stands(api):
    """This is the second loop, `DENIED → APPEALED → SUBMITTED`, and the board allows it at most once: a remand that would push `remand_count` above 1 is rejected with `ERR_REMAND_LIMIT_EXCEEDED`.
    Appealing contests a denial and moves the application `DENIED → APPEALED`.

    Design: Difficulty/non_linear_state_machine/course_application_info_request_loop_then_remand_refills_the_budget
    """
    world = _remanded_application()
    application_id = world["application"]["id"]
    review_action(
        application_id, "REQUEST_INFO",
    )
    appellant_action(application_id, "SUPPLEMENT", world["applicant_headers"])
    review_action(
        application_id, "DENY",
        denial_reason="Outline still lacks an ethics learning objective.",
    )
    appellant_action(
        application_id, "APPEAL", world["applicant_headers"],
        appeal_grounds="Second appeal on the same record.",
    )

    response = api.application_appeal_decision(
        application_id,
        {"disposition": "REMAND", "decision_reason": "Send back once more."},
        make_panelist_headers("panelist-one"),
    )
    validate_error(response, "ERR_REMAND_LIMIT_EXCEEDED")

    application = read_application(application_id)
    assert application["status"] == "APPEALED"
    assert application["remand_count"] == 1


def _uncertified_period_past_its_deadline():
    """A period that closed on 2026-01-01 with no credit claimed against it at
    all, whose filing deadline the default clock has already passed."""
    attorney = create_attorney(
        bar_number="BAR-5005",
        full_name="Anton Kowalczyk",
        admission_date="2009-06-01T00:00:00Z",
        compliance_group="GROUP_1",
        principal_office_jurisdiction="ST",
    )
    cycle = create_cycle(
        attorney["id"], "2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z"
    )
    return {"attorney": attorney, "cycle": cycle}


def _suspended_period():
    """Runs the batch twice — once at the default instant and once exactly sixty
    days later — which carries the filing axis to administrative suspension."""
    first_sweep = run_sweep()
    set_clock("2026-09-30T00:00:00Z")
    second_sweep = run_sweep()
    return first_sweep, second_sweep


def test_the_first_sweep_moves_only_the_filing_axis(api):
    """`credit_status` tracks the credit picture and takes `OPEN`, `SATISFIED`, `DEFICIENT` or `CLOSED_COMITY`, starting at `OPEN`.
    The two advance independently, and every combination is legitimate: a cycle can be `SATISFIED` and yet `DELINQUENT` (the credits were earned but the filing was late), or `OPEN` and `GOOD_STANDING`, or `DEFICIENT` and `ADMIN_SUSPENDED`.
    The first: a cycle whose `administrative_status` is `GOOD_STANDING`, whose `credit_status` is `OPEN` or `DEFICIENT`, and whose `filing_deadline` is at or before the run's `as_of`, moves `administrative_status` from `GOOD_STANDING` to `DELINQUENT`.
    Its `delinquent_since` is set to the run's `as_of` — not to the deadline it missed — and a `FeeAssessment` is created with `fee_type` `LATE_COMPLIANCE`, the cycle's `attorney_id` and `cycle_id`, an `assessed_by_sweep_id` naming this run, `status` of `ASSESSED` and an `amount_cents` derived as described below.

    Design: Difficulty/non_linear_state_machine/compliance_cycle_administrative_dimension_advances_twice_while_credit_dimension_stays_open
    """
    world = _uncertified_period_past_its_deadline()

    sweep = run_sweep()

    cycle = read_cycle(world["cycle"]["id"])
    assert cycle["administrative_status"] == "DELINQUENT"
    assert cycle["credit_status"] == "OPEN"
    assert cycle["delinquent_since"].startswith("2026-08-01T00:00:00")
    assert sweep["delinquencies_issued"] == 1
    assert sweep["suspensions_issued"] == 0


def test_the_late_fee_of_a_wholly_uncertified_period_is_clamped_to_its_ceiling(api):
    """Step five picks a base amount from the rounded hour count: zero hours gives 15000 cents, one to five hours gives 25000, six to fifteen gives 40000, and sixteen or more gives 60000.
    Step six adds a surcharge of 2500 cents for each deficient hour, counting at most twenty hours.
    Step seven caps the total: `amount_cents` is the smaller of 100000 cents and the base plus surcharge.
    That assessment raises the attorney's `outstanding_fee_cents` by its `amount_cents`, and the run's `delinquencies_issued` and `late_fees_assessed_cents` tallies rise by one and by that amount respectively.

    Design: Difficulty/non_linear_state_machine/compliance_cycle_administrative_dimension_advances_twice_while_credit_dimension_stays_open
    """
    world = _uncertified_period_past_its_deadline()

    sweep = run_sweep()

    assessments = list_fee_assessments(
        attorney_id=world["attorney"]["id"], fee_type="LATE_COMPLIANCE"
    )
    assert len(assessments) == 1
    assert assessments[0]["status"] == "ASSESSED"
    assert assessments[0]["amount_cents"] == 100000
    assert sweep["late_fees_assessed_cents"] == 100000
    assert read_attorney(world["attorney"]["id"])["outstanding_fee_cents"] == 100000


def test_the_second_sweep_suspends_the_filing_axis_and_leaves_the_credit_axis_open(api):
    """The second enforcement step: a cycle whose `administrative_status` is `DELINQUENT`, whose `credit_status` is `OPEN` or `DEFICIENT`, and whose `delinquent_since` is at least 60 days before the run's `as_of`, moves `administrative_status` from `DELINQUENT` to `ADMIN_SUSPENDED`.
    This cascades: the attorney's own `status` moves `ACTIVE → ADMIN_SUSPENDED`, which is the only way that value is ever written; every reciprocity or comity claim of that attorney still in `SUBMITTED` is denied with `determination_reason` of `ATTORNEY_ADMIN_SUSPENDED`, as §3.7 notes; and a second `FeeAssessment` is created with `fee_type` `REINSTATEMENT` for 50000 cents, naming the same `attorney_id`, `cycle_id` and `assessed_by_sweep_id`, which raises `outstanding_fee_cents` again.
    No transition writes both dimensions unless it is explicitly stated to do so, and a cycle has no terminal state in either dimension — a satisfied cycle can be dragged back open years later by a voided credit.

    Design: Difficulty/non_linear_state_machine/compliance_cycle_administrative_dimension_advances_twice_while_credit_dimension_stays_open
    """
    world = _uncertified_period_past_its_deadline()

    first_sweep, second_sweep = _suspended_period()

    cycle = read_cycle(world["cycle"]["id"])
    assert cycle["administrative_status"] == "ADMIN_SUSPENDED"
    assert cycle["credit_status"] == "OPEN"

    attorney = read_attorney(world["attorney"]["id"])
    assert attorney["status"] == "ADMIN_SUSPENDED"
    assert attorney["outstanding_fee_cents"] == 150000

    assert second_sweep["suspensions_issued"] == 1
    assert second_sweep["delinquencies_issued"] == 0


def test_a_board_order_reinstatement_reaches_reinstated_with_credits_still_open(api):
    """On success the named cycle moves `administrative_status` from `ADMIN_SUSPENDED` to `REINSTATED` and its `delinquent_since` returns to null, and the attorney's `status` moves `ADMIN_SUSPENDED → ACTIVE`.
    Under `FEES_AND_CREDITS_CURED` the cycle's `credit_status` also moves to `SATISFIED`, since the cure evaluation just proved the requirement met; under `BOARD_ORDER` the `credit_status` is left exactly as it was, so a reinstated attorney may perfectly well hold a cycle that is `REINSTATED` and `DEFICIENT` at the same time.
    Both bases require the attorney's `status` to be `ADMIN_SUSPENDED` and require the attorney's `outstanding_fee_cents` to be exactly zero — every assessment paid, waived or voided — and a non-zero balance is rejected with `ERR_OUTSTANDING_FEE_BALANCE`, which is evaluated after every other check in the order of §2.8.

    Design: Difficulty/non_linear_state_machine/compliance_cycle_administrative_dimension_advances_twice_while_credit_dimension_stays_open
    """
    world = _uncertified_period_past_its_deadline()
    _suspended_period()
    attorney_id = world["attorney"]["id"]
    for assessment in list_fee_assessments(attorney_id=attorney_id, status="ASSESSED"):
        pay_fee_as_attorney(assessment["id"], attorney_id)
    assert read_attorney(attorney_id)["outstanding_fee_cents"] == 0

    reinstate_attorney(
        attorney_id, world["cycle"]["id"], cure_basis="BOARD_ORDER",
        reason="Hardship petition granted.",
    )

    cycle = read_cycle(world["cycle"]["id"])
    assert cycle["administrative_status"] == "REINSTATED"
    assert cycle["credit_status"] == "OPEN"
    assert cycle["delinquent_since"] is None
    assert cycle["certified_at"] is None
    assert cycle["earned_countable_minutes"] == 0
    assert read_attorney(attorney_id)["status"] == "ACTIVE"
