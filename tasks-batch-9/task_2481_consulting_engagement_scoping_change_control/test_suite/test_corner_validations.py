"""Field-level and precondition-level refusals, each at its own bound.

Every test here drives one declared validation to its edge, checks the refusal,
and then checks that the neighbouring accepted value really is accepted — a
refusal that fires everywhere is as wrong as one that never fires.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ConsultingApiClient
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_economics_view,
    assert_fields,
    assert_money,
    assert_pagination_meta,
    assert_two_dp,
)

LATE_CLOCK = "2026-09-21T09:00:00Z"
SEED_WEEK_3 = "2026-09-18"
OUTCOME_TARGET_BONUS_CENTS = 30000000
RESCIND_NOTE = "Client withdrew the request before it was assessed"


def test_pagination_bounds_are_refused_before_any_row_is_matched(
    api: ConsultingApiClient,
) -> None:
    """Three bad page windows, then the widest legal one over the same data.

    PRD 2.3: "A `limit` outside the range 1 through 100, a non-integer value for
    either parameter, or a negative `offset` is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/pagination_bounds_rejected_before_any_filtering
    """
    sc = fx.build_screening_pursuit(api)

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        response = api.list_opportunities(sc.partner, params)
        validate_error(response, E.ERR_INVALID_PAGINATION)
        assert response.json()["response_type"] == "error"

    rows, meta = validate_paginated(
        api.list_opportunities(sc.partner, {"limit": 100, "offset": 0})
    )
    assert len(rows) == 1
    assert_pagination_meta(meta, total_count=1, has_more=False)


def test_inverted_date_ranges_are_refused_on_both_windows_that_declare_one(
    api: ConsultingApiClient,
) -> None:
    """A pursuit window must be strictly ordered; a review window may be one day.

    PRD 3.2: "A pursuit whose `target_end_date` is not strictly after its
    `target_start_date` is refused with `ERR_INVALID_DATE_RANGE`; the same
    date-range code guards deliverable creation, deliverable editing and
    quality-checkpoint scheduling."

    PRD 3.9: "A checkpoint is scheduled by either the engagement manager or firm
    leadership, naming the `engagement_id` under review, the
    `reviewer_consultant_id` who will conduct it, the `checkpoint_type` — one of
    `SCOPE_GATE`, `MIDPOINT` or `PRE_DELIVERY` — and a review window given as
    `window_start_date` and `window_end_date`, where the end must fall on or
    after the start."

    Design: Corner/validations/inverted_date_ranges_rejected_on_opportunity_and_review
    """
    sc = fx.build_active_engagement(api)

    validate_error(
        api.create_opportunity(
            F.opportunity_payload(
                sc.client_id,
                sc.partner_id,
                sc.manager_id,
                target_start_date="2026-12-01",
                target_end_date="2026-09-30",
            ),
            sc.partner,
        ),
        E.ERR_INVALID_DATE_RANGE,
    )
    validate_error(
        api.create_quality_review(
            F.quality_review_payload(
                sc.engagement_id,
                sc.reviewer_id,
                window_start_date="2026-10-10",
                window_end_date="2026-10-04",
            ),
            sc.manager,
        ),
        E.ERR_INVALID_DATE_RANGE,
    )

    # A single-day window is not inverted: the end falls on the start
    same_day = fx.schedule_review(
        sc, window_start_date="2026-10-04", window_end_date="2026-10-04"
    )
    assert_fields(
        same_day,
        status=C.REVIEW_SCHEDULED,
        window_start_date="2026-10-04",
        window_end_date="2026-10-04",
    )
    _, meta = validate_paginated(
        api.list_quality_reviews(sc.manager, {"engagement_id": sc.engagement_id})
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)


def test_a_target_start_date_before_the_clock_date_is_refused(
    api: ConsultingApiClient,
) -> None:
    """One day early is refused; the clock date itself is accepted.

    PRD 3.2: "A pursuit whose `target_start_date` falls before the current
    logical clock date is refused with `ERR_TARGET_DATE_IN_PAST`."

    Design: Corner/validations/target_start_date_in_the_past_is_refused
    """
    sc = fx.build_master_data(api)

    validate_error(
        api.create_opportunity(
            F.opportunity_payload(
                sc.client_id,
                sc.partner_id,
                sc.manager_id,
                target_start_date="2026-08-02",
            ),
            sc.partner,
        ),
        E.ERR_TARGET_DATE_IN_PAST,
    )

    row = fx.open_pursuit(sc, target_start_date="2026-08-03")

    assert_fields(row, status="SCREENING", target_start_date="2026-08-03")
    assert_two_dp(row, "qualification_score_intake", 68.00)
    _, meta = validate_paginated(
        api.list_opportunities(sc.partner, {"client_id": sc.client_id})
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)


def test_the_logical_clock_moves_forward_or_stands_still(
    api: ConsultingApiClient,
) -> None:
    """One second back is refused; the same instant and one second on are not.

    PRD 2.6: "The clock is advanced only by a practice administrator supplying a
    `current_utc` instant, and it is forward-only: a submitted value earlier than
    the current value is rejected with `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP 409)."

    PRD 2.6: "Setting the clock to exactly its current value is accepted."

    Design: Corner/validations/logical_clock_is_forward_only
    """
    fx.set_clock(api, C.SEED_CLOCK)
    fx.set_clock(api, C.SEED_DELIVERY_CLOCK)

    validate_error(
        api.set_clock(
            F.clock_payload("2026-09-13T23:59:59Z"), fx.PRACTICE_ADMIN_HEADERS
        ),
        E.ERR_CLOCK_REWIND_FORBIDDEN,
    )

    standing_still = fx.set_clock(api, C.SEED_DELIVERY_CLOCK)
    assert standing_still["current_utc"].startswith("2026-09-14T09:00:00")

    one_second_on = fx.set_clock(api, "2026-09-14T09:00:01Z")
    assert one_second_on["current_utc"].startswith("2026-09-14T09:00:01")


def test_timesheet_hours_are_bounded_at_sixty_and_above_zero(
    api: ConsultingApiClient,
) -> None:
    """60.00 books; 60.01 and 0.00 do not, on weeks that cannot collide.

    PRD 3.7: "`hours` must be greater than 0.00 and at most 60.00; anything
    outside that range is refused with `ERR_TIMESHEET_HOURS_OUT_OF_RANGE`."

    Design: Corner/validations/timesheet_hours_bounds_at_the_sixty_hour_ceiling
    """
    sc = fx.build_started_engagement(api, clock=LATE_CLOCK)

    at_the_ceiling = fx.log_time(sc, 60.0, C.SEED_WEEK_1)
    assert_two_dp(at_the_ceiling, "hours", 60.00)
    assert_money(at_the_ceiling, "cost_cents", 3720000)

    # Distinct weeks, so the duplicate-line rule can never mask the bound
    for week, hours in ((C.SEED_WEEK_2, 60.01), (SEED_WEEK_3, 0.0)):
        validate_error(
            api.create_time_entry(
                F.time_entry_payload(
                    sc.engagement_id, sc.d1_id, sc.partner_id, week, hours
                ),
                sc.partner,
            ),
            E.ERR_TIMESHEET_HOURS_OUT_OF_RANGE,
        )

    rows, meta = validate_paginated(
        api.list_time_entries(sc.manager, {"engagement_id": sc.engagement_id})
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert rows[0]["id"] == at_the_ceiling["id"]


def test_the_engagement_window_check_outranks_the_future_week_check(
    api: ConsultingApiClient,
) -> None:
    """A week both outside the window and in the future reports the window.

    PRD 3.7: "The `week_ending_date` must fall inside the engagement's planned
    delivery window, from `planned_start_date` through `planned_end_date`
    inclusive, otherwise `ERR_TIME_ENTRY_OUTSIDE_ENGAGEMENT_WINDOW`, and it must
    not be later than the current logical clock date, otherwise
    `ERR_FUTURE_TIMESHEET_LINE`."

    Design: Corner/validations/engagement_window_check_outranks_the_future_date_check
    """
    sc = fx.build_started_engagement(api, clock=LATE_CLOCK)
    assert_fields(
        fx.read_engagement(sc),
        planned_start_date=C.SEED_TARGET_START_DATE,
        planned_end_date=C.SEED_TARGET_END_DATE,
    )

    # 2026-12-25 is past the window end and also past the clock
    validate_error(
        api.create_time_entry(
            F.time_entry_payload(
                sc.engagement_id, sc.d1_id, sc.partner_id, "2026-12-25", 8.0
            ),
            sc.partner,
        ),
        E.ERR_TIME_ENTRY_OUTSIDE_ENGAGEMENT_WINDOW,
    )
    # 2026-10-02 is inside the window but still ahead of the clock
    validate_error(
        api.create_time_entry(
            F.time_entry_payload(
                sc.engagement_id, sc.d1_id, sc.partner_id, "2026-10-02", 8.0
            ),
            sc.partner,
        ),
        E.ERR_FUTURE_TIMESHEET_LINE,
    )

    accepted = fx.log_time(sc, 8.0, SEED_WEEK_3)
    assert_fields(
        accepted, week_ending_date=SEED_WEEK_3, status=C.TIME_ENTRY_SUBMITTED
    )
    assert_two_dp(fx.read_engagement(sc), "approved_hours_burned", 0.00)


def test_a_rejected_line_stops_blocking_the_week_it_occupied(
    api: ConsultingApiClient,
) -> None:
    """The uniqueness key covers live lines only, not the whole history.

    PRD 3.7: "The combination of `engagement_id`, `deliverable_id`,
    `consultant_id` and `week_ending_date` must be unique among lines that are
    still `SUBMITTED` or already `APPROVED`; a repeat is refused with
    `ERR_DUPLICATE_TIMESHEET_LINE`, while lines that were rejected or reversed do
    not block a fresh submission for the same week."

    Design: Corner/validations/duplicate_timesheet_line_blocked_only_by_live_rows
    """
    sc = fx.build_started_engagement(api)
    first = fx.log_time(sc, 20.0, C.SEED_WEEK_1)

    validate_error(
        api.create_time_entry(
            F.time_entry_payload(
                sc.engagement_id, sc.d1_id, sc.partner_id, C.SEED_WEEK_1, 30.0
            ),
            sc.partner,
        ),
        E.ERR_DUPLICATE_TIMESHEET_LINE,
    )

    rejected = get_success_data(
        api.time_entry_decision(first["id"], {"decision": "REJECT"}, sc.manager)
    )
    assert_fields(rejected, status=C.TIME_ENTRY_REJECTED)

    replacement = fx.log_time(sc, 30.0, C.SEED_WEEK_1)
    assert_two_dp(replacement, "hours", 30.00)
    assert_money(replacement, "cost_cents", 1860000)
    assert_fields(replacement, status=C.TIME_ENTRY_SUBMITTED)
    _, meta = validate_paginated(
        api.list_time_entries(sc.manager, {"engagement_id": sc.engagement_id})
    )
    assert_pagination_meta(meta, total_count=2, has_more=False)


def test_the_three_narrative_baseline_gates_fire_in_their_declared_order(
    api: ConsultingApiClient,
) -> None:
    """One scope violating all three gates surfaces them one at a time.

    PRD 3.4: "The `assumptions`, `exclusions` and `client_responsibilities` lists
    must each hold at least one entry, and an empty one of any of the three is
    refused with `ERR_ASSUMPTIONS_REQUIRED`."

    PRD 2.10: "Note in particular that on scope baselining the four
    scope-completeness checks fire in exactly that sequence — deliverable count,
    then the assumption and exclusion and responsibility lists, then acceptance
    criteria, then the completion-weight sum — so a scope with no deliverables at
    all reports the count error rather than any of the later three."

    Design: Corner/validations/baseline_narrative_and_weight_gates_each_fire_in_priority_order
    """
    sc = fx.build_scoped_pursuit(
        api,
        scope={"exclusions": []},
        deliverables=[
            dict(C.SEED_D1, acceptance_criteria=""),
            dict(C.SEED_D2, depends_on_index=0, completion_weight_pct=70.0),
        ],
    )

    validate_error(
        api.baseline_scope(sc.opportunity_id, {}, sc.manager),
        E.ERR_ASSUMPTIONS_REQUIRED,
    )
    assert_fields(fx.read_opportunity(sc), status="SCOPING", baselined_at=None)

    fx.edit_scope(sc)
    validate_error(
        api.baseline_scope(sc.opportunity_id, {}, sc.manager),
        E.ERR_ACCEPTANCE_CRITERIA_MISSING,
    )
    assert_fields(fx.read_opportunity(sc), status="SCOPING", baselined_at=None)

    get_success_data(
        api.patch_deliverable(
            sc.d1_id,
            {"acceptance_criteria": "Signed-off baseline cost-to-serve model"},
            sc.manager,
        )
    )
    validate_error(
        api.baseline_scope(sc.opportunity_id, {}, sc.manager),
        E.ERR_COMPLETION_WEIGHT_SUM_INVALID,
    )
    assert_fields(fx.read_opportunity(sc), status="SCOPING", baselined_at=None)

    get_success_data(
        api.patch_deliverable(sc.d2_id, {"completion_weight_pct": 60.0}, sc.manager)
    )
    baselined = fx.baseline_scope(sc)

    assert_fields(baselined, status="SCOPE_BASELINED", longest_dependency_chain=2)
    assert_two_dp(baselined, "total_estimated_hours", C.CANON_TOTAL_ESTIMATED_HOURS)
    assert_two_dp(baselined, "scope_discount_pct", C.CANON_SCOPE_DISCOUNT_PCT)
    assert_money(
        baselined, "baseline_effort_cost_cents", C.CANON_BASELINE_EFFORT_COST_CENTS
    )


def test_all_three_dependency_constraints_report_the_same_code(
    api: ConsultingApiClient,
) -> None:
    """A cycle, a self-reference and a foreign predecessor are one rule, not three.

    PRD 3.3: "Dependencies are constrained in three ways at once, all reported as
    `ERR_DEPENDENCY_CYCLE`: the named predecessor must belong to the same pursuit
    and not to another, it must not be the deliverable itself, and it must not
    close a cycle anywhere in the pursuit's dependency graph."

    Design: Corner/validations/dependency_cycle_and_self_reference_both_refused
    """
    sc = fx.build_scoped_pursuit(api)
    sibling = fx.build_sibling_pursuit(
        sc, deliverables=[dict(C.SEED_D1, name="Foreign diagnostic")]
    )
    before = fx.read_deliverable(sc, sc.d1_id)

    # d2 already depends on d1: a cycle, then a self-reference, then a foreigner
    for candidate in (sc.d2_id, sc.d1_id, sibling.d1_id):
        validate_error(
            api.patch_deliverable(
                sc.d1_id, {"depends_on_deliverable_id": candidate}, sc.manager
            ),
            E.ERR_DEPENDENCY_CYCLE,
        )

    after = fx.read_deliverable(sc, sc.d1_id)
    assert_fields(
        after, depends_on_deliverable_id=None, version=before["version"]
    )
    assert_fields(
        fx.read_deliverable(sc, sc.d2_id), depends_on_deliverable_id=sc.d1_id
    )


def test_leaving_planned_needs_an_accepted_predecessor_and_then_a_lead(
    api: ConsultingApiClient,
) -> None:
    """Both first-move gates fire, in the order §2.10 fixes for them.

    PRD 3.6: "Two further preconditions apply to that first move and to that move
    only: the deliverable's `lead_consultant_id` must not be null, otherwise
    `ERR_DELIVERABLE_LEAD_UNASSIGNED`, and if the deliverable names a
    `depends_on_deliverable_id`, that predecessor must already have reached
    `ACCEPTED`, otherwise `ERR_DEPENDENCY_NOT_ACCEPTED`."

    PRD 2.10: "Business referential rules follow in order: practice match
    (`ERR_CONSULTANT_PRACTICE_MISMATCH`), reviewer certification
    (`ERR_REVIEWER_NOT_CERTIFIED`), cross-engagement scope of a referenced row
    (`ERR_DELIVERABLE_NOT_IN_ENGAGEMENT_SCOPE`), dependency cycles
    (`ERR_DEPENDENCY_CYCLE`), predecessor acceptance
    (`ERR_DEPENDENCY_NOT_ACCEPTED`), then lead assignment
    (`ERR_DELIVERABLE_LEAD_UNASSIGNED`)."

    Design: Corner/validations/leaving_planned_requires_a_lead_then_an_accepted_predecessor
    """
    sc = fx.build_active_engagement(api)
    fx.start_deliverable(sc, sc.d1_id, lead_id=sc.consultant_id)
    fx.set_status(sc, sc.d1_id, C.DELIVERABLE_SUBMITTED)

    # d2 has no lead and an unaccepted predecessor; predecessor ranks first
    validate_error(
        api.set_deliverable_status(
            sc.d2_id, {"target_status": C.DELIVERABLE_IN_PROGRESS}, sc.manager
        ),
        E.ERR_DEPENDENCY_NOT_ACCEPTED,
    )

    fx.set_status(
        sc, sc.d1_id, C.DELIVERABLE_ACCEPTED, headers=sc.client_contact
    )
    validate_error(
        api.set_deliverable_status(
            sc.d2_id, {"target_status": C.DELIVERABLE_IN_PROGRESS}, sc.manager
        ),
        E.ERR_DELIVERABLE_LEAD_UNASSIGNED,
    )
    assert_fields(fx.read_deliverable(sc, sc.d2_id), status=C.DELIVERABLE_PLANNED)

    started = fx.start_deliverable(sc, sc.d2_id, lead_id=sc.manager_id)

    assert_fields(
        started,
        status=C.DELIVERABLE_IN_PROGRESS,
        lead_consultant_id=sc.manager_id,
    )
    assert_fields(
        fx.read_consultant(sc, sc.manager_id), active_lead_deliverable_count=1
    )


def test_only_a_certified_consultant_may_be_named_as_reviewer(
    api: ConsultingApiClient,
) -> None:
    """The certification flag is a gate on scheduling, not on recording.

    PRD 3.9: "The nominated reviewer must have `quality_reviewer_certified` set
    to true, otherwise `ERR_REVIEWER_NOT_CERTIFIED`."

    Design: Corner/validations/quality_reviewer_must_be_certified
    """
    sc = fx.build_active_engagement(api)
    # An uncertified consultant who is neither the lead partner nor the
    # engagement manager, so PRD 2.10's earlier segregation-of-duties step
    # cannot pre-empt the certification gate.
    assert_fields(
        fx.read_consultant(sc, sc.consultant_id), quality_reviewer_certified=False
    )

    validate_error(
        api.create_quality_review(
            F.quality_review_payload(sc.engagement_id, sc.consultant_id), sc.manager
        ),
        E.ERR_REVIEWER_NOT_CERTIFIED,
    )

    scheduled = fx.schedule_review(sc)
    assert_fields(
        scheduled,
        status=C.REVIEW_SCHEDULED,
        reviewer_consultant_id=sc.reviewer_id,
    )
    _, meta = validate_paginated(
        api.list_quality_reviews(sc.manager, {"engagement_id": sc.engagement_id})
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)


def test_an_outcome_can_only_be_recorded_inside_the_closed_window(
    api: ConsultingApiClient,
) -> None:
    """One day before the window is too early; the last day is not too late.

    PRD 3.9: "The current logical clock date must lie inside the closed window
    from `window_start_date` through `window_end_date`, boundary days included;
    outside it, the attempt is refused with `ERR_REVIEW_WINDOW_NOT_OPEN`."

    Design: Corner/validations/review_outcome_only_inside_the_closed_window
    """
    sc = fx.build_active_engagement(api)
    review = fx.schedule_review(sc)

    fx.set_clock(api, "2026-09-19T23:00:00Z")
    validate_error(
        api.record_outcome(review["id"], F.record_outcome_payload(), sc.reviewer),
        E.ERR_REVIEW_WINDOW_NOT_OPEN,
    )
    assert_fields(
        fx.read_quality_review(sc, review["id"]), status=C.REVIEW_SCHEDULED
    )

    fx.set_clock(api, "2026-09-30T23:59:00Z")
    recorded = fx.record_review_outcome(
        sc, review["id"], C.REVIEW_PASSED, C.SEVERITY_NONE
    )

    assert_fields(
        recorded, status=C.REVIEW_PASSED, findings_severity=C.SEVERITY_NONE
    )
    assert fx.list_escalations(sc) == []
    assert_fields(fx.read_engagement(sc), delivery_state=C.DELIVERY_ACTIVE)


def test_a_severity_that_contradicts_the_outcome_is_refused(
    api: ConsultingApiClient,
) -> None:
    """Neither a clean pass with findings nor a conditional without them stands.

    PRD 3.9: "And the severity must be consistent with the outcome: `NONE` for a
    `PASSED` outcome, either `LOW` or `MEDIUM` for a `CONDITIONAL` outcome, and
    either `HIGH` or `CRITICAL` for a `FAILED` outcome."

    PRD 3.9: "Any other pairing is refused with
    `ERR_FINDINGS_SEVERITY_INCONSISTENT`."

    Design: Corner/validations/findings_severity_must_match_the_outcome
    """
    sc = fx.build_active_engagement(api)
    review = fx.schedule_review(sc)
    fx.set_clock(api, C.SEED_REVIEW_CLOCK)

    for outcome, severity in (
        (C.REVIEW_PASSED, C.SEVERITY_HIGH),
        (C.REVIEW_CONDITIONAL, C.SEVERITY_NONE),
    ):
        validate_error(
            api.record_outcome(
                review["id"],
                F.record_outcome_payload(outcome, severity),
                sc.reviewer,
            ),
            E.ERR_FINDINGS_SEVERITY_INCONSISTENT,
        )
        assert_fields(
            fx.read_quality_review(sc, review["id"]), status=C.REVIEW_SCHEDULED
        )

    recorded = fx.record_review_outcome(
        sc, review["id"], C.REVIEW_CONDITIONAL, C.SEVERITY_MEDIUM
    )

    assert_fields(
        recorded,
        status=C.REVIEW_CONDITIONAL,
        findings_severity=C.SEVERITY_MEDIUM,
    )
    # A conditional finding is filed, never escalated
    assert fx.list_escalations(sc) == []


def test_a_second_client_cannot_reuse_a_registered_client_code(
    api: ConsultingApiClient,
) -> None:
    """The code is the register's unique key; the name is not.

    PRD 3.1: "The `client_code` must be unique across every client on the
    register; a repeat is refused with `ERR_CLIENT_CODE_TAKEN`."

    Design: Corner/validations/client_code_must_be_unique
    """
    fx.set_clock(api, C.SEED_CLOCK)
    fx.create_client(api)

    validate_error(
        api.create_client(
            F.client_payload(name="Northwind Retail Group (US)"),
            fx.PRACTICE_ADMIN_HEADERS,
        ),
        E.ERR_CLIENT_CODE_TAKEN,
    )

    second = fx.create_client(
        api,
        client_code="NWR002",
        name="Northwind Wholesale",
        adverse_party_codes=...,
    )

    assert_fields(
        second,
        client_code="NWR002",
        status="ACTIVE",
        adverse_party_codes=[],
        completed_engagement_count=0,
    )
    _, meta = validate_paginated(api.list_clients(fx.PRACTICE_ADMIN_HEADERS, {}))
    assert_pagination_meta(meta, total_count=2, has_more=False)


def test_qualification_needs_a_cleared_conflict_and_then_a_verified_budget(
    api: ConsultingApiClient,
) -> None:
    """The safety gate is reported before the fiscal one, never the reverse.

    PRD 3.2: "`NOT_CHECKED` and `WAIVER_REQUIRED` are less severe but still
    blocking for qualification and for statement-of-work drafting, both of which
    insist that `conflict_status` be either `CLEAR` or `CLEARED_WITH_WAIVER` and
    otherwise return `ERR_CONFLICT_NOT_CLEARED`."

    PRD 3.2: "The pursuit must still be in `SCREENING`, the acting partner must
    be its `owner_partner_consultant_id`, `verified_budget_cents` must be
    non-null — a decision attempted without it fails with
    `ERR_BUDGET_NOT_VERIFIED` — and the conflict position must not be `BLOCKED`."

    Design: Corner/validations/qualification_requires_clearance_then_a_verified_budget
    """
    sc = fx.build_screening_pursuit(api)

    validate_error(
        api.qualify(sc.opportunity_id, {}, sc.partner), E.ERR_CONFLICT_NOT_CLEARED
    )

    cleared = fx.screen_conflicts(sc)
    assert_fields(cleared, conflict_status="CLEAR", status="SCREENING")
    validate_error(
        api.qualify(sc.opportunity_id, {}, sc.partner), E.ERR_BUDGET_NOT_VERIFIED
    )

    fx.verify_budget(sc, C.SEED_VERIFIED_BUDGET_CENTS)
    decided = get_success_data(api.qualify(sc.opportunity_id, {}, sc.partner))

    assert_fields(decided, status="QUALIFIED", conflict_status="CLEAR")
    assert_two_dp(decided, "qualification_score_verified", 68.00)


def test_the_outcome_bonus_is_required_on_one_model_and_banned_on_the_others(
    api: ConsultingApiClient,
) -> None:
    """Same frozen scope, three refused drafts, then the priced outcome deal.

    PRD 3.5: "An `OUTCOME_BASED` document must also carry `target_bonus_cents`,
    the outcome bonus the client is willing to put at risk; omitting it, or
    supplying a value that is not positive, is refused with
    `ERR_OUTCOME_TARGET_BONUS_REQUIRED`."

    PRD 3.5: "Conversely, a `FIXED_FEE` or `TIME_AND_MATERIALS` document must not
    carry `target_bonus_cents` at all, and supplying one is refused with
    `ERR_TARGET_BONUS_NOT_APPLICABLE`."

    Design: Corner/validations/target_bonus_is_required_for_outcome_and_rejected_otherwise
    """
    sc = fx.build_baselined_pursuit(api)
    version = sc.opportunity_version

    for overrides, expected in (
        ({"pricing_model": C.PRICING_OUTCOME_BASED}, E.ERR_OUTCOME_TARGET_BONUS_REQUIRED),
        (
            {"pricing_model": C.PRICING_OUTCOME_BASED, "target_bonus_cents": 0},
            E.ERR_OUTCOME_TARGET_BONUS_REQUIRED,
        ),
        (
            {
                "pricing_model": C.PRICING_FIXED_FEE,
                "target_bonus_cents": OUTCOME_TARGET_BONUS_CENTS,
            },
            E.ERR_TARGET_BONUS_NOT_APPLICABLE,
        ),
    ):
        validate_error(
            api.create_sow(
                F.sow_payload(sc.opportunity_id, version, **overrides), sc.partner
            ),
            expected,
        )
    assert_fields(fx.read_opportunity(sc), status="SCOPE_BASELINED")

    drafted = fx.draft_sow(
        sc,
        pricing_model=C.PRICING_OUTCOME_BASED,
        target_bonus_cents=OUTCOME_TARGET_BONUS_CENTS,
    )

    # 40 + 15 + 8 + 10 + 3 points, so the high tier at 0.20
    assert_fields(drafted, risk_score=76, status="DRAFT")
    assert_two_dp(drafted, "risk_premium_pct", 0.20)
    # 8566982 * 0.70 fixed, with the 0.35 risk-loaded cap binding the rest
    assert_money(drafted, "fixed_component_cents", 5996887)
    assert_money(drafted, "at_risk_component_cents", 3598132)
    assert_money(drafted, "not_to_exceed_cents", None)
    assert_money(drafted, "quoted_fee_cents", 9595019)
    assert_fields(fx.read_opportunity(sc), status="SOW_ISSUED")


def test_the_freeze_stops_scope_content_but_not_delivery_staffing(
    api: ConsultingApiClient,
) -> None:
    """Three content writes are refused; the lead assignment still lands.

    PRD 3.4: "From this point the scope is frozen: both the scope-narrative edit
    and any deliverable edit return `ERR_SCOPE_FROZEN`, as does an attempt to add
    a further deliverable."

    PRD 3.3: "Lead assignment is the one scoping-adjacent operation that
    deliberately stays open after freezing, because delivery staffing continues
    long after the win."

    Design: Corner/validations/scope_freeze_blocks_content_edits_but_not_staffing
    """
    sc = fx.build_baselined_pursuit(api)

    validate_error(
        api.patch_scope(
            sc.opportunity_id,
            F.scope_payload(exclusions=["Change management"]),
            sc.manager,
        ),
        E.ERR_SCOPE_FROZEN,
    )
    validate_error(
        api.create_deliverable(
            F.deliverable_payload(
                sc.opportunity_id, name="Late addition", completion_weight_pct=10.0
            ),
            sc.manager,
        ),
        E.ERR_SCOPE_FROZEN,
    )
    validate_error(
        api.patch_deliverable(
            sc.d1_id, {"effort_hours_estimate": 200.0}, sc.manager
        ),
        E.ERR_SCOPE_FROZEN,
    )

    opportunity = fx.read_opportunity(sc)
    assert_fields(opportunity, exclusions=list(C.SEED_EXCLUSIONS))
    assert_two_dp(opportunity, "total_estimated_hours", C.CANON_TOTAL_ESTIMATED_HOURS)
    deliverable = fx.read_deliverable(sc, sc.d1_id)
    assert_two_dp(deliverable, "effort_hours_estimate", 120.25)
    assert_money(deliverable, "line_cost_cents", C.CANON_D1_LINE_COST_CENTS)

    assigned = fx.assign_lead(sc, sc.d1_id, sc.consultant_id)
    assert_fields(assigned, lead_consultant_id=sc.consultant_id)


def test_closing_cannot_begin_while_one_deliverable_is_unaccepted(
    api: ConsultingApiClient,
) -> None:
    """Every deliverable, not most of them, and completion reaches 100.00.

    PRD 3.9: "Every deliverable of the engagement's pursuit must have reached
    `ACCEPTED`, otherwise `ERR_DELIVERABLES_NOT_ACCEPTED`."

    Design: Corner/validations/closing_requires_every_deliverable_accepted
    """
    sc = fx.build_active_engagement(api)
    fx.start_deliverable(sc, sc.d1_id, lead_id=sc.consultant_id)
    fx.accept_deliverable(sc, sc.d1_id)

    validate_error(
        api.begin_closing(sc.engagement_id, {}, sc.partner),
        E.ERR_DELIVERABLES_NOT_ACCEPTED,
    )
    assert_fields(fx.read_deliverable(sc, sc.d2_id), status=C.DELIVERABLE_PLANNED)
    assert_fields(fx.read_engagement(sc), delivery_state=C.DELIVERY_ACTIVE)

    fx.start_deliverable(sc, sc.d2_id, lead_id=sc.manager_id)
    fx.accept_deliverable(sc, sc.d2_id)
    closing = fx.begin_closing(sc)

    assert_fields(closing, delivery_state=C.DELIVERY_CLOSING)
    view = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_economics_view(
        view,
        hours_burn_pct=0.00,
        completion_pct=100.00,
        progress_variance_pct=-100.00,
        projected_cost_cents=6825500,
        projected_margin_pct=33.61,
        economics_state=C.ECONOMICS_ON_TRACK,
    )


def test_a_draft_change_request_blocks_closing_until_it_is_withdrawn(
    api: ConsultingApiClient,
) -> None:
    """A request that never moved a figure still blocks the gate.

    PRD 3.9: "No change request of the engagement may sit in `DRAFT`,
    `IMPACT_ASSESSED`, `PENDING_LEADERSHIP_APPROVAL` or
    `PENDING_CLIENT_APPROVAL`, otherwise
    `ERR_OPEN_CHANGE_REQUEST_BLOCKS_CLOSING`."

    PRD 3.8: "A `DRAFT` request may be rescinded by the manager who raised it —
    the acting identity must equal `requested_by_consultant_id` — moving it
    `DRAFT → RESCINDED`, stamping `rescinded_at` and touching no engagement
    field, because no impact was ever applied."

    Design: Corner/validations/open_change_request_blocks_closing
    """
    sc = fx.build_active_engagement(api)
    fx.accept_all_deliverables(sc)
    request = fx.raise_change_request(sc)
    assert_fields(
        request,
        status=C.CR_DRAFT,
        fee_delta_cents=None,
        requested_by_consultant_id=sc.manager_id,
    )

    validate_error(
        api.begin_closing(sc.engagement_id, {}, sc.partner),
        E.ERR_OPEN_CHANGE_REQUEST_BLOCKS_CLOSING,
    )

    rescinded = get_success_data(
        api.rescind_change_request(
            request["id"], {"note": RESCIND_NOTE}, sc.manager
        )
    )
    assert_fields(rescinded, status=C.CR_RESCINDED, fee_delta_cents=None)

    closing = fx.begin_closing(sc)

    assert_fields(closing, delivery_state=C.DELIVERY_CLOSING)
    assert_money(closing, "contracted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_two_dp(closing, "cumulative_change_pct", 0.00)


def test_a_checkpoint_still_scheduled_blocks_closing_until_it_is_recorded(
    api: ConsultingApiClient,
) -> None:
    """The gate is on the checkpoint's state, not on its eventual verdict.

    PRD 3.9: "No quality checkpoint of the engagement may still be `SCHEDULED`,
    otherwise `ERR_QUALITY_GATE_PENDING`."

    Design: Corner/validations/scheduled_review_blocks_closing_until_it_is_recorded
    """
    sc = fx.build_active_engagement(api)
    fx.accept_all_deliverables(sc)
    review = fx.schedule_review(sc, checkpoint_type=C.CHECKPOINT_PRE_DELIVERY)

    validate_error(
        api.begin_closing(sc.engagement_id, {}, sc.partner),
        E.ERR_QUALITY_GATE_PENDING,
    )
    assert_fields(fx.read_engagement(sc), delivery_state=C.DELIVERY_ACTIVE)

    fx.set_clock(api, C.SEED_REVIEW_CLOCK)
    recorded = fx.record_review_outcome(
        sc, review["id"], C.REVIEW_PASSED, C.SEVERITY_NONE
    )
    assert_fields(recorded, status=C.REVIEW_PASSED)

    closing = fx.begin_closing(sc)

    assert_fields(closing, delivery_state=C.DELIVERY_CLOSING)
    assert fx.list_escalations(sc) == []


def test_a_failed_checkpoint_outranks_the_unaccepted_deliverable_gate(
    api: ConsultingApiClient,
) -> None:
    """Two closing gates are violated at once and the safety band wins.

    PRD 3.9: "And no quality checkpoint may sit at `FAILED` whose linked
    escalation has not reached `RESOLVED`, otherwise `ERR_QUALITY_GATE_FAILED`."

    PRD 2.10: "Business safety rules come next, in this order: conflict blocked
    (`ERR_CONFLICT_BLOCKED`), conflict not cleared (`ERR_CONFLICT_NOT_CLEARED`),
    a failed quality gate with an unresolved escalation
    (`ERR_QUALITY_GATE_FAILED`), then a pending quality gate
    (`ERR_QUALITY_GATE_PENDING`)."

    Design: Corner/validations/failed_review_gate_outranks_the_deliverable_gate
    """
    sc = fx.build_active_engagement(api)
    fx.start_deliverable(sc, sc.d1_id, lead_id=sc.consultant_id)
    fx.accept_deliverable(sc, sc.d1_id)
    review = fx.schedule_review(sc)
    fx.set_clock(api, C.SEED_REVIEW_CLOCK)

    failed = fx.record_review_outcome(
        sc, review["id"], C.REVIEW_FAILED, C.SEVERITY_HIGH
    )
    assert_fields(
        failed, status=C.REVIEW_FAILED, findings_severity=C.SEVERITY_HIGH
    )
    escalation = fx.first_escalation(sc)
    assert_fields(
        escalation,
        source=C.ESCALATION_SOURCE_QUALITY,
        severity=C.SEVERITY_HIGH,
        status=C.ESCALATION_OPEN,
        source_quality_review_id=review["id"],
    )
    # HIGH opens in OPEN rather than DELIVERY_HELD, so nothing is suspended
    assert_fields(
        fx.read_engagement(sc),
        delivery_state=C.DELIVERY_ACTIVE,
        suspended_deliverable_count=0,
        leadership_review_required=True,
    )

    validate_error(
        api.begin_closing(sc.engagement_id, {}, sc.partner),
        E.ERR_QUALITY_GATE_FAILED,
    )
    assert_fields(fx.read_deliverable(sc, sc.d2_id), status=C.DELIVERABLE_PLANNED)


def test_the_not_to_exceed_ceiling_is_checked_when_a_line_is_approved(
    api: ConsultingApiClient,
) -> None:
    """One hour of partner time separates a breach from an approval.

    PRD 3.7: "On a `TIME_AND_MATERIALS` engagement one further gate applies
    before any of this happens: the sum of `billed_value_cents` across the
    engagement's already-`APPROVED` lines, plus the `billed_value_cents` of the
    line being approved, must not exceed the engagement's `not_to_exceed_cents`;
    a breach is refused with `ERR_NOT_TO_EXCEED_BREACHED`."

    Design: Corner/validations/not_to_exceed_ceiling_checked_at_timesheet_approval
    """
    sc = fx.build_started_engagement(
        api,
        clock=LATE_CLOCK,
        sow={"pricing_model": C.PRICING_TIME_AND_MATERIALS},
    )
    assert_money(fx.read_engagement(sc), "not_to_exceed_cents", C.CANON_TNM_QUOTED_CENTS)
    fx.log_and_approve_time(sc, 60.0, C.SEED_WEEK_1)

    breaching = fx.log_time(sc, 48.0, C.SEED_WEEK_2)
    assert_money(breaching, "billed_value_cents", 4218000)
    # 5272500 already approved plus 4218000 clears the 9423680 ceiling
    validate_error(
        api.time_entry_decision(breaching["id"], {"decision": "APPROVE"}, sc.manager),
        E.ERR_NOT_TO_EXCEED_BREACHED,
    )
    assert_fields(
        fx.read_time_entry(sc, breaching["id"]), status=C.TIME_ENTRY_SUBMITTED
    )
    assert_two_dp(fx.read_engagement(sc), "approved_hours_burned", 60.00)

    inside = fx.log_and_approve_time(sc, 47.0, SEED_WEEK_3)

    assert_money(inside, "billed_value_cents", 4130125)
    engagement = fx.read_engagement(sc)
    assert_two_dp(engagement, "approved_hours_burned", 107.00)
    assert_money(engagement, "burned_cost_cents", 6634000)


def test_a_follow_on_pursuit_needs_an_origin_client_that_was_satisfied(
    api: ConsultingApiClient,
) -> None:
    """7.25 is below the inclusive bar, so only the net-new pursuit opens.

    PRD 3.9: "A follow-on opportunity — one naming a non-null
    `origin_engagement_id` — is admitted only when the origin engagement's
    assessment exists and its `csat_score` is 7.50 or greater; the bar is
    inclusive, so exactly 7.50 is eligible."

    Design: Corner/validations/follow_on_opportunity_requires_a_satisfied_client
    """
    sc = fx.build_closed_engagement(api)
    filed = fx.file_satisfaction(
        sc,
        delivery_score=7,
        value_score=7,
        communication_score=8,
        would_refer=False,
    )
    # 2.80 + 2.45 + 2.00 with no referral bonus
    assert_two_dp(filed, "csat_score", 7.25)

    payload = F.opportunity_payload(
        sc.client_id,
        sc.partner_id,
        sc.manager_id,
        origin_engagement_id=sc.engagement_id,
        objective_summary="Second-wave network rollout",
    )
    validate_error(
        api.create_opportunity(payload, sc.partner), E.ERR_FOLLOW_ON_NOT_ELIGIBLE
    )

    payload.pop("origin_engagement_id")
    net_new = get_success_data(api.create_opportunity(payload, sc.partner))

    assert_fields(net_new, origin_engagement_id=None, status="SCREENING")
    # One closed engagement now earns 10 * 1/3 of the relationship term
    assert_two_dp(net_new, "qualification_score_intake", 71.33)


def test_an_assessment_is_admitted_only_once_delivery_has_closed(
    api: ConsultingApiClient,
) -> None:
    """CLOSING is not CLOSED, and the same body is refused twice before it lands.

    PRD 3.9: "An assessment filed against an engagement that has not reached
    `CLOSED` is refused with `ERR_ENGAGEMENT_STATE_INVALID`, and so is a second
    assessment against an engagement that already has one."

    Design: Corner/validations/satisfaction_assessment_requires_a_closed_engagement
    """
    sc = fx.build_active_engagement(api)
    payload = F.satisfaction_payload(
        sc.engagement_id, delivery_score=9, value_score=9, communication_score=9
    )

    validate_error(
        api.create_satisfaction_assessment(payload, sc.client_contact),
        E.ERR_ENGAGEMENT_STATE_INVALID,
    )

    fx.accept_all_deliverables(sc)
    fx.begin_closing(sc)
    validate_error(
        api.create_satisfaction_assessment(payload, sc.client_contact),
        E.ERR_ENGAGEMENT_STATE_INVALID,
    )

    fx.close_engagement(sc)
    filed = get_success_data(
        api.create_satisfaction_assessment(payload, sc.client_contact)
    )

    # 3.60 + 3.15 + 2.25 plus the 0.25 referral bonus
    assert_two_dp(filed, "csat_score", 9.25)
    assert_fields(fx.read_engagement(sc), delivery_state=C.DELIVERY_CLOSED)
    assert_fields(fx.read_client(sc), completed_engagement_count=1)
