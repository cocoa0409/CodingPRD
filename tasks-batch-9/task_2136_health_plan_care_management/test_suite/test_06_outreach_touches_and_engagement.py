"""Outreach scheduling, the six-step completion, engagement and cadence."""
import pytest

from test_helpers import (
    ApiErrorId, PROGRAM_ADMIN, activate, assert_caseload_points, assert_touch,
    cancel_touch, complete_touch, create_care_manager, create_member, disenroll,
    create_program, create_touch_payload, enroll, make_care_manager_headers,
    make_clinical_reviewer_headers, plan_intervention, read_care_manager,
    read_care_plan, read_enrollment, read_touch, schedule_touch, set_clock,
    setup_active_care_plan, setup_completed_touch_history, setup_draft_care_plan,
    setup_program_and_managers, stratify, submit_plan, validate_error,
    validate_error_is_one_of, validate_paginated, validate_success,
)

FIVE_DAY_WINDOWS = [
    ("2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z"),
    ("2026-08-03T09:00:00Z", "2026-08-03T09:30:00Z"),
    ("2026-08-04T09:00:00Z", "2026-08-04T09:30:00Z"),
    ("2026-08-05T09:00:00Z", "2026-08-05T09:30:00Z"),
    ("2026-08-06T09:00:00Z", "2026-08-06T09:30:00Z"),
]


def _engagement_probe_scenario(external_member_id="MBR-4001"):
    return setup_active_care_plan(
        program_overrides={"name": "Engagement Probe", "min_risk_tier": "LOW"},
        member_overrides={"external_member_id": external_member_id,
                          "full_name": "Ed Marsh", "birth_date": "1966-01-30",
                          "chronic_condition_count": 0},
        goal_specs=[{"domain": "BEHAVIORAL", "description": "Monthly check-in"}],
        plan_title="Engagement plan",
    )


def test_engagement_score_reads_the_cadence_snapshot_not_the_new_tier(api):
    """PRD §3.6: "The expected number of contacts in that window comes from the
    enrollment's `cadence_tier_snapshot` — and from the snapshot only, never from
    the live `cadence_tier` and never from the value step 5 is about to write."
    PRD §3.6: "The contact interval implied by a snapshot of `STANDARD` is 30
    days, of `INTENSIVE` is 14 days, and of `TOC_INTENSIVE` is 7 days. Divide 90
    by that interval, discard any fractional part, and take the larger of the
    result and 1; that is the expected contact count."
    PRD §3.7: "It also refreshes `cadence_tier_snapshot`, which is the only event
    besides activation that does so — an ordinary cadence change during touch
    completion leaves the snapshot alone, which is what keeps the engagement
    denominator stable across a measurement window."

    Design: Difficulty/combinatorial_formula/engagement_denominator_reads_cadence_snapshot_not_current_tier
    """
    scenario = _engagement_probe_scenario()
    enrollment_id = scenario["enrollment"]["id"]
    care_manager_id = scenario["care_manager"]["id"]
    touches = [
        schedule_touch(enrollment_id, care_manager_id,
                       scheduled_start_at=start, scheduled_end_at=end)
        for start, end in FIVE_DAY_WINDOWS
    ]

    outcomes = ["REACHED", "REACHED", "NOT_REACHED", "NOT_REACHED", "NOT_REACHED"]
    for index, outcome in enumerate(outcomes):
        set_clock(FIVE_DAY_WINDOWS[index][0])
        complete_touch(touches[index]["id"], care_manager_id, outcome,
                       "Reviewed plan by phone." if outcome == "REACHED" else None)

    enrollment = read_enrollment(enrollment_id)
    assert enrollment["engagement_score"] == 67, (
        "two reached contacts over the STANDARD denominator of 3 give 67"
    )
    assert enrollment["engagement_score"] != 33, (
        "the INTENSIVE denominator of 6 must not be used"
    )
    assert enrollment["cadence_tier_snapshot"] == "STANDARD"
    assert enrollment["cadence_tier"] == "INTENSIVE"
    assert enrollment["reached_touch_count"] == 2


def test_third_consecutive_failure_disengages_and_suspends_the_plan(api):
    """PRD §3.6: "If `consecutive_failed_outreach_count` is 3 or more, the
    enrollment becomes `DISENGAGED`."
    PRD §3.6: "Entering `DISENGAGED` — from `UNREACHED` or from `AT_RISK` alike —
    moves the enrollment's care plan from `ACTIVE` to `SUSPENDED`, whose
    `compliance_posture` consequently reads `DEFICIENT`."
    PRD §3.6: "Whenever this step actually changes the tier, `acuity_weight_points`
    is recomputed from the tier points and the new cadence multiplier, the owning
    care manager's `assigned_caseload_points` is recomputed as a full sum, and
    their `capacity_status` is refreshed."

    Design: Difficulty/combinatorial_formula/engagement_denominator_reads_cadence_snapshot_not_current_tier
    """
    scenario = _engagement_probe_scenario(external_member_id="MBR-4002")
    enrollment_id = scenario["enrollment"]["id"]
    care_manager_id = scenario["care_manager"]["id"]
    touches = [
        schedule_touch(enrollment_id, care_manager_id,
                       scheduled_start_at=start, scheduled_end_at=end)
        for start, end in FIVE_DAY_WINDOWS
    ]
    outcomes = ["REACHED", "REACHED", "NOT_REACHED", "NOT_REACHED", "NOT_REACHED"]
    for index, outcome in enumerate(outcomes):
        set_clock(FIVE_DAY_WINDOWS[index][0])
        complete_touch(touches[index]["id"], care_manager_id, outcome,
                       "Reviewed plan by phone." if outcome == "REACHED" else None)

    enrollment = read_enrollment(enrollment_id)
    assert enrollment["engagement_status"] == "DISENGAGED"
    assert enrollment["consecutive_failed_outreach_count"] == 3
    assert enrollment["cadence_tier"] == "INTENSIVE"
    assert_caseload_points(enrollment["acuity_weight_points"], 1.5)
    assert_caseload_points(
        read_care_manager(care_manager_id)["assigned_caseload_points"], 1.5
    )

    plan = read_care_plan(scenario["plan"]["id"])
    assert plan["status"] == "SUSPENDED"
    assert plan["compliance_posture"] == "DEFICIENT"


def _cadence_probe_touches(external_member_id):
    scenario = setup_active_care_plan(
        program_overrides={"name": "Cadence Probe", "min_risk_tier": "LOW"},
        member_overrides={"external_member_id": external_member_id,
                          "full_name": "Jo Blake", "birth_date": "1969-05-14",
                          "chronic_condition_count": 0},
        goal_specs=[{"domain": "CLINICAL", "description": "Blood pressure control"}],
        plan_title="Cadence plan",
    )
    enrollment_id = scenario["enrollment"]["id"]
    care_manager_id = scenario["care_manager"]["id"]
    scenario["touches"] = [
        schedule_touch(enrollment_id, care_manager_id,
                       scheduled_start_at=start, scheduled_end_at=end)
        for start, end in FIVE_DAY_WINDOWS[:4]
    ]
    return scenario


def test_engaged_relaxation_extends_the_next_contact_deadline(api):
    """PRD §3.6: "The base instant is the enrollment's `last_reached_touch_at`
    when that is not null, and `activated_at` otherwise."
    PRD §3.6: "Second, relaxation: when `engagement_status` is `ENGAGED` and
    `consecutive_failed_outreach_count` is 0, the interval becomes the smaller of
    45 days and the starting interval plus 7 days."

    Design: Difficulty/combinatorial_formula/next_touch_due_at_nested_clamps_across_three_inputs
    """
    scenario = _cadence_probe_touches("MBR-4101")
    enrollment_id = scenario["enrollment"]["id"]
    care_manager_id = scenario["care_manager"]["id"]
    touches = scenario["touches"]

    set_clock(FIVE_DAY_WINDOWS[0][0])
    complete_touch(touches[0]["id"], care_manager_id, "REACHED",
                   "Initial outreach completed.")
    set_clock(FIVE_DAY_WINDOWS[1][0])
    complete_touch(touches[1]["id"], care_manager_id, "REACHED",
                   "Second outreach completed.")

    after_second = read_enrollment(enrollment_id)
    assert after_second["engagement_status"] == "ENGAGED"
    assert after_second["next_touch_due_at"] == "2026-09-09T09:00:00.000Z", (
        "30 + 7 days off last_reached_touch_at 2026-08-03T09:00:00.000Z"
    )

    set_clock(FIVE_DAY_WINDOWS[2][0])
    complete_touch(touches[2]["id"], care_manager_id, "NOT_REACHED")
    after_third = read_enrollment(enrollment_id)
    assert after_third["next_touch_due_at"] == "2026-09-02T09:00:00.000Z", (
        "one failure removes the relaxation but does not yet escalate"
    )


def test_escalation_overrides_relaxation_after_two_failures(api):
    """PRD §3.6: "First, escalation: when `consecutive_failed_outreach_count` is 2
    or more, the interval becomes the larger of 3 days and half the starting
    interval with any fractional part discarded."
    PRD §3.6: "`next_touch_due_at` is the base instant advanced by the resulting
    whole number of days, with the time-of-day component of the base preserved
    exactly."

    Design: Difficulty/combinatorial_formula/next_touch_due_at_nested_clamps_across_three_inputs
    """
    scenario = _cadence_probe_touches("MBR-4102")
    enrollment_id = scenario["enrollment"]["id"]
    care_manager_id = scenario["care_manager"]["id"]
    touches = scenario["touches"]

    for index, outcome in enumerate(["REACHED", "REACHED", "NOT_REACHED",
                                     "NOT_REACHED"]):
        set_clock(FIVE_DAY_WINDOWS[index][0])
        complete_touch(touches[index]["id"], care_manager_id, outcome,
                       "Outreach completed." if outcome == "REACHED" else None)

    enrollment = read_enrollment(enrollment_id)
    assert enrollment["consecutive_failed_outreach_count"] == 2
    assert enrollment["last_reached_touch_at"] == "2026-08-03T09:00:00.000Z"
    assert enrollment["next_touch_due_at"] == "2026-08-18T09:00:00.000Z", (
        "escalation halves the 30-day interval to 15 days off the same base"
    )
    assert enrollment["cadence_tier"] == "STANDARD"
    assert enrollment["engagement_status"] == "ENGAGED"


def _over_capacity_setting():
    """Manager Y ends up carrying 14.5 points against a 12.0 ceiling.

    Y also carries two ACTIVE enrollments: one whose care plan is ACTIVE and one
    whose only care plan is still DRAFT.
    """
    program = create_program(name="Priority Ladder Program", min_risk_tier="LOW")
    manager_x = create_care_manager(full_name="Rita Nolan", capacity_points=20.0)
    manager_y = create_care_manager(full_name="Dana Ruiz", capacity_points=12.0)

    draft_member = create_member(external_member_id="MBR-1101", full_name="Ann Doyle",
                                 birth_date="1962-04-04", chronic_condition_count=6)
    control_member = create_member(external_member_id="MBR-1103",
                                   full_name="Cyd Nash", birth_date="1970-11-11",
                                   chronic_condition_count=6)
    high_member = create_member(external_member_id="MBR-1102", full_name="Ben Cole",
                                birth_date="1948-10-10", chronic_condition_count=15)
    stratify(draft_member["id"], "CONCURRENT")
    stratify(control_member["id"], "CONCURRENT")
    assert stratify(high_member["id"], "CONCURRENT")["tier"] == "HIGH"

    draft_enrollment = activate(
        enroll(draft_member["id"], program["id"], manager_y["id"])["id"]
    )
    control_enrollment = activate(
        enroll(control_member["id"], program["id"], manager_y["id"])["id"]
    )
    high_enrollment = enroll(high_member["id"], program["id"], manager_y["id"])

    from test_helpers import add_goal, author_plan, review_plan

    control_plan = author_plan(control_enrollment["id"], manager_y["id"],
                               title="Control plan")
    add_goal(control_plan["id"], manager_y["id"], domain="CLINICAL",
             description="Reduce readmissions")
    submit_plan(control_plan["id"], manager_y["id"])
    control_plan = review_plan(control_plan["id"], manager_x["id"], "APPROVE")
    assert control_plan["status"] == "ACTIVE"

    draft_plan = author_plan(draft_enrollment["id"], manager_y["id"],
                             title="Draft plan")
    add_goal(draft_plan["id"], manager_y["id"], domain="CLINICAL",
             description="Medication reconciliation")
    assert draft_plan["status"] == "DRAFT"

    activated_high = activate(high_enrollment["id"])
    assert_caseload_points(activated_high["acuity_weight_points"], 10.5)

    ledger = read_care_manager(manager_y["id"])
    assert_caseload_points(ledger["assigned_caseload_points"], 14.5)
    assert ledger["capacity_status"] == "OVER_CAPACITY"

    return {"manager_x": manager_x, "manager_y": manager_y,
            "control_enrollment": control_enrollment,
            "draft_enrollment": draft_enrollment,
            "draft_plan": draft_plan}


def test_over_capacity_manager_takes_no_new_booking(api):
    """PRD §3.6: "And the named care manager's `capacity_status` must read `OPEN`;
    a manager already carrying more caseload points than their ceiling takes no
    new bookings, and the attempt returns `ERR_CARE_MANAGER_OVER_CAPACITY`."
    PRD §3.4: "It then recomputes the owning manager's `assigned_caseload_points`
    as a full sum and refreshes their `capacity_status` from that new figure — and
    note carefully that activation performs **no** capacity precheck of its own,
    so activating a high-risk enrollment may itself be the event that flips its
    owner to `OVER_CAPACITY`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_when_touch_targets_terminal_enrollment_on_full_manager
    """
    setting = _over_capacity_setting()

    response = api.create_touch(
        create_touch_payload(
            setting["control_enrollment"]["id"], setting["manager_y"]["id"],
            scheduled_start_at="2026-08-05T09:00:00Z",
            scheduled_end_at="2026-08-05T09:30:00Z",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_CARE_MANAGER_OVER_CAPACITY.value)
    assert response.status_code == 409

    _, meta = validate_paginated(
        api.list_touches(PROGRAM_ADMIN,
                         params={"care_manager_id": setting["manager_y"]["id"]})
    )
    assert meta["total_count"] == 0


def test_state_gate_precedes_the_capacity_gate_on_touch_scheduling(api):
    """PRD §2.6: "When a request could fail several checks at once, the service
    reports the failure that comes first in the following fixed ladder. The
    ordering is normative: a request that violates two rules always surfaces the
    earlier one."
    PRD §2.6: "**Cross-entity state gates** — a touch may be scheduled only on an
    enrollment that has a care plan in `ACTIVE` status; a care plan may be
    submitted or reviewed only while its enrollment's `enrollment_status` is
    `ACTIVE`; and an intervention may be created or completed only while its
    owning plan is `ACTIVE`."
    PRD §2.6: "**Fiscal and capacity ceilings, evaluated last** — caseload ceiling
    (`ERR_CASELOAD_WOULD_EXCEED_CAPACITY`), then care-manager capacity posture on
    a new touch (`ERR_CARE_MANAGER_OVER_CAPACITY`), then the program staff-minute
    budget (`ERR_PROGRAM_STAFF_BUDGET_EXCEEDED`), and finally the empty
    auto-assignment pool (`ERR_NO_ELIGIBLE_CARE_MANAGER`)."

    The booking below violates both rungs at once: the enrollment's only care plan
    is still `DRAFT` and the named manager is already over capacity.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_when_touch_targets_terminal_enrollment_on_full_manager
    """
    setting = _over_capacity_setting()

    response = api.create_touch(
        create_touch_payload(
            setting["draft_enrollment"]["id"], setting["manager_y"]["id"],
            scheduled_start_at="2026-08-05T14:00:00Z",
            scheduled_end_at="2026-08-05T14:30:00Z",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_CARE_PLAN_NOT_ACTIVE.value)
    assert response.status_code == 409

    _, meta = validate_paginated(
        api.list_touches(
            PROGRAM_ADMIN,
            params={"enrollment_id": setting["draft_enrollment"]["id"]},
        )
    )
    assert meta["total_count"] == 0


def _window_ladder_scenario():
    scenario = setup_active_care_plan(
        program_overrides={"name": "Window Ladder Program"},
        member_overrides={"external_member_id": "MBR-1301", "full_name": "Kai Frost",
                          "birth_date": "1968-06-30"},
        goal_specs=[{"domain": "CLINICAL", "description": "Weekly vitals"}],
        plan_title="Window plan",
    )
    care_manager_id = scenario["care_manager"]["id"]
    scenario["past_touch"] = schedule_touch(
        scenario["enrollment"]["id"], care_manager_id,
        scheduled_start_at="2026-08-05T09:00:00Z",
        scheduled_end_at="2026-08-05T09:30:00Z",
    )
    set_clock("2026-08-06T00:00:00Z")
    scenario["future_touch"] = schedule_touch(
        scenario["enrollment"]["id"], care_manager_id,
        scheduled_start_at="2026-08-06T09:00:00Z",
        scheduled_end_at="2026-08-06T09:30:00Z",
    )
    return scenario


def test_past_window_precedes_the_calendar_conflict(api):
    """PRD §2.6: "**Temporal rules** — window ordering
    (`ERR_TOUCH_WINDOW_INVALID`, `ERR_SERVICE_WINDOW_INVALID`), then window
    recency (`ERR_TOUCH_WINDOW_IN_PAST`, `ERR_SERVICE_WINDOW_IN_PAST`), then touch
    readiness (`ERR_TOUCH_NOT_YET_DUE`), then measurement-window emptiness
    (`ERR_MEASUREMENT_PERIOD_EMPTY`)."
    PRD §3.6: "and it must not be in the past, meaning `scheduled_start_at` is at
    or after the logical clock's current instant, else `ERR_TOUCH_WINDOW_IN_PAST`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_when_past_window_also_collides
    """
    scenario = _window_ladder_scenario()
    care_manager_id = scenario["care_manager"]["id"]

    response = api.create_touch(
        create_touch_payload(
            scenario["enrollment"]["id"], care_manager_id,
            scheduled_start_at="2026-08-05T09:15:00Z",
            scheduled_end_at="2026-08-05T09:45:00Z",
        ),
        make_care_manager_headers(care_manager_id),
    )
    validate_error(response, ApiErrorId.ERR_TOUCH_WINDOW_IN_PAST.value)
    assert response.status_code == 422
    assert read_touch(scenario["past_touch"]["id"])["status"] == "SCHEDULED"


def test_future_window_that_only_collides_reports_a_slot_conflict(api):
    """PRD §3.6: "The candidate conflicts with an existing touch when the expanded
    start is earlier than that touch's `scheduled_end_at` and that touch's
    `scheduled_start_at` is earlier than the expanded end. Any conflict rejects
    the booking with `ERR_CARE_MANAGER_SLOT_CONFLICT`."
    PRD §2.6: "**Interval and uniqueness constraints** — care-manager calendar
    conflict (`ERR_CARE_MANAGER_SLOT_CONFLICT`), then duplicate open referral
    (`ERR_DUPLICATE_OPEN_REFERRAL`), then community resource concurrency
    (`ERR_RESOURCE_CAPACITY_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_when_past_window_also_collides
    """
    scenario = _window_ladder_scenario()
    care_manager_id = scenario["care_manager"]["id"]

    response = api.create_touch(
        create_touch_payload(
            scenario["enrollment"]["id"], care_manager_id,
            scheduled_start_at="2026-08-06T09:20:00Z",
            scheduled_end_at="2026-08-06T09:50:00Z",
        ),
        make_care_manager_headers(care_manager_id),
    )
    validate_error(response, ApiErrorId.ERR_CARE_MANAGER_SLOT_CONFLICT.value)
    assert response.status_code == 409
    assert read_touch(scenario["future_touch"]["id"])["status"] == "SCHEDULED"


def test_touch_is_refused_while_the_only_care_plan_is_draft(api):
    """PRD §3.6: "The enrollment must have a care plan in `ACTIVE` status — there
    is no outreach against an unapproved plan — else `ERR_CARE_PLAN_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/touch_scheduling_gated_by_care_plan_status
    """
    scenario = setup_draft_care_plan(
        program_overrides={"name": "Plan Gate Program"},
        member_overrides={"external_member_id": "MBR-1701", "full_name": "Ida Cross",
                          "birth_date": "1961-02-20"},
        goal_specs=[{"domain": "CLINICAL", "description": "Daily weights"}],
        plan_title="Gate plan",
    )
    assert scenario["plan"]["status"] == "DRAFT"
    care_manager_id = scenario["care_manager"]["id"]

    response = api.create_touch(
        create_touch_payload(
            scenario["enrollment"]["id"], care_manager_id,
            scheduled_start_at="2026-08-08T10:00:00Z",
            scheduled_end_at="2026-08-08T10:30:00Z",
        ),
        make_care_manager_headers(care_manager_id),
    )
    validate_error(response, ApiErrorId.ERR_CARE_PLAN_NOT_ACTIVE.value)
    assert response.status_code == 409

    _, meta = validate_paginated(
        api.list_touches(PROGRAM_ADMIN,
                         params={"enrollment_id": scenario["enrollment"]["id"]})
    )
    assert meta["total_count"] == 0


def test_identical_touch_is_accepted_once_the_plan_is_approved(api):
    """PRD §3.5: "Approval moves the plan from `PENDING_REVIEW` to `ACTIVE`,
    stamps `approved_at` with the logical clock, sets `review_decision` to
    `APPROVED`, records `reviewed_by_care_manager_id` as the reviewer's
    `X-User-ID`, and computes `next_review_due_at` as `approved_at` advanced by
    the program's `care_plan_review_interval_days` days."
    PRD §3.6: "The enrollment must have a care plan in `ACTIVE` status — there is
    no outreach against an unapproved plan — else `ERR_CARE_PLAN_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/touch_scheduling_gated_by_care_plan_status
    """
    scenario = setup_draft_care_plan(
        program_overrides={"name": "Plan Gate Program"},
        member_overrides={"external_member_id": "MBR-1702", "full_name": "Ida Cross",
                          "birth_date": "1961-02-20"},
        goal_specs=[{"domain": "CLINICAL", "description": "Daily weights"}],
        plan_title="Gate plan",
    )
    care_manager_id = scenario["care_manager"]["id"]
    payload = create_touch_payload(
        scenario["enrollment"]["id"], care_manager_id,
        scheduled_start_at="2026-08-08T10:00:00Z",
        scheduled_end_at="2026-08-08T10:30:00Z",
    )
    author_headers = make_care_manager_headers(care_manager_id)

    blocked = api.create_touch(payload, author_headers)
    validate_error(blocked, ApiErrorId.ERR_CARE_PLAN_NOT_ACTIVE.value)

    submit_plan(scenario["plan"]["id"], care_manager_id)
    approved = validate_success(
        api.review_care_plan(
            scenario["plan"]["id"], {"decision": "APPROVE"},
            make_clinical_reviewer_headers(scenario["reviewer"]["id"]),
        )
    )
    assert approved["status"] == "ACTIVE"

    data = validate_success(api.create_touch(payload, author_headers), 201)
    assert_touch(data)
    assert data["status"] == "SCHEDULED"
    assert data["satisfied_toc_obligation"] is False


def _buffer_scenario(external_member_id):
    scenario = setup_active_care_plan(
        program_overrides={"name": "Calendar Buffer Program"},
        member_overrides={"external_member_id": external_member_id,
                          "full_name": "Zed Novak", "birth_date": "1972-10-10"},
        goal_specs=[{"domain": "CLINICAL", "description": "Symptom monitoring"}],
        plan_title="Buffer plan",
    )
    scenario["base_touch"] = schedule_touch(
        scenario["enrollment"]["id"], scenario["care_manager"]["id"],
        scheduled_start_at="2026-08-10T09:00:00Z",
        scheduled_end_at="2026-08-10T09:30:00Z",
    )
    return scenario


def test_back_to_back_booking_is_rejected_by_the_documentation_buffer(api):
    """PRD §3.6: "Conflict detection therefore expands the *candidate* window by
    15 minutes on each side — 15 minutes earlier than `scheduled_start_at` and 15
    minutes later than `scheduled_end_at` — and tests that expanded window against
    every existing touch on the same `care_manager_id` whose `status` is
    `SCHEDULED`, each taken in its raw unexpanded form."
    PRD §3.6: "Because the comparison is strict on both sides, back-to-back
    booking is rejected: a candidate beginning at the exact instant an existing
    touch ends is expanded 15 minutes backwards and therefore overlaps it."

    Design: Difficulty/resource_temporal_overlap/care_manager_buffered_interval_rejects_back_to_back_touch
    """
    scenario = _buffer_scenario("MBR-2101")
    care_manager_id = scenario["care_manager"]["id"]
    headers = make_care_manager_headers(care_manager_id)

    adjacent = api.create_touch(
        create_touch_payload(
            scenario["enrollment"]["id"], care_manager_id,
            scheduled_start_at="2026-08-10T09:30:00Z",
            scheduled_end_at="2026-08-10T10:00:00Z",
        ),
        headers,
    )
    validate_error(adjacent, ApiErrorId.ERR_CARE_MANAGER_SLOT_CONFLICT.value)
    assert adjacent.status_code == 409

    near_miss = api.create_touch(
        create_touch_payload(
            scenario["enrollment"]["id"], care_manager_id,
            scheduled_start_at="2026-08-10T09:44:00Z",
            scheduled_end_at="2026-08-10T10:14:00Z",
        ),
        headers,
    )
    validate_error(near_miss, ApiErrorId.ERR_CARE_MANAGER_SLOT_CONFLICT.value)
    assert near_miss.status_code == 409

    rows, meta = validate_paginated(
        api.list_touches(PROGRAM_ADMIN,
                         params={"care_manager_id": care_manager_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario["base_touch"]["id"]


def test_smallest_accepted_gap_is_exactly_fifteen_minutes(api):
    """PRD §3.6: "The smallest accepted gap is exactly 15 minutes — a candidate
    beginning exactly 15 minutes after an existing touch's end is accepted."
    PRD §3.6: "Touches in `COMPLETED` or `CANCELLED` release their interval
    entirely and are never occupants."

    Design: Difficulty/resource_temporal_overlap/care_manager_buffered_interval_rejects_back_to_back_touch
    """
    scenario = _buffer_scenario("MBR-2102")
    care_manager_id = scenario["care_manager"]["id"]

    data = validate_success(
        api.create_touch(
            create_touch_payload(
                scenario["enrollment"]["id"], care_manager_id,
                scheduled_start_at="2026-08-10T09:45:00Z",
                scheduled_end_at="2026-08-10T10:15:00Z",
            ),
            make_care_manager_headers(care_manager_id),
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"
    assert read_touch(scenario["base_touch"]["id"])["status"] == "SCHEDULED"


def test_cancelling_a_completed_touch_is_rejected(api):
    """PRD §3.6: "A touch already `COMPLETED` or `CANCELLED` cannot be cancelled
    again, and the attempt returns `ERR_TOUCH_NOT_SCHEDULED`."
    PRD §3.6: "*Step 1 — record the touch.* `status` becomes `COMPLETED`,
    `completed_at` is stamped from the logical clock, `outcome` takes the supplied
    value, and the `documentation_note` is stored."

    Design: Corner/state_machines/touch_cancel_after_completion_returns_touch_not_scheduled
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Touch Guard Program"},
        member_overrides={"external_member_id": "MBR-4401", "full_name": "Tou Tia",
                          "birth_date": "1977-07-07"},
        goal_specs=[{"domain": "CLINICAL", "description": "Guard goal"}],
        plan_title="Touch guard plan",
    )
    care_manager_id = scenario["care_manager"]["id"]
    touch = schedule_touch(scenario["enrollment"]["id"], care_manager_id,
                           scheduled_start_at="2026-08-04T09:00:00Z",
                           scheduled_end_at="2026-08-04T09:30:00Z")
    set_clock("2026-08-04T09:00:00Z")
    completed = complete_touch(touch["id"], care_manager_id, "REACHED",
                               "Spoke with member.")
    assert completed["status"] == "COMPLETED"

    response = api.cancel_touch(
        touch["id"], {"cancel_reason": "Too late."},
        make_care_manager_headers(care_manager_id),
    )
    validate_error(response, ApiErrorId.ERR_TOUCH_NOT_SCHEDULED.value)
    assert response.status_code == 409

    after = read_touch(touch["id"])
    assert after["status"] == "COMPLETED"
    assert after.get("cancel_reason") is None


def test_care_plan_resumes_when_the_member_re_engages(api):
    """PRD §3.6: "Leaving `DISENGAGED` — whether the enrollment lands in `ENGAGED`
    or in `AT_RISK` — moves that same plan from `SUSPENDED` back to `ACTIVE`, and
    its `compliance_posture` is recomputed, reading `AT_RISK` when the plan still
    has one or more goals in `AT_RISK` and `COMPLIANT` when it does not."
    PRD §3.6: "When the `outcome` is `REACHED`, the enrollment's
    `last_reached_touch_at` is set to this touch's `completed_at`, its
    `consecutive_failed_outreach_count` is reset to 0, and its
    `reached_touch_count` increases by one"

    Design: Corner/state_machines/care_plan_resumes_when_member_re_engages_after_disengagement
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Re-engagement Program", "min_risk_tier": "LOW"},
        member_overrides={"external_member_id": "MBR-5101", "full_name": "Ree Engage",
                          "birth_date": "1971-11-21", "chronic_condition_count": 0},
        goal_specs=[{"domain": "BEHAVIORAL", "description": "Regular contact"}],
        plan_title="Re-engagement plan",
    )
    enrollment_id = scenario["enrollment"]["id"]
    care_manager_id = scenario["care_manager"]["id"]
    windows = FIVE_DAY_WINDOWS + [("2026-08-07T09:00:00Z", "2026-08-07T09:30:00Z")]
    touches = [
        schedule_touch(enrollment_id, care_manager_id,
                       scheduled_start_at=start, scheduled_end_at=end)
        for start, end in windows
    ]

    outcomes = ["REACHED", "REACHED", "NOT_REACHED", "NOT_REACHED", "NOT_REACHED"]
    for index, outcome in enumerate(outcomes):
        set_clock(windows[index][0])
        complete_touch(touches[index]["id"], care_manager_id, outcome,
                       f"Contact {index + 1}." if outcome == "REACHED" else None)

    suspended = read_care_plan(scenario["plan"]["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["compliance_posture"] == "DEFICIENT"

    set_clock(windows[5][0])
    complete_touch(touches[5]["id"], care_manager_id, "REACHED",
                   "Member re-engaged.")

    enrollment = read_enrollment(enrollment_id)
    assert enrollment["engagement_status"] == "ENGAGED"
    assert enrollment["engagement_score"] == 100
    assert enrollment["consecutive_failed_outreach_count"] == 0
    assert enrollment["reached_touch_count"] == 3
    assert enrollment["cadence_tier"] == "STANDARD"
    assert_caseload_points(enrollment["acuity_weight_points"], 1.0)
    assert enrollment["next_touch_due_at"] == "2026-09-13T09:00:00.000Z"

    resumed = read_care_plan(scenario["plan"]["id"])
    assert resumed["status"] == "ACTIVE"
    assert resumed["compliance_posture"] == "COMPLIANT"


def test_reached_completion_without_a_contact_note_is_rejected(api):
    """PRD §3.6: "Accreditation requires a contact note for every conversation
    that actually happened, so a completion carrying `REACHED` without a present,
    non-empty `documentation_note` is refused with `ERR_DOCUMENTATION_REQUIRED`; a
    `NOT_REACHED` completion needs no note."

    Design: Corner/validations/reached_touch_without_note_returns_documentation_required
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Documentation Program"},
        member_overrides={"external_member_id": "MBR-6801", "full_name": "Doc Dee",
                          "birth_date": "1970-01-01"},
        goal_specs=[{"domain": "CLINICAL", "description": "Doc goal"}],
        plan_title="Doc plan",
    )
    care_manager_id = scenario["care_manager"]["id"]
    headers = make_care_manager_headers(care_manager_id)
    touch = schedule_touch(scenario["enrollment"]["id"], care_manager_id,
                           scheduled_start_at="2026-08-04T09:00:00Z",
                           scheduled_end_at="2026-08-04T09:30:00Z")
    set_clock("2026-08-04T09:00:00Z")

    response = api.complete_touch(touch["id"], {"outcome": "REACHED"}, headers)
    validate_error(response, ApiErrorId.ERR_DOCUMENTATION_REQUIRED.value)
    assert response.status_code == 422
    assert read_touch(touch["id"])["status"] == "SCHEDULED"

    data = validate_success(
        api.complete_touch(
            touch["id"],
            {"outcome": "REACHED",
             "documentation_note": "Discussed discharge instructions."},
            headers,
        )
    )
    assert data["status"] == "COMPLETED"
    assert data["documentation_note"] == "Discussed discharge instructions."
    assert read_enrollment(scenario["enrollment"]["id"])["reached_touch_count"] == 1


def test_completing_a_touch_before_its_start_instant_is_rejected(api):
    """PRD §3.6: "The touch must be `SCHEDULED`, else `ERR_TOUCH_NOT_SCHEDULED`,
    and its `scheduled_start_at` must already have been reached on the logical
    clock — completing early returns `ERR_TOUCH_NOT_YET_DUE`."

    Design: Corner/validations/touch_completed_before_start_returns_touch_not_yet_due
    """
    scenario = setup_active_care_plan(
        program_overrides={"name": "Not Due Program"},
        member_overrides={"external_member_id": "MBR-6901", "full_name": "Soon Sam",
                          "birth_date": "1970-01-01"},
        goal_specs=[{"domain": "CLINICAL", "description": "Not due goal"}],
        plan_title="Not due plan",
    )
    care_manager_id = scenario["care_manager"]["id"]
    touch = schedule_touch(scenario["enrollment"]["id"], care_manager_id,
                           modality="VIDEO",
                           scheduled_start_at="2026-08-20T09:00:00Z",
                           scheduled_end_at="2026-08-20T09:30:00Z")

    response = api.complete_touch(
        touch["id"], {"outcome": "NOT_REACHED"},
        make_care_manager_headers(care_manager_id),
    )
    validate_error(response, ApiErrorId.ERR_TOUCH_NOT_YET_DUE.value)
    assert response.status_code == 409

    after = read_touch(touch["id"])
    assert after["status"] == "SCHEDULED"
    assert after.get("outcome") is None
    assert read_enrollment(
        scenario["enrollment"]["id"]
    )["consecutive_failed_outreach_count"] == 0


def test_enrollment_listing_filters_by_care_manager_and_status(api):
    """PRD §3.3: "Enrollments may later be listed and narrowed by `member_id`,
    `program_id`, `care_manager_id`, `enrollment_status` or `engagement_status`."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/endpoints/enrollment_list_filters_by_care_manager_and_status
    """
    setting = setup_program_and_managers(
        program_overrides={"name": "Filter Program"},
        manager_overrides={"full_name": "Rita Nolan"},
        reviewer_overrides={"full_name": "Dana Ruiz"},
    )
    manager_a = setting["care_manager"]["id"]
    manager_b = setting["reviewer"]["id"]
    program_id = setting["program"]["id"]

    enrollments = []
    for index, manager_id in enumerate((manager_a, manager_a, manager_b), start=1):
        member = create_member(external_member_id=f"MBR-810{index}",
                               full_name=f"Fil {index}",
                               birth_date=f"1970-01-0{index}",
                               chronic_condition_count=0)
        stratify(member["id"], "CONCURRENT")
        enrollments.append(enroll(member["id"], program_id, manager_id))
    activate(enrollments[0]["id"])

    active_rows, active_meta = validate_paginated(
        api.list_enrollments(PROGRAM_ADMIN,
                             params={"care_manager_id": manager_a,
                                     "enrollment_status": "ACTIVE"})
    )
    assert active_meta["total_count"] == 1
    assert active_rows[0]["id"] == enrollments[0]["id"]

    manager_rows, manager_meta = validate_paginated(
        api.list_enrollments(PROGRAM_ADMIN, params={"care_manager_id": manager_a})
    )
    assert manager_meta["total_count"] == 2
    returned = {row["id"] for row in manager_rows}
    assert returned == {enrollments[0]["id"], enrollments[1]["id"]}
    assert enrollments[2]["id"] not in returned
