"""
Validation rules examined one at a time: the referential admission rules on a
deployment, the four uniqueness scopes, the time-window rule that spans three
endpoints, the branch-bound decision fields, and the settlement rules that
answer three different requests with three different codes.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_ALTERNATIVE_ALREADY_ACTIVE,
    ERR_APPEAL_ALREADY_OPEN,
    ERR_ASSIGNMENT_ALREADY_EXISTS,
    ERR_CITATION_STATUS_INVALID,
    ERR_DECISION_FIELDS_INVALID,
    ERR_DIVERSION_NOT_ELIGIBLE,
    ERR_DUPLICATE_CODE,
    ERR_INVALID_SERVICE_HOURS,
    ERR_INVALID_TIME_WINDOW,
    ERR_LINE_NOT_ASSIGNED_TO_ZONE,
    ERR_NOTHING_OUTSTANDING,
    ERR_REDUCTION_BELOW_FLOOR,
    ERR_SETTLEMENT_STATUS_INVALID,
)
from test_helpers.assertions import (
    assert_citation_money_identity,
    assert_installment_schedule,
    assert_instant_equals,
    assert_ledger_row,
    ids_of,
)
from test_helpers.constants import (
    ADJUDICATION_REDUCED,
    ADJUDICATION_UPHELD,
    APPEAL_STATUS_SUBMITTED,
    APPEAL_STATUS_WITHDRAWN,
    BASIS_ACCRUAL,
    CLOCK_EPOCH,
    DECISION_PENDING,
    DECISION_REDUCE,
    DECISION_UPHOLD,
    DEPLOYMENT_STATUS_PLANNED,
    DISMISSAL_REASON_FIRST_OFFENSE_DIVERSION,
    DISMISSAL_REASON_PROCEDURAL_DEFECT,
    GROUNDS_HARDSHIP,
    GROUNDS_SIGNAGE_DEFICIENCY,
    HEARING_STATUS_HELD,
    HEARING_STATUS_SCHEDULED,
    MODE_BUS,
    OUTCOME_WARNING_ISSUED,
    PAYMENT_SOURCE_DOWN_PAYMENT,
    PLAN_STATUS_ACTIVE,
    SAMPLING_CLUSTER_RANDOM,
    SERVICE_STATUS_FORFEITED,
    SETTLEMENT_OUTSTANDING,
    SETTLEMENT_PLAN_ACTIVE,
    SETTLEMENT_SERVICE_ACTIVE,
)
from test_helpers.fixtures import OBSERVATION_AT, WINDOW_END, WINDOW_START
from test_helpers.test_users import (
    ANALYST_HEADERS,
    HEARING_OFFICER_HEADERS,
    PLANNER_HEADERS,
    make_rider_headers,
)

SECOND_ENCOUNTER_AT = "2026-08-05T07:30:00Z"
LATER_EFFECTIVE_FROM = "2026-09-01T00:00:00Z"
REPORT_WINDOW_END = "2026-09-01T00:00:00Z"
SUB_MINUTE_WINDOW_START = "2026-08-05T06:00:30Z"
DISMISS = "DISMISS"


def test_planning_on_a_line_the_zone_never_adopted_is_a_referential_refusal(api):
    """
    First, the line must actually be enforceable inside the zone: an attachment
    must exist for that exact zone-and-line pair whose `effective_from` is at or
    before the requested `window_start`, and where none does the request is
    refused with `ERR_LINE_NOT_ASSIGNED_TO_ZONE`.

    Design: Corner/validations/deployment_on_a_line_not_assigned_to_the_zone_is_rejected
    """
    env = fixtures.build_environment(
        api,
        designate=False,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
    )
    unattached = fixtures.register_line(
        api,
        line_code="L2",
        mode=MODE_BUS,
        daily_boardings=18000,
        baseline_evasion_rate_bps=450,
    )

    response = api.create_inspection_deployment(
        factories.deployment_payload(unattached["id"], env["zone"]["id"]),
        PLANNER_HEADERS,
    )
    validate_error(response, ERR_LINE_NOT_ASSIGNED_TO_ZONE, 422)

    # Neither identifier is the problem: both rows resolve on their own reads.
    validate_success(api.get_fare_zone(env["zone"]["id"], PLANNER_HEADERS))
    validate_success(api.get_transit_line(unattached["id"], PLANNER_HEADERS))

    _, meta = validate_paginated(
        api.list_deployments(PLANNER_HEADERS, {"zone_id": env["zone"]["id"]})
    )
    assert meta["total_count"] == 0


def test_a_repeated_zone_code_and_a_repeated_badge_number_share_one_code(api):
    """
    A duplicate `zone_code` is refused with `ERR_DUPLICATE_CODE`. ... A duplicate
    `badge_number` is refused with `ERR_DUPLICATE_CODE`.

    Design: Corner/validations/duplicate_zone_code_and_duplicate_badge_number_are_rejected
    """
    fixtures.move_clock(api, CLOCK_EPOCH)
    zone = fixtures.register_zone(
        api,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )
    first_inspector = fixtures.register_inspector(api, status="ACTIVE")

    validate_error(
        api.create_fare_zone(
            factories.fare_zone_payload(
                zone_code="ZN1", name="Duplicate Code Zone", required_sign_count=4
            ),
            PLANNER_HEADERS,
        ),
        ERR_DUPLICATE_CODE,
        409,
    )
    validate_error(
        api.create_inspector(
            factories.inspector_payload(
                badge_number="B-100",
                display_name="Inspector Two",
                certification_expiry="2027-06-01T00:00:00Z",
                status="ACTIVE",
            ),
            PLANNER_HEADERS,
        ),
        ERR_DUPLICATE_CODE,
        409,
    )

    rows, meta = validate_paginated(api.list_fare_zones(PLANNER_HEADERS))
    assert meta["total_count"] == 1
    assert ids_of(rows) == [zone["id"]]

    second_inspector = validate_success(
        api.create_inspector(
            factories.inspector_payload(
                badge_number="B-200",
                display_name="Inspector Two",
                certification_expiry="2027-06-01T00:00:00Z",
                status="ACTIVE",
            ),
            PLANNER_HEADERS,
        ),
        201,
    )
    assert second_inspector["badge_number"] == "B-200"
    assert second_inspector["id"] != first_inspector["id"]


def test_the_zone_and_line_pair_is_the_unique_key_not_the_effective_instant(api):
    """
    Only one attachment may exist for a given zone-and-line pair; a second
    attempt at the same pair is refused with `ERR_ASSIGNMENT_ALREADY_EXISTS`.

    Design: Corner/validations/repeating_a_zone_line_pair_is_rejected
    """
    fixtures.move_clock(api, CLOCK_EPOCH)
    first_zone = fixtures.register_zone(
        api,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )
    second_zone = fixtures.register_zone(
        api,
        zone_code="ZN2",
        name="Midtown POP Zone",
        required_sign_count=6,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )
    line = fixtures.register_line(api)
    assignment = fixtures.assign_line(api, first_zone["id"], line["id"])

    validate_error(
        api.create_zone_line_assignment(
            factories.zone_line_assignment_payload(
                first_zone["id"],
                line["id"],
                platform_segment_count=6,
                effective_from=LATER_EFFECTIVE_FROM,
            ),
            PLANNER_HEADERS,
        ),
        ERR_ASSIGNMENT_ALREADY_EXISTS,
        409,
    )

    stored = get_success_data(api.get_zone_line_assignment(assignment["id"], PLANNER_HEADERS))
    assert stored["platform_segment_count"] == 4
    assert_instant_equals(stored["effective_from"], CLOCK_EPOCH, "assignment.effective_from")

    cross_zone = validate_success(
        api.create_zone_line_assignment(
            factories.zone_line_assignment_payload(
                second_zone["id"], line["id"], platform_segment_count=2
            ),
            PLANNER_HEADERS,
        ),
        201,
    )
    assert cross_zone["zone_id"] == second_zone["id"]

    _, meta = validate_paginated(
        api.list_zone_line_assignments(PLANNER_HEADERS, {"line_id": line["id"]})
    )
    assert meta["total_count"] == 2


def test_one_time_window_rule_answers_a_reversal_a_stray_second_and_a_report(api):
    """
    Where a report or a deployment declares a window, `window_end` must be
    strictly later than `window_start`; a request that violates this ... is
    rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 422).  Deployment windows carry
    the additional requirement that `window_start` and `window_end` be a whole
    number of minutes apart, enforced under the same code.

    Design: Corner/validations/reversed_and_sub_minute_windows_are_rejected_on_deployments_and_reports
    """
    env = fixtures.build_environment(
        api,
        designate=False,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
    )
    line_id = env["line"]["id"]
    zone_id = env["zone"]["id"]

    validate_error(
        api.create_inspection_deployment(
            factories.deployment_payload(
                line_id, zone_id, window_start=WINDOW_END, window_end=WINDOW_START
            ),
            PLANNER_HEADERS,
        ),
        ERR_INVALID_TIME_WINDOW,
        422,
    )
    validate_error(
        api.create_inspection_deployment(
            factories.deployment_payload(
                line_id, zone_id, window_start=SUB_MINUTE_WINDOW_START, window_end=WINDOW_END
            ),
            PLANNER_HEADERS,
        ),
        ERR_INVALID_TIME_WINDOW,
        422,
    )
    validate_error(
        api.get_revenue_recovery_report(
            factories.revenue_report_params(
                window_start=REPORT_WINDOW_END, window_end=CLOCK_EPOCH, basis=BASIS_ACCRUAL
            ),
            ANALYST_HEADERS,
        ),
        ERR_INVALID_TIME_WINDOW,
        422,
    )
    # The comparison is strict, so a window of zero length fails the same rule.
    validate_error(
        api.create_inspection_deployment(
            factories.deployment_payload(
                line_id, zone_id, window_start=WINDOW_START, window_end=WINDOW_START
            ),
            PLANNER_HEADERS,
        ),
        ERR_INVALID_TIME_WINDOW,
        422,
    )

    _, meta = validate_paginated(api.list_deployments(PLANNER_HEADERS))
    assert meta["total_count"] == 0


def test_two_lines_sharing_a_window_sit_inside_a_zone_cap_of_two(api):
    """
    Second, no two live deployments may collide on the same line: if any other
    deployment on the same `line_id` ... shares any instant with the requested
    half-open window, the request is refused with
    `ERR_DEPLOYMENT_WINDOW_OVERLAP`. ... Third, the zone's own concurrency cap is
    respected: the count of deployments on the same `zone_id` ... must be
    strictly less than that zone's `max_concurrent_deployments`.

    Design: Corner/validations/a_second_deployment_on_another_line_in_the_same_zone_satisfies_every_temporal_rule
    """
    env = fixtures.build_environment(
        api,
        designate=False,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=2,
    )
    zone_id = env["zone"]["id"]
    second_line = fixtures.register_line(
        api,
        line_code="L2",
        mode=MODE_BUS,
        daily_boardings=18000,
        baseline_evasion_rate_bps=450,
    )
    fixtures.assign_line(api, zone_id, second_line["id"], platform_segment_count=2)

    first = fixtures.plan_deployment(api, env["line"]["id"], zone_id)

    second = validate_success(
        api.create_inspection_deployment(
            factories.deployment_payload(
                second_line["id"],
                zone_id,
                window_start=WINDOW_START,
                window_end=WINDOW_END,
                planned_inspector_count=2,
                sampling_method=SAMPLING_CLUSTER_RANDOM,
                target_sample_size=4,
            ),
            PLANNER_HEADERS,
        ),
        201,
    )
    assert second["status"] == DEPLOYMENT_STATUS_PLANNED
    assert second["id"] != first["id"]
    assert second["sampling_method"] == SAMPLING_CLUSTER_RANDOM
    assert second["target_sample_size"] == 4
    # The same-line collision rule never fired: the two rows sit on different lines.
    assert second["line_id"] != first["line_id"]

    rows, meta = validate_paginated(
        api.list_deployments(PLANNER_HEADERS, {"zone_id": zone_id})
    )
    assert meta["total_count"] == 2
    assert sorted(ids_of(rows)) == sorted([first["id"], second["id"]])


def test_three_decision_rules_answer_six_malformed_decisions_in_priority_order(api):
    """
    A request that omits a field its branch requires, or supplies one its branch
    forbids, is refused with `ERR_DECISION_FIELDS_INVALID`. ...
    `FIRST_OFFENSE_DIVERSION` may be used only where the citation's
    `offense_sequence` is exactly 1, and using it on any higher rung is refused
    with `ERR_DIVERSION_NOT_ELIGIBLE`. ... `reduced_penalty_cents` must be at
    least the citation's `reduction_floor_cents` and strictly below its current
    `assessed_penalty_cents` ... anything below the floor is refused with
    `ERR_REDUCTION_BELOW_FLOOR`.

    Design: Corner/validations/hearing_decision_field_pairing_diversion_and_reduction_floor_rules
    """
    env = fixtures.build_environment(api)
    inspector_id = env["inspector"]["id"]
    deployment = fixtures.build_active_deployment(api, env)
    warned = fixtures.build_pending_encounter(api, env, deployment)
    fixtures.resolve(api, warned["id"], inspector_id, OUTCOME_WARNING_ISSUED)
    encounter = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at=SECOND_ENCOUNTER_AT
    )
    citation = fixtures.issue_citation(api, encounter["id"], inspector_id)

    assert citation["offense_sequence"] == 2
    assert citation["assessed_penalty_cents"] == 18000
    assert citation["admin_fee_cents"] == 2160
    assert citation["total_due_cents"] == 20160
    assert citation["reduction_floor_cents"] == 9000
    assert_citation_money_identity(citation)

    hearing = fixtures.contest(api, citation["id"], env["rider"]["id"])
    hearing_id = hearing["id"]

    for payload in (
        {"decision": DISMISS},
        {"decision": DECISION_REDUCE},
        {"decision": DECISION_UPHOLD, "dismissal_reason_code": DISMISSAL_REASON_PROCEDURAL_DEFECT},
    ):
        validate_error(
            api.decide_hearing(hearing_id, payload, HEARING_OFFICER_HEADERS),
            ERR_DECISION_FIELDS_INVALID,
            422,
        )

    validate_error(
        api.decide_hearing(
            hearing_id,
            {
                "decision": DISMISS,
                "dismissal_reason_code": DISMISSAL_REASON_FIRST_OFFENSE_DIVERSION,
            },
            HEARING_OFFICER_HEADERS,
        ),
        ERR_DIVERSION_NOT_ELIGIBLE,
        422,
    )

    for amount in (8000, 18000):
        validate_error(
            api.decide_hearing(
                hearing_id,
                {"decision": DECISION_REDUCE, "reduced_penalty_cents": amount},
                HEARING_OFFICER_HEADERS,
            ),
            ERR_REDUCTION_BELOW_FLOOR,
            422,
        )

    untouched = fixtures.read_hearing(api, hearing_id)
    assert untouched["status"] == HEARING_STATUS_SCHEDULED
    assert untouched["decision"] == DECISION_PENDING
    assert not untouched.get("decided_at")

    decided = validate_success(
        api.decide_hearing(
            hearing_id,
            {"decision": DECISION_REDUCE, "reduced_penalty_cents": 12000},
            HEARING_OFFICER_HEADERS,
        )
    )
    assert decided["status"] == HEARING_STATUS_HELD
    assert decided["decision"] == DECISION_REDUCE
    assert_instant_equals(decided["decided_at"], OBSERVATION_AT, "hearing.decided_at")

    reduced = fixtures.read_citation(api, citation["id"])
    assert reduced["adjudication_status"] == ADJUDICATION_REDUCED
    assert reduced["assessed_penalty_cents"] == 12000
    assert reduced["admin_fee_cents"] == 1440
    assert reduced["total_due_cents"] == 13440
    assert_citation_money_identity(reduced)


def test_a_reduction_below_the_amount_already_paid_leaves_nothing_to_work_off(api):
    """
    A rider who had already paid more than the reduced total therefore sees the
    balance floor at 0 rather than going negative. ... its
    `outstanding_balance_cents` must be strictly greater than 0, otherwise
    `ERR_NOTHING_OUTSTANDING`.

    Design: Corner/validations/nothing_outstanding_fires_when_a_reduction_lands_below_the_amount_already_paid
    """
    env = fixtures.build_environment(api)
    inspector_id = env["inspector"]["id"]
    rider_id = env["rider"]["id"]
    deployment = fixtures.build_active_deployment(api, env)
    warned = fixtures.build_pending_encounter(api, env, deployment)
    fixtures.resolve(api, warned["id"], inspector_id, OUTCOME_WARNING_ISSUED)
    encounter = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at=SECOND_ENCOUNTER_AT
    )
    citation = fixtures.issue_citation(api, encounter["id"], inspector_id)
    assert citation["total_due_cents"] == 20160

    fixtures.pay_direct(api, citation["id"], 14000, rider_id)
    hearing = fixtures.contest(api, citation["id"], rider_id)
    fixtures.decide_hearing(api, hearing["id"], DECISION_REDUCE, reduced_penalty_cents=12000)

    overpaid = fixtures.read_citation(api, citation["id"])
    assert overpaid["total_due_cents"] == 13440
    assert overpaid["amount_paid_cents"] == 14000
    assert overpaid["outstanding_balance_cents"] == 0
    assert overpaid["adjudication_status"] == ADJUDICATION_REDUCED
    assert overpaid["settlement_status"] == SETTLEMENT_OUTSTANDING
    assert overpaid["version"] == 4
    assert_citation_money_identity(overpaid)

    response = api.create_service_assignment(
        factories.service_assignment_payload(
            citation["id"], "Riverside Food Bank", overpaid["version"]
        ),
        make_rider_headers(rider_id),
    )
    validate_error(response, ERR_NOTHING_OUTSTANDING, 422)
    raised = response.json()["data"]["error_id"]
    assert raised != ERR_SETTLEMENT_STATUS_INVALID
    assert raised != ERR_CITATION_STATUS_INVALID

    _, meta = validate_paginated(
        api.list_service_assignments(PLANNER_HEADERS, {"citation_id": citation["id"]})
    )
    assert meta["total_count"] == 0


def test_a_withdrawn_appeal_reopens_the_door_a_live_one_had_closed(api):
    """
    Appellate review is a single bite of the apple, so a citation that already
    carries an appeal in `SUBMITTED` or `SUPPLEMENT_REQUESTED` is refused with
    `ERR_APPEAL_ALREADY_OPEN`. ... A rider may also abandon an appeal from either
    live state, moving it to `WITHDRAWN`.

    Design: Corner/validations/a_second_open_appeal_on_the_same_citation_is_refused_until_the_first_is_withdrawn
    """
    chain = fixtures.build_upheld_citation_chain(api)
    citation_id = chain["citation"]["id"]
    hearing_id = chain["hearing"]["id"]
    rider_id = chain["rider"]["id"]
    rider_headers = make_rider_headers(rider_id)

    first = fixtures.file_appeal(
        api,
        citation_id,
        hearing_id,
        rider_id,
        GROUNDS_SIGNAGE_DEFICIENCY,
        statement="No signage at the boarding platform.",
    )
    assert first["status"] == APPEAL_STATUS_SUBMITTED
    assert first["round_index"] == 1

    validate_error(
        api.create_appeal(
            factories.appeal_payload(
                citation_id,
                hearing_id,
                GROUNDS_HARDSHIP,
                statement="Second filing while the first is open.",
            ),
            rider_headers,
        ),
        ERR_APPEAL_ALREADY_OPEN,
        409,
    )

    withdrawn = validate_success(api.withdraw_appeal(first["id"], rider_headers))
    assert withdrawn["status"] == APPEAL_STATUS_WITHDRAWN

    refiled = validate_success(
        api.create_appeal(
            factories.appeal_payload(
                citation_id,
                hearing_id,
                GROUNDS_HARDSHIP,
                statement="Refiled after withdrawal.",
            ),
            rider_headers,
        ),
        201,
    )
    assert refiled["status"] == APPEAL_STATUS_SUBMITTED
    assert refiled["round_index"] == 1
    assert refiled["id"] != first["id"]

    _, meta = validate_paginated(
        api.list_appeals(PLANNER_HEADERS, {"citation_id": citation_id})
    )
    assert meta["total_count"] == 2

    assert fixtures.read_citation(api, citation_id)["adjudication_status"] == ADJUDICATION_UPHELD


def test_a_live_service_alternative_answers_three_requests_three_ways(api):
    """
    Hours are credited by a planner, who posts an `hours` figure that must be a
    whole number of at least 1; anything else is refused with
    `ERR_INVALID_SERVICE_HOURS`. ... A rider or a planner may pay against a
    citation whose `settlement_status` is `OUTSTANDING`; any other settlement
    state is refused with `ERR_SETTLEMENT_STATUS_INVALID`. ... where the citation
    has an `ACTIVE` community-service assignment or an `ACTIVE` payment plan, a
    request with `supersede_alternative` false is refused with
    `ERR_ALTERNATIVE_ALREADY_ACTIVE`, while a request with
    `supersede_alternative` true is admitted and supersedes it.

    Design: Corner/validations/service_alternative_hours_conflict_and_settlement_status_rules
    """
    chain = fixtures.build_citation_chain(api)
    citation = chain["citation"]
    rider_id = chain["rider"]["id"]
    rider_headers = make_rider_headers(rider_id)
    assert citation["total_due_cents"] == 9720

    assignment = validate_success(
        api.create_service_assignment(
            factories.service_assignment_payload(
                citation["id"], "Riverside Food Bank", citation["version"]
            ),
            rider_headers,
        ),
        201,
    )
    assert assignment["required_hours"] == 7

    pinned = fixtures.read_citation(api, citation["id"])
    assert pinned["settlement_status"] == SETTLEMENT_SERVICE_ACTIVE

    validate_error(
        api.log_service_hours(assignment["id"], factories.log_hours_payload(0), PLANNER_HEADERS),
        ERR_INVALID_SERVICE_HOURS,
        422,
    )
    assert fixtures.read_service_assignment(api, assignment["id"])["hours_completed"] == 0

    validate_error(
        api.create_citation_payment(
            citation["id"], factories.citation_payment_payload(1000), rider_headers
        ),
        ERR_SETTLEMENT_STATUS_INVALID,
        409,
    )

    validate_error(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation["id"],
                installment_count=2,
                down_payment_cents=1000,
                expected_citation_version=pinned["version"],
            ),
            rider_headers,
        ),
        ERR_ALTERNATIVE_ALREADY_ACTIVE,
        409,
    )

    plan = validate_success(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation["id"],
                installment_count=2,
                down_payment_cents=1000,
                expected_citation_version=pinned["version"],
                supersede_alternative=True,
            ),
            rider_headers,
        ),
        201,
    )
    assert plan["status"] == PLAN_STATUS_ACTIVE
    assert plan["financed_cents"] == 8720
    assert plan["base_installment_cents"] == 4360
    assert plan["final_installment_cents"] == 4360
    assert_installment_schedule(plan)

    assert fixtures.read_service_assignment(api, assignment["id"])["status"] == (
        SERVICE_STATUS_FORFEITED
    )
    settled = fixtures.read_citation(api, citation["id"])
    assert settled["settlement_status"] == SETTLEMENT_PLAN_ACTIVE
    assert_citation_money_identity(settled)

    rows = fixtures.citation_ledger(api, citation["id"])
    assert len(rows) == 1
    assert_ledger_row(
        rows[0],
        PAYMENT_SOURCE_DOWN_PAYMENT,
        1000,
        plan_id=plan["id"],
        applied_at=OBSERVATION_AT,
        label="down payment row",
    )
