"""Rules that turn exactly on one minute, one second or one day.

Each test builds its own register through the endpoints the PRD declares,
because the board's database is empty at the start of every test.
"""
from datetime import datetime

from test_helpers import (
    TEST_USERS,
    create_accredited_provider,
    create_attorney,
    create_code_verified_course,
    create_credit_record_payload,
    create_cycle,
    credit_allocation_entry,
    list_fee_assessments,
    make_attorney_headers,
    read_attorney,
    read_credit_record,
    read_cycle,
    read_cycle_summary,
    set_clock,
    validate_success,
)

BOARD_HEADERS = TEST_USERS["board_admin_headers"]


def _instant(value):
    """Parses a wire timestamp so two spellings of the same instant compare."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual, expected, label):
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def build_self_study_pool():
    """One sponsor, three self-study modules whose minutes are chosen so that
    the second claim lands the cycle exactly on the self-study allowance, and
    one attorney with a full two-year period. Returns a dict of the rows."""
    provider = create_accredited_provider(
        name="Prairie State Law Institute", provider_type="LAW_SCHOOL"
    )
    course_a = create_code_verified_course(
        provider, 345, "2026-02-01T09:00:00Z", delivery_format="SELF_STUDY",
        title="Self-Study: Land Use Basics",
        credit_allocations=[credit_allocation_entry("GENERAL", 345)],
    )
    course_b = create_code_verified_course(
        provider, 30, "2026-02-02T09:00:00Z", delivery_format="SELF_STUDY",
        title="Self-Study: Notice Pleading",
        credit_allocations=[credit_allocation_entry("GENERAL", 30)],
    )
    course_c = create_code_verified_course(
        provider, 30, "2026-02-03T09:00:00Z", delivery_format="SELF_STUDY",
        title="Self-Study: Service of Process",
        credit_allocations=[credit_allocation_entry("GENERAL", 30)],
    )
    attorney = create_attorney(
        bar_number="BAR-1010",
        full_name="Yusuf Demirci",
        admission_date="2016-07-01T00:00:00Z",
        compliance_group="GROUP_1",
        principal_office_jurisdiction="ST",
    )
    cycle = create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    assert cycle["required_total_minutes"] == 1800, cycle
    return {
        "provider": provider,
        "course_a": course_a,
        "course_b": course_b,
        "course_c": course_c,
        "attorney": attorney,
        "cycle": cycle,
    }


def claim_self_study(api, attorney, course, attended_minutes, completion_date):
    """Files one attendance-code claim against a self-study module."""
    payload = create_credit_record_payload(
        attorney["id"],
        course["id"],
        verification_method="ATTENDANCE_CODE",
        attendance_code=course["attendance_code"],
        attended_minutes=attended_minutes,
        completion_date=completion_date,
        certificate_reference=None,
    )
    return api.create_credit_record(payload, make_attorney_headers(attorney["id"]))


def test_self_study_claim_that_lands_exactly_on_the_360_minute_allowance_counts(api):
    """A record whose `effective_format` is `SELF_STUDY` has its room reduced to
    the smallest of three quantities: its own credited minutes, the 360-minute
    self-study allowance (6 credit hours per cycle) less self-study minutes
    already used, and the 900-minute non-live allowance (15 credit hours per
    cycle) less non-live minutes already used. Whatever room survives is floored
    at zero, and the result is that record's `countable_minutes`. The records in
    the variant's input set are processed in ascending order of
    `completion_date`, breaking ties by ascending `created_at`. After the record
    is accounted for, the run adds its countable minutes to the overall
    countable total; adds them to the self-study and non-live allowances used
    when its `effective_format` is `SELF_STUDY`; adds them to the on-demand and
    non-live allowances used when its `effective_format` is `ON_DEMAND`; adds
    them to the running live total when its `effective_format` is `LIVE`; and
    adds them to the reciprocity allowance used when its `source` is
    `RECIPROCITY`. An `ON_DEMAND` course always yields `ON_DEMAND`, and a
    `SELF_STUDY` course always yields `SELF_STUDY`. Four bucket fields report
    the **provisional** run's cap consumption: `self_study_used_minutes`,
    `on_demand_used_minutes`, `nonlive_used_minutes` and
    `reciprocity_used_minutes`. Two counts close the payload: `records_counted`
    is the size of the provisional input set, and `records_excluded` is the
    number of the cycle's records in `REJECTED` or `VOIDED`.

    Design: Difficulty/boundary_precision_check/self_study_cap_exactly_at_360_minutes_then_one_record_past_it
    """
    state = build_self_study_pool()
    first = validate_success(
        claim_self_study(
            api, state["attorney"], state["course_a"], 345, "2026-02-05T00:00:00Z"
        ),
        expected_status=201,
    )
    assert first["countable_minutes"] == 345, first

    # The claim that consumes the last fifteen minutes of the allowance.
    second = validate_success(
        claim_self_study(
            api, state["attorney"], state["course_b"], 30, "2026-02-10T00:00:00Z"
        ),
        expected_status=201,
    )

    assert second["credited_minutes"] == 30, second
    assert second["effective_format"] == "SELF_STUDY", second
    assert second["status"] == "VERIFIED", second
    assert read_credit_record(second["id"])["countable_minutes"] == 15, second
    cycle = read_cycle(state["cycle"]["id"])
    assert cycle["earned_countable_minutes"] == 360, cycle
    summary = read_cycle_summary(state["cycle"]["id"])
    assert summary["self_study_used_minutes"] == 360, summary
    assert summary["nonlive_used_minutes"] == 360, summary
    assert summary["records_counted"] == 2, summary


def test_self_study_claim_one_record_past_the_360_minute_allowance_counts_nothing(api):
    """A record whose `effective_format` is `SELF_STUDY` has its room reduced to
    the smallest of three quantities: its own credited minutes, the 360-minute
    self-study allowance (6 credit hours per cycle) less self-study minutes
    already used, and the 900-minute non-live allowance (15 credit hours per
    cycle) less non-live minutes already used. Whatever room survives is floored
    at zero, and the result is that record's `countable_minutes`. The records in
    the variant's input set are processed in ascending order of
    `completion_date`, breaking ties by ascending `created_at`. When every
    record in the input set has been processed, the overall countable total
    becomes `earned_countable_minutes`, the three specialty running totals
    become `earned_ethics_minutes`, `earned_technology_minutes` and
    `earned_bias_minutes`, and the running live total becomes
    `earned_live_minutes`. The effective total for the period is
    `earned_countable_minutes` plus `carryover_in_general_minutes` plus
    `carryover_in_ethics_minutes` — carried-in ethics minutes count toward the
    general requirement as well as their own. The four shortfalls are then: the
    total shortfall, being `required_total_minutes` less the effective total,
    floored at zero; the ethics shortfall, being `required_ethics_minutes` less
    the effective ethics figure, floored at zero; the technology shortfall,
    being `required_technology_minutes` less `earned_technology_minutes`,
    floored at zero; and the bias shortfall, being `required_bias_minutes` less
    `earned_bias_minutes`, floored at zero. Two counts close the payload:
    `records_counted` is the size of the provisional input set, and
    `records_excluded` is the number of the cycle's records in `REJECTED` or
    `VOIDED`.

    Design: Difficulty/boundary_precision_check/self_study_cap_exactly_at_360_minutes_then_one_record_past_it
    """
    state = build_self_study_pool()
    validate_success(
        claim_self_study(
            api, state["attorney"], state["course_a"], 345, "2026-02-05T00:00:00Z"
        ),
        expected_status=201,
    )
    validate_success(
        claim_self_study(
            api, state["attorney"], state["course_b"], 30, "2026-02-10T00:00:00Z"
        ),
        expected_status=201,
    )

    # The allowance is already spent to the minute, so this claim earns nothing.
    third = validate_success(
        claim_self_study(
            api, state["attorney"], state["course_c"], 30, "2026-02-15T00:00:00Z"
        ),
        expected_status=201,
    )

    assert third["credited_minutes"] == 30, third
    assert third["status"] == "VERIFIED", third
    assert read_credit_record(third["id"])["countable_minutes"] == 0, third
    cycle = read_cycle(state["cycle"]["id"])
    assert cycle["earned_countable_minutes"] == 360, cycle
    summary = read_cycle_summary(state["cycle"]["id"])
    assert summary["self_study_used_minutes"] == 360, summary
    assert summary["nonlive_used_minutes"] == 360, summary
    assert summary["records_counted"] == 3, summary
    assert summary["projected_final_deficiency_total_minutes"] == 1440, summary


def build_group_three_period():
    """One attorney in the ninety-one-day filing group with a full two-year
    period whose deadline falls after the clock's startup instant."""
    attorney = create_attorney(
        bar_number="BAR-2020",
        full_name="Constance Mbeki",
        admission_date="2010-02-01T00:00:00Z",
        compliance_group="GROUP_3",
        principal_office_jurisdiction="ST",
    )
    cycle = create_cycle(
        attorney["id"], "2024-06-01T00:00:00Z", "2026-06-01T00:00:00Z"
    )
    assert_same_instant(
        cycle["filing_deadline"], "2026-08-31T00:00:00Z", "filing_deadline"
    )
    assert cycle["required_total_minutes"] == 1800, cycle
    return attorney, cycle


def run_reporting_sweep(api):
    """Executes the board's batch reporting run against the logical clock."""
    return validate_success(
        api.create_reporting_sweep(BOARD_HEADERS), expected_status=201
    )


def take_cycle_to_delinquency(api, cycle):
    """The run standing exactly on the filing deadline, which is what makes the
    period delinquent in the first place."""
    set_clock("2026-08-31T00:00:00Z")
    sweep = run_reporting_sweep(api)
    assert sweep["delinquencies_issued"] == 1, sweep
    delinquent = read_cycle(cycle["id"])
    assert delinquent["administrative_status"] == "DELINQUENT", delinquent
    assert_same_instant(
        delinquent["delinquent_since"], "2026-08-31T00:00:00Z", "delinquent_since"
    )
    return sweep


def test_reporting_run_one_second_before_the_filing_deadline_issues_nothing(api):
    """Finally, `filing_deadline` is `period_end` plus an offset drawn from the
    attorney's `compliance_group`: 31 days for `GROUP_1`, 61 days for `GROUP_2`
    and 91 days for `GROUP_3`. That deadline, not `period_end`, is what a
    delinquency is measured against. Day arithmetic — the roster due date, the
    appeal window, the suspension interval, the grace window, the
    filing-deadline offsets — is UTC calendar-day arithmetic against the logical
    clock. The first: a cycle whose `administrative_status` is `GOOD_STANDING`,
    whose `credit_status` is `OPEN` or `DEFICIENT`, and whose `filing_deadline`
    is at or before the run's `as_of`, moves `administrative_status` from
    `GOOD_STANDING` to `DELINQUENT`. Each run stamps `as_of` with the current
    logical instant and takes a `sweep_number` one higher than the previous
    run's, the first run being number 1. `cycles_examined` counts the cycles the
    run considered.

    Design: Difficulty/boundary_precision_check/sweep_deadline_and_suspension_day_boundaries_are_both_inclusive
    """
    attorney, cycle = build_group_three_period()
    set_clock("2026-08-30T23:59:59Z")

    sweep = run_reporting_sweep(api)

    assert sweep["sweep_number"] == 1, sweep
    assert_same_instant(sweep["as_of"], "2026-08-30T23:59:59Z", "sweep as_of")
    assert sweep["cycles_examined"] == 1, sweep
    assert sweep["delinquencies_issued"] == 0, sweep
    assert sweep["late_fees_assessed_cents"] == 0, sweep
    untouched = read_cycle(cycle["id"])
    assert untouched["administrative_status"] == "GOOD_STANDING", untouched
    assert untouched["delinquent_since"] is None, untouched
    assert read_attorney(attorney["id"])["outstanding_fee_cents"] == 0
    assert list_fee_assessments(attorney_id=attorney["id"]) == []


def test_reporting_run_exactly_on_the_filing_deadline_issues_the_delinquency(api):
    """The first: a cycle whose `administrative_status` is `GOOD_STANDING`,
    whose `credit_status` is `OPEN` or `DEFICIENT`, and whose `filing_deadline`
    is at or before the run's `as_of`, moves `administrative_status` from
    `GOOD_STANDING` to `DELINQUENT`. Its `delinquent_since` is set to the run's
    `as_of` — not to the deadline it missed — and a `FeeAssessment` is created
    with `fee_type` `LATE_COMPLIANCE`, the cycle's `attorney_id` and `cycle_id`,
    an `assessed_by_sweep_id` naming this run, `status` of `ASSESSED` and an
    `amount_cents` derived as described below. That assessment raises the
    attorney's `outstanding_fee_cents` by its `amount_cents`, and the run's
    `delinquencies_issued` and `late_fees_assessed_cents` tallies rise by one
    and by that amount respectively. Each run stamps `as_of` with the current
    logical instant and takes a `sweep_number` one higher than the previous
    run's, the first run being number 1. Step three totals the shortfall across
    all four requirements: the total deficiency plus the ethics, technology and
    elimination-of-bias deficiencies, added together as one number of minutes.
    Step four converts that to whole hours, rounding **up** — one minute short
    is one deficient hour. Step five picks a base amount from the rounded hour
    count: zero hours gives 15000 cents, one to five hours gives 25000, six to
    fifteen gives 40000, and sixteen or more gives 60000. Step six adds a
    surcharge of 2500 cents for each deficient hour, counting at most twenty
    hours. Step seven caps the total: `amount_cents` is the smaller of 100000
    cents and the base plus surcharge.

    Design: Difficulty/boundary_precision_check/sweep_deadline_and_suspension_day_boundaries_are_both_inclusive
    """
    attorney, cycle = build_group_three_period()
    set_clock("2026-08-30T23:59:59Z")
    early = run_reporting_sweep(api)
    assert early["sweep_number"] == 1, early
    assert early["delinquencies_issued"] == 0, early

    set_clock("2026-08-31T00:00:00Z")
    sweep = run_reporting_sweep(api)

    assert sweep["sweep_number"] == 2, sweep
    assert sweep["delinquencies_issued"] == 1, sweep
    assert sweep["late_fees_assessed_cents"] == 100000, sweep
    delinquent = read_cycle(cycle["id"])
    assert delinquent["administrative_status"] == "DELINQUENT", delinquent
    assert_same_instant(
        delinquent["delinquent_since"], "2026-08-31T00:00:00Z", "delinquent_since"
    )
    assessments = list_fee_assessments(attorney_id=attorney["id"])
    assert len(assessments) == 1, assessments
    late_fee = assessments[0]
    assert late_fee["fee_type"] == "LATE_COMPLIANCE", late_fee
    assert late_fee["amount_cents"] == 100000, late_fee
    assert late_fee["status"] == "ASSESSED", late_fee
    assert late_fee["cycle_id"] == cycle["id"], late_fee
    assert late_fee["assessed_by_sweep_id"] == sweep["id"], late_fee
    assert read_attorney(attorney["id"])["outstanding_fee_cents"] == 100000


def test_reporting_run_fifty_nine_days_after_the_delinquency_suspends_nobody(api):
    """The second enforcement step: a cycle whose `administrative_status` is
    `DELINQUENT`, whose `credit_status` is `OPEN` or `DEFICIENT`, and whose
    `delinquent_since` is at least 60 days before the run's `as_of`, moves
    `administrative_status` from `DELINQUENT` to `ADMIN_SUSPENDED`. Day
    arithmetic — the roster due date, the appeal window, the suspension
    interval, the grace window, the filing-deadline offsets — is UTC
    calendar-day arithmetic against the logical clock. `ADMIN_SUSPENDED` is
    deliberately unreachable this way — it is written only by the board's batch
    run and cleared only by reinstatement — so a standing change that names
    `ADMIN_SUSPENDED` as its target, or that addresses an attorney already
    sitting in `ADMIN_SUSPENDED`, is rejected with
    `ERR_INVALID_STATE_TRANSITION`.

    Design: Difficulty/boundary_precision_check/sweep_deadline_and_suspension_day_boundaries_are_both_inclusive
    """
    attorney, cycle = build_group_three_period()
    take_cycle_to_delinquency(api, cycle)

    set_clock("2026-10-29T00:00:00Z")
    sweep = run_reporting_sweep(api)

    assert sweep["sweep_number"] == 2, sweep
    assert sweep["suspensions_issued"] == 0, sweep
    assert sweep["delinquencies_issued"] == 0, sweep
    assert sweep["late_fees_assessed_cents"] == 0, sweep
    still_delinquent = read_cycle(cycle["id"])
    assert still_delinquent["administrative_status"] == "DELINQUENT", still_delinquent
    assert_same_instant(
        still_delinquent["delinquent_since"], "2026-08-31T00:00:00Z", "delinquent_since"
    )
    assert read_attorney(attorney["id"])["status"] == "ACTIVE"
    assert read_attorney(attorney["id"])["outstanding_fee_cents"] == 100000


def test_reporting_run_exactly_sixty_days_after_the_delinquency_suspends_the_cycle(api):
    """The second enforcement step: a cycle whose `administrative_status` is
    `DELINQUENT`, whose `credit_status` is `OPEN` or `DEFICIENT`, and whose
    `delinquent_since` is at least 60 days before the run's `as_of`, moves
    `administrative_status` from `DELINQUENT` to `ADMIN_SUSPENDED`. This
    cascades: the attorney's own `status` moves `ACTIVE → ADMIN_SUSPENDED`,
    which is the only way that value is ever written; every reciprocity or
    comity claim of that attorney still in `SUBMITTED` is denied with
    `determination_reason` of `ATTORNEY_ADMIN_SUSPENDED`, as §3.7 notes; and a
    second `FeeAssessment` is created with `fee_type` `REINSTATEMENT` for 50000
    cents, naming the same `attorney_id`, `cycle_id` and `assessed_by_sweep_id`,
    which raises `outstanding_fee_cents` again. The run's `suspensions_issued`
    rises by one and its `late_fees_assessed_cents` rises by the reinstatement
    amount as well — that tally is the run's total money assessed, not its
    late-fee money alone. Day arithmetic — the roster due date, the appeal
    window, the suspension interval, the grace window, the filing-deadline
    offsets — is UTC calendar-day arithmetic against the logical clock.

    Design: Difficulty/boundary_precision_check/sweep_deadline_and_suspension_day_boundaries_are_both_inclusive
    """
    attorney, cycle = build_group_three_period()
    take_cycle_to_delinquency(api, cycle)

    set_clock("2026-10-30T00:00:00Z")
    sweep = run_reporting_sweep(api)

    assert sweep["sweep_number"] == 2, sweep
    assert sweep["suspensions_issued"] == 1, sweep
    assert sweep["late_fees_assessed_cents"] == 50000, sweep
    suspended = read_cycle(cycle["id"])
    assert suspended["administrative_status"] == "ADMIN_SUSPENDED", suspended
    assert read_attorney(attorney["id"])["status"] == "ADMIN_SUSPENDED"
    assert read_attorney(attorney["id"])["outstanding_fee_cents"] == 150000
    reinstatement_fees = list_fee_assessments(
        attorney_id=attorney["id"], fee_type="REINSTATEMENT"
    )
    assert len(reinstatement_fees) == 1, reinstatement_fees
    reinstatement_fee = reinstatement_fees[0]
    assert reinstatement_fee["amount_cents"] == 50000, reinstatement_fee
    assert reinstatement_fee["status"] == "ASSESSED", reinstatement_fee
    assert reinstatement_fee["cycle_id"] == cycle["id"], reinstatement_fee
    assert reinstatement_fee["assessed_by_sweep_id"] == sweep["id"], reinstatement_fee
