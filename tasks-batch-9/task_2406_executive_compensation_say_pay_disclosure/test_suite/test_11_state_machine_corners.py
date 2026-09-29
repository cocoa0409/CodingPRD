"""State-machine corners of the compensation calendar.

Covers the lifecycle edges the PRD pins down: the state a freshly granted award
starts in, the peer group's screening and committee-approval transitions and the
terminal lockdown of `APPROVED`, the terminal lockdown of a `HELD` engagement,
the metric locking that rides on program approval, the conditional revert half of
the peer-exclusion cascade, the ledger sync that follows vesting, and the
out-of-order rungs of the restatement recovery ladder.
"""

import pytest

from test_helpers import (
    CHAIR,
    CHAIR_ONE,
    CHAIR_TWO,
    CONSULTANT,
    COUNSEL,
    IR_LEAD,
    ApiErrorId,
    analyze_payload,
    api_client,
    assert_money,
    assert_payout_award,
    assert_peer_group,
    create_payout_award_payload,
    create_restatement_event,
    hold_engagement_payload,
    make_comp_committee_chair_headers,
    order_recovery,
    read_award,
    read_determinations,
    read_engagement,
    read_metric,
    read_pay_program,
    read_peer_group,
    read_peer_group_member,
    read_restatement_event,
    restated_metric_result,
    reverse_recovery_payload,
    schedule_engagement,
    schedule_engagement_payload,
    set_clock,
    settlement_payload,
    setup_pay_program,
    setup_peer_group,
    setup_program_with_certified_metrics,
    setup_vested_annual_incentive_award,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_new_annual_incentive_award_starts_granted_with_no_factor_and_target_realizable():
    """A grant against a metric-less vehicle starts GRANTED, unfactored, at assumed target.

    "New awards begin in `GRANTED`, with `settlement_date` and `vest_price_usd` null."
    "If that set is **empty**, the award has no factor at all: `certified_factor_pct` and
    `earned_amount_usd` both stay null, and the computation stops there — an empty
    contribution list must not collapse to 0.00, because a null factor is what lets the
    forward-looking valuation fall back to assumed target performance."
    "For a `GRANTED` `ANNUAL_INCENTIVE` award it is `target_amount_usd` multiplied by the
    factor (certified if available, otherwise the assumed 100.00 percent) divided by 100,
    rounded to two decimal places."

    Design: Corner/state_machines/a_newly_granted_award_starts_in_granted_with_zero_realized_value
    """
    env = setup_pay_program(approve=False)

    response = api_client.create_payout_award(
        env["program"]["id"],
        create_payout_award_payload(env["ceo"]["id"], "ANNUAL_INCENTIVE"),
        CONSULTANT,
    )
    award = validate_success(response, 201)
    assert_payout_award(award)

    assert award["status"] == "GRANTED", "a new award begins in GRANTED"
    assert award["settlement_date"] is None, "a new award has a null settlement_date"
    assert award["vest_price_usd"] is None, "a new award has a null vest_price_usd"
    # 1,200,000 base salary at an sti_target_pct of 150.00 targets 1,800,000.00.
    assert_money(award["target_amount_usd"], 1800000.00, "target_amount_usd")
    assert award["certified_factor_pct"] is None, (
        "an empty metric set leaves certified_factor_pct null rather than 0.00"
    )
    assert award["earned_amount_usd"] is None, (
        "an empty metric set leaves earned_amount_usd null rather than 0.00"
    )
    assert_money(award["realized_value_usd"], 0.00, "realized_value_usd")
    assert_money(award["realizable_value_usd"], 1800000.00, "realizable_value_usd")

    program = read_pay_program(env["program"]["id"])
    assert_money(program["realized_pay_total_usd"], 0.00, "realized_pay_total_usd")
    assert_money(program["realizable_pay_total_usd"], 1800000.00, "realizable_pay_total_usd")


def test_approving_a_screened_peer_group_records_the_chair_and_keeps_the_benchmark():
    """Committee approval freezes the screened benchmark and stamps the acting chair.

    "Committee approval by a `CompCommitteeChair` moves the group `SCREENED → APPROVED` and
    freezes it."
    "The chair's `X-User-ID` is recorded as `approved_by_user_id`, the group's `version`
    increments, and the frozen benchmark is then pushed through the programs that depend on
    it: at the first level, every pay program referencing this group whose design is still
    `DRAFT` recomputes `fixed_leg_usd`, `benchmark_ratio`, `lti_multiple`, `lti_target_usd`,
    `target_tdc_usd` and `benchmark_posture`; at the second level, caused by the first, each
    such program that already has a non-null `pay_percentile_rank` recomputes
    `pay_percentile_rank`, `degree_of_alignment` and `alignment_status`; at the third level,
    caused by either of the first two, every `SCREENED` proxy-advisor screen of a touched
    program becomes `STALE`."

    Design: Corner/state_machines/approving_a_screened_peer_group_records_the_approving_chair
    """
    env = setup_peer_group(peer_tickers=("BRVO",), target_status="SCREENED")

    response = api_client.approve_peer_group(
        env["peer_group"]["id"], make_comp_committee_chair_headers(CHAIR_ONE)
    )
    group = validate_success(response, 200)
    assert_peer_group(group)

    assert group["status"] == "APPROVED", "a SCREENED group approves to APPROVED"
    assert group["approved_by_user_id"] == CHAIR_ONE, (
        "approved_by_user_id carries the acting chair's X-User-ID"
    )
    assert_money(group["benchmark_target_tdc_usd"], 12000000.00, "benchmark_target_tdc_usd")
    assert group["accepted_member_count"] == 1
    # create, member add, screen, approve — one increment each.
    assert group["version"] == 4, "each of the four mutations increments version by exactly one"


def test_screening_an_approved_peer_group_is_refused_and_leaves_the_benchmark_intact():
    """APPROVED is terminal, so re-screening cannot let the benchmark drift.

    "It is refused on a group that is not in `DRAFT` with `ERR_PEER_GROUP_NOT_MUTABLE`,
    refused on a group with zero `ACCEPTED` members with `ERR_PEER_GROUP_EMPTY`, and refused
    with `ERR_PEER_OUTSIDE_SIZE_BAND` unless every `ACCEPTED` member either sits inside both
    bands or was admitted as a `BUSINESS_MODEL_ANALOG` — note that a `TALENT_COMPETITOR` peer
    whose ratios have since drifted out of band does block screening even though it was
    admissible at add time."
    "`APPROVED` is terminal for a peer group: it never reverts, and its membership can never
    change again."

    Design: Corner/state_machines/screening_an_approved_peer_group_cannot_reopen_the_benchmark
    """
    env = setup_peer_group(peer_tickers=("BRVO",), target_status="APPROVED")
    before = read_peer_group(env["peer_group"]["id"])

    response = api_client.screen_peer_group(env["peer_group"]["id"], CONSULTANT)
    validate_error(response, ApiErrorId.ERR_PEER_GROUP_NOT_MUTABLE, 409)

    after = read_peer_group(env["peer_group"]["id"])
    assert after["status"] == "APPROVED", "the refused screen left the group APPROVED"
    assert after["version"] == before["version"], "a refused screen is not a mutation"
    assert_money(after["benchmark_target_tdc_usd"], 12000000.00, "benchmark_target_tdc_usd")
    assert_money(after["median_revenue_usd"], before["median_revenue_usd"], "median_revenue_usd")
    assert after["accepted_member_count"] == before["accepted_member_count"]


def test_peer_group_approval_is_refused_before_screening_and_on_a_repeat_attempt():
    """Approve is guarded by a single source state, so it is not idempotent.

    "Approval requires the group to be in `SCREENED` — a `DRAFT` group is rejected with
    `ERR_PEER_GROUP_NOT_SCREENED` — and requires a non-null `benchmark_target_tdc_usd`, which
    successful screening guarantees."

    Design: Corner/state_machines/peer_group_approval_is_rejected_before_screening_and_on_the_second_attempt
    """
    env = setup_peer_group(peer_tickers=("BRVO",), target_status="DRAFT")
    group_id = env["peer_group"]["id"]

    too_early = api_client.approve_peer_group(
        group_id, make_comp_committee_chair_headers(CHAIR_ONE)
    )
    validate_error(too_early, ApiErrorId.ERR_PEER_GROUP_NOT_SCREENED, 409)

    validate_success(api_client.screen_peer_group(group_id, CONSULTANT), 200)
    approved = validate_success(
        api_client.approve_peer_group(group_id, make_comp_committee_chair_headers(CHAIR_ONE)), 200
    )
    assert approved["status"] == "APPROVED"

    # An APPROVED group is no longer SCREENED, so the repeat approval is refused; the PRD
    # names the state gate without pinning which of the two group gates answers first.
    again = api_client.approve_peer_group(
        group_id, make_comp_committee_chair_headers(CHAIR_TWO)
    )
    validate_error_is_one_of(
        again,
        [ApiErrorId.ERR_PEER_GROUP_NOT_SCREENED, ApiErrorId.ERR_PEER_GROUP_NOT_MUTABLE],
    )

    final = read_peer_group(group_id)
    assert final["approved_by_user_id"] == CHAIR_ONE, (
        "the refused second approval did not overwrite approved_by_user_id"
    )
    assert final["version"] == 4, "create, member add, screen and one approval — nothing else"


def test_holding_an_already_held_engagement_cannot_recount_the_investor():
    """HELD is terminal: neither hold nor schedule has an outgoing edge from it.

    "Holding a `SCHEDULED` engagement — any other status is `ERR_ENGAGEMENT_STATE_INVALID` —
    records the investor's `feedback_position` as `SUPPORTIVE`, `CONCERNED` or `OPPOSED`
    together with an optional `feedback_summary`, stamps `held_at` with the current logical
    time, moves the engagement `SCHEDULED → HELD`, and increments its `version`."
    "An engagement that is not in `REQUESTED` is refused with
    `ERR_ENGAGEMENT_STATE_INVALID`, and a `window_start` strictly before the current logical
    time is refused with `ERR_ENGAGEMENT_WINDOW_IN_PAST`."

    Design: Corner/state_machines/holding_an_already_held_engagement_cannot_recount_the_investor
    """
    env = setup_pay_program(approve=False)
    program_id = env["program"]["id"]

    engagement = api_client.create_outreach_engagement(
        program_id,
        {
            "investor_name": "BlackRock",
            "investor_key": "BLACKROCK",
            "ownership_pct": 20.00,
            "channel": "MEETING",
        },
        IR_LEAD,
    )
    engagement = validate_success(engagement, 201)
    schedule_engagement(engagement["id"], "2027-03-01T00:00:00Z", "2027-03-05T00:00:00Z")
    held = validate_success(
        api_client.hold_outreach_engagement(
            engagement["id"], hold_engagement_payload("SUPPORTIVE"), IR_LEAD
        ),
        200,
    )
    assert held["engagement_status"] == "HELD"
    assert held["feedback_position"] == "SUPPORTIVE"

    retry_hold = api_client.hold_outreach_engagement(
        engagement["id"], hold_engagement_payload("CONCERNED"), IR_LEAD
    )
    validate_error(retry_hold, ApiErrorId.ERR_ENGAGEMENT_STATE_INVALID, 409)

    retry_schedule = api_client.schedule_outreach_engagement(
        engagement["id"],
        schedule_engagement_payload("2027-03-10T00:00:00Z", "2027-03-12T00:00:00Z"),
        IR_LEAD,
    )
    validate_error(retry_schedule, ApiErrorId.ERR_ENGAGEMENT_STATE_INVALID, 409)

    after = read_engagement(program_id, engagement["id"])
    assert after["engagement_status"] == "HELD"
    assert after["feedback_position"] == "SUPPORTIVE", (
        "the refused hold did not overwrite the recorded position"
    )
    assert after.get("window_start") == held.get("window_start"), (
        "the refused schedule did not move the booked window"
    )
    assert after["version"] == held["version"], "neither refusal was a mutation"

    program = read_pay_program(program_id)
    assert_money(program["outreach_coverage_pct"], 20.00, "outreach_coverage_pct")


def test_screening_populates_both_medians_and_both_benchmark_variants_in_one_pass():
    """One screening call writes the medians, the size-fit score and both benchmark variants.

    "Sort the accepted peers' `revenue_usd` ascending, breaking ties by the membership row's
    `created_at` ascending; where the count is odd, `median_revenue_usd` is the middle value
    rounded half-up to two decimal places, and where the count is even it is the mean of the
    two middle values, likewise rounded to two decimal places."
    "The benchmark itself is computed twice, in two variants, and **both are always stored**
    regardless of which one the group has elected."

    Design: Corner/state_machines/screening_populates_both_medians_and_both_benchmark_variants_in_one_pass
    """
    env = setup_peer_group(peer_tickers=("BRVO", "CHRL"), target_status="DRAFT")

    group = validate_success(api_client.screen_peer_group(env["peer_group"]["id"], CONSULTANT), 200)
    assert_peer_group(group)

    assert group["status"] == "SCREENED"
    assert group["accepted_member_count"] == 2
    # Mean of 8,000,000,000 and 12,000,000,000; mean of 16,000,000,000 and 30,000,000,000.
    assert_money(group["median_revenue_usd"], 10000000000.00, "median_revenue_usd")
    assert_money(group["median_market_cap_usd"], 23000000000.00, "median_market_cap_usd")
    # The revenue median equals the issuer's own revenue, so the fit is perfect.
    assert_money(group["size_fit_score"], 100.00, "size_fit_score")
    # Raw list [12,000,000, 18,000,000] selects the lower middle value.
    assert_money(
        group["benchmark_target_tdc_raw_usd"], 12000000.00, "benchmark_target_tdc_raw_usd"
    )
    # Size-adjusted: BRVO 12,000,000 * 1.2500 and CHRL 18,000,000 * 0.8333.
    assert_money(
        group["benchmark_target_tdc_adjusted_usd"],
        14999400.00,
        "benchmark_target_tdc_adjusted_usd",
    )
    assert_money(group["benchmark_target_tdc_usd"], 12000000.00, "benchmark_target_tdc_usd")
    assert group["screened_at"] is not None, "screening stamps screened_at"
    assert group["screened_at"].startswith("2026-08-01T00:00:00"), (
        "screened_at carries the current logical time"
    )


def test_approving_a_program_locks_every_draft_metric_and_snapshots_its_target():
    """Committee approval cascades down to every DRAFT metric of the program.

    "When the committee approves the program design, every `DRAFT` metric of that program
    moves `DRAFT → LOCKED` and takes a snapshot: `locked_target_value` is set to the metric's
    `target_value` at that instant, and the snapshot never moves again."

    Design: Corner/state_machines/approving_a_program_locks_every_draft_metric_and_snapshots_its_target
    """
    env = setup_pay_program(
        metric_curves=("ADJ_EPS_LINEAR", "COST_RATIO_STEP"), approve=False
    )
    program_id = env["program"]["id"]
    eps, cost_ratio = env["metrics"]

    program = validate_success(
        api_client.approve_pay_program(program_id, make_comp_committee_chair_headers(CHAIR_ONE)),
        200,
    )

    assert program["design_status"] == "COMMITTEE_APPROVED"
    assert program["vote_status"] == "NOT_VOTED", "approval never touches the vote dimension"
    assert program["approved_by_user_id"] == CHAIR_ONE
    assert_money(program["target_tdc_usd"], 15000000.00, "target_tdc_usd")

    locked_eps = read_metric(program_id, eps["id"])
    assert locked_eps["status"] == "LOCKED"
    assert locked_eps["locked_target_value"] == pytest.approx(5.00, abs=0.01)
    assert locked_eps["version"] == 2, "definition then locking — two mutations"

    locked_cost = read_metric(program_id, cost_ratio["id"])
    assert locked_cost["status"] == "LOCKED"
    assert locked_cost["locked_target_value"] == pytest.approx(0.65, abs=0.001)
    assert locked_cost["version"] == 2, "definition then locking — two mutations"


def test_excluding_a_member_reverts_only_a_screened_group_and_clears_its_benchmarks():
    """The revert half of the exclusion cascade is conditional on the group's state.

    "Caused by that, the owning group recomputes `accepted_member_count`, and if the group was
    `SCREENED` it falls back `SCREENED → DRAFT` with `median_revenue_usd`,
    `median_market_cap_usd`, `size_fit_score`, `screened_at`,
    `benchmark_target_tdc_raw_usd`, `benchmark_target_tdc_adjusted_usd` and
    `benchmark_target_tdc_usd` all cleared to null."

    Design: Corner/state_machines/excluding_a_member_reverts_only_a_screened_group_and_clears_its_benchmarks
    """
    env = setup_peer_group(peer_tickers=("BRVO", "CHRL"), target_status="SCREENED")
    group_id = env["peer_group"]["id"]

    charlie = validate_success(
        api_client.exclude_peer_group_member(
            env["members"]["CHRL"]["id"],
            {"exclusion_reason": "Charlie exited the comparable business line mid-year."},
            CONSULTANT,
        ),
        200,
    )
    assert charlie["status"] == "EXCLUDED"

    reverted = read_peer_group(group_id)
    assert reverted["status"] == "DRAFT", "excluding from a SCREENED group reverts it to DRAFT"
    for field in (
        "median_revenue_usd",
        "median_market_cap_usd",
        "size_fit_score",
        "screened_at",
        "benchmark_target_tdc_raw_usd",
        "benchmark_target_tdc_adjusted_usd",
        "benchmark_target_tdc_usd",
    ):
        assert reverted[field] is None, f"the revert clears {field} to null"
    assert reverted["accepted_member_count"] == 1

    bravo = validate_success(
        api_client.exclude_peer_group_member(
            env["members"]["BRVO"]["id"],
            {"exclusion_reason": "Bravo announced a take-private transaction."},
            CONSULTANT,
        ),
        200,
    )
    assert bravo["status"] == "EXCLUDED"

    emptied = read_peer_group(group_id)
    assert emptied["status"] == "DRAFT", "a DRAFT group has no revert left to fire"
    assert emptied["accepted_member_count"] == 0
    assert emptied["screened_at"] is None
    assert read_peer_group_member(group_id, env["members"]["BRVO"]["id"])["status"] == "EXCLUDED"


def test_vesting_an_award_syncs_the_program_realized_and_realizable_totals():
    """Settlement reconciles the award's value with its program's totals in one request.

    "Either branch then makes the owning program recompute `realized_pay_total_usd` and
    `realizable_pay_total_usd`; on the vesting branch the program additionally recomputes
    `pay_percentile_rank`, `degree_of_alignment` and `alignment_status`, and a changed
    `alignment_status` flips the program's `SCREENED` screens to `STALE`."
    "For any other status — `VESTED` or `CLAWED_BACK` — the realizable value simply equals the
    realized value, since nothing remains outstanding."

    Design: Corner/state_machines/vesting_an_award_syncs_the_program_realized_pay_total
    """
    env = setup_program_with_certified_metrics(
        achievements=(5.50,),
        metric_curves=("ADJ_EPS_LINEAR",),
        metric_overrides=[{"weight_pct": 100.00}],
    )
    program_id = env["program"]["id"]

    # Granted after certification, so the award already carries the certified factor.
    granted = validate_success(
        api_client.create_payout_award(
            program_id,
            create_payout_award_payload(env["ceo"]["id"], "ANNUAL_INCENTIVE"),
            CONSULTANT,
        ),
        201,
    )
    assert_money(granted["certified_factor_pct"], 150.00, "certified_factor_pct")
    assert_money(granted["earned_amount_usd"], 2700000.00, "earned_amount_usd")

    set_clock("2026-10-01T00:00:00Z")
    vested = validate_success(
        api_client.settle_payout_award(
            granted["id"], settlement_payload("VEST", "2026-09-30T00:00:00Z"), CONSULTANT
        ),
        200,
    )

    assert vested["status"] == "VESTED"
    assert_money(vested["certified_factor_pct"], 150.00, "certified_factor_pct")
    assert_money(vested["earned_amount_usd"], 2700000.00, "earned_amount_usd")
    assert_money(vested["realized_value_usd"], 2700000.00, "realized_value_usd")
    assert_money(vested["realizable_value_usd"], 2700000.00, "realizable_value_usd")
    assert vested["settlement_date"].startswith("2026-09-30T00:00:00")

    program = read_pay_program(program_id)
    assert_money(program["realized_pay_total_usd"], 2700000.00, "realized_pay_total_usd")
    assert_money(program["realizable_pay_total_usd"], 2700000.00, "realizable_pay_total_usd")
    # BRVO's disclosed 12,000,000 is not strictly below the realized 2,700,000.00.
    assert_money(program["pay_percentile_rank"], 0.00, "pay_percentile_rank")
    assert_money(program["degree_of_alignment"], 30.00, "degree_of_alignment")
    assert program["alignment_status"] == "ALIGNED"


def test_the_restatement_recovery_ladder_rejects_every_out_of_order_step():
    """Each rung of the clawback ladder enforces its own precondition and moves no dollars.

    "Ordering recovery is a `CompCommitteeChair` action on an `ANALYZED` event — any other
    state is `ERR_EVENT_STATE_INVALID` — which moves the event `ANALYZED → RECOVERY_ORDERED`
    and, as its cascade, moves every `CALCULATED` determination of the event `CALCULATED →
    NOTICED`, stamping each row's `noticed_at` with the current logical time and incrementing
    each row's `version`."
    "Executing recovery is a `CompCommitteeChair` action, and it is gated three ways: the
    determination must be in `NOTICED`, or the answer is `ERR_DETERMINATION_STATE_INVALID`;
    `acknowledged_at` must be non-null, or the answer is
    `ERR_DETERMINATION_NOT_ACKNOWLEDGED`; and the acting `X-User-ID` must differ from
    `acknowledged_by_user_id`, or the answer is `ERR_SEGREGATION_OF_DUTIES`."
    "A `CompCommitteeChair` reverses a `RECOVERED` determination — any other status is
    `ERR_DETERMINATION_STATE_INVALID` — supplying a `reversal_reason` explaining why, for
    instance because the restatement itself was withdrawn."

    Design: Corner/state_machines/the_restatement_recovery_ladder_rejects_every_out_of_order_step
    """
    env = setup_vested_annual_incentive_award()
    award_id = env["awards"]["annual_incentive"]["id"]
    event = create_restatement_event(env["issuer"]["id"])

    # Rung one: recovery cannot be ordered on an event that has not been analysed.
    validate_error(
        api_client.order_restatement_recovery(event["id"], CHAIR),
        ApiErrorId.ERR_EVENT_STATE_INVALID,
        409,
    )

    analyzed = validate_success(
        api_client.analyze_restatement_event(
            event["id"],
            analyze_payload([restated_metric_result(env["metrics"][0]["id"], 5.00)]),
            COUNSEL,
        ),
        200,
    )
    assert analyzed["status"] == "ANALYZED"
    assert analyzed["determination_count"] == 1
    assert_money(analyzed["recoverable_total_usd"], 540000.00, "recoverable_total_usd")

    determination = read_determinations(restatement_event_id=event["id"])[0]
    assert determination["status"] == "CALCULATED"
    assert_money(determination["original_factor_pct"], 130.00, "original_factor_pct")
    assert_money(determination["restated_factor_pct"], 100.00, "restated_factor_pct")
    assert_money(determination["restated_amount_usd"], 1800000.00, "restated_amount_usd")
    assert_money(determination["recoverable_amount_usd"], 540000.00, "recoverable_amount_usd")

    # Rung two: a CALCULATED determination is not yet recoverable.
    validate_error(
        api_client.recover_clawback_determination(determination["id"], CHAIR),
        ApiErrorId.ERR_DETERMINATION_STATE_INVALID,
        409,
    )

    order_recovery(event["id"])
    noticed = read_determinations(restatement_event_id=event["id"])[0]
    assert noticed["status"] == "NOTICED"
    assert read_restatement_event(env["issuer"]["id"], event["id"])["status"] == "RECOVERY_ORDERED"

    # Rung three: a NOTICED determination the officer has not acknowledged is not recoverable.
    validate_error(
        api_client.recover_clawback_determination(determination["id"], CHAIR),
        ApiErrorId.ERR_DETERMINATION_NOT_ACKNOWLEDGED,
        422,
    )

    # Rung four: a recovery that never happened cannot be reversed.
    validate_error(
        api_client.reverse_clawback_recovery(
            determination["id"],
            reverse_recovery_payload("Attempted before any recovery was executed."),
            CHAIR,
        ),
        ApiErrorId.ERR_DETERMINATION_STATE_INVALID,
        409,
    )

    award = read_award(award_id)
    assert award["status"] == "VESTED", "no rejected rung moved the award out of VESTED"
    assert_money(award["realized_value_usd"], 2340000.00, "realized_value_usd")
    final_event = read_restatement_event(env["issuer"]["id"], event["id"])
    assert_money(final_event["recovered_total_usd"], 0.00, "recovered_total_usd")
