"""Input, uniqueness, temporal and cross-entity validation corners.

Every test in this module drives one validation rule of the wetland mitigation
banking API to its boundary: the aggregate ceilings on a release schedule and on
a work plan's standard weights, the milestone window buffer, the three
uniqueness scopes, the recusal gate, the remedial due date, the fiscal gates on
instrument execution and settlement, the easement precondition in front of every
credit release, and the ordering of role, foreign-key and ownership checks.

Each test builds its own world from scratch against an empty database.
"""

from test_helpers import (
    ApiErrorId,
    CANONICAL_PERFORMANCE_STANDARDS,
    CLOCK_EPOCH,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    add_milestone,
    api_client,
    approve_release_payload,
    assert_cents,
    assert_credits,
    assert_score,
    bank_state,
    bank_version,
    claim_milestone,
    create_bank_payload,
    create_milestone_payload,
    create_permittee_payload,
    create_prospectus_payload,
    create_vote_payload,
    create_work_plan_payload,
    get_success_data,
    make_irt_member_headers,
    make_permittee_headers,
    make_program_admin_headers,
    make_sponsor_headers,
    milestone_state,
    open_monitoring_report,
    permittee_state,
    quote_credits,
    record_easement_on_bank,
    register_irt_member,
    register_permittee,
    register_sponsor,
    remedial_action_state,
    remedial_actions_for_report,
    report_state,
    reserve_sale,
    review_report_payload,
    sale_state,
    set_clock,
    setup_approved_prospectus_and_work_plan,
    setup_bank_under_review,
    setup_draft_bank,
    setup_executed_bank,
    setup_sellable_bank,
    submit_monitoring_report,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRST_WINDOW_START = "2026-08-01T00:00:00Z"
FIRST_WINDOW_END = "2026-09-01T00:00:00Z"
SECOND_WINDOW_START = "2027-09-01T00:00:00Z"
SECOND_WINDOW_END = "2027-10-01T00:00:00Z"


def _milestones_of(world):
    """The bank's release schedule as (rows, meta) through the flat list read."""
    return validate_paginated(
        api_client.list_milestones(
            world["sponsor_headers"],
            params={"bank_id": world["bank"]["id"], "limit": 10, "offset": 0},
        )
    )


# ─── The release schedule ceiling of 1.000 ────────────

def test_release_schedule_beyond_one_point_zero_is_rejected():
    """A bank already carrying 0.150 refuses a further milestone of 0.900,
    because the aggregate 1.050 exceeds the authorised fraction, and the refused
    row is never created.

    PRD §3.6: "Summed across all of a bank's milestones — including the one being added — those fractions may not exceed 1.000, and an over-subscription is rejected with `ERR_RELEASE_SCHEDULE_OVERSUBSCRIBED`, because a bank cannot promise to release more credits than it was authorised to generate."
    Design: Corner/validations/release_schedule_sum_at_exactly_one_is_accepted_and_beyond_is_rejected
    """
    set_clock(CLOCK_EPOCH)
    world = setup_executed_bank(record_easement=True)
    add_milestone(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start=FIRST_WINDOW_START,
        window_end=FIRST_WINDOW_END,
    )

    response = api_client.create_milestone(
        create_milestone_payload(
            world["bank"]["id"],
            milestone_code="CONSTRUCTION_COMPLETE",
            release_pct=0.900,
            window_start=SECOND_WINDOW_START,
            window_end=SECOND_WINDOW_END,
        ),
        world["sponsor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_RELEASE_SCHEDULE_OVERSUBSCRIBED, 422)

    rows, meta = _milestones_of(world)
    assert meta["total_count"] == 1, (
        "the refused 0.900 milestone must not have been created; "
        f"schedule holds {meta['total_count']} rows"
    )
    assert [row["release_pct"] for row in rows] == [0.150], (
        f"only the 0.150 milestone may remain, got {[r['release_pct'] for r in rows]}"
    )


def test_release_schedule_summing_to_exactly_one_point_zero_is_accepted():
    """0.150 plus 0.850 sums to exactly 1.000 and is admitted because the
    comparison is an at-most, and the new milestone provisions 83.95 credits.

    PRD §3.6: "Summed across all of a bank's milestones — including the one being added — those fractions may not exceed 1.000, and an over-subscription is rejected with `ERR_RELEASE_SCHEDULE_OVERSUBSCRIBED`, because a bank cannot promise to release more credits than it was authorised to generate."
    PRD §3.6: "That provisional figure is the bank's authorised credit total multiplied by the milestone's release percentage, rounded half up to 2 decimal places."
    Design: Corner/validations/release_schedule_sum_at_exactly_one_is_accepted_and_beyond_is_rejected
    """
    set_clock(CLOCK_EPOCH)
    world = setup_executed_bank(record_easement=True)
    first = add_milestone(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start=FIRST_WINDOW_START,
        window_end=FIRST_WINDOW_END,
    )

    response = api_client.create_milestone(
        create_milestone_payload(
            world["bank"]["id"],
            milestone_code="CONSTRUCTION_COMPLETE",
            release_pct=0.850,
            window_start=SECOND_WINDOW_START,
            window_end=SECOND_WINDOW_END,
        ),
        world["sponsor_headers"],
    )
    second = validate_success(response, 201)

    assert first["release_pct"] == 0.150, "the first milestone keeps its 0.150 fraction"
    assert second["release_pct"] == 0.850, (
        f"expected the accepted milestone at 0.850, got {second['release_pct']}"
    )
    assert_credits(second["provisional_release_credits"], 83.95, "provisional_release_credits")
    assert second["status"] == "PENDING", (
        f"a freshly scheduled milestone opens in PENDING, got {second['status']}"
    )
    assert_credits(second["final_release_credits"], 0.00, "final_release_credits")

    _rows, meta = _milestones_of(world)
    assert meta["total_count"] == 2, (
        f"both milestones must be on the schedule, got {meta['total_count']}"
    )


# ─── The 365-day milestone window buffer ──────────────

def test_milestone_window_buffer_of_364_days_is_rejected():
    """A second window starting 2027-08-31, only 364 days after the first
    window's end of 2026-09-01, is too tightly spaced and is refused.

    PRD §3.6: "Consecutive windows on one bank must additionally be separated by a full year of monitoring: a new milestone's window start must fall no earlier than 365 days after the latest window end already on that bank's schedule, and a separation of exactly 365 days is accepted."
    PRD §3.6: "A tighter spacing is rejected with `ERR_MILESTONE_WINDOW_BUFFER`."
    Design: Corner/validations/milestone_window_buffer_of_exactly_365_days_is_accepted
    """
    set_clock(CLOCK_EPOCH)
    world = setup_executed_bank(record_easement=True)
    add_milestone(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start=FIRST_WINDOW_START,
        window_end=FIRST_WINDOW_END,
    )

    response = api_client.create_milestone(
        create_milestone_payload(
            world["bank"]["id"],
            milestone_code="CONSTRUCTION_COMPLETE",
            release_pct=0.200,
            window_start="2027-08-31T00:00:00Z",
            window_end="2027-09-30T00:00:00Z",
        ),
        world["sponsor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_MILESTONE_WINDOW_BUFFER, 409)

    _rows, meta = _milestones_of(world)
    assert meta["total_count"] == 1, (
        "the too-tightly-spaced milestone must not have been created; "
        f"schedule holds {meta['total_count']} rows"
    )


def test_milestone_window_buffer_of_exactly_365_days_is_accepted():
    """A second window starting 2027-09-01, exactly 365 days after the first
    window's end, clears the buffer and provisions 19.75 credits.

    PRD §3.6: "Consecutive windows on one bank must additionally be separated by a full year of monitoring: a new milestone's window start must fall no earlier than 365 days after the latest window end already on that bank's schedule, and a separation of exactly 365 days is accepted."
    PRD §3.6: "That provisional figure is the bank's authorised credit total multiplied by the milestone's release percentage, rounded half up to 2 decimal places."
    Design: Corner/validations/milestone_window_buffer_of_exactly_365_days_is_accepted
    """
    set_clock(CLOCK_EPOCH)
    world = setup_executed_bank(record_easement=True)
    add_milestone(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start=FIRST_WINDOW_START,
        window_end=FIRST_WINDOW_END,
    )

    response = api_client.create_milestone(
        create_milestone_payload(
            world["bank"]["id"],
            milestone_code="CONSTRUCTION_COMPLETE",
            release_pct=0.200,
            window_start=SECOND_WINDOW_START,
            window_end=SECOND_WINDOW_END,
        ),
        world["sponsor_headers"],
    )
    second = validate_success(response, 201)

    assert second["window_start"].startswith("2027-09-01T00:00:00"), (
        f"expected the accepted window to start 2027-09-01, got {second['window_start']}"
    )
    assert_credits(second["provisional_release_credits"], 19.75, "provisional_release_credits")
    assert second["status"] == "PENDING", (
        f"a freshly scheduled milestone opens in PENDING, got {second['status']}"
    )

    _rows, meta = _milestones_of(world)
    assert meta["total_count"] == 2, (
        f"both milestones must be on the schedule, got {meta['total_count']}"
    )


# ─── One 409 per uniqueness scope ─────────────────────

def test_second_vote_by_the_same_member_in_the_same_round_is_rejected():
    """A member who has already recorded a position in the current revision round
    cannot record a second one, and the refused OBJECT leaves the tallies alone.

    PRD §3.3: "One vote per member per prospectus per round is allowed; a second attempt in the same round is rejected with `ERR_DUPLICATE_VOTE`."
    Design: Corner/validations/duplicate_key_constraints_are_rejected_per_collection
    """
    set_clock(CLOCK_EPOCH)
    world = setup_bank_under_review(
        work_plan_state="SUBMITTED", vote_positions=["CONCUR", "CONCUR", "CONCUR"]
    )

    response = api_client.create_prospectus_vote(
        world["prospectus"]["id"],
        create_vote_payload("OBJECT"),
        world["member_headers"][0],
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_VOTE, 409)

    votes, meta = validate_paginated(
        api_client.list_prospectus_votes(
            world["prospectus"]["id"],
            world["chair_headers"],
            params={"limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 3, (
        f"the refused vote must not have been recorded, got {meta['total_count']} votes"
    )
    assert all(vote["position"] != "OBJECT" for vote in votes), (
        f"no OBJECT vote may exist, got {[v['position'] for v in votes]}"
    )

    prospectus = get_success_data(
        api_client.get_prospectus(world["prospectus"]["id"], world["chair_headers"])
    )
    assert prospectus["concur_count"] == 3, (
        f"expected concur_count 3, got {prospectus['concur_count']}"
    )
    assert prospectus["object_count"] == 0, (
        f"the refused OBJECT must not raise the object tally, got {prospectus['object_count']}"
    )
    assert prospectus["veto_recorded"] is False, (
        "the refused veto vote must leave veto_recorded false"
    )


def test_second_permittee_reusing_a_permit_number_is_rejected():
    """The Corps permit identifier is globally unique across permit holders, so a
    second registration carrying COE-2026-00417 is refused.

    PRD §3.1: "The permit number is the Corps permit identifier and must match the shape of three uppercase letters, a hyphen, four decimal digits, a hyphen and five decimal digits; it is globally unique across all permit holders, and a repeat registration is rejected with `ERR_DUPLICATE_PERMIT_NUMBER`."
    Design: Corner/validations/duplicate_key_constraints_are_rejected_per_collection
    """
    set_clock(CLOCK_EPOCH)
    first = register_permittee(
        organization_name="Delta Logistics Park",
        permit_number="COE-2026-00417",
        impact_huc8_code="03130002",
        required_credits=20.00,
    )

    response = api_client.create_permittee(
        create_permittee_payload(
            organization_name="Delta Logistics Park Phase II",
            permit_number="COE-2026-00417",
            impact_huc8_code="03130003",
            required_credits=5.00,
        ),
        make_program_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_PERMIT_NUMBER, 409)

    held = get_success_data(
        api_client.get_permittee(first["id"], make_permittee_headers(first["id"]))
    )
    assert held["organization_name"] == "Delta Logistics Park", (
        "the incumbent permit holder must be untouched by the refused registration"
    )
    assert_credits(held["required_credits"], 20.00, "required_credits")


def test_second_milestone_reusing_a_code_on_one_bank_is_rejected():
    """A milestone code is unique within its bank, so a second
    INSTRUMENT_EXECUTION on the same bank is refused even with a lawful fraction
    and a lawfully spaced window.

    PRD §3.6: "The milestone code is one of `INSTRUMENT_EXECUTION`, `CONSTRUCTION_COMPLETE`, `PERF_YEAR_3`, `PERF_YEAR_5` or `PERF_YEAR_10`, and it must be unique within its bank; a repeat is rejected with `ERR_DUPLICATE_MILESTONE_CODE`."
    Design: Corner/validations/duplicate_key_constraints_are_rejected_per_collection
    """
    set_clock(CLOCK_EPOCH)
    world = setup_executed_bank(record_easement=True)
    add_milestone(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start=FIRST_WINDOW_START,
        window_end=FIRST_WINDOW_END,
    )

    response = api_client.create_milestone(
        create_milestone_payload(
            world["bank"]["id"],
            milestone_code="INSTRUMENT_EXECUTION",
            release_pct=0.100,
            window_start=SECOND_WINDOW_START,
            window_end=SECOND_WINDOW_END,
        ),
        world["sponsor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_MILESTONE_CODE, 409)

    _rows, meta = _milestones_of(world)
    assert meta["total_count"] == 1, (
        f"the duplicate milestone code must not have been created, got {meta['total_count']}"
    )


# ─── The standard-weight vector must sum to 1.000 ─────

def _standards_summing_to(*weights):
    """The canonical four standards with their weights overridden in order."""
    standards = [dict(entry) for entry in CANONICAL_PERFORMANCE_STANDARDS]
    for entry, weight in zip(standards, weights):
        entry["weight"] = weight
    return standards


def test_work_plan_whose_standard_weights_sum_below_one_is_rejected():
    """A plan whose four weights sum to 0.900 rather than 1.000 is refused, and
    no work plan row is created for the bank.

    PRD §3.4: "The weights across a plan's standards must sum to exactly 1.000; any other sum is rejected with `ERR_STANDARD_WEIGHTS_INVALID`."
    Design: Corner/validations/standard_weights_not_summing_to_one_are_rejected
    """
    set_clock(CLOCK_EPOCH)
    world = setup_draft_bank()

    response = api_client.create_work_plan(
        create_work_plan_payload(
            world["bank"]["id"],
            performance_standards=_standards_summing_to(0.300, 0.250, 0.300, 0.050),
        ),
        world["sponsor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STANDARD_WEIGHTS_INVALID, 422)

    _rows, meta = validate_paginated(
        api_client.list_bank_work_plans(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused plan must not have been created, got {meta['total_count']} work plans"
    )


def test_work_plan_whose_standard_weights_sum_to_one_is_accepted_as_a_draft():
    """Correcting the fourth weight back to 0.150 makes the vector sum to 1.000
    and the plan is drafted with 98.77 planned credits, materialising no
    performance standards yet.

    PRD §3.4: "The weights across a plan's standards must sum to exactly 1.000; any other sum is rejected with `ERR_STANDARD_WEIGHTS_INVALID`."
    PRD §3.4: "Each stratum's credit contribution is its acreage multiplied by its lift factor, rounded half up to 2 decimal places, and the plan total is the sum of those already-rounded per-stratum contributions."
    Design: Corner/validations/standard_weights_not_summing_to_one_are_rejected
    """
    set_clock(CLOCK_EPOCH)
    world = setup_draft_bank()

    refused = api_client.create_work_plan(
        create_work_plan_payload(
            world["bank"]["id"],
            performance_standards=_standards_summing_to(0.300, 0.250, 0.300, 0.050),
        ),
        world["sponsor_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_STANDARD_WEIGHTS_INVALID, 422)

    accepted = validate_success(
        api_client.create_work_plan(
            create_work_plan_payload(
                world["bank"]["id"],
                performance_standards=_standards_summing_to(0.300, 0.250, 0.300, 0.150),
            ),
            world["sponsor_headers"],
        ),
        201,
    )
    assert_credits(accepted["total_planned_credits"], 98.77, "total_planned_credits")
    assert accepted["status"] == "DRAFT", (
        f"a freshly drafted plan opens in DRAFT, got {accepted['status']}"
    )
    assert accepted["submitted_at"] is None, (
        f"submitted_at must open null, got {accepted['submitted_at']}"
    )

    _rows, meta = validate_paginated(
        api_client.list_bank_performance_standards(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, (
        "performance standards materialise only when the plan is approved, "
        f"got {meta['total_count']} rows"
    )


# ─── One approved work plan per bank, enforced at drafting ──

SECOND_PLAN_OVERRIDES = {
    "hydrology_restoration_acres": 100.00,
    "planting_acres": 50.00,
    "invasive_control_acres": 10.00,
    "invasive_control_protocol": "MECHANICAL",
    "credit_strata": [
        {"stratum_code": "EMERGENT_MARSH", "acres": 40.00, "lift_factor": 0.500}
    ],
    "performance_standards": [
        {
            "standard_code": "HYDROPERIOD_DAYS",
            "comparator": "GTE",
            "threshold_value": 130,
            "weight": 1.000,
            "effective_from_year": 1,
        }
    ],
}


def test_drafting_a_second_work_plan_after_approval_is_rejected():
    """Once a bank's plan is APPROVED the guard fires at creation time, so no
    second DRAFT plan is ever brought into existence.

    PRD §3.4: "Only one plan per bank may ever reach `APPROVED`; drafting a further plan for a bank that already has an approved one is rejected with `ERR_WORK_PLAN_ALREADY_APPROVED`, and so is any attempt to approve a second plan."
    Design: Corner/validations/second_work_plan_after_approval_is_rejected
    """
    set_clock(CLOCK_EPOCH)
    world = setup_executed_bank(record_easement=True)

    response = api_client.create_work_plan(
        create_work_plan_payload(world["bank"]["id"], **SECOND_PLAN_OVERRIDES),
        world["sponsor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_WORK_PLAN_ALREADY_APPROVED, 409)

    rows, meta = validate_paginated(
        api_client.list_bank_work_plans(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, (
        f"the bank must still hold exactly one plan, got {meta['total_count']}"
    )
    assert rows[0]["id"] == world["work_plan"]["id"], (
        "the surviving plan must be the originally approved one"
    )
    assert rows[0]["status"] == "APPROVED", (
        f"the surviving plan must still read APPROVED, got {rows[0]['status']}"
    )


def test_refused_second_work_plan_leaves_the_standards_and_authorised_total_intact():
    """The refused plan materialises nothing: the bank keeps the first plan's
    four standards with the HYDROPERIOD_DAYS threshold at 120, and its authorised
    credit total stays at 98.77.

    PRD §3.4: "Only one plan per bank may ever reach `APPROVED`; drafting a further plan for a bank that already has an approved one is rejected with `ERR_WORK_PLAN_ALREADY_APPROVED`, and so is any attempt to approve a second plan."
    PRD §3.5: "The bank's `total_authorized_credits` is set to the approved work plan's planned credit total, and that copy is the only authorised figure the commercial side of the system ever consults."
    Design: Corner/validations/second_work_plan_after_approval_is_rejected
    """
    set_clock(CLOCK_EPOCH)
    world = setup_executed_bank(record_easement=True)

    response = api_client.create_work_plan(
        create_work_plan_payload(world["bank"]["id"], **SECOND_PLAN_OVERRIDES),
        world["sponsor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_WORK_PLAN_ALREADY_APPROVED, 409)

    rows, meta = validate_paginated(
        api_client.list_bank_performance_standards(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 4, (
        f"the first plan's four standards must be the only ones, got {meta['total_count']}"
    )
    hydroperiod = [row for row in rows if row["standard_code"] == "HYDROPERIOD_DAYS"]
    assert len(hydroperiod) == 1, "exactly one HYDROPERIOD_DAYS standard may exist on the bank"
    assert hydroperiod[0]["threshold_value"] == 120, (
        "the refused plan's threshold of 130 must not have overwritten the approved 120, "
        f"got {hydroperiod[0]['threshold_value']}"
    )

    bank = bank_state(world)
    assert_credits(bank["total_authorized_credits"], 98.77, "total_authorized_credits")


# ─── The remedial due date ────────────────────────────

YEAR3_FAILING_MEASUREMENTS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 96},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 20.0},
    {"standard_code": "NATIVE_COVER_PCT", "measured_value": 60.0},
    {"standard_code": "STEM_DENSITY_PER_ACRE", "measured_value": 400},
]


def _bank_with_an_open_remedial_action():
    """A bank whose year-3 report is accepted at 2029-08-15 with a failing
    compliance status, so one remedial action stands OPEN against it."""
    set_clock(CLOCK_EPOCH)
    world = setup_executed_bank(record_easement=True)
    set_clock("2029-08-15T00:00:00Z")
    report = open_monitoring_report(
        world,
        monitoring_year=3,
        window_start="2029-08-01T00:00:00Z",
        window_end="2029-09-01T00:00:00Z",
        measurements_array=YEAR3_FAILING_MEASUREMENTS,
    )
    submit_monitoring_report(world, report["id"])
    accepted = get_success_data(
        api_client.review_monitoring_report(
            report["id"], review_report_payload("ACCEPT"), world["member_headers"][1]
        )
    )
    assert accepted["compliance_status"] == "FAIL", (
        f"the failing year must score FAIL, got {accepted['compliance_status']}"
    )
    actions = remedial_actions_for_report(world, report["id"])
    assert len(actions) == 1, (
        f"the failing acceptance must open exactly one remedial action, got {len(actions)}"
    )
    return world, report, actions[0]


def test_corrective_work_submitted_one_day_past_the_due_date_is_rejected():
    """With due_at at 2030-08-15, a submission on 2030-08-16 is past due and the
    action stays OPEN in its first round with nothing stamped.

    PRD §3.7: "Submitting the work advances the action `OPEN → WORK_SUBMITTED` and stamps `work_submitted_at` with the clock, and it is admissible only while the logical clock has not passed the action's due date — on the due instant itself submission is still accepted, but past it the request is rejected with `ERR_REMEDIAL_PAST_DUE`."
    Design: Corner/validations/corrective_work_submitted_after_the_due_date_is_rejected
    """
    world, _report, action = _bank_with_an_open_remedial_action()

    set_clock("2030-08-16T00:00:00Z")
    response = api_client.submit_remedial_work(action["id"], world["sponsor_headers"])
    validate_error(response, ApiErrorId.ERR_REMEDIAL_PAST_DUE, 409)

    held = remedial_action_state(action["id"], world)
    assert held["status"] == "OPEN", (
        f"a past-due submission must leave the action OPEN, got {held['status']}"
    )
    assert held["round_number"] == 1, (
        f"the round number must not advance, got {held['round_number']}"
    )
    assert held["work_submitted_at"] is None, (
        f"work_submitted_at must stay null, got {held['work_submitted_at']}"
    )
    assert held["cleared_at"] is None, (
        f"cleared_at must stay null, got {held['cleared_at']}"
    )


def test_remedial_due_date_is_the_review_clock_plus_365_days_and_admits_the_due_instant():
    """The action opened at the 2029-08-15 review is due 2030-08-15 and scopes the
    three missed standards, and a submission at exactly that instant is accepted.

    PRD §3.7: "The first hop creates a remedial action against this report. It opens in `OPEN` status with `round_number` at 1, its `monitoring_report_id` naming the failing report, its `opened_at` stamped with the logical clock, its `due_at` set to that clock plus 365 days, and its `corrective_scope` auto-generated as the literal text `REMEDIATE: ` followed by the failed standard codes joined by commas in the same ascending order they were listed in."
    PRD §3.7: "Submitting the work advances the action `OPEN → WORK_SUBMITTED` and stamps `work_submitted_at` with the clock, and it is admissible only while the logical clock has not passed the action's due date — on the due instant itself submission is still accepted, but past it the request is rejected with `ERR_REMEDIAL_PAST_DUE`."
    Design: Corner/validations/corrective_work_submitted_after_the_due_date_is_rejected
    """
    world, _report, action = _bank_with_an_open_remedial_action()

    assert action["due_at"].startswith("2030-08-15T00:00:00"), (
        f"due_at must be the 2029-08-15 review clock plus 365 days, got {action['due_at']}"
    )
    assert (
        action["corrective_scope"]
        == "REMEDIATE: HYDROPERIOD_DAYS,INVASIVE_COVER_PCT,NATIVE_COVER_PCT"
    ), f"unexpected corrective_scope: {action['corrective_scope']}"
    assert bank_state(world)["sales_posture"] == "RESTRICTED", (
        "a bank carrying an OPEN remedial action must read RESTRICTED"
    )

    set_clock("2030-08-15T00:00:00Z")
    submitted = validate_success(
        api_client.submit_remedial_work(action["id"], world["sponsor_headers"]), 200
    )
    assert submitted["status"] == "WORK_SUBMITTED", (
        f"a submission on the due instant is accepted, got {submitted['status']}"
    )


# ─── The recusal gate on votes and report reviews ─────

YEAR1_MEASUREMENTS_AT_THRESHOLD = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 120},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 8.0},
]


def _world_with_a_recused_member_and_a_submitted_report():
    """A fully instrumented bank, a fourth review-team member seated RECUSED, and
    a year-1 monitoring report standing in SUBMITTED at clock 2027-08-15."""
    set_clock(CLOCK_EPOCH)
    world = setup_executed_bank(record_easement=True)
    recused = register_irt_member(agency="USFWS", roster_status="RECUSED")
    assert recused["roster_status"] == "RECUSED", (
        f"the fourth member must be seated RECUSED, got {recused['roster_status']}"
    )
    set_clock("2027-08-15T00:00:00Z")
    report = open_monitoring_report(
        world,
        monitoring_year=1,
        window_start="2027-08-01T00:00:00Z",
        window_end="2027-09-01T00:00:00Z",
        measurements_array=YEAR1_MEASUREMENTS_AT_THRESHOLD,
    )
    submit_monitoring_report(world, report["id"])
    return world, recused, report


def test_recused_member_cannot_record_a_prospectus_vote():
    """The recusal check stands ahead of the prospectus state check, so the
    recused member's vote is refused on recusal and no fourth vote is recorded.

    PRD §2.1: "A member whose `roster_status` is `RECUSED` may neither vote on a prospectus, nor review a monitoring report, nor inspect a remedial action, nor approve a credit release; all four are rejected with `ERR_MEMBER_RECUSED` (HTTP 403)."
    PRD §2.10: "Ownership and standing checks come next, in this order: sponsor ownership (`ERR_NOT_BANK_SPONSOR`), permittee ownership (`ERR_NOT_SALE_PERMITTEE`), then review-team recusal (`ERR_MEMBER_RECUSED`)."
    Design: Corner/validations/recused_member_cannot_vote_or_review
    """
    world, recused, _report = _world_with_a_recused_member_and_a_submitted_report()

    response = api_client.create_prospectus_vote(
        world["prospectus"]["id"],
        create_vote_payload("CONCUR"),
        make_irt_member_headers(recused["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MEMBER_RECUSED, 403)

    _votes, meta = validate_paginated(
        api_client.list_prospectus_votes(
            world["prospectus"]["id"],
            world["chair_headers"],
            params={"limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 3, (
        f"the recused member's vote must not be recorded, got {meta['total_count']} votes"
    )


def test_recused_member_cannot_review_a_monitoring_report():
    """The same recused member cannot score the submitted report either, and the
    report is left in SUBMITTED with no reviewer recorded.

    PRD §2.1: "A member whose `roster_status` is `RECUSED` may neither vote on a prospectus, nor review a monitoring report, nor inspect a remedial action, nor approve a credit release; all four are rejected with `ERR_MEMBER_RECUSED` (HTTP 403)."
    Design: Corner/validations/recused_member_cannot_vote_or_review
    """
    world, recused, report = _world_with_a_recused_member_and_a_submitted_report()

    response = api_client.review_monitoring_report(
        report["id"], review_report_payload("ACCEPT"), make_irt_member_headers(recused["id"])
    )
    validate_error(response, ApiErrorId.ERR_MEMBER_RECUSED, 403)

    held = report_state(report["id"], world)
    assert held["review_status"] == "SUBMITTED", (
        f"the refused review must leave the report SUBMITTED, got {held['review_status']}"
    )
    assert held["reviewed_by_member_id"] is None, (
        f"no reviewer may be recorded, got {held['reviewed_by_member_id']}"
    )
    assert held["compliance_status"] == "UNEVALUATED", (
        f"the refused review performs no scoring, got {held['compliance_status']}"
    )


def test_seated_member_review_after_the_recusal_refusals_succeeds():
    """Nothing but the recusal blocked the review: the identical call by a SEATED
    member accepts and scores the report at 1.0000 with a PASS.

    PRD §3.7: "Accepting is the branch with teeth. The report's review status advances `SUBMITTED → ACCEPTED`, `reviewed_by_member_id` records the acting member, `reviewed_at` is stamped, and the report is scored against the standards effective for its monitoring year."
    PRD §3.7: "The compliance status then follows from those two outputs in order: it is `PASS` when no standard failed, otherwise `PARTIAL` when the attainment score is at least 0.85 — the boundary is inclusive — and otherwise `FAIL`."
    Design: Corner/validations/recused_member_cannot_vote_or_review
    """
    world, recused, report = _world_with_a_recused_member_and_a_submitted_report()

    validate_error(
        api_client.review_monitoring_report(
            report["id"], review_report_payload("ACCEPT"), make_irt_member_headers(recused["id"])
        ),
        ApiErrorId.ERR_MEMBER_RECUSED,
        403,
    )

    accepted = validate_success(
        api_client.review_monitoring_report(
            report["id"], review_report_payload("ACCEPT"), world["member_headers"][1]
        ),
        200,
    )
    assert accepted["review_status"] == "ACCEPTED", (
        f"the seated member's review must accept the report, got {accepted['review_status']}"
    )
    assert accepted["reviewed_by_member_id"] == world["members"][1]["id"], (
        "the accepting member must be recorded as the reviewer"
    )
    assert_score(accepted["attainment_score"], 1.0000)
    assert accepted["compliance_status"] == "PASS", (
        f"both year-1 standards are met, so compliance must be PASS, "
        f"got {accepted['compliance_status']}"
    )
    assert accepted["failed_standard_codes"] == [], (
        f"no standard failed, got {accepted['failed_standard_codes']}"
    )


# ─── The escrow gate in front of settlement ───────────

SHORT_ESCROW_CENTS = 30_000_000
QUOTED_PRICE_FOR_EIGHT_CREDITS_CENTS = 32216400


def _reserved_sale_priced_above_the_escrow_balance():
    """A RESERVED sale for 8.00 credits on the canonical DEPRESSIONAL bank whose
    quoted price of 32216400 cents outruns the buyer's 30000000-cent escrow."""
    set_clock(CLOCK_EPOCH)
    world = setup_sellable_bank(
        permittee_required_credits=20.00,
        permittee_deposit_cents=SHORT_ESCROW_CENTS,
    )
    sale = quote_credits(world, 8.00)
    assert_cents(
        sale["quoted_price_cents"],
        QUOTED_PRICE_FOR_EIGHT_CREDITS_CENTS,
        "quoted_price_cents for 8.00 credits",
    )
    assert_cents(
        permittee_state(world)["escrow_balance_cents"],
        SHORT_ESCROW_CENTS,
        "escrow_balance_cents before settlement",
    )
    reserved = reserve_sale(world, sale["id"])
    assert reserved["status"] == "RESERVED", (
        f"the sale must be on hold before settlement, got {reserved['status']}"
    )
    return world, sale


def test_settlement_short_of_the_executed_price_is_rejected():
    """The buyer holds 30000000 cents against an executed-variant price of
    32216400, so the sponsor's settlement is refused and the sale stays on hold.

    PRD §3.8: "Settlement belongs to the sponsor. It advances the sale `RESERVED → EXECUTED` and requires the bank's posture to be `OPEN` or `SOLD_OUT`, the logical clock to be no later than the hold's expiry instant, and the buyer's escrow balance to be at least the executed-variant price computed for this very request — a shortfall is rejected with `ERR_INSUFFICIENT_ESCROW` and carries HTTP 402."
    Design: Corner/validations/execution_below_the_escrow_balance_is_rejected
    """
    world, sale = _reserved_sale_priced_above_the_escrow_balance()

    response = api_client.execute_credit_sale(sale["id"], world["sponsor_headers"])
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_ESCROW, 402)

    held = sale_state(sale["id"], world)
    assert held["status"] == "RESERVED", (
        f"the refused settlement must leave the sale RESERVED, got {held['status']}"
    )
    assert held["executed_price_cents"] is None, (
        f"no settled price may be stamped, got {held['executed_price_cents']}"
    )
    assert held["executed_at"] is None, (
        f"no settlement instant may be stamped, got {held['executed_at']}"
    )


def test_refused_settlement_appends_no_ledger_pair_and_spends_no_escrow():
    """The HOLD_RELEASED/SOLD pair belongs to a successful settlement only: after
    the refusal the ledger still holds three entries, the escrow is untouched and
    the credits remain on hold rather than sold.

    PRD §3.8: "Settlement belongs to the sponsor. It advances the sale `RESERVED → EXECUTED` and requires the bank's posture to be `OPEN` or `SOLD_OUT`, the logical clock to be no later than the hold's expiry instant, and the buyer's escrow balance to be at least the executed-variant price computed for this very request — a shortfall is rejected with `ERR_INSUFFICIENT_ESCROW` and carries HTTP 402."
    PRD §3.8: "On success the settled price is stamped onto `executed_price_cents`, `executed_at` is stamped with the clock, and **two** ledger entries are appended in a pinned order: first a `HOLD_RELEASED` entry returning the requested credits as a positive delta, then a `SOLD` entry taking the same quantity away as a negative delta."
    Design: Corner/validations/execution_below_the_escrow_balance_is_rejected
    """
    world, sale = _reserved_sale_priced_above_the_escrow_balance()

    validate_error(
        api_client.execute_credit_sale(sale["id"], world["sponsor_headers"]),
        ApiErrorId.ERR_INSUFFICIENT_ESCROW,
        402,
    )

    buyer = permittee_state(world)
    assert_cents(
        buyer["escrow_balance_cents"], 30000000, "escrow_balance_cents after the refusal"
    )
    assert_cents(buyer["deposited_cents"], 30000000, "deposited_cents after the refusal")

    entries, meta = validate_paginated(
        api_client.list_bank_ledger(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 3, (
        f"only GENERATED, RELEASED and HOLD_PLACED may stand on the ledger, "
        f"got {meta['total_count']} entries"
    )
    assert [entry["entry_type"] for entry in entries] == [
        "GENERATED",
        "RELEASED",
        "HOLD_PLACED",
    ], (
        "the refused settlement must append neither HOLD_RELEASED nor SOLD, got "
        f"{[entry['entry_type'] for entry in entries]}"
    )

    bank = bank_state(world)
    assert_credits(bank["credits_on_hold"], 8.00, "credits_on_hold after the refusal")
    assert_credits(bank["credits_sold"], 0.00, "credits_sold after the refusal")
    assert_credits(bank["credits_available"], 6.82, "credits_available after the refusal")


# ─── The performance assurance gate on execution ──────

BOND_ONE_CENT_SHORT = 24_999_999


def _bank_ready_for_execution_with_a_short_bond():
    """An APPROVED prospectus and an APPROVED work plan behind a sponsor whose
    posted assurance is one cent below the 25,000,000-cent floor."""
    set_clock(CLOCK_EPOCH)
    world = setup_approved_prospectus_and_work_plan(sponsor_bond_cents=BOND_ONE_CENT_SHORT)
    assert_cents(
        world["sponsor"]["performance_bond_cents"],
        BOND_ONE_CENT_SHORT,
        "sponsor performance_bond_cents",
    )
    return world


def test_instrument_execution_one_cent_below_the_bond_floor_is_rejected():
    """Everything ecological is in order — prospectus APPROVED, work plan
    APPROVED — yet the chair cannot execute the instrument on a 24999999-cent
    bond, and the bank is left where it stood.

    PRD §3.5: "The bank must have a prospectus in `APPROVED` status, and without one the request is rejected with `ERR_PROSPECTUS_NOT_APPROVED`; it must have a work plan in `APPROVED` status, and without one the request is rejected with `ERR_WORK_PLAN_MISSING`; and the owning sponsor's posted performance assurance must be at least 25,000,000 cents — a quarter of a million dollars — with a shortfall rejected as `ERR_PERFORMANCE_BOND_INSUFFICIENT`."
    Design: Corner/validations/instrument_execution_below_the_minimum_bond_is_rejected
    """
    world = _bank_ready_for_execution_with_a_short_bond()

    response = api_client.execute_instrument(world["bank"]["id"], world["chair_headers"])
    validate_error(response, ApiErrorId.ERR_PERFORMANCE_BOND_INSUFFICIENT, 402)

    bank = bank_state(world)
    assert bank["status"] == "PROSPECTUS_REVIEW", (
        f"the refused execution must leave the bank in PROSPECTUS_REVIEW, got {bank['status']}"
    )
    assert bank["instrument_executed_at"] is None, (
        f"no execution instant may be stamped, got {bank['instrument_executed_at']}"
    )


def test_refused_execution_authorises_no_credits_and_appends_no_ledger_entry():
    """The authorised total, the GENERATED entry and the sales posture all belong
    to a successful execution: after the refusal the bank authorises 0.00 credits,
    its ledger is empty and its posture is still FROZEN.

    PRD §3.5: "The bank's `total_authorized_credits` is set to the approved work plan's planned credit total, and that copy is the only authorised figure the commercial side of the system ever consults."
    PRD §3.5: "A ledger entry of type `GENERATED` is appended, carrying a delta of 0.00 and therefore a balance of 0.00, attributed to the bank itself through a source entity type of `MITIGATION_BANK` and the bank's own identifier, with a memo recording the authorised credit total in the form `INSTRUMENT EXECUTED authorized=<total_authorized_credits>`."
    PRD §2.8: "If the bank's `status` is `DRAFT`, `PROSPECTUS_REVIEW`, `SUSPENDED` or `CLOSED`, the posture is `FROZEN`."
    Design: Corner/validations/instrument_execution_below_the_minimum_bond_is_rejected
    """
    world = _bank_ready_for_execution_with_a_short_bond()

    validate_error(
        api_client.execute_instrument(world["bank"]["id"], world["chair_headers"]),
        ApiErrorId.ERR_PERFORMANCE_BOND_INSUFFICIENT,
        402,
    )

    bank = bank_state(world)
    assert_credits(bank["total_authorized_credits"], 0.00, "total_authorized_credits")
    assert bank["sales_posture"] == "FROZEN", (
        f"a bank still in PROSPECTUS_REVIEW reads FROZEN, got {bank['sales_posture']}"
    )

    _entries, meta = validate_paginated(
        api_client.list_bank_ledger(
            world["bank"]["id"], world["chair_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused execution must append no GENERATED entry, got {meta['total_count']}"
    )


def test_refused_execution_leaves_the_endowment_requirement_as_registered():
    """The 113680000-cent requirement was quantified at registration from the
    4200000-cent annual cost, and the refused execution neither re-derives it
    away nor funds a cent of it.

    PRD §3.2: "Registration is also where the long-term stewardship obligation is first quantified, onto `stewardship_required_cents`."
    PRD §3.2: "The calculation capitalises the annual stewardship cost at a non-wasting payout rate of 3.75 percent: the base endowment is the annual stewardship cost divided by 0.0375, rounded **up** to the next whole cent whatever the remainder."
    PRD §3.2: "The required endowment is the base endowment plus the administrative fee."
    Design: Corner/validations/instrument_execution_below_the_minimum_bond_is_rejected
    """
    world = _bank_ready_for_execution_with_a_short_bond()

    validate_error(
        api_client.execute_instrument(world["bank"]["id"], world["chair_headers"]),
        ApiErrorId.ERR_PERFORMANCE_BOND_INSUFFICIENT,
        402,
    )

    bank = bank_state(world)
    assert_cents(
        bank["stewardship_required_cents"],
        TEST_DEFAULTS["STEWARDSHIP_REQUIRED_CENTS"],
        "stewardship_required_cents",
    )
    assert_cents(bank["stewardship_funded_cents"], 0, "stewardship_funded_cents")


# ─── The easement precondition on every release ────────

def _claimed_milestone_on_a_bank_without_an_easement():
    """An instrumented bank with its endowment at the interim gate but no
    conservation easement recorded, carrying one CLAIMED 0.150 milestone."""
    set_clock(CLOCK_EPOCH)
    world = setup_executed_bank(
        record_easement=False,
        stewardship_funded_cents=TEST_DEFAULTS["STEWARDSHIP_INTERIM_GATE_CENTS"],
    )
    assert world["bank"]["easement_recorded"] is False, (
        "the bank must start with no easement recorded"
    )
    milestone = add_milestone(
        world,
        milestone_code="INSTRUMENT_EXECUTION",
        release_pct=0.150,
        window_start=FIRST_WINDOW_START,
        window_end=FIRST_WINDOW_END,
    )
    claim_milestone(world, milestone["id"])
    return world, milestone


def test_release_approval_without_a_recorded_easement_is_rejected():
    """The claimed milestone cannot be approved while the easement is missing, and
    the refusal leaves the milestone in CLAIMED with nothing released.

    PRD §3.6: "The conservation easement must already be recorded, or the request is rejected with `ERR_EASEMENT_NOT_RECORDED`."
    PRD §2.8: "Otherwise, if the conservation easement has not been recorded, the posture is `RESTRICTED`."
    Design: Corner/validations/release_approval_before_easement_recording_is_rejected
    """
    world, milestone = _claimed_milestone_on_a_bank_without_an_easement()

    response = api_client.approve_milestone_release(
        milestone["id"], approve_release_payload(bank_version(world)), world["member_headers"][0]
    )
    validate_error(response, ApiErrorId.ERR_EASEMENT_NOT_RECORDED, 422)

    held = milestone_state(milestone["id"], world)
    assert held["status"] == "CLAIMED", (
        f"the refused approval must leave the milestone CLAIMED, got {held['status']}"
    )
    assert_credits(held["final_release_credits"], 0.00, "final_release_credits")

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 0.00, "credits_released after the refusal")
    assert bank["sales_posture"] == "RESTRICTED", (
        f"an easement-less bank reads RESTRICTED, got {bank['sales_posture']}"
    )

    _entries, meta = validate_paginated(
        api_client.list_bank_ledger(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the GENERATED entry may stand on the ledger, got {meta['total_count']}"
    )


def test_recording_the_easement_admits_the_same_release_approval():
    """Nothing about the milestone changed: recording the easement is enough for
    the identical approval to release 14.82 credits and open the bank for sales.

    PRD §3.5: "The sponsor supplies a single `deed_reference` — the deed book and page reference under which the easement was recorded — and the server sets `easement_recorded` to true, stamps `easement_recorded_at` with the logical clock, stores the supplied reference into `easement_deed_reference`, recomputes the posture, and increments the bank's `version` by one."
    PRD §3.6: "Approval then advances the milestone `CLAIMED → APPROVED` and performs a compact cascade."
    PRD §3.6: "A ledger entry of type `RELEASED` is appended carrying the final release quantity as a positive delta, attributed through a source entity type of `RELEASE_MILESTONE` and the milestone's own identifier, with a memo naming the release, its milestone code and the attainment factor applied."
    Design: Corner/validations/release_approval_before_easement_recording_is_rejected
    """
    world, milestone = _claimed_milestone_on_a_bank_without_an_easement()

    validate_error(
        api_client.approve_milestone_release(
            milestone["id"],
            approve_release_payload(bank_version(world)),
            world["member_headers"][0],
        ),
        ApiErrorId.ERR_EASEMENT_NOT_RECORDED,
        422,
    )

    recorded = record_easement_on_bank(world, deed_reference="BK4412-PG221")
    assert recorded["easement_recorded"] is True, (
        "recording the easement must raise the easement_recorded flag"
    )
    assert recorded["easement_recorded_at"] is not None, (
        "easement_recorded_at must be stamped with the logical clock"
    )
    assert recorded["easement_recorded_at"].startswith("2026-08-01T00:00:00"), (
        f"easement_recorded_at must carry the clock instant, got {recorded['easement_recorded_at']}"
    )

    approved = validate_success(
        api_client.approve_milestone_release(
            milestone["id"],
            approve_release_payload(bank_version(world)),
            world["member_headers"][0],
        ),
        200,
    )
    assert approved["status"] == "APPROVED", (
        f"the second approval must advance the milestone to APPROVED, got {approved['status']}"
    )
    assert_credits(approved["final_release_credits"], 14.82, "final_release_credits")

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 14.82, "credits_released")
    assert_credits(bank["credits_available"], 14.82, "credits_available")
    assert bank["sales_posture"] == "OPEN", (
        f"a released, easement-backed bank reads OPEN, got {bank['sales_posture']}"
    )

    _entries, meta = validate_paginated(
        api_client.list_bank_ledger(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2, (
        f"the refused approval appended nothing, so exactly two entries stand, "
        f"got {meta['total_count']}"
    )


# ─── Role, body foreign key, then ownership ────────────

def _ghost_bank_payload():
    """A bank registration naming a sponsor identifier that resolves to nothing."""
    return create_bank_payload(
        NON_EXISTENT_UUID,
        site_name="Ghost Flats",
        site_huc8_code="03130009",
        service_area_huc8_codes=["03130009"],
        hgm_class="FLATS",
        annual_stewardship_cost_cents=1000000,
    )


def test_permittee_registering_a_bank_is_refused_on_role_before_the_body_key():
    """A permit holder posting a bank whose `sponsor_id` resolves to nothing is
    turned away on its role, not on the unresolvable foreign key.

    PRD §2.1: "Once authenticated, the caller's role must appear in the authorised-role list of the endpoint being invoked, as tabulated in §4; a role acting outside its list is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.10: "Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorisation against the endpoint's role list (`ERR_ROLE_NOT_PERMITTED`)."
    Design: Corner/validations/role_check_outranks_body_fk_resolution_and_ownership
    """
    set_clock(CLOCK_EPOCH)

    response = api_client.create_bank(
        _ghost_bank_payload(), make_permittee_headers(NON_EXISTENT_UUID)
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)


def test_sponsor_registering_a_bank_for_a_missing_sponsor_is_refused_on_the_body_key():
    """The identical body carried by a Sponsor clears the role gate and then fails
    on foreign-key resolution, which stands ahead of every ownership check.

    PRD §2.10: "Immediately after the path, every foreign key supplied in a request body — `bank_id`, `permittee_id`, `sponsor_id`, `predecessor_milestone_id` — is resolved against live rows, again returning that entity's own not-found code; this applies to the creation of banks, prospectuses, work plans, milestones, monitoring reports and credit sales."
    PRD §2.10: "Ownership and standing checks come next, in this order: sponsor ownership (`ERR_NOT_BANK_SPONSOR`), permittee ownership (`ERR_NOT_SALE_PERMITTEE`), then review-team recusal (`ERR_MEMBER_RECUSED`)."
    Design: Corner/validations/role_check_outranks_body_fk_resolution_and_ownership
    """
    set_clock(CLOCK_EPOCH)

    response = api_client.create_bank(
        _ghost_bank_payload(), make_sponsor_headers(NON_EXISTENT_UUID)
    )
    validate_error(response, ApiErrorId.ERR_SPONSOR_NOT_FOUND, 404)


def test_sponsor_drafting_a_prospectus_on_another_sponsors_bank_is_refused_on_ownership():
    """With both the role gate and the body key satisfied, the third rung fires:
    sponsor B cannot draft a prospectus on sponsor A's bank, and nothing is
    created anywhere.

    PRD §2.1: "Concretely, a Sponsor write is admissible only when the targeted bank's `sponsor_id` equals `X-User-ID` — whether the bank is named directly in the path, reached through the target row's `bank_id`, or reached through the monitoring report that a remedial action was opened against — and a mismatch is rejected with `ERR_NOT_BANK_SPONSOR` (HTTP 403)."
    PRD §2.9: "Whenever a bank enters or leaves `SUSPENDED`, the owning sponsor's `good_standing` is recomputed, and its `banks_count` is maintained as the count of bank rows naming it as sponsor, counted across every status without exception."
    Design: Corner/validations/role_check_outranks_body_fk_resolution_and_ownership
    """
    set_clock(CLOCK_EPOCH)
    world = setup_draft_bank()
    sponsor_b = register_sponsor(
        legal_name="Blackwater Restoration Trust", legal_entity_type="NGO"
    )

    response = api_client.create_prospectus(
        create_prospectus_payload(
            world["bank"]["id"],
            objective_summary="Hostile takeover of a neighbour's bank",
            proposed_credits=10.00,
        ),
        make_sponsor_headers(sponsor_b["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_BANK_SPONSOR, 403)

    _banks, banks_meta = validate_paginated(
        api_client.list_banks(world["admin_headers"], params={"limit": 10, "offset": 0})
    )
    assert banks_meta["total_count"] == 1, (
        f"only sponsor A's bank may exist, got {banks_meta['total_count']} banks"
    )

    _prospectuses, prospectus_meta = validate_paginated(
        api_client.list_bank_prospectuses(
            world["bank"]["id"], world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert prospectus_meta["total_count"] == 0, (
        f"the refused prospectus must not have been created, "
        f"got {prospectus_meta['total_count']}"
    )

    refreshed_b = validate_success(
        api_client.get_sponsor(sponsor_b["id"], make_program_admin_headers()), 200
    )
    assert refreshed_b["banks_count"] == 0, (
        f"sponsor B still holds no bank, got banks_count {refreshed_b['banks_count']}"
    )
