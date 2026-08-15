"""Timesheets, streaks, and verification: the reject/resubmit cycle,
chronological streak recompute with weekday-gap resets, the long-term
conversion threshold at day 10, per-day rounding order, and the provisional
vs final pay split; plus duplicate, range, and long-term-extension rules."""
from test_helpers import (
    ApiErrorId,
    get_absence,
    get_school,
    get_timesheet,
    make_coordinator_headers,
    make_substitute_headers,
    review_absence,
    review_timesheet,
    submit_timesheet,
    validate_error,
    validate_success,
    verified_assignment_ctx,
    worked_assignment_ctx,
)


def test_timesheet_reject_resubmit_cycle(api):
    """PRD 3.5: "The coordinator reviews with a `decision` of `APPROVE` or
    `REJECT`: approving requires the sheet `SUBMITTED` (else
    `ERR_TIMESHEET_INVALID_STATE`) and its assignment still `WORKED` (else
    `ERR_ASSIGNMENT_INVALID_STATE`); rejecting under the same guards moves it
    to `REJECTED`, from which the substitute may resubmit corrected
    `hours_worked`, returning it to `SUBMITTED` — resubmission from any other
    status fails with `ERR_TIMESHEET_INVALID_STATE`."

    Design: Corner/state_machines/timesheet_reject_resubmit_cycle
    """
    ctx = worked_assignment_ctx(start_date="2026-08-03", end_date="2026-08-03")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    sub_headers = make_substitute_headers(ctx["sub"]["id"])

    sheet = submit_timesheet(ctx["assignment"]["id"], ctx["sub"]["id"], "2026-08-03", 6.0)
    rejected = review_timesheet(sheet["id"], "REJECT", coord_headers)
    assert rejected["status"] == "REJECTED"

    resubmitted = validate_success(
        api.resubmit_timesheet(sheet["id"], {"hours_worked": 8.0}, sub_headers), 200
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["hours_worked"] == 8.0

    res = api.resubmit_timesheet(sheet["id"], {"hours_worked": 7.5}, sub_headers)
    validate_error(res, ApiErrorId.ERR_TIMESHEET_INVALID_STATE, expected_status=409)

    approved = review_timesheet(sheet["id"], "APPROVE", coord_headers)
    assert approved["status"] == "APPROVED"
    assert approved["streak_index"] == 1
    assert approved["day_pay_cents"] == 20000


def test_streak_gap_reset_on_unapproved_weekday(api):
    """PRD 3.5: "The `streak_index` of the earliest approved date is 1; each
    subsequent approved date increments it when the date is the next district
    workday after the previous one — weekend gaps do not break a streak —
    while any weekday gap (a skipped Monday-through-Friday date with no
    approved timesheet between two approved dates) resets the index to 1."

    Design: Corner/calculations/streak_gap_reset_on_unapproved_weekday
    """
    ctx = worked_assignment_ctx(start_date="2026-08-03", end_date="2026-08-07")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    ts1 = submit_timesheet(ctx["assignment"]["id"], ctx["sub"]["id"], "2026-08-03")
    ts2 = submit_timesheet(ctx["assignment"]["id"], ctx["sub"]["id"], "2026-08-04")
    ts3 = submit_timesheet(ctx["assignment"]["id"], ctx["sub"]["id"], "2026-08-07")

    ts1 = review_timesheet(ts1["id"], "APPROVE", coord_headers)
    ts2 = review_timesheet(ts2["id"], "APPROVE", coord_headers)
    assert ts1["streak_index"] == 1
    assert ts2["streak_index"] == 2

    ts3 = review_timesheet(ts3["id"], "APPROVE", coord_headers)
    assert ts3["streak_index"] == 1, (
        "Wed 2026-08-05 and Thu 2026-08-06 are unapproved weekdays: gap resets"
    )
    assert ts3["day_pay_cents"] == 20000


def test_out_of_order_approval_recomputes_streaks(api, district_admin_headers):
    """PRD 3.5: "On each approval the system runs a full chronological
    recompute over the assignment's `APPROVED` timesheets, sorted by
    `work_date` ascending — dates are unique, so no tie-breaking exists."

    Design: Corner/calculations/out_of_order_approval_recomputes_streaks
    """
    ctx = worked_assignment_ctx(start_date="2026-08-03", end_date="2026-08-04")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    ts_mon = submit_timesheet(ctx["assignment"]["id"], ctx["sub"]["id"], "2026-08-03")
    ts_tue = submit_timesheet(ctx["assignment"]["id"], ctx["sub"]["id"], "2026-08-04")

    tue_first = review_timesheet(ts_tue["id"], "APPROVE", coord_headers)
    assert tue_first["streak_index"] == 1

    mon = review_timesheet(ts_mon["id"], "APPROVE", coord_headers)
    assert mon["streak_index"] == 1

    tue_after = get_timesheet(ts_tue["id"])
    assert tue_after["streak_index"] == 2, "rewritten by the chronological recompute"
    assert tue_after["day_pay_cents"] == 20000, (
        "rate unchanged at premium 1.00; only the streak position moved"
    )


def test_uniqueness_constraints_across_entities(api, district_admin_headers):
    """PRD 2.8: "One `ACTIVE` mark per school, substitute, and mark type; one
    qualification per substitute, subject, and grade band; one timesheet per
    assignment and work date — surfacing as `ERR_DUPLICATE_MARK`,
    `ERR_DUPLICATE_QUALIFICATION`, or `ERR_DUPLICATE_TIMESHEET` (409)."
    PRD 3.2: "it is granted against a `substitute_id`, and granting the same
    subject-and-band twice is refused with `ERR_DUPLICATE_QUALIFICATION`."

    Design: Corner/validations/uniqueness_constraints_across_entities
    """
    ctx = worked_assignment_ctx(start_date="2026-08-03", end_date="2026-08-03")
    sub_headers = make_substitute_headers(ctx["sub"]["id"])
    submit_timesheet(ctx["assignment"]["id"], ctx["sub"]["id"], "2026-08-03")

    res = api.create_qualification(
        {"substitute_id": ctx["sub"]["id"], "subject": "MATH", "grade_band": "HIGH"},
        district_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_QUALIFICATION, expected_status=409)

    res = api.create_timesheet(
        {"assignment_id": ctx["assignment"]["id"], "work_date": "2026-08-03",
         "hours_worked": 4.0},
        sub_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_TIMESHEET, expected_status=409)


def test_timesheet_out_of_range_and_weekend_work_date(api):
    """PRD 3.5: "the submission is only accepted while the assignment is
    `WORKED` (else `ERR_ASSIGNMENT_INVALID_STATE`), the date must be a weekday
    inside the assignment's range (`ERR_INVALID_DATE_RANGE`, with the
    dedicated `ERR_TIMESHEET_OUT_OF_RANGE` guarding the range rule), and a
    second sheet for the same assignment and date is refused with
    `ERR_DUPLICATE_TIMESHEET`."

    Design: Corner/validations/timesheet_out_of_range_and_weekend_work_date
    """
    ctx = worked_assignment_ctx(start_date="2026-08-03", end_date="2026-08-04")
    sub_headers = make_substitute_headers(ctx["sub"]["id"])

    res = api.create_timesheet(
        {"assignment_id": ctx["assignment"]["id"], "work_date": "2026-08-05",
         "hours_worked": 8.0},
        sub_headers,
    )
    validate_error(res, ApiErrorId.ERR_TIMESHEET_OUT_OF_RANGE, expected_status=409)

    res = api.create_timesheet(
        {"assignment_id": ctx["assignment"]["id"], "work_date": "2026-08-09",
         "hours_worked": 8.0},
        sub_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=422)


def test_extend_requires_long_term_approval_then_succeeds(api, district_admin_headers):
    """PRD 3.5: "if the extension pushes `total_days` strictly past
    `long_term_approval_days` and the absence's `approval_status` is not
    `APPROVED`, the extension is refused outright with
    `ERR_LONG_TERM_APPROVAL_REQUIRED` — get district approval first, extend
    second."
    PRD 3.5: "The extension moves both the assignment's and the absence's
    `end_date`, recomputes `total_days` and `scheduled_days`, recomputes
    `provisional_pay_cents` from the new schedule, and adjusts the school's
    committed budget by the delta."
    PRD 3.3: "Approval moves `approval_status` to `APPROVED` and is permitted
    from `PENDING` or `NOT_REQUIRED`"

    Design: Corner/validations/extend_requires_long_term_approval_then_succeeds
    """
    ctx = worked_assignment_ctx(start_date="2026-08-03", end_date="2026-08-05")
    assert ctx["assignment"]["provisional_pay_cents"] == 60000
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    res = api.extend_assignment(
        ctx["assignment"]["id"], {"new_end_date": "2026-08-10"}, coord_headers
    )
    validate_error(res, ApiErrorId.ERR_LONG_TERM_APPROVAL_REQUIRED, expected_status=409)

    review_absence(ctx["absence"]["id"], "APPROVE")

    extended = validate_success(
        api.extend_assignment(
            ctx["assignment"]["id"], {"new_end_date": "2026-08-10"}, coord_headers
        ),
        200,
    )
    assert extended["scheduled_days"] == 6
    assert extended["provisional_pay_cents"] == 120000

    school = get_school(ctx["school"]["id"])
    assert school["coverage_budget_committed_cents"] == 120000, (
        "delta +60000 applied to the existing 60000 commitment"
    )

    absence = get_absence(ctx["absence"]["id"])
    assert absence["end_date"] == "2026-08-10"
    assert absence["total_days"] == 6


def test_provisional_vs_final_pay_diverge_on_rejected_day(api):
    """PRD 3.4: "From the snapshot comes `provisional_pay_cents`:
    `scheduled_days` times the substitute's `base_daily_rate_cents` scaled by
    the snapshot multiplier, the product rounded half up to integer cents once
    per assignment"
    PRD 3.5: "Verification computes `final_payout_cents` as the sum of the
    per-day `day_pay_cents` over approved sheets — per-day-then-sum is
    authoritative precisely because summing first and rounding once would
    price long-term days differently"
    PRD 3.5: "The provisional figure is thereby replaced: where
    `provisional_pay_cents` was a scheduled-day estimate at premium rates, the
    final payout reflects actually approved days with streak-based long-term
    conversion."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_assignment_pay
    """
    ctx = verified_assignment_ctx(
        start_date="2026-08-03",
        end_date="2026-08-05",
        approved_dates=["2026-08-03", "2026-08-04"],
        rejected_dates=["2026-08-05"],
    )
    assignment = ctx["assignment"]
    assert assignment["status"] == "VERIFIED"
    assert assignment["provisional_pay_cents"] == 60000, (
        "3 scheduled days x round_half_up(20000 x 1.00), frozen at offer time"
    )
    assert assignment["final_payout_cents"] == 40000, (
        "2 approved days at 20000; the rejected Wednesday sheet is excluded"
    )
    assert assignment["provisional_pay_cents"] != assignment["final_payout_cents"]


def test_provisional_vs_final_side_effects_on_absence(api):
    """PRD 3.5: "The assignment's `worked_days_count` refreshes to the number
    of its approved sheets, and `long_term_converted` flips true once any
    approved sheet's `streak_index` has reached the threshold."
    PRD 3.5: "Verification computes `final_payout_cents` as the sum of the
    per-day `day_pay_cents` over approved sheets — per-day-then-sum is
    authoritative precisely because summing first and rounding once would
    price long-term days differently — appends the `COMPLETION` (+1)
    reliability event, increments the completion counters, runs suspension
    evaluation, moves the absence from `ASSIGNED` to `COMPLETED` with
    `days_covered_sub` set to the assignment's `worked_days_count`, and
    recomputes `days_uncovered`."
    PRD 3.6: "The conservation invariant holds at all times: internal days
    plus substitute days plus uncovered days exactly equal `total_days`."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_assignment_pay
    """
    ctx = verified_assignment_ctx(
        start_date="2026-08-03",
        end_date="2026-08-05",
        approved_dates=["2026-08-03", "2026-08-04"],
        rejected_dates=["2026-08-05"],
    )
    assert ctx["assignment"]["worked_days_count"] == 2
    assert ctx["assignment"]["long_term_converted"] is False, (
        "highest streak_index is 2, below the threshold of 10"
    )
    absence = ctx["absence"]
    assert absence["fill_status"] == "COMPLETED"
    assert absence["days_covered_sub"] == 2
    assert absence["days_covered_internal"] == 0
    assert absence["days_uncovered"] == 1


def test_final_payout_per_day_rounding_order(api):
    """PRD 3.5: "Each approved date's `day_pay_cents` is then fixed: when its
    `streak_index` has reached the district's `long_term_threshold_days`, the
    day pays the substitute's `base_daily_rate_cents` scaled by
    `long_term_rate_multiplier`; otherwise it pays the base scaled by the
    offer's `premium_multiplier_snapshot` — each day's amount rounded half up
    to integer cents individually, before any summation."
    PRD 3.5: "Verification computes `final_payout_cents` as the sum of the
    per-day `day_pay_cents` over approved sheets — per-day-then-sum is
    authoritative precisely because summing first and rounding once would
    price long-term days differently"

    Design: Difficulty/combinatorial_formula/final_payout_per_day_rounding_order
    """
    ctx = verified_assignment_ctx(
        start_date="2026-08-03",
        end_date="2026-08-18",
        sub_rate=10002,
        budget=2_000_000,
    )
    ts9 = get_timesheet(ctx["timesheets"][8]["id"])   # 2026-08-13
    ts10 = get_timesheet(ctx["timesheets"][9]["id"])  # 2026-08-14
    assert ts9["streak_index"] == 9
    assert ts9["day_pay_cents"] == 10002, "streak 9 < 10: premium rate 1.00"
    assert ts10["streak_index"] == 10
    assert ts10["day_pay_cents"] == 11502, "round_half_up(10002 x 1.15) = 11502.30 -> 11502"

    assignment = ctx["assignment"]
    assert assignment["long_term_converted"] is True
    assert assignment["final_payout_cents"] == 124524, (
        "9 x 10002 + 3 x 11502 with per-day rounding; sum-then-round would "
        "give 124525"
    )


def test_final_payout_rounding_visible_in_individual_day_pay(api):
    """PRD 3.5: "each day's amount rounded half up to integer cents
    individually, before any summation."
    PRD 2.6: "Where a calculation produces a non-integer, the rounding method
    is always **round half up**. Rounding order is pinned wherever it is
    observable: per-day amounts are rounded first and then summed, never the
    reverse, because the two orders can differ by cents."

    Design: Difficulty/combinatorial_formula/final_payout_per_day_rounding_order
    """
    ctx = verified_assignment_ctx(
        start_date="2026-08-03",
        end_date="2026-08-18",
        sub_rate=10002,
        budget=2_000_000,
    )
    converted_days = [get_timesheet(t["id"]) for t in ctx["timesheets"][9:]]
    assert [t["streak_index"] for t in converted_days] == [10, 11, 12]
    assert all(t["day_pay_cents"] == 11502 for t in converted_days), (
        "each converted day rounds 11502.30 to 11502 individually (3 x 11502 = "
        "34506, not the 34507 sum-then-round would produce)"
    )
    assert ctx["assignment"]["worked_days_count"] == 12


def test_long_term_threshold_nine_day_streak_never_converts(api):
    """PRD 3.1: "an approved-workday streak at or beyond
    `long_term_threshold_days` (10 by default) converts to the long-term rate,
    which is `long_term_rate_multiplier` — 1.15, or 115% of the substitute's
    base rate — applied per converted day."
    PRD 3.5: "The assignment's `worked_days_count` refreshes to the number of
    its approved sheets, and `long_term_converted` flips true once any
    approved sheet's `streak_index` has reached the threshold."

    Design: Difficulty/boundary_precision_check/long_term_conversion_threshold_9_vs_10_days
    """
    ctx = verified_assignment_ctx(start_date="2026-08-03", end_date="2026-08-13")
    assignment = ctx["assignment"]
    assert assignment["worked_days_count"] == 9
    assert assignment["long_term_converted"] is False, (
        "streak tops out at 9 < 10: no conversion"
    )
    last = get_timesheet(ctx["timesheets"][-1]["id"])
    assert last["streak_index"] == 9
    assert last["day_pay_cents"] == 20000, "still the premium rate"
    assert assignment["final_payout_cents"] == 180000, "9 x 20000"


def test_long_term_threshold_ten_day_streak_converts_on_day_ten(api):
    """PRD 3.1: "an approved-workday streak at or beyond
    `long_term_threshold_days` (10 by default) converts to the long-term rate,
    which is `long_term_rate_multiplier` — 1.15, or 115% of the substitute's
    base rate — applied per converted day."
    PRD 3.5: "Each approved date's `day_pay_cents` is then fixed: when its
    `streak_index` has reached the district's `long_term_threshold_days`, the
    day pays the substitute's `base_daily_rate_cents` scaled by
    `long_term_rate_multiplier`; otherwise it pays the base scaled by the
    offer's `premium_multiplier_snapshot` — each day's amount rounded half up
    to integer cents individually, before any summation."

    Design: Difficulty/boundary_precision_check/long_term_conversion_threshold_9_vs_10_days
    """
    ctx = verified_assignment_ctx(start_date="2026-08-03", end_date="2026-08-14")
    ts9 = get_timesheet(ctx["timesheets"][8]["id"])   # 2026-08-13
    ts10 = get_timesheet(ctx["timesheets"][9]["id"])  # 2026-08-14
    assert ts9["streak_index"] == 9
    assert ts9["day_pay_cents"] == 20000, "day 9 is still below the threshold"
    assert ts10["streak_index"] == 10
    assert ts10["day_pay_cents"] == 23000, "round_half_up(20000 x 1.15): the >= 10 day converts"

    assignment = ctx["assignment"]
    assert assignment["long_term_converted"] is True
    assert assignment["final_payout_cents"] == 203000, "9 x 20000 + 23000"
