"""Enforcement lifecycle: criticism finalization, corrective action plans, consent
orders, publication branches, follow-up scheduling and the ledgers they move.

Every test builds its own state from an empty database through the API the PRD
declares.
"""

from test_helpers import (
    ANALYST,
    EIC,
    SUPERVISING_EXAMINER_ID,
    SUPERVISOR,
    SUPERVISOR_B,
    TEST_DEFAULTS,
    ApiErrorId,
    add_scope_area,
    api_client as api,
    assert_slot_ledger_conserved,
    build_reviews,
    bulk_review,
    corrective_action_plan_payload,
    disposition_data_call,
    issue_criticism,
    issue_data_call,
    lock_scope,
    make_insurer_respondent_headers,
    propose_plan,
    publish_report_payload,
    read_cycle,
    read_data_call,
    read_examination,
    read_insurer,
    read_scope_area,
    record_standard_workpapers,
    respond_to_criticism,
    respond_to_data_call,
    review_file_sample,
    review_plan,
    set_clock,
    setup_area_in_fieldwork,
    setup_cycle_with_selected_targets,
    setup_examination_in_criticism,
    setup_examination_in_negotiation,
    setup_examination_with_executed_order,
    setup_locked_examination,
    systematic_file_references,
    validate_error,
    validate_paginated,
    validate_success,
)

# The canonical claims sample: three MATERIAL error files quantifying 25000,
# 18000 and 7333 cents of harm across ten reviewed files of a 4000-file
# population.  Population extrapolation therefore freezes
# round_half_up(50333 / 10) * 4000 = 5033 * 4000 cents.
EXTRAPOLATED_EXPOSURE_CENTS = 20_132_000


def _drive_examination_to_criticism(exam_id, insurer_id, harm_cents=()):
    """Carry an already-opened examination through fieldwork into CRITICISM.

    Adds one CLAIMS area over a 4000-file population with a ten-file sample,
    locks the scope, issues one data call for the whole population, has the
    carrier produce every record, accepts the production, records both
    workpapers and reviews every drawn file.
    """
    area = add_scope_area(exam_id, "CLAIMS", population_size=4000, sample_size=10)
    lock_scope(exam_id)
    data_call = issue_data_call(
        area["id"], records_requested=4000, response_due_date="2026-09-15"
    )
    respond_to_data_call(data_call["id"], insurer_id, records_received=4000)
    disposition_data_call(data_call["id"], "ACCEPTED")
    record_standard_workpapers(exam_id, "CLAIMS")
    references = systematic_file_references("CLAIMS", 4000, 10)
    bulk_review(data_call["id"], build_reviews(references, harm_cents))
    return {"scope_area": area, "data_call": data_call, "file_references": references}


def test_corrective_action_plan_is_refused_while_the_examination_is_still_in_criticism():
    """A plan proposed from CRITICISM is refused on state grounds, not on the version pin.

    PRD §3.8: "The acting `X-User-ID` must equal the examination's `insurer_id`,
    otherwise `ERR_NOT_EXAM_SUBJECT`; the examination's `status` must be
    `NEGOTIATION`, otherwise `ERR_EXAM_NOT_IN_NEGOTIATION`."

    The pin supplied here is read from the examination immediately before the
    call, so PRD §2.6's `ERR_STALE_EXAMINATION_VERSION` would have passed:
    "If `expected_examination_version` does not equal the examination's current
    `version`, the request is rejected with `ERR_STALE_EXAMINATION_VERSION` and
    HTTP 412."

    Design: Corner/state_machines/corrective_action_plans_are_refused_outside_negotiation
    """
    scenario = setup_examination_in_criticism()
    examination = read_examination(scenario["exam_id"])
    assert examination["status"] == "CRITICISM"

    response = api.propose_corrective_action_plan(
        scenario["exam_id"],
        corrective_action_plan_payload(examination["version"]),
        make_insurer_respondent_headers(scenario["insurer_id"]),
    )
    validate_error(response, ApiErrorId.ERR_EXAM_NOT_IN_NEGOTIATION.value)

    plans, meta = validate_paginated(
        api.list_corrective_action_plans(scenario["exam_id"], SUPERVISOR)
    )
    assert meta["total_count"] == 0, "the rejected proposal must not persist a plan"
    assert plans == []

    after = read_examination(scenario["exam_id"])
    assert after["status"] == "CRITICISM"
    assert after["version"] == examination["version"], (
        "a rejected write leaves the examination version untouched"
    )


def test_publication_is_refused_from_criticism_with_a_sustained_finding_and_from_negotiation():
    """Two structurally opposite refusals share one publication error code.

    PRD §3.10: "Publication from any state other than `CRITICISM` or
    `ORDER_PENDING` is rejected with `ERR_EXAM_NOT_READY_FOR_PUBLICATION`, and so
    is publication from `CRITICISM` when the examination already has one or more
    `SUSTAINED` criticisms — such an examination must route through `NEGOTIATION`
    and an executed order rather than publishing directly."

    PRD §3.7: "It lowers `open_criticism_count` by 1 and lowers
    `pending_restitution_cents` by the criticism's `restitution_exposure_cents`,
    and it leaves `sustained_criticism_count`, `aggregate_restitution_cents` and
    `penalty_units_total` completely untouched — no fiscal accrual of any kind."

    Design: Corner/state_machines/publication_is_refused_from_criticism_with_a_sustained_finding_and_from_negotiation
    """
    scenario = setup_examination_in_criticism()
    material = issue_criticism(
        scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
    )
    minor = issue_criticism(
        scenario["exam_id"],
        scenario["scope_area_id"],
        "MINOR",
        1,
        statute_citation="NRS 686A.310(1)(n)",
    )
    respond_to_criticism(material["id"], scenario["insurer_id"], "DISPUTE")
    finalized = validate_success(
        api.finalize_criticism(
            material["id"],
            {
                "disposition": "SUSTAINED",
                "penalty_units": 20,
                "disposition_note": "Criticism sustained after review of the carrier rebuttal.",
            },
            SUPERVISOR,
        )
    )
    assert finalized["status"] == "SUSTAINED"

    first_attempt = api.publish_report(
        scenario["exam_id"], publish_report_payload(), SUPERVISOR_B
    )
    validate_error(first_attempt, ApiErrorId.ERR_EXAM_NOT_READY_FOR_PUBLICATION.value)

    mid = read_examination(scenario["exam_id"])
    assert mid["status"] == "CRITICISM"
    assert mid["sustained_criticism_count"] == 1
    assert mid["open_criticism_count"] == 1

    respond_to_criticism(minor["id"], scenario["insurer_id"], "CONCUR")
    validate_success(
        api.finalize_criticism(
            minor["id"],
            {
                "disposition": "WITHDRAWN",
                "disposition_note": "Criticism withdrawn: the cited files were documented.",
            },
            SUPERVISOR,
        )
    )

    negotiating = read_examination(scenario["exam_id"])
    assert negotiating["status"] == "NEGOTIATION"
    assert negotiating["open_criticism_count"] == 0
    assert negotiating["pending_restitution_cents"] == 0
    assert negotiating["aggregate_restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS
    assert negotiating["penalty_units_total"] == 20

    second_attempt = api.publish_report(
        scenario["exam_id"], publish_report_payload(), SUPERVISOR_B
    )
    validate_error(second_attempt, ApiErrorId.ERR_EXAM_NOT_READY_FOR_PUBLICATION.value)
    assert read_examination(scenario["exam_id"])["status"] == "NEGOTIATION"


def test_clean_publication_from_criticism_requires_no_order_and_schedules_no_followup():
    """The clean branch closes the areas but creates no follow-up and needs no order.

    PRD §3.10: "The examination advances `CRITICISM → PUBLISHED`, stamps
    `report_published_at` from the logical clock, records the supplied
    `public_summary`, sets `followup_required` to false and leaves
    `followup_due_date` null."

    PRD §3.10: "Every scope area still in `TESTED` moves to `CLOSED`, each with
    its `version` incremented by 1."

    PRD §3.10: "No follow-up examination is created on this branch and no consent
    order was required."

    PRD §3.1: "The three enforcement counters are never client-writable:
    `open_exam_count` tracks the carrier's examinations whose `status` is neither
    `PUBLISHED` nor `ABORTED`; `pending_enforcement_exam_count` tracks those whose
    `status` is `NEGOTIATION` or `ORDER_PENDING`; and
    `lifetime_restitution_ordered_cents` accumulates the `restitution_cents` of
    every consent order on the carrier's examinations that has reached
    `EXECUTED`."

    Design: Corner/state_machines/clean_publication_from_criticism_requires_no_order_and_schedules_no_followup
    """
    scenario = setup_examination_in_criticism(harm_cents=())
    examination = read_examination(scenario["exam_id"])
    assert examination["status"] == "CRITICISM"
    assert examination["open_criticism_count"] == 0
    assert examination["sustained_criticism_count"] == 0

    published = validate_success(
        api.publish_report(scenario["exam_id"], publish_report_payload(), SUPERVISOR_B)
    )
    assert published["status"] == "PUBLISHED"
    assert published["public_summary"] == TEST_DEFAULTS["PUBLIC_SUMMARY"]
    # PRD §2.4: before any client sets it the logical clock reads 2026-08-01T00:00:00Z.
    assert published["report_published_at"].startswith("2026-08-01T00:00:00"), (
        f"report_published_at is stamped from the logical clock, got "
        f"{published['report_published_at']!r}"
    )
    assert published["followup_required"] is False
    assert published["followup_due_date"] is None

    successors, meta = validate_paginated(
        api.list_examinations(
            SUPERVISOR, {"predecessor_exam_id": scenario["exam_id"]}
        )
    )
    assert meta["total_count"] == 0, "the clean branch creates no follow-up examination"
    assert successors == []

    area = read_scope_area(scenario["scope_area_id"])
    assert area["status"] == "CLOSED"
    assert area["error_rate_pct"] == 0.00
    assert area["tolerance_breached"] is False
    assert area["escalation_required"] is False

    insurer = read_insurer(scenario["insurer_id"])
    assert insurer["open_exam_count"] == 0
    assert insurer["pending_enforcement_exam_count"] == 0
    assert insurer["lifetime_restitution_ordered_cents"] == 0


def test_publication_from_order_pending_schedules_an_end_of_month_clamped_followup_examination():
    """An 18-month follow-up off a day-31 publication clamps to 2028-02-29.

    PRD §3.10: "Otherwise the interval is twelve calendar months when the most
    severe sustained criticism is `EGREGIOUS`, eighteen calendar months when it is
    `MATERIAL`, and twenty-four calendar months when it is `MINOR`."

    PRD §3.10: "`followup_due_date` is the date part of the logical clock at
    publication advanced by that many calendar months, clamped to the last day of
    the target month when the day of the month does not exist there — a
    publication on the 31st advancing into a 30-day month lands on the 30th."

    PRD §3.10: "It carries the same `insurer_id`, a `predecessor_exam_id` pointing
    at the examination just published, no `cycle_id`, an `exam_type` of
    `TARGETED_EXAM`, a `mode` of `DESK` regardless of the predecessor's mode, the
    predecessor's `lead_state_code` copied across, a `fieldwork_start_date` equal
    to `followup_due_date`, and a `fieldwork_end_date` sixty days after
    `followup_due_date`."

    PRD §3.10: "The carrier's `pending_enforcement_exam_count` is lowered by 1."

    PRD §3.1: "The three enforcement counters are never client-writable:
    `open_exam_count` tracks the carrier's examinations whose `status` is neither
    `PUBLISHED` nor `ABORTED`; `pending_enforcement_exam_count` tracks those whose
    `status` is `NEGOTIATION` or `ORDER_PENDING`; and
    `lifetime_restitution_ordered_cents` accumulates the `restitution_cents` of
    every consent order on the carrier's examinations that has reached
    `EXECUTED`."

    Design: Corner/state_machines/publication_from_order_pending_schedules_an_end_of_month_clamped_followup_examination
    """
    scenario = setup_examination_with_executed_order(
        penalty_variant="PER_VIOLATION", order_number="NV-MC-2026-0042"
    )
    order = scenario["consent_order"]
    # PRD §3.8: "the gross penalty is the examination's `penalty_units_total`
    # multiplied by 25,000 cents (250 dollars per statutory violation unit)."
    assert order["status"] == "EXECUTED"
    assert order["restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS
    assert order["penalty_gross_cents"] == 500_000
    # PRD §3.8 step three: the 20632000-cent subtotal is below 25,000,000 cents.
    assert order["cooperation_credit_pct"] == 0.05
    assert order["penalty_net_cents"] == 475_000
    assert order["order_total_cents"] == 20_607_000

    clock = set_clock("2026-08-31T00:00:00Z", SUPERVISOR)
    assert clock["data_calls_flagged_overdue"] == 0, (
        "the only data call is already ACCEPTED and cannot be swept out of ISSUED"
    )

    published = validate_success(
        api.publish_report(scenario["exam_id"], publish_report_payload(), SUPERVISOR_B)
    )
    assert published["status"] == "PUBLISHED"
    assert published["followup_required"] is True
    assert published["followup_due_date"] == "2028-02-29", (
        "2026-08-31 plus eighteen calendar months clamps to the last day of "
        "February 2028"
    )

    followups, meta = validate_paginated(
        api.list_examinations(
            SUPERVISOR, {"predecessor_exam_id": scenario["exam_id"]}
        )
    )
    assert meta["total_count"] == 1
    followup = followups[0]
    assert followup["insurer_id"] == scenario["insurer_id"]
    assert followup["predecessor_exam_id"] == scenario["exam_id"]
    assert followup["cycle_id"] is None
    assert followup["exam_type"] == "TARGETED_EXAM"
    assert followup["mode"] == "DESK"
    assert followup["lead_state_code"] == "NV"
    assert followup["status"] == "SCOPING"
    assert followup["fieldwork_start_date"] == "2028-02-29"
    assert followup["fieldwork_end_date"] == "2028-04-29", (
        "sixty days after 2028-02-29 crosses a 31-day March"
    )

    insurer = read_insurer(scenario["insurer_id"])
    assert insurer["open_exam_count"] == 1, (
        "the published examination released its slot and the follow-up took a new one"
    )
    assert insurer["pending_enforcement_exam_count"] == 0
    assert insurer["lifetime_restitution_ordered_cents"] == EXTRAPOLATED_EXPOSURE_CENTS


def test_a_rejected_production_after_one_review_leaves_the_area_in_fieldwork():
    """With one file already reviewed the rejection cascade takes the non-rollback branch.

    PRD §3.4: "And if at least one sample of the area has already been reviewed,
    the area stays in `FIELDWORK` and keeps its samples — only the rejection
    counter moves."

    PRD §3.4: "It raises the examination's `rejected_data_call_count` by 1 in
    every case, and increments the call's `version` by 1."

    PRD §3.4: "The comparison is strict: a gap of exactly three days is accepted,
    a gap of two is not."

    Design: Corner/state_machines/a_rejected_production_after_one_review_leaves_the_area_in_fieldwork
    """
    scenario = setup_area_in_fieldwork()
    first_sample = scenario["file_samples"][0]
    review_file_sample(
        first_sample["id"], "MATERIAL", underpaid_amount_cents=25_000, days_to_pay=61
    )

    # 2026-09-18 is exactly three whole days from the live call's 2026-09-15.
    replacement = issue_data_call(
        scenario["scope_area_id"],
        records_requested=4000,
        response_due_date="2026-09-18",
    )
    respond_to_data_call(replacement["id"], scenario["insurer_id"], records_received=100)
    rejected = disposition_data_call(
        replacement["id"],
        "REJECTED",
        disposition_reason="The supplemental production is not responsive to the request.",
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["samples_drawn_count"] == 0, "rejecting draws no samples at all"

    area = read_scope_area(scenario["scope_area_id"])
    assert area["status"] == "FIELDWORK", (
        "the area must not roll back to PLANNED once a sample has been reviewed"
    )
    assert area["reviewed_sample_count"] == 1
    assert area["error_count"] == 1

    samples, meta = validate_paginated(
        api.list_file_samples(scenario["data_call_id"], EIC)
    )
    assert meta["total_count"] == 10, "not one sample of the accepted call was deleted"
    assert samples[0]["file_reference"] == "CLM-000001"

    accepted_call = read_data_call(scenario["data_call_id"])
    assert accepted_call["status"] == "ACCEPTED"
    assert accepted_call["samples_drawn_count"] == 10

    examination = read_examination(scenario["exam_id"])
    assert examination["rejected_data_call_count"] == 1
    assert examination["status"] == "FIELDWORK", "the examination never rolls back"


def test_the_cycle_closes_when_its_last_examination_publishes():
    """Publishing the cycle's single target releases its slot and closes the cycle.

    PRD §3.2: "When the last examination attributed to the cycle reaches
    `PUBLISHED` or `ABORTED` — that is, when `slots_committed` falls to 0 while
    `selected_target_count` is 1 or more — the cycle advances
    `TARGETS_SELECTED → CLOSED`, stamps `closed_at` from the logical clock and
    increments its `version` by 1."

    PRD §3.2: "Each examination created by selection is stamped with the carrier's
    `insurer_id`, the originating `cycle_id`, an `exam_type` of
    `MARKET_CONDUCT_EXAM`, a `mode` copied from the cycle's `default_exam_mode`, a
    `lead_state_code` of `NV` (the examining department's own state), a
    `fieldwork_start_date` and `fieldwork_end_date` copied from the cycle's
    defaults, and a `status` of `SCOPING`."

    PRD §3.2: "Each creation raises the carrier's `open_exam_count` by 1 and the
    cycle's `slots_committed` by 1, thereby lowering `slots_available` by 1."

    PRD §3.1: "The three enforcement counters are never client-writable:
    `open_exam_count` tracks the carrier's examinations whose `status` is neither
    `PUBLISHED` nor `ABORTED`; `pending_enforcement_exam_count` tracks those whose
    `status` is `NEGOTIATION` or `ORDER_PENDING`; and
    `lifetime_restitution_ordered_cents` accumulates the `restitution_cents` of
    every consent order on the carrier's examinations that has reached
    `EXECUTED`."

    Design: Corner/state_machines/the_cycle_closes_when_its_last_examination_publishes
    """
    scenario = setup_cycle_with_selected_targets(target_slot_capacity=1)

    before = read_cycle(scenario["cycle_id"])
    assert before["status"] == "TARGETS_SELECTED"
    assert before["selected_target_count"] == 1
    assert before["slots_committed"] == 1
    assert before["slots_available"] == 0
    assert_slot_ledger_conserved(before)

    examination = scenario["examination"]
    assert examination["mode"] == "ON_SITE", "copied from the cycle's default_exam_mode"
    assert examination["lead_state_code"] == "NV"
    assert examination["fieldwork_start_date"] == TEST_DEFAULTS["FIELDWORK_START_DATE"]
    assert examination["status"] == "SCOPING"

    _drive_examination_to_criticism(scenario["exam_id"], scenario["insurer_id"])
    published = validate_success(
        api.publish_report(scenario["exam_id"], publish_report_payload(), SUPERVISOR_B)
    )
    assert published["status"] == "PUBLISHED"

    closed = read_cycle(scenario["cycle_id"])
    assert closed["slots_committed"] == 0
    assert closed["slots_available"] == 1
    assert_slot_ledger_conserved(closed)
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"].startswith("2026-08-01T00:00:00"), (
        f"closed_at is stamped from the logical clock, got {closed['closed_at']!r}"
    )

    assert read_insurer(scenario["insurer_id"])["open_exam_count"] == 0


def test_the_clock_sweep_flags_an_overdue_data_call_which_can_still_be_answered():
    """The sweep drives ISSUED to OVERDUE, and OVERDUE is still answerable.

    PRD §3.4: "When the logical clock is moved forward, every data call still in
    `ISSUED` whose `response_due_date` now lies before the new clock date is swept
    `ISSUED → OVERDUE`, each such call's `version` being incremented by 1, and the
    count of swept calls is returned as `data_calls_flagged_overdue`."

    PRD §3.4: "`days_late` is the whole-day difference from `response_due_date` to
    the response date, floored at zero — a response on or before the due date
    yields 0 — and `is_late` is true exactly when `days_late` is 1 or more."

    PRD §3.4: "The lateness penalty is then applied to that **already-rounded**
    figure: half a percentage point is deducted for each day late, the result is
    rounded half up to two decimals again, and the outcome is floored at 0.00
    before being stored as `effective_completeness_pct`."

    Design: Corner/state_machines/the_clock_sweep_flags_an_overdue_data_call_which_can_still_be_answered
    """
    scenario = setup_locked_examination()
    data_call = issue_data_call(
        scenario["scope_area_id"],
        records_requested=4000,
        response_due_date="2026-09-15",
    )
    assert data_call["status"] == "ISSUED"

    clock = set_clock("2026-09-16T00:00:00Z", EIC)
    assert clock["data_calls_flagged_overdue"] == 1
    assert clock["current_utc"].startswith("2026-09-16T00:00:00")

    swept = read_data_call(data_call["id"])
    assert swept["status"] == "OVERDUE"
    assert swept["is_late"] is False, "the sweep does not set the response lateness"
    assert swept["days_late"] == 0

    responded = respond_to_data_call(
        data_call["id"], scenario["insurer_id"], records_received=4000
    )
    assert responded["status"] == "RESPONDED"
    assert responded["is_late"] is True
    assert responded["days_late"] == 1
    assert responded["completeness_pct"] == 100.00
    assert responded["effective_completeness_pct"] == 99.50

    accepted = disposition_data_call(data_call["id"], "ACCEPTED")
    assert accepted["status"] == "ACCEPTED", "99.50 clears the 95.00 acceptance floor"
    assert accepted["sample_draw_interval"] == 400
    assert accepted["samples_drawn_count"] == 10


def test_plan_revision_and_rejection_both_keep_the_examination_in_negotiation():
    """Only APPROVE moves the examination; revision and rejection do not.

    PRD §3.8: "`REQUEST_REVISION` moves the plan to `REVISION_REQUESTED` and
    leaves the examination in `NEGOTIATION`."

    PRD §3.8: "`REJECT` moves the plan to `REJECTED` and likewise leaves the
    examination in `NEGOTIATION`, obliging the carrier to propose a superseding
    plan."

    PRD §3.8: "A new plan opens in `PROPOSED` and supersedes any earlier plan on
    the examination whose `status` is `PROPOSED` or `REVISION_REQUESTED`: that
    earlier plan moves to `SUPERSEDED` and has its `version` incremented by 1, and
    the new plan takes a `revision_round` one greater than the superseded plan's."

    PRD §3.8: "Any of the three records `reviewed_by_user_id` from `X-User-ID` and
    the `review_note`, and increments the plan's `version` by 1."

    Design: Corner/state_machines/plan_revision_and_rejection_both_keep_the_examination_in_negotiation
    """
    scenario = setup_examination_in_negotiation()
    exam_id = scenario["exam_id"]

    first_plan = propose_plan(exam_id, scenario["insurer_id"])
    assert first_plan["status"] == "PROPOSED"
    assert first_plan["revision_round"] == 1

    revised = review_plan(
        first_plan["id"],
        "REQUEST_REVISION",
        review_note="The milestone schedule is not specific enough; refile with dates.",
        headers=SUPERVISOR,
    )
    assert revised["status"] == "REVISION_REQUESTED"
    assert revised["reviewed_by_user_id"] == SUPERVISING_EXAMINER_ID
    assert read_examination(exam_id)["status"] == "NEGOTIATION"

    second_plan = propose_plan(
        exam_id,
        scenario["insurer_id"],
        milestone_count=6,
        completion_due_date="2027-06-30",
        narrative="The carrier refiles with six dated milestones and a named owner.",
    )
    assert second_plan["status"] == "PROPOSED"
    assert second_plan["revision_round"] == 2

    superseded = validate_success(
        api.get_corrective_action_plan(first_plan["id"], SUPERVISOR)
    )
    assert superseded["status"] == "SUPERSEDED"

    rejected = review_plan(
        second_plan["id"],
        "REJECT",
        review_note="The refiled plan still fails to address the rating-file findings.",
        headers=SUPERVISOR,
    )
    assert rejected["status"] == "REJECTED"

    after = read_examination(exam_id)
    assert after["status"] == "NEGOTIATION", (
        "only the APPROVE decision advances the examination to ORDER_PENDING"
    )
    assert after["aggregate_restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS, (
        "plan review has no fiscal side effect"
    )

    plans, meta = validate_paginated(
        api.list_corrective_action_plans(exam_id, SUPERVISOR)
    )
    assert meta["total_count"] == 2
    assert {plan["id"] for plan in plans} == {first_plan["id"], second_plan["id"]}
    for plan in plans:
        assert plan["exam_id"] == exam_id
