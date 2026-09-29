"""Floor programming: the three-bucket budget, compliance and reimbursement."""
from test_helpers import (
    ApiErrorId,
    allocate_budget,
    assert_floor_budget_partition,
    assert_program_event,
    hold_program,
    propose_program,
    read_floor,
    read_program_event,
    receipt_line,
    set_clock,
    setup_approved_program,
    setup_certified_ra_on_floor,
    setup_held_program,
    validate_error,
    validate_success,
)

FIVE_LINES = [
    receipt_line("FOOD", 10101),
    receipt_line("FOOD", 10101),
    receipt_line("FOOD", 10101),
    receipt_line("FOOD", 10101),
    receipt_line("SUPPLIES", 2005),
]


class TestReimbursementRounding:
    def test_each_receipt_line_is_rounded_before_the_lines_are_summed(
        self, api, director_headers
    ):
        """PRD §3.8: "Each line is reimbursed at its category's rate — three quarters
        for `FOOD`, nine tenths for `SUPPLIES` and the full amount for `HONORARIUM` —
        and, as elsewhere in this system, **the rate is applied to each line and that
        line is rounded half-up to whole cents before the lines are summed** into
        `reimbursed_amount_cents`."
        PRD §3.8: "Grouping lines by category and rounding once per category, or
        summing first and rounding at the end, produces a different figure and is
        wrong."

        Design: Difficulty/combinatorial_formula/program_reimbursement_rounds_each_receipt_line_before_summing
        """
        base = setup_held_program(
            budget_cents=100_000,
            requested_amount_cents=40_000,
            title="Floor Feast",
            category="SOCIAL",
        )

        reimbursed = validate_success(
            api.reimburse_program_event(
                base["event"]["id"], {"receipt_lines": FIVE_LINES}, director_headers
            )
        )

        assert_program_event(reimbursed)
        assert reimbursed["reimbursed_amount_cents"] == 32109, (
            "four FOOD lines at 7,576 plus one SUPPLIES line at 1,805; got "
            f"{reimbursed['reimbursed_amount_cents']}"
        )
        assert reimbursed["status"] == "REIMBURSED"
        assert reimbursed["encumbered_amount_cents"] == 0

    def test_reimbursement_moves_the_encumbrance_into_the_spent_bucket(
        self, api, director_headers
    ):
        """PRD §3.8: "On success the event moves `HELD → REIMBURSED` and the buckets
        move in a fixed order: the floor's `programming_encumbered_cents` is reduced by
        the event's stored `encumbered_amount_cents`, which is then zeroed; the floor's
        `programming_spent_cents` grows by `reimbursed_amount_cents`; and
        `programming_available_cents` is recomputed as the budget less the encumbered
        portion less the spent portion."

        Design: Difficulty/combinatorial_formula/program_reimbursement_rounds_each_receipt_line_before_summing
        """
        base = setup_held_program(
            budget_cents=100_000,
            requested_amount_cents=40_000,
            title="Floor Feast",
            category="SOCIAL",
        )

        validate_success(
            api.reimburse_program_event(
                base["event"]["id"], {"receipt_lines": FIVE_LINES}, director_headers
            )
        )

        floor = read_floor(base["floor"]["id"])
        assert floor["programming_spent_cents"] == 32109
        assert floor["programming_encumbered_cents"] == 0
        assert floor["programming_available_cents"] == 67891
        assert floor["programming_budget_cents"] == 100_000
        assert_floor_budget_partition(floor)


class TestReimbursementCheckOrder:
    def test_reimbursing_an_unheld_event_reports_the_state_error(self, api, director_headers):
        """PRD §3.8: "Reimbursement against an event whose status is not `HELD` is
        refused with `ERR_PROGRAM_NOT_HELD`, and the array must not be empty."
        PRD §2.7: "Checks are evaluated in ascending priority and the first failure
        wins; later checks never run."

        Design: Difficulty/priority_pair_validation_conflict/reimbursement_state_check_outranks_floor_budget_check
        """
        base = setup_approved_program(
            budget_cents=40_000,
            requested_amount_cents=40_000,
            title="Study Jam",
            category="EDUCATIONAL",
        )
        assert base["event"]["status"] == "APPROVED"
        assert read_floor(base["floor"]["id"])["programming_available_cents"] == 0

        response = api.reimburse_program_event(
            base["event"]["id"],
            {"receipt_lines": [receipt_line("HONORARIUM", 50_000)]},
            director_headers,
        )

        validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_HELD.value, 409)
        assert read_program_event(base["event"]["id"])["status"] == "APPROVED"

    def test_holding_the_event_exposes_the_floor_budget_error_underneath(
        self, api, director_headers
    ):
        """PRD §3.8: "What is checked is the overrun: the amount by which
        `reimbursed_amount_cents` exceeds the event's `requested_amount_cents`, or zero
        when it does not exceed it at all, must fit inside the floor's
        `programming_available_cents`, and an overrun that does not fit is
        `ERR_FLOOR_BUDGET_EXCEEDED`."
        PRD §2.7: "**Fiscal constraints** — programming budget allocation and
        availability at approval, then the reimbursement overrun check."

        Design: Difficulty/priority_pair_validation_conflict/reimbursement_state_check_outranks_floor_budget_check
        """
        base = setup_approved_program(
            budget_cents=40_000,
            requested_amount_cents=40_000,
            title="Study Jam",
            category="EDUCATIONAL",
            scheduled_for="2026-08-03T18:00:00Z",
        )
        receipts = {"receipt_lines": [receipt_line("HONORARIUM", 50_000)]}
        validate_error(
            api.reimburse_program_event(base["event"]["id"], receipts, director_headers),
            ApiErrorId.ERR_PROGRAM_NOT_HELD.value,
            409,
        )

        set_clock("2026-08-03T19:00:00Z")
        hold_program(base["event"]["id"], base["ra_headers"], attendance_count=25)

        response = api.reimburse_program_event(
            base["event"]["id"], receipts, director_headers
        )

        validate_error(response, ApiErrorId.ERR_FLOOR_BUDGET_EXCEEDED.value, 409)
        event = read_program_event(base["event"]["id"])
        assert event["status"] == "HELD", (
            "the identical receipts were fiscally impossible all along"
        )
        assert event["reimbursed_amount_cents"] is None
        floor = read_floor(base["floor"]["id"])
        assert floor["programming_spent_cents"] == 0
        assert floor["programming_encumbered_cents"] == 40_000
        assert floor["programming_available_cents"] == 0
        assert_floor_budget_partition(floor)


class TestBudgetCompensation:
    def test_cancelling_an_approved_program_returns_the_exact_encumbrance(
        self, api, director_headers
    ):
        """PRD §3.8: "`APPROVE` moves it to `APPROVED` and encumbers the ask: the
        event's `encumbered_amount_cents` is set to its `requested_amount_cents`, the
        floor's `programming_encumbered_cents` grows by that amount and
        `programming_available_cents` is recomputed."
        PRD §3.8: "`CANCEL` is the compensating action, available from either
        `APPROVED` or `HELD`: it moves the event to `CANCELLED`, subtracts exactly the
        stored `encumbered_amount_cents` from the floor's `programming_encumbered_cents`,
        resets the event's `encumbered_amount_cents` to zero, and recomputes
        `programming_available_cents` back to precisely its pre-approval value."

        Design: Difficulty/compensating_invariant/floor_budget_three_bucket_partition_restored_by_program_cancel
        """
        base = setup_approved_program(
            budget_cents=100_000,
            requested_amount_cents=40_000,
            title="Wellness Walk",
            category="WELLNESS",
            scheduled_for="2026-08-04T17:00:00Z",
        )
        before = read_floor(base["floor"]["id"])
        assert before["programming_available_cents"] == 60_000
        assert before["programming_encumbered_cents"] == 40_000
        assert before["programming_spent_cents"] == 0

        cancelled = validate_success(
            api.program_event_outcome(
                base["event"]["id"], {"action": "CANCEL"}, director_headers
            )
        )

        after = read_floor(base["floor"]["id"])
        assert after["programming_available_cents"] == 100_000
        assert after["programming_encumbered_cents"] == 0
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["encumbered_amount_cents"] == 0

    def test_cancellation_leaves_the_spent_bucket_and_compliance_untouched(
        self, api, director_headers
    ):
        """PRD §3.8: "`programming_available_cents` is what remains: the budget less
        the encumbered portion less the spent portion. That identity holds after every
        operation described here, and it is the invariant against which every bucket
        movement should be checked."
        PRD §3.8: "A floor's `held_program_count` is the number of its events whose
        status is `HELD` or `REIMBURSED`; proposed, approved, denied and cancelled
        events never count."

        Design: Difficulty/compensating_invariant/floor_budget_three_bucket_partition_restored_by_program_cancel
        """
        base = setup_approved_program(
            budget_cents=100_000,
            requested_amount_cents=40_000,
            title="Wellness Walk",
            category="WELLNESS",
            scheduled_for="2026-08-04T17:00:00Z",
        )

        validate_success(
            api.program_event_outcome(
                base["event"]["id"], {"action": "CANCEL"}, director_headers
            )
        )

        floor = read_floor(base["floor"]["id"])
        assert floor["programming_spent_cents"] == 0, (
            "a cancellation never moves money into the spent bucket"
        )
        assert floor["programming_budget_cents"] == 100_000
        assert_floor_budget_partition(floor)
        assert floor["held_program_count"] == 0
        assert floor["programming_compliance_status"] == "PENDING"


def test_floor_turns_compliant_only_with_four_programs_including_the_category_mix(
    api, director_headers
):
    """PRD §3.8: "The floor's `programming_compliance_status` is `COMPLIANT` when that
    count reaches `required_programs_per_term` — the comparison is inclusive, so exactly
    the required number qualifies — **and** the qualifying set contains at least one
    `EDUCATIONAL` event and at least one `WELLNESS` event."
    PRD §3.8: "A read of one floor's programming summary reports `budget_cents`,
    `encumbered_cents`, `spent_cents` and `available_cents` mirroring the three buckets
    and the remainder, together with `held_program_count`, `compliance_status`, and the
    two booleans `has_educational` and `has_wellness` that show which half of the
    category mix is satisfied."

    Design: Corner/calculations/floor_compliance_requires_four_programs_including_educational_and_wellness
    """
    base = setup_certified_ra_on_floor(required_programs_per_term=4)
    floor_id = base["floor"]["id"]
    allocate_budget(floor_id, 40_000)
    events = []
    for title, category in (
        ("Movie Night", "SOCIAL"),
        ("Pancake Study Break", "SOCIAL"),
        ("Resume Workshop", "EDUCATIONAL"),
        ("Sleep Clinic", "WELLNESS"),
    ):
        event = propose_program(
            base["ra_headers"],
            floor_id,
            title=title,
            category=category,
            scheduled_for="2026-08-02T18:00:00Z",
            requested_amount_cents=5_000,
        )
        validate_success(
            api.decide_program_event(event["id"], {"decision": "APPROVE"}, director_headers)
        )
        events.append(event)

    set_clock("2026-08-02T19:00:00Z")
    for event, attendance in zip(events[:3], (22, 18, 12)):
        hold_program(event["id"], base["ra_headers"], attendance_count=attendance)

    before = read_floor(floor_id)
    assert before["held_program_count"] == 3
    assert before["programming_compliance_status"] == "PENDING"

    fourth = hold_program(events[3]["id"], base["ra_headers"], attendance_count=9)

    after = read_floor(floor_id)
    assert after["held_program_count"] == 4
    assert after["programming_compliance_status"] == "COMPLIANT"
    summary = validate_success(api.get_programming_summary(floor_id, director_headers))
    assert summary["budget_cents"] == 40_000
    assert summary["encumbered_cents"] == 20_000
    assert summary["spent_cents"] == 0
    assert summary["available_cents"] == 20_000
    assert summary["has_educational"] is True
    assert summary["has_wellness"] is True
    assert fourth["attendance_count"] == 9
    assert fourth["status"] == "HELD"


def test_approving_a_program_on_an_unfunded_floor_reports_the_allocation_gap(
    api, director_headers
):
    """PRD §3.8: "The floor must have money allocated at all: a
    `programming_budget_cents` of zero is refused with
    `ERR_PROGRAM_BUDGET_NOT_ALLOCATED`."
    PRD §3.8: "The budget-allocation check is evaluated before the availability check,
    so a floor with no budget at all reports the allocation code."

    Design: Corner/validations/program_approval_on_a_floor_with_no_allocation_returns_budget_not_allocated
    """
    base = setup_certified_ra_on_floor()
    event = propose_program(
        base["ra_headers"],
        base["floor"]["id"],
        title="Hallway Trivia",
        category="SOCIAL",
        scheduled_for="2026-08-04T19:00:00Z",
        requested_amount_cents=1,
    )

    response = api.decide_program_event(
        event["id"], {"decision": "APPROVE"}, director_headers
    )

    validate_error(response, ApiErrorId.ERR_PROGRAM_BUDGET_NOT_ALLOCATED.value, 409)
    refused = read_program_event(event["id"])
    assert refused["status"] == "PROPOSED"
    assert refused["encumbered_amount_cents"] == 0
    floor = read_floor(base["floor"]["id"])
    assert floor["programming_budget_cents"] == 0
    assert floor["programming_encumbered_cents"] == 0
    assert floor["programming_available_cents"] == 0
