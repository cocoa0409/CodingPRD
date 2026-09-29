"""
Endpoint surfaces: the bodyless action, the read-only derivation, the optional
cross-entity link, the clock-conditional action and the filtered collection read.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CHARTERING_EXAMINER_HEADERS,
    COUNSEL_HEADERS,
    ESCROW_AGENT_HEADERS,
    INSURANCE_EXAMINER_HEADERS,
    fixtures as fx,
    make_independent_director_headers,
)
from test_helpers.assertions import assert_fields_equal
from test_helpers.factories import exam_result_payload, subscription_payload
from test_helpers.types import (
    BLOCKED_REASON_NONE,
    CLEARANCE_UNSCREENED,
    EXAM_OUTCOME_PASSED,
    EXAM_PASSED,
    EXAM_SCHEDULED,
    EXAM_SCOPE_FULL,
    FUNDING_PLEDGED,
    RAISE_OPEN,
    RAISE_STRUCTURING,
    STAGE_PRE_OPENING,
    VERDICT_ADEQUATE,
)


# ---------------------------------------------------------------------------
# Corner / endpoints
# ---------------------------------------------------------------------------
def test_opening_the_offering_takes_no_body_and_cannot_be_replayed(api):
    """
    Opening an offering is an action with nothing to say: it carries no fields, returns the
    whole raise, and moves it out of structuring with a single version bump. None of the
    balances move, because opening an offering is not a subscription. Replaying the very same
    call on the now-open raise is refused for its status, and the refusal bumps nothing — so
    the action is emphatically not idempotent.

    PRD: "Opening the offering for subscription is a `CharterCounsel` action that moves the raise from `STRUCTURING` to `OPEN`."
    PRD: "A raise in any other status is refused with `ERR_RAISE_NOT_OPENABLE`."
    PRD: "Opening increments the raise's `version` by one."

    Design: Corner/endpoints/endpoint_capital_raise_open_action_flips_status_and_bumps_version
    """
    world = fx.open_group(api)
    raise_id = fx.add_capital_raise(api, world)
    before = fx.read_raise(api, raise_id)
    assert_fields_equal(before, status=RAISE_STRUCTURING)

    opened = validate_success(
        api.open_capital_raise(raise_id, COUNSEL_HEADERS), expected_status=200
    )
    assert_fields_equal(
        opened,
        status=RAISE_OPEN,
        version=before["version"] + 1,
        subscribed_shares=0,
        pledged_gross_cents=0,
        projected_reimbursement_cents=0,
        projected_net_release_cents=0,
    )

    validate_error(
        api.open_capital_raise(raise_id, COUNSEL_HEADERS),
        "ERR_RAISE_NOT_OPENABLE",
        expected_status=409,
    )
    assert_fields_equal(
        fx.read_raise(api, raise_id),
        status=RAISE_OPEN,
        version=before["version"] + 1,
    )


def test_the_adequacy_read_shows_every_intermediate_term_and_writes_nothing(
    api, submitted_plan_group
):
    """
    The derivation is reconcilable end to end. A loan book at 6511 basis points of assets sits
    eleven points past the trip point, which is one full ten-point step and therefore a five
    point add-on; with no scenario breaching the floor the risk add-on is that same five. The
    national base tier of 800 loses to the risk-adjusted 805, so the requirement is 805, and
    the plan's worst governing minimum of 882 clears it. Reading the derivation is not an
    event: the plan's version is exactly where it was.

    PRD: "The whole derivation is also available as a read-only computation on the group, which returns every intermediate term so it can be reconciled: `business_plan_id`, `charter_type`, `base_required_bps`, `concentration_bps`, `concentration_add_on_bps`, `breach_scenario_count`, `risk_add_on_bps`, `required_leverage_bps`, `worst_governing_min_leverage_ratio_bps` and `verdict`."
    PRD: "This read mutates nothing."
    PRD: "The charter type sets a base tier: 800 basis points when the group's `charter_type` is `NATIONAL`, 850 basis points when it is `STATE_MEMBER`, and 900 basis points when it is `STATE_NONMEMBER`."
    PRD: "The requirement is the **larger** of the base tier and the risk-adjusted floor, and then the **smaller** of that result and the ceiling of 1200 basis points."
    PRD: "When the plan's `worst_governing_min_leverage_ratio_bps` is greater than or equal to `required_leverage_bps`, the verdict is `ADEQUATE`; otherwise it is `DEFICIENT`."

    Design: Corner/endpoints/endpoint_capital_adequacy_read_returns_the_full_derivation
    """
    world = submitted_plan_group
    before = fx.read_plan(api, world["plan_id"])

    derivation = validate_success(
        api.get_capital_adequacy(
            world["group_id"],
            make_independent_director_headers(world["o3"]),
            params={"business_plan_id": world["plan_id"]},
        ),
        expected_status=200,
    )
    assert_fields_equal(
        derivation,
        business_plan_id=world["plan_id"],
        charter_type="NATIONAL",
        base_required_bps=800,
        concentration_bps=6511,
        concentration_add_on_bps=5,
        breach_scenario_count=0,
        risk_add_on_bps=5,
        required_leverage_bps=805,
        worst_governing_min_leverage_ratio_bps=882,
        verdict=VERDICT_ADEQUATE,
    )
    assert_fields_equal(
        fx.read_plan(api, world["plan_id"]), version=before["version"]
    )


def test_a_subscribing_organizer_must_belong_to_the_offering_s_own_group(api):
    """
    The optional link to a subscribing organizer is checked against the raise's group. An
    organizer of an unrelated charter project is refused for the mismatch and not for absence
    — the identifier resolves perfectly well — and the book is untouched by the refusal. The
    project's own chief executive is accepted, priced at the offering's 1000 cents a share,
    and the row is then reachable through the organizer filter, which returns it alone and
    returns nothing at all for the foreign organizer.

    PRD: "`organizer_id` is optional and identifies a subscribing organizer; when omitted the subscriber is an outside investor, and when supplied it must name an `Organizer` whose group is the same group as the raise's, failing which the request is refused with `ERR_SUBSCRIBER_ORGANIZER_MISMATCH`."
    PRD: "Whether the row that *does* exist is also *eligible* — the right group, the right status — is a separate and later check with its own conflict code, described with the workflow it guards."

    Design: Corner/endpoints/endpoint_subscription_links_to_an_organizer_of_the_same_group
    """
    world = fx.composition_met_group(api)
    fx.open_raise(api, world)
    other = fx.second_group(api)

    validate_error(
        api.create_subscription(
            subscription_payload(
                world["raise_id"],
                subscriber_name="Yusuf Bello",
                shares=250_000,
                organizer_id=other["ob1"],
            ),
            ESCROW_AGENT_HEADERS,
        ),
        "ERR_SUBSCRIBER_ORGANIZER_MISMATCH",
        expected_status=409,
    )
    assert_fields_equal(fx.read_raise(api, world["raise_id"]), subscribed_shares=0)

    subscription = get_success_data(
        api.create_subscription(
            subscription_payload(
                world["raise_id"],
                subscriber_name="Dana Whitfield",
                shares=250_000,
                organizer_id=world["o1"],
            ),
            ESCROW_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        subscription,
        organizer_id=world["o1"],
        amount_cents=250_000_000,
        funding_state=FUNDING_PLEDGED,
        clearance_state=CLEARANCE_UNSCREENED,
    )

    mine, mine_meta = validate_paginated(
        api.list_subscriptions(COUNSEL_HEADERS, params={"organizer_id": world["o1"]})
    )
    assert mine_meta["total_count"] == 1, (
        f"the organizer filter must return the single linked row, got {mine_meta['total_count']}"
    )
    assert mine[0]["id"] == subscription["id"]

    _, foreign_meta = validate_paginated(
        api.list_subscriptions(COUNSEL_HEADERS, params={"organizer_id": other["ob1"]})
    )
    assert foreign_meta["total_count"] == 0, (
        "the foreign organizer must be linked to nothing, since his subscription was refused"
    )
    assert_fields_equal(fx.read_raise(api, world["raise_id"]), subscribed_shares=250_000)


def test_the_same_examination_result_is_refused_before_the_visit_and_taken_after_it(api):
    """
    Nothing about the request changes; only the clock does. Reported while the calendar still
    reads the beginning of August, a visit scheduled for October has not begun and the result
    is refused, leaving the examination scheduled with no findings recorded. Moved to exactly
    the instant the window opens, the identical call is accepted — the bound is inclusive — and
    two findings sit one below the three-finding pass ceiling. The group is left in pre-opening
    with nothing blocking it, since a passing visit is a permission to open rather than the
    opening itself.

    PRD: "The current logical clock must be at or after the examination's `window_start_utc`, so a visit cannot be reported before it has begun; a result recorded at exactly the start instant is accepted, while one recorded a second earlier is refused with `ERR_EXAM_WINDOW_NOT_STARTED`."
    PRD: "An `outcome` of `PASSED` additionally requires the supplied `finding_count` to be no more than 3: exactly three findings can still be recorded as a pass, a fourth cannot, and the attempt is refused with `ERR_FINDINGS_EXCEED_PASS_LIMIT`."
    PRD: "A `PlatformAdmin` moves the clock forward by supplying `to_iso8601`; the response carries the new value as `current_utc`."

    Design: Corner/endpoints/endpoint_exam_result_is_conditional_on_the_window_having_started
    """
    world = fx.pre_opening_group(api)
    exam_id = fx.schedule_exam(api, world)

    validate_error(
        api.record_exam_result(
            exam_id,
            exam_result_payload(EXAM_OUTCOME_PASSED, 2),
            CHARTERING_EXAMINER_HEADERS,
        ),
        "ERR_EXAM_WINDOW_NOT_STARTED",
        expected_status=409,
    )
    assert_fields_equal(
        fx.read_exam(api, exam_id), status=EXAM_SCHEDULED, finding_count=0
    )

    clock = fx.set_clock(api, "2026-10-05T09:00:00Z")
    assert clock["current_utc"].startswith("2026-10-05T09:00:00"), (
        f"the clock must report its new value: {clock['current_utc']!r}"
    )

    passed = validate_success(
        api.record_exam_result(
            exam_id,
            exam_result_payload(EXAM_OUTCOME_PASSED, 2),
            CHARTERING_EXAMINER_HEADERS,
        ),
        expected_status=200,
    )
    assert_fields_equal(passed, status=EXAM_PASSED, finding_count=2)
    assert_fields_equal(
        fx.read_group(api, world["group_id"]),
        stage=STAGE_PRE_OPENING,
        opening_blocked_reason=BLOCKED_REASON_NONE,
    )


def test_an_examination_read_exposes_its_buffer_and_the_status_filter_narrows_the_list(api):
    """
    A single examination read back shows the two-day report-writing tail computed onto the end
    of its window: a visit closing at five in the afternoon of the seventh occupies the calendar
    until the same hour on the ninth. The collection read honours the status filter exactly —
    the scheduled visit is the one row returned, and asking for passed visits returns none,
    because nothing has been reported yet.

    PRD: "Each examination's `buffer_end_utc` is derived as its `window_end_utc` plus 48 hours — two full days of report-writing time — and the interval it occupies runs from `window_start_utc` inclusive to `buffer_end_utc` exclusive."
    PRD: "The filters are the channel through which each foreign key becomes reverse-reachable: organizers may be narrowed by `group_id`, `role_on_board`, `qualification_status` and `is_independent`; business plans by `group_id`, `supersedes_plan_id` and `status`; stress scenarios by `business_plan_id`, `scenario_code` and `governing_variant`; capital raises by `group_id` and `status`; subscriptions by `capital_raise_id`, `organizer_id`, `funding_state`, `clearance_state` and `counts_toward_escrow`; regulatory filings by `group_id`, `pinned_business_plan_id`, `authority` and `status`; approval conditions by `filing_id`, `category`, `status` and `is_pre_opening_blocking`; policy documents by `group_id`, `drafted_by_organizer_id`, `adopted_by_organizer_id`, `domain` and `status`; vendor contracts by `group_id`, `service_domain`, `criticality` and `status`; conversion windows by `vendor_contract_id` and `status`; readiness exams by `group_id`, `exam_scope` and `status`; and deviation requests by `group_id`, `baseline_plan_id`, `metric`, `status` and `requires_regulator_approval`."

    Design: Corner/endpoints/endpoint_readiness_exam_read_and_filtered_list
    """
    world = fx.pre_opening_group(api)
    exam_id = fx.schedule_exam(api, world)

    exam = validate_success(
        api.get_readiness_exam(exam_id, INSURANCE_EXAMINER_HEADERS), expected_status=200
    )
    assert_fields_equal(
        exam,
        id=exam_id,
        group_id=world["group_id"],
        exam_scope=EXAM_SCOPE_FULL,
        status=EXAM_SCHEDULED,
        finding_count=0,
    )
    assert exam["window_end_utc"].startswith("2026-10-07T17:00:00"), (
        f"the window must close as scheduled: {exam['window_end_utc']!r}"
    )
    assert exam["buffer_end_utc"].startswith("2026-10-09T17:00:00"), (
        f"the buffer must land exactly 48 hours later: {exam['buffer_end_utc']!r}"
    )

    scheduled, scheduled_meta = validate_paginated(
        api.list_readiness_exams(
            INSURANCE_EXAMINER_HEADERS,
            params={"group_id": world["group_id"], "status": EXAM_SCHEDULED},
        )
    )
    assert scheduled_meta["total_count"] == 1, (
        f"the scheduled filter must return the one visit, got {scheduled_meta['total_count']}"
    )
    assert scheduled[0]["id"] == exam_id

    _, passed_meta = validate_paginated(
        api.list_readiness_exams(
            INSURANCE_EXAMINER_HEADERS,
            params={"group_id": world["group_id"], "status": EXAM_PASSED},
        )
    )
    assert passed_meta["total_count"] == 0, (
        f"no visit has been reported, so the passed filter must be empty, got "
        f"{passed_meta['total_count']}"
    )
